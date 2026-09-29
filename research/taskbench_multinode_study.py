"""Contract-only multi-node repair study on released TaskBench tool graphs.

This deliberately tests interface feasibility, not semantic task success.
No language-model output, reference path, or outcome label is used.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from hashlib import sha256
from pathlib import Path
import argparse
import json
import random
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "experiments"))
from repair_region import Edge, least_region  # noqa: E402

RANDOM_SEED = 20260924
ASSIGNMENTS_PER_GRAPH = 128
MIN_NODES = 3
MAX_NODES = 5


def read_rows(data_dir):
    with (data_dir / "data.json").open(encoding="utf-8") as stream:
        yield from (json.loads(line) for line in stream if line.strip())


def one_type(node):
    ins = node.get("input-type", [])
    outs = node.get("output-type", [])
    return len(ins) == len(outs) == 1


def original_graph(row):
    nodes = json.loads(row["sampled_nodes"])
    links = json.loads(row["sampled_links"])
    names = [node["task"] for node in nodes]
    if not (MIN_NODES <= len(names) <= MAX_NODES) or len(names) != len(set(names)):
        return None
    if not all(one_type(node) for node in nodes):
        return None
    if len(links) < len(nodes) - 1:
        return None
    metadata = {node["task"]: node for node in nodes}
    edges = [(link["source"], link["target"]) for link in links]
    if any(u not in metadata or v not in metadata or u == v for u, v in edges):
        return None
    if any(metadata[u]["output-type"][0].lower() != metadata[v]["input-type"][0].lower()
           for u, v in edges):
        return None
    indegree = Counter(v for _, v in edges)
    outdegree = Counter(u for u, _ in edges)
    # Every retained tool has one input port, so two incoming resources would
    # make the port assignment ambiguous.
    if any(indegree[name] > 1 for name in names):
        return None
    sources = [n for n in names if indegree[n] == 0]
    sinks = [n for n in names if outdegree[n] == 0]
    if not sources or not sinks:
        return None
    # Exclude disconnected or cyclic graphs; all original nodes must be on a source-to-sink path.
    adjacent = defaultdict(list)
    for u, v in edges:
        adjacent[u].append(v)
    seen = set(sources)
    queue = list(sources)
    for u in queue:
        for v in adjacent[u]:
            if v not in seen:
                seen.add(v)
                queue.append(v)
    if len(seen) != len(names):
        return None
    remaining = {name: indegree[name] for name in names}
    ready = list(sources)
    visited = 0
    for u in ready:
        visited += 1
        for v in adjacent[u]:
            remaining[v] -= 1
            if remaining[v] == 0:
                ready.append(v)
    if visited != len(names):
        return None
    return metadata, edges, sources, sinks


def signature(graph):
    metadata, edges, _, _ = graph
    return json.dumps({"nodes": sorted((name, tuple(v["input-type"]), tuple(v["output-type"]))
                                       for name, v in metadata.items()),
                       "edges": sorted(edges)}, sort_keys=True)


def alternatives(tool_desc):
    return sorted((node for node in tool_desc["nodes"] if one_type(node)),
                  key=lambda node: node["id"])


def build_edges(graph, assignment):
    metadata, links, sources, sinks = graph
    nodes = ["__input_" + name for name in sources] + list(metadata) + ["__output_" + name for name in sinks]
    immutable = {n for n in nodes if n.startswith("__")}
    edges = []
    for name in sources:
        old = metadata[name]["input-type"][0].lower()
        new = assignment[name]["input-type"][0].lower()
        edges.append(Edge("__input_" + name, name, ok_01=old == new, ok_11=old == new))
    for u, v in links:
        old_u = metadata[u]["output-type"][0].lower()
        old_v = metadata[v]["input-type"][0].lower()
        new_u = assignment[u]["output-type"][0].lower()
        new_v = assignment[v]["input-type"][0].lower()
        edges.append(Edge(u, v, ok_00=old_u == old_v, ok_10=new_u == old_v,
                          ok_01=old_u == new_v, ok_11=new_u == new_v))
    for name in sinks:
        old = metadata[name]["output-type"][0].lower()
        new = assignment[name]["output-type"][0].lower()
        edges.append(Edge(name, "__output_" + name, ok_10=old == new, ok_11=old == new))
    return nodes, edges, immutable


def enumerate_oracle(nodes, edges, failed, immutable):
    free = [node for node in nodes if node not in immutable]
    feasible = []
    for bits in range(1 << len(free)):
        region = {node for index, node in enumerate(free) if bits & (1 << index)}
        if not failed <= region:
            continue
        if all((e.ok_11 if e.source in region and e.target in region else
                e.ok_10 if e.source in region else
                e.ok_01 if e.target in region else e.ok_00) for e in edges):
            feasible.append(region)
    return min(feasible, key=lambda value: (len(value), sorted(value))) if feasible else None


def bounded_safe(nodes, edges, failed, immutable, rounds):
    # Same-information bounded-propagation baseline: perform exactly the stated
    # number of synchronous implication rounds, then validate every edge.
    # It never admits an invalid region. It may reject a longer feasible repair.
    region = set(failed)
    for _ in range(rounds):
        newly_required = set()
        for edge in edges:
            if edge.source in region and edge.target not in region and not edge.ok_10:
                newly_required.add(edge.target)
            if edge.target in region and edge.source not in region and not edge.ok_01:
                newly_required.add(edge.source)
        region.update(newly_required)
    if region & immutable:
        return None
    if all((e.ok_11 if e.source in region and e.target in region else
            e.ok_10 if e.source in region else
            e.ok_01 if e.target in region else e.ok_00) for e in edges):
        return region
    return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--domain", choices=("multimedia", "huggingface"), default="multimedia")
    parser.add_argument("--seed", type=int, default=RANDOM_SEED)
    args = parser.parse_args()
    data_dir = ROOT / f"research/external/taskbench_{args.domain}"
    source_files = {name: sha256((data_dir / name).read_bytes()).hexdigest()
                    for name in ("data.json", "graph_desc.json", "tool_desc.json")}
    catalog = alternatives(json.loads((data_dir / "tool_desc.json").read_text(encoding="utf-8")))
    eligible = {}
    sampled = Counter()
    for row in read_rows(data_dir):
        graph = original_graph(row)
        if graph is None:
            continue
        sampled[row["type"]] += 1
        eligible.setdefault(signature(graph), (row["id"], row["type"], graph))
    counts = Counter()
    examples = []
    by_structure = defaultdict(Counter)
    graph_stats = []
    for key, (sample_id, structure, graph) in sorted(eligible.items()):
        metadata, _, _, _ = graph
        names = sorted(metadata)
        graph_counts = Counter()
        # Failure at each actual tool node, not only favorable positions.
        for failed_name in names:
            rng = random.Random(f"{args.seed}:{sample_id}:{failed_name}")
            for _ in range(ASSIGNMENTS_PER_GRAPH):
                assignment = {name: rng.choice([candidate for candidate in catalog
                                                if candidate["id"] != name]) for name in names}
                nodes, edges, immutable = build_edges(graph, assignment)
                oracle = enumerate_oracle(nodes, edges, {failed_name}, immutable)
                closed = least_region(nodes, edges, {failed_name}, immutable=immutable)
                local = bounded_safe(nodes, edges, {failed_name}, immutable, rounds=1)
                two_hop = bounded_safe(nodes, edges, {failed_name}, immutable, rounds=2)
                triggered = any((edge.source == failed_name and not edge.ok_10) or
                                (edge.target == failed_name and not edge.ok_01)
                                for edge in edges)
                counts["assignments"] += 1
                graph_counts["assignments"] += 1
                by_structure[structure]["assignments"] += 1
                if triggered:
                    counts["seed_interface_changed"] += 1
                if oracle is not None:
                    counts["oracle_feasible"] += 1
                    graph_counts["oracle_feasible"] += 1
                    by_structure[structure]["oracle_feasible"] += 1
                    counts[f"region_size_{len(oracle)}"] += 1
                    if triggered:
                        counts["changed_feasible"] += 1
                        graph_counts["changed_feasible"] += 1
                    if len(oracle) >= 3:
                        counts["multi_node_feasible"] += 1
                        by_structure[structure]["multi_node_feasible"] += 1
                    if local is not None:
                        counts["one_hop_admitted"] += 1
                        graph_counts["one_hop_admitted"] += 1
                        by_structure[structure]["one_hop_admitted"] += 1
                        if triggered:
                            counts["changed_one_hop_admitted"] += 1
                            graph_counts["changed_one_hop_admitted"] += 1
                    elif len(oracle) >= 3 and len(examples) < 12:
                        examples.append({"sample_id": sample_id, "structure": structure,
                                         "failed": failed_name,
                                         "assignment": {n: assignment[n]["id"] for n in names},
                                         "least_region": sorted(oracle),
                                         "witnesses": closed.witnesses})
                    if two_hop is not None:
                        counts["two_hop_admitted"] += 1
                        graph_counts["two_hop_admitted"] += 1
                        if triggered:
                            counts["changed_two_hop_admitted"] += 1
                            graph_counts["changed_two_hop_admitted"] += 1
                if closed.feasible != (oracle is not None) or (oracle is not None and set(closed.nodes) != oracle):
                    counts["closure_oracle_mismatch"] += 1
                if local is not None and (oracle is None or local != oracle):
                    counts["one_hop_oracle_mismatch"] += 1
                if two_hop is not None and (oracle is None or two_hop != oracle):
                    counts["two_hop_oracle_mismatch"] += 1
        graph_stats.append({"graph_sha256": sha256(key.encode()).hexdigest(),
                            "source_sample_id": sample_id, "structure": structure,
                            "node_count": len(names), "counts": dict(graph_counts)})
    for key in ("closure_oracle_mismatch", "one_hop_oracle_mismatch", "two_hop_oracle_mismatch"):
        counts.setdefault(key, 0)
    report = {
        "scope": "Public TaskBench Multimedia resource-dependency graphs; one-input/one-output tools, 3-5 nodes; structural feasibility only, not semantic correctness or agent pass",
        "source": f"https://github.com/microsoft/JARVIS/tree/main/taskbench/data_{args.domain}",
        "sha256": source_files, "selection": {"eligible_rows": dict(sampled),
            "distinct_graphs": len(eligible), "catalog_tools": len(catalog),
            "assignment_draws_per_graph_node": ASSIGNMENTS_PER_GRAPH,
            "random_seed": args.seed},
        "counts": dict(counts), "by_structure": {k: dict(v) for k, v in by_structure.items()},
        "examples": examples, "by_graph": graph_stats,
    }
    suffix = "" if args.seed == RANDOM_SEED else f"_seed{args.seed}"
    out = ROOT / f"research/continuation_repair/taskbench_{args.domain}_multinode_results{suffix}.json"
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({"selection": report["selection"], "counts": report["counts"],
                      "by_structure": report["by_structure"]}, indent=2))


if __name__ == "__main__":
    main()
