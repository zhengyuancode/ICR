"""Joint-choice interface study with function-preserving format variants.

TaskBench supplies workflow topology and resource types. The interventions
below are synthetic representation variants of *the same named operation*;
they do not claim that TaskBench releases runnable substitute tools.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from hashlib import sha256
from pathlib import Path
from time import perf_counter
import argparse
import json
import random
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from experiments.joint_repair import Choice, exhaustive_oracle, solve_tree
from research.taskbench_multinode_study import read_rows, original_graph, signature

FORMATS = ("plain", "json", "proto")


def pool(graph, seed):
    metadata, _, _, _ = graph
    rng = random.Random(f"{seed}:{sha256(signature(graph).encode()).hexdigest()}")
    choices = {}
    for name, node in sorted(metadata.items()):
        input_resource = node["input-type"][0].casefold()
        output_resource = node["output-type"][0].casefold()
        function = name
        choices[name] = [Choice(f"{name}::original", f"{input_resource}:plain",
                                f"{output_resource}:plain", original=True,
                                function_id=function)]
        for index in range(2):
            # A format variant decodes its own declared input representation
            # and encodes its output; the operation identity does not change.
            incoming = rng.choices(FORMATS, weights=(2, 1, 1))[0]
            outgoing = rng.choices(FORMATS, weights=(2, 1, 1))[0]
            choices[name].append(Choice(f"{name}::format{index + 1}",
                                        f"{input_resource}:{incoming}",
                                        f"{output_resource}:{outgoing}",
                                        change_cost=rng.randint(1, 3),
                                        function_id=function))
    return choices


def greedy_forward(options, edges, failed):
    """Same-information topological greedy, trying each failed-node option."""
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
        selected = {}
        for node in order:
            candidates = [seed] if node == failed else options[node]
            eligible = [item for item in candidates
                        if (incoming[node] or item.input_type == old[node].input_type)
                        and (outgoing[node] or item.output_type == old[node].output_type)
                        and all(selected[parent].output_type == item.input_type
                                for parent in incoming[node])]
            if not eligible:
                break
            selected[node] = min(eligible, key=lambda item: (
                0 if item.original else item.change_cost, item.original is False,
                item.name))
        else:
            changed = [item for item in selected.values() if not item.original]
            key = (sum(item.change_cost for item in changed), len(changed))
            if best is None or key < best:
                best = key
    return best


def run_domain(domain, seed):
    data_dir = ROOT / f"research/external/taskbench_{domain}"
    eligible = {}
    for row in read_rows(data_dir):
        graph = original_graph(row)
        if graph is not None:
            eligible.setdefault(signature(graph), graph)
    count, by_size = Counter(), defaultdict(Counter)
    timing = Counter()
    examples = []
    graph_rows = []
    for graph in eligible.values():
        metadata, edges, _, _ = graph
        options = pool(graph, seed)
        graph_count = Counter()
        for failed in sorted(metadata):
            start = perf_counter()
            optimal = solve_tree(options, edges, {failed})
            timing["dp_seconds"] += perf_counter() - start
            start = perf_counter()
            oracle = exhaustive_oracle(options, edges, {failed})
            timing["oracle_seconds"] += perf_counter() - start
            if (optimal.feasible, optimal.cost, len(optimal.changed)) != (
                oracle.feasible, oracle.cost, len(oracle.changed)):
                raise AssertionError((domain, signature(graph), failed, optimal, oracle))
            start = perf_counter()
            greedy = greedy_forward(options, edges, failed)
            timing["greedy_seconds"] += perf_counter() - start
            key = by_size[len(metadata)]
            for target in (count, key, graph_count):
                target["instances"] += 1
                target["dp_feasible"] += optimal.feasible
                target["greedy_feasible"] += greedy is not None
                target["oracle_agreement"] += 1
                if optimal.feasible and greedy is None:
                    target["greedy_false_negative"] += 1
                if optimal.feasible and greedy is not None and greedy[0] > optimal.cost:
                    target["greedy_cost_suboptimal"] += 1
                if optimal.feasible and len(optimal.changed) >= 3:
                    target["three_node_repairs"] += 1
            if optimal.feasible and (greedy is None or greedy[0] > optimal.cost) and len(examples) < 6:
                examples.append({"graph_sha256": sha256(signature(graph).encode()).hexdigest(),
                                 "failed": failed, "edges": edges,
                                 "options": {name: [vars(item) for item in items]
                                             for name, items in options.items()},
                                 "optimal": vars(optimal), "greedy": greedy})
        graph_rows.append({"graph_sha256": sha256(signature(graph).encode()).hexdigest(),
                           "node_count": len(metadata), "counts": dict(graph_count)})
    return {"graphs": len(eligible), "counts": dict(count),
            "by_size": {str(k): dict(v) for k, v in by_size.items()},
            "timing": dict(timing), "examples": examples, "by_graph": graph_rows,
            "source_hashes": {name: sha256((data_dir / name).read_bytes()).hexdigest()
                              for name in ("data.json", "tool_desc.json")}}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=20260924)
    args = parser.parse_args()
    report = {"protocol": "TaskBench topology and resource types with two synthetic, "
                          "function-preserving representation variants per node; "
                          "all source/sink representations frozen; exact DP versus "
                          "same-information forward greedy and exhaustive oracle",
              "seed": args.seed,
              "domains": {domain: run_domain(domain, args.seed)
                          for domain in ("multimedia", "huggingface")}}
    suffix = "" if args.seed == 20260924 else f"_seed{args.seed}"
    output = ROOT / f"research/continuation_repair/joint_taskbench_results{suffix}.json"
    output.write_text(json.dumps(report, indent=2, default=list), encoding="utf-8")
    print(json.dumps({domain: {"graphs": value["graphs"], "counts": value["counts"],
                               "timing": value["timing"]}
                      for domain, value in report["domains"].items()}, indent=2))


if __name__ == "__main__":
    main()
