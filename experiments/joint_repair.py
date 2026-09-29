"""Exact joint tool-choice and repair-region optimization on a tool forest.

Each node has one original implementation and zero or more alternatives.
Options are supplied by an application-specific function-equivalence filter;
this module checks resource interfaces and never infers semantic equivalence.
For a forest, pairwise interface constraints permit exact dynamic programming.
"""
from __future__ import annotations

from dataclasses import dataclass
from collections import defaultdict
from itertools import product


@dataclass(frozen=True)
class Choice:
    name: str
    input_type: str
    output_type: str
    change_cost: int = 1
    original: bool = False
    function_id: str | None = None


@dataclass(frozen=True)
class JointResult:
    feasible: bool
    assignment: dict[str, str]
    changed: frozenset[str]
    cost: int | None
    states: int
    compatibility_checks: int


def _prepare(options, edges, failed, immutable, forced, require_function_match):
    names = sorted(options)
    if not names:
        raise ValueError("at least one node is required")
    nodes = set(names)
    failed, immutable, forced = set(failed), set(immutable), dict(forced)
    if not failed <= nodes or not immutable <= nodes or not set(forced) <= nodes:
        raise ValueError("unknown node in constraints")
    if failed & immutable:
        raise ValueError("a failed node cannot be immutable")
    by_name, originals, choices = {}, {}, {}
    for node in names:
        pool = tuple(options[node])
        if not pool or len({item.name for item in pool}) != len(pool):
            raise ValueError(f"empty or duplicate choices for {node}")
        original = [item for item in pool if item.original]
        if len(original) != 1 or any(item.change_cost < 0 for item in pool):
            raise ValueError(f"invalid original or negative cost for {node}")
        originals[node] = original[0]
        by_name[node] = {item.name: item for item in pool}
        if require_function_match and original[0].function_id is None:
            raise ValueError(f"missing function identity for {node}")
        allowed = [item for item in pool
                   if (not require_function_match or item.function_id == original[0].function_id)
                   and (node not in failed or not item.original)
                   and (node not in immutable or item.original)
                   and (node not in forced or item.name == forced[node])]
        choices[node] = tuple(sorted(allowed, key=lambda item: item.name))
    edge_list = list(edges)
    if any(u not in nodes or v not in nodes or u == v for u, v in edge_list):
        raise ValueError("invalid edge endpoint")
    if len(edge_list) != len(set(edge_list)):
        raise ValueError("duplicate edge")
    if any(originals[u].output_type.casefold() != originals[v].input_type.casefold()
           for u, v in edge_list):
        raise ValueError("original workflow is not resource compatible")
    incoming = defaultdict(int)
    outgoing = defaultdict(int)
    neighbors = defaultdict(list)
    for u, v in edge_list:
        incoming[v] += 1
        outgoing[u] += 1
        neighbors[u].append(v)
        neighbors[v].append(u)
    for node in names:
        if incoming[node] == 0:
            choices[node] = tuple(item for item in choices[node]
                                  if item.input_type.casefold() == originals[node].input_type.casefold())
        if outgoing[node] == 0:
            choices[node] = tuple(item for item in choices[node]
                                  if item.output_type.casefold() == originals[node].output_type.casefold())
    return names, edge_list, choices, originals, neighbors, by_name


def _compatible(edge, parent, child, parent_choice, child_choice):
    if edge == (parent, child):
        return parent_choice.output_type.casefold() == child_choice.input_type.casefold()
    return child_choice.output_type.casefold() == parent_choice.input_type.casefold()


def solve_tree(options, edges, failed, *, immutable=(), forced=None,
               require_function_match=True):
    """Find minimum-cost compatible choices and their induced repair region.

    Costs are additive; ties prefer fewer changes and stable option names.
    The undirected dependency graph must be a forest. Runtime is
    O(sum_(u,v) |A_u| |A_v|) after option eligibility is determined.
    """
    names, edges, choices, originals, neighbors, by_name = _prepare(
        options, edges, failed, immutable, forced or {}, require_function_match)
    edge_set = set(edges)
    seen, roots, children, order = set(), [], defaultdict(list), []
    for root in names:
        if root in seen:
            continue
        roots.append(root)
        seen.add(root)
        stack = [(root, None)]
        while stack:
            node, parent = stack.pop()
            order.append(node)
            for neighbor in sorted(neighbors[node], reverse=True):
                if neighbor == parent:
                    continue
                if neighbor in seen:
                    raise ValueError("joint tree solver requires a forest")
                seen.add(neighbor)
                children[node].append(neighbor)
                stack.append((neighbor, node))
    dp, back = {}, {}
    checks = 0
    for node in reversed(order):
        dp[node], back[node] = {}, {}
        for item in choices[node]:
            cost = (0 if item.original else item.change_cost,
                    0 if item.original else 1)
            selected = {}
            for child in children[node]:
                edge = (node, child) if (node, child) in edge_set else (child, node)
                feasible = []
                for child_name, child_cost in dp[child].items():
                    checks += 1
                    if _compatible(edge, node, child, item, by_name[child][child_name]):
                        feasible.append((child_cost, child_name))
                if not feasible:
                    break
                child_cost, child_name = min(feasible)
                cost = (cost[0] + child_cost[0], cost[1] + child_cost[1])
                selected[child] = child_name
            else:
                dp[node][item.name] = cost
                back[node][item.name] = selected
    if any(not dp[root] for root in roots):
        return JointResult(False, {}, frozenset(), None,
                           sum(map(len, dp.values())), checks)
    selected_roots = {root: min((value, name) for name, value in dp[root].items())[1]
                      for root in roots}
    assignment = {}
    stack = list(selected_roots.items())
    while stack:
        node, name = stack.pop()
        assignment[node] = name
        stack.extend(back[node][name].items())
    changed = frozenset(node for node, name in assignment.items()
                        if name != originals[node].name)
    return JointResult(True, assignment, changed,
                       sum(dp[root][selected_roots[root]][0] for root in roots),
                       sum(map(len, dp.values())), checks)


def exhaustive_oracle(options, edges, failed, *, immutable=(), forced=None,
                      require_function_match=True):
    """Enumerate all assignments; intended only for small-graph validation."""
    names, edge_list, choices, originals, _, _ = _prepare(
        options, edges, failed, immutable, forced or {}, require_function_match)
    checked = 0
    best = None
    for row in product(*(choices[node] for node in names)):
        checked += 1
        assignment = dict(zip(names, row))
        if any(assignment[u].output_type.casefold() != assignment[v].input_type.casefold()
               for u, v in edge_list):
            continue
        changed = frozenset(node for node in names if not assignment[node].original)
        key = (sum(assignment[node].change_cost for node in changed), len(changed),
               tuple(assignment[node].name for node in names))
        if best is None or key < best[0]:
            best = (key, assignment, changed)
    if best is None:
        return JointResult(False, {}, frozenset(), None, checked, checked * len(edge_list))
    return JointResult(True, {node: item.name for node, item in best[1].items()},
                       best[2], best[0][0], checked, checked * len(edge_list))
