"""Graph-cluster uncertainty and seed sensitivity for joint-choice study."""
from pathlib import Path
import json
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
FILES = [(20260924, "joint_taskbench_results.json"),
         (20260925, "joint_taskbench_results_seed20260925.json"),
         (20260926, "joint_taskbench_results_seed20260926.json")]


def main():
    rng = np.random.default_rng(20260924)
    report = {"unit": "distinct TaskBench workflow graph; stratified graph-cluster bootstrap",
              "draws": 20000, "seeds": {}}
    for seed, filename in FILES:
        source = json.loads((ROOT / "research/continuation_repair" / filename)
                            .read_text(encoding="utf-8"))
        strata = []
        counts = {key: 0 for key in ("instances", "dp_feasible", "greedy_feasible",
                                      "greedy_false_negative", "greedy_cost_suboptimal",
                                      "three_node_repairs")}
        for domain in ("multimedia", "huggingface"):
            rows = source["domains"][domain]["by_graph"]
            matrix = np.array([[row["counts"].get(key, 0) for key in counts]
                               for row in rows], dtype=np.int64)
            strata.append(matrix)
            for col, key in enumerate(counts):
                counts[key] += int(matrix[:, col].sum())
        sampled = np.zeros((20000, len(counts)), dtype=np.int64)
        for matrix in strata:
            indices = rng.integers(0, len(matrix), size=(20000, len(matrix)))
            sampled += matrix[indices].sum(axis=1)
        columns = list(counts)
        gap = sampled[:, columns.index("greedy_false_negative")] / sampled[:, columns.index("instances")]
        conditional = (sampled[:, columns.index("greedy_false_negative")] /
                       sampled[:, columns.index("dp_feasible")])
        report["seeds"][str(seed)] = {
            "counts": counts,
            "feasibility_gap": counts["greedy_false_negative"] / counts["instances"],
            "feasibility_gap_ci95": np.quantile(gap, [.025, .975]).tolist(),
            "conditional_greedy_miss": counts["greedy_false_negative"] / counts["dp_feasible"],
            "conditional_greedy_miss_ci95": np.quantile(conditional, [.025, .975]).tolist(),
        }
    output = ROOT / "research/continuation_repair/joint_taskbench_analysis.json"
    output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
