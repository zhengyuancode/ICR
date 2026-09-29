"""Same-information lookahead control for the frozen joint-choice study.

This reproduces the exact published graph/option generator and compares
fixed-width topological beam search with the optimal tree solver. It never
uses oracle assignments to construct beam states.
"""
from collections import Counter, defaultdict
from hashlib import sha256
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from experiments.joint_repair import solve_tree  # noqa: E402
from research.joint_taskbench_study import pool  # noqa: E402
from research.taskbench_multinode_study import original_graph, read_rows, signature  # noqa: E402


def beam_forward(options, edges, failed, width):
    nodes = sorted(options)
    incoming, outgoing, indegree = defaultdict(list), defaultdict(list), Counter()
    for u, v in edges:
        outgoing[u].append(v)
        incoming[v].append(u)
        indegree[v] += 1
    ready = sorted(node for node in nodes if indegree[node] == 0)
    order = []
    for node in ready:
        order.append(node)
        for child in sorted(outgoing[node]):
            indegree[child] -= 1
            if indegree[child] == 0:
                ready.append(child)
    assert len(order) == len(nodes)
    old = {node: next(x for x in options[node] if x.original) for node in nodes}
    best = None
    for seed in (item for item in options[failed] if not item.original):
        beam = [(0, 0, {})]
        for node in order:
            expanded = []
            candidates = [seed] if node == failed else options[node]
            for cost, changed, selected in beam:
                for item in candidates:
                    if not incoming[node] and item.input_type != old[node].input_type:
                        continue
                    if not outgoing[node] and item.output_type != old[node].output_type:
                        continue
                    if any(selected[parent].output_type != item.input_type
                           for parent in incoming[node]):
                        continue
                    row = dict(selected)
                    row[node] = item
                    expanded.append((cost + (0 if item.original else item.change_cost),
                                     changed + int(not item.original), row))
            if not expanded:
                beam = []
                break
            expanded.sort(key=lambda state: (state[0], state[1],
                                            tuple(item.name for item in state[2].values())))
            beam = expanded[:width]
        if beam:
            candidate = beam[0][:2]
            if best is None or candidate < best:
                best = candidate
    return best


def main():
    widths = (1, 2, 4, 8)
    results = {}
    for seed in (20260924, 20260925, 20260926):
        counts = Counter()
        by_graph = []
        for domain in ("multimedia", "huggingface"):
            data_dir = ROOT / f"research/external/taskbench_{domain}"
            graphs = {}
            for row in read_rows(data_dir):
                graph = original_graph(row)
                if graph is not None:
                    graphs.setdefault(signature(graph), graph)
            for graph in graphs.values():
                metadata, edges, _, _ = graph
                options = pool(graph, seed)
                local = Counter()
                for failed in sorted(metadata):
                    optimal = solve_tree(options, edges, {failed})
                    local["instances"] += 1
                    local["optimal_feasible"] += optimal.feasible
                    for width in widths:
                        result = beam_forward(options, edges, failed, width)
                        local[f"beam{width}_feasible"] += result is not None
                        if optimal.feasible and result is None:
                            local[f"beam{width}_miss"] += 1
                        if optimal.feasible and result and result[0] > optimal.cost:
                            local[f"beam{width}_suboptimal"] += 1
                counts.update(local)
                by_graph.append({"domain": domain,
                                 "graph_sha256": sha256(signature(graph).encode()).hexdigest(),
                                 "counts": dict(local)})
        results[str(seed)] = {"counts": dict(counts), "by_graph": by_graph}
        print(seed, dict(counts), flush=True)
    output = ROOT / "research/continuation_repair/joint_beam_sensitivity.json"
    output.write_text(json.dumps({"widths": widths, "seeds": results}, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
