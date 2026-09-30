"""Same-instance wall-time check of the exact tree solver and width-eight beam."""
from __future__ import annotations

from collections import Counter
import json
from pathlib import Path
from statistics import median
from time import perf_counter_ns

from experiments.joint_repair import solve_tree
from research.joint_beam_sensitivity import beam_forward
from research.joint_taskbench_study import pool
from research.taskbench_multinode_study import original_graph, read_rows, signature


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "research/continuation_repair/joint_beam_timing_20260930.json"


def percentile(values: list[float], q: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(q * len(ordered)))]


def main() -> None:
    seed = 20260924
    times: dict[str, list[float]] = {"dp": [], "beam8": []}
    node_counts = Counter()
    matches = Counter()
    for domain in ("multimedia", "huggingface"):
        directory = ROOT / f"research/external/taskbench_{domain}"
        graphs = {}
        for row in read_rows(directory):
            graph = original_graph(row)
            if graph is not None:
                graphs.setdefault(signature(graph), graph)
        for graph in graphs.values():
            metadata, edges, _, _ = graph
            options = pool(graph, seed)
            node_counts[len(metadata)] += 1
            for failed in sorted(metadata):
                elapsed = {"dp": [], "beam8": []}
                for repeat in range(5):
                    methods = ("dp", "beam8") if repeat % 2 == 0 else ("beam8", "dp")
                    for method in methods:
                        start = perf_counter_ns()
                        if method == "dp":
                            exact = solve_tree(options, edges, {failed})
                        else:
                            approx = beam_forward(options, edges, failed, 8)
                        elapsed[method].append((perf_counter_ns() - start) / 1e6)
                for method in elapsed:
                    times[method].append(median(elapsed[method]))
                matches["instances"] += 1
                matches["same_status_and_cost"] += ((approx is not None) == exact.feasible
                    and (not exact.feasible or approx[0] == exact.cost))
    report = {
        "role": "Post-review single-process wall-time measurement, Python 3, same generated instances; five alternating-order repetitions per method and instance",
        "seed": seed,
        "graph_node_count_distribution": {str(k): v for k, v in sorted(node_counts.items())},
        "agreement": dict(matches),
        "timing_ms": {name: {"median": median(v), "p95": percentile(v, .95),
                              "sum": sum(v)} for name, v in times.items()},
    }
    OUTPUT.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
