"""Graph-clustered uncertainty for the public TaskBench contract study."""
from pathlib import Path
import json

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
DOMAINS = ("multimedia", "huggingface")
SEED = 20260924
DRAWS = 20000
FIELDS = ("assignments", "oracle_feasible", "one_hop_admitted", "two_hop_admitted",
          "changed_feasible", "changed_one_hop_admitted", "changed_two_hop_admitted")


def read(domain):
    path = ROOT / f"research/continuation_repair/taskbench_{domain}_multinode_results.json"
    result = json.loads(path.read_text(encoding="utf-8"))
    matrix = np.array([[row["counts"].get(key, 0) for key in FIELDS]
                       for row in result["by_graph"]], dtype=np.int64)
    assert np.array_equal(matrix.sum(axis=0),
                          np.array([result["counts"].get(key, 0) for key in FIELDS]))
    return result, matrix


def fractions(counts):
    index = {name: k for k, name in enumerate(FIELDS)}
    cf = counts[index["changed_feasible"]]
    return {"one_hop_miss_among_changed_feasible":
            (cf - counts[index["changed_one_hop_admitted"]]) / cf,
            "two_hop_miss_among_changed_feasible":
            (cf - counts[index["changed_two_hop_admitted"]]) / cf}


def main():
    sources = {domain: read(domain) for domain in DOMAINS}
    rng = np.random.default_rng(SEED)
    distributions = {name: [] for name in fractions(sum(m.sum(axis=0) for _, m in sources.values()))}
    for _ in range(DRAWS):
        # Stratify by dataset domain and resample distinct graphs, not assignments.
        total = sum(matrix[rng.integers(0, len(matrix), len(matrix))].sum(axis=0)
                    for _, matrix in sources.values())
        sample = fractions(total)
        for name, value in sample.items():
            distributions[name].append(value)
    point_counts = sum(matrix.sum(axis=0) for _, matrix in sources.values())
    report = {"unit": "distinct TaskBench tool graph, stratified by domain",
              "seed": SEED, "draws": DRAWS,
              "domains": {domain: {"graphs": len(matrix),
                                   "counts": {name: int(value) for name, value in zip(FIELDS, matrix.sum(axis=0))},
                                   "fractions": fractions(matrix.sum(axis=0))}
                          for domain, (_, matrix) in sources.items()},
              "combined": {"graphs": sum(len(matrix) for _, matrix in sources.values()),
                           "counts": {name: int(value) for name, value in zip(FIELDS, point_counts)},
                           "fractions": fractions(point_counts),
                           "graph_bootstrap_95ci":
                           {name: np.quantile(values, [0.025, 0.975]).tolist()
                            for name, values in distributions.items()}}}
    out = ROOT / "research/continuation_repair/taskbench_multinode_analysis.json"
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report["combined"], indent=2))


if __name__ == "__main__":
    main()
