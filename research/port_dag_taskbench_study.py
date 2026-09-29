"""Joint repair on released TaskBench multi-input DAG topologies.

The graph and resource types are public. Alternative implementations are
controlled same-operation representation variants; they are not released
executable substitute tools. All baselines receive identical option pools.
"""
from collections import Counter, defaultdict
from hashlib import sha256
from itertools import permutations
from pathlib import Path
import argparse
import json
import random
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from experiments.port_joint_repair import PortChoice, solve_ports, exhaustive_ports  # noqa: E402
from research.taskbench_multinode_study import read_rows  # noqa: E402

FORMATS = ("plain", "json", "proto")


def graph_from_row(row):
    raw_nodes = json.loads(row["sampled_nodes"])
    links = json.loads(row["sampled_links"])
    if not 3 <= len(raw_nodes) <= 8:
        return None
    metadata = {node["task"]: node for node in raw_nodes}
    if len(metadata) != len(raw_nodes):
        return None
    if any(len(node.get("output-type", [])) != 1 or not node.get("input-type")
           for node in raw_nodes):
        return None
    incoming, outgoing = defaultdict(list), defaultdict(list)
    for link in links:
        source, target = link["source"], link["target"]
        if source not in metadata or target not in metadata or source == target:
            return None
        incoming[target].append(source)
        outgoing[source].append(target)
    if max((len(value) for value in incoming.values()), default=0) < 2:
        return None
    if len(links) < len(metadata) - 1:
        return None
    # Give each incoming dependency a unique, resource-compatible input port.
    # Ambiguous repeated-type matches are excluded instead of guessing binding.
    port_edges = []
    for target, sources in incoming.items():
        ports = metadata[target]["input-type"]
        matches = [assignment for assignment in permutations(range(len(ports)), len(sources))
                   if all(metadata[source]["output-type"][0].casefold() == ports[port].casefold()
                          for source, port in zip(sources, assignment))]
        if len(matches) != 1:
            return None
        port_edges.extend((source, target, port)
                          for source, port in zip(sources, matches[0]))
    indegree = Counter(target for _, target, _ in port_edges)
    ready = [node for node in metadata if indegree[node] == 0]
    visited = []
    for node in ready:
        visited.append(node)
        for child in outgoing[node]:
            indegree[child] -= 1
            if indegree[child] == 0:
                ready.append(child)
    if len(visited) != len(metadata):
        return None
    undirected = defaultdict(set)
    for source, target, _ in port_edges:
        undirected[source].add(target)
        undirected[target].add(source)
    seen, queue = {next(iter(metadata))}, [next(iter(metadata))]
    for node in queue:
        for neighbor in undirected[node] - seen:
            seen.add(neighbor)
            queue.append(neighbor)
    if len(seen) != len(metadata):
        return None
    return metadata, tuple(sorted(port_edges))


def signature(graph):
    metadata, edges = graph
    return json.dumps({"nodes": sorted((name, tuple(node["input-type"]),
                                        tuple(node["output-type"]))
                                       for name, node in metadata.items()),
                       "edges": edges}, sort_keys=True)


def options_for(graph, seed, variants=2):
    metadata, _ = graph
    rng = random.Random(f"{seed}:{sha256(signature(graph).encode()).hexdigest()}")
    pools = {}
    for name, node in sorted(metadata.items()):
        inputs = tuple(f"{kind.casefold()}:plain" for kind in node["input-type"])
        output = f"{node['output-type'][0].casefold()}:plain"
        pools[name] = [PortChoice(f"{name}::original", inputs, output,
                                  original=True, function_id=name)]
        for index in range(variants):
            variant_inputs = tuple(f"{kind.casefold()}:{rng.choices(FORMATS,weights=(2,1,1))[0]}"
                                   for kind in node["input-type"])
            variant_output = f"{node['output-type'][0].casefold()}:{rng.choices(FORMATS,weights=(2,1,1))[0]}"
            pools[name].append(PortChoice(f"{name}::format{index + 1}",
                                          variant_inputs, variant_output,
                                          change_cost=rng.randint(1, 3), function_id=name))
    return pools


def beam_ports(options, edges, failed, width):
    nodes = sorted(options)
    incoming, outgoing, indegree = defaultdict(list), defaultdict(list), Counter()
    for source, target, port in edges:
        incoming[target].append((source, port))
        outgoing[source].append(target)
        indegree[target] += 1
    ready = sorted(node for node in nodes if indegree[node] == 0)
    order = []
    for node in ready:
        order.append(node)
        for child in sorted(outgoing[node]):
            indegree[child] -= 1
            if indegree[child] == 0:
                ready.append(child)
    original = {node: next(item for item in options[node] if item.original) for node in nodes}
    best = None
    for seed in (item for item in options[failed] if not item.original):
        beam = [(0, 0, {})]
        for node in order:
            expanded = []
            candidates = (seed,) if node == failed else options[node]
            bound = {port for _, port in incoming[node]}
            for cost, changed, chosen in beam:
                for item in candidates:
                    if any(kind != original[node].inputs[port]
                           for port, kind in enumerate(item.inputs) if port not in bound):
                        continue
                    if not outgoing[node] and item.output != original[node].output:
                        continue
                    if any(chosen[source].output != item.inputs[port]
                           for source, port in incoming[node]):
                        continue
                    new = dict(chosen)
                    new[node] = item
                    expanded.append((cost + (0 if item.original else item.change_cost),
                                     changed + int(not item.original), new))
            if not expanded:
                beam = []
                break
            expanded.sort(key=lambda row: (row[0], row[1],
                                          tuple(item.name for item in row[2].values())))
            beam = expanded[:width]
        if beam:
            value = beam[0][:2]
            if best is None or value < best:
                best = value
    return best


def run_domain(domain, seed, variants=2):
    data_dir = ROOT / f"research/external/taskbench_{domain}"
    unique = {}
    for row in read_rows(data_dir):
        graph = graph_from_row(row)
        if graph is not None:
            unique.setdefault(signature(graph), graph)
    count, by_width, by_size = Counter(), defaultdict(Counter), defaultdict(Counter)
    graph_rows = []
    for graph in unique.values():
        metadata, edges = graph
        pools = options_for(graph, seed, variants)
        local = Counter()
        widths = set()
        for failed in sorted(metadata):
            exact = solve_ports(pools, edges, {failed})
            if len(metadata) <= 6:
                oracle = exhaustive_ports(pools, edges, {failed})
                assert (exact.feasible, exact.cost, len(exact.changed)) == (
                    oracle.feasible, oracle.cost, len(oracle.changed))
            widths.add(exact.max_width)
            results = {width: beam_ports(pools, edges, failed, width)
                       for width in (1, 2, 4, 8)}
            for target in (count, local, by_width[exact.max_width], by_size[len(metadata)]):
                target["instances"] += 1
                target["exact_feasible"] += exact.feasible
                target["oracle_checked"] += len(metadata) <= 6
                for width, result in results.items():
                    target[f"beam{width}_feasible"] += result is not None
                    target[f"beam{width}_miss"] += exact.feasible and result is None
                    target[f"beam{width}_cost_suboptimal"] += (
                        exact.feasible and result is not None and result[0] > exact.cost)
        graph_rows.append({"signature_sha256": sha256(signature(graph).encode()).hexdigest(),
                           "nodes": len(metadata), "widths": sorted(widths), "counts": dict(local)})
    return {"graphs": len(unique), "counts": dict(count),
            "by_width": {str(width): dict(value) for width, value in by_width.items()},
            "by_size": {str(size): dict(value) for size, value in by_size.items()},
            "by_graph": graph_rows,
            "source_sha256": sha256((data_dir / "data.json").read_bytes()).hexdigest()}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=20260924)
    parser.add_argument("--variants", type=int, default=2)
    args = parser.parse_args()
    assert 2 <= args.variants <= 5
    report = {"protocol": "Released 3-8-node connected TaskBench multi-input DAGs with unique "
                          "resource-compatible input-port mapping; controlled same-operation format "
                          "variants; same-information exact VE and topological beam widths 1/2/4/8",
              "seed": args.seed, "variants_per_operation": args.variants,
              "domains": {domain: run_domain(domain, args.seed, args.variants)
                          for domain in ("multimedia", "huggingface")}}
    suffix = '' if args.variants == 2 else f'_variants{args.variants}'
    output = ROOT / f"research/continuation_repair/port_dag_taskbench_seed{args.seed}{suffix}.json"
    output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({domain: {"graphs": value["graphs"], "counts": value["counts"],
                               "by_width": value["by_width"]}
                      for domain, value in report["domains"].items()}, indent=2))


if __name__ == "__main__":
    main()
