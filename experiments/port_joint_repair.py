"""Exact minimum-cost repair on DAGs with explicitly bound input ports.

The application supplies function-equivalent implementations and the mapping
from dependency edges to input ports. Pairwise interface constraints and unary
replacement costs are solved by min-sum variable elimination. Runtime is
exponential in the induced width, not in the total number of workflow nodes.
"""
from __future__ import annotations

from dataclasses import dataclass
from itertools import product


@dataclass(frozen=True)
class PortChoice:
    name: str
    inputs: tuple[str, ...]
    output: str
    change_cost: int = 1
    original: bool = False
    function_id: str | None = None


@dataclass(frozen=True)
class PortResult:
    feasible: bool
    assignment: dict[str, str]
    changed: frozenset[str]
    cost: int | None
    states: int
    max_width: int


def _prepare(options, edges, failed, immutable, forced, require_function_match):
    nodes = tuple(sorted(options))
    if not nodes:
        raise ValueError("no workflow nodes")
    known = set(nodes)
    failed, immutable, forced = set(failed), set(immutable), dict(forced or {})
    if not failed <= known or not immutable <= known or not set(forced) <= known:
        raise ValueError("unknown constrained node")
    if failed & immutable:
        raise ValueError("failed node cannot be immutable")
    original, pools = {}, {}
    for node in nodes:
        items = tuple(options[node])
        if not items or len({item.name for item in items}) != len(items):
            raise ValueError("empty or duplicate option pool")
        originals = [item for item in items if item.original]
        if len(originals) != 1 or any(item.change_cost < 0 for item in items):
            raise ValueError("invalid original or cost")
        original[node] = originals[0]
        if require_function_match and original[node].function_id is None:
            raise ValueError("missing function identity")
        if any(len(item.inputs) != len(original[node].inputs) for item in items):
            raise ValueError("option input port count changed")
        pools[node] = tuple(sorted((item for item in items
                                    if (not require_function_match or
                                        item.function_id == original[node].function_id)
                                    and (node not in failed or not item.original)
                                    and (node not in immutable or item.original)
                                    and (node not in forced or item.name == forced[node])),
                                   key=lambda item: item.name))
    edge_list = tuple(edges)
    if len(edge_list) != len(set(edge_list)):
        raise ValueError("duplicate edge")
    bound_ports = set()
    outgoing = set()
    for source, target, port in edge_list:
        if source not in known or target not in known or source == target:
            raise ValueError("invalid edge")
        if not isinstance(port, int) or not 0 <= port < len(original[target].inputs):
            raise ValueError("invalid target port")
        if (target, port) in bound_ports:
            raise ValueError("two dependencies bound to one input port")
        bound_ports.add((target, port))
        outgoing.add(source)
        if original[source].output.casefold() != original[target].inputs[port].casefold():
            raise ValueError("original workflow has incompatible edge")
    for node in nodes:
        pools[node] = tuple(item for item in pools[node]
                            if all(item.inputs[port].casefold() == original[node].inputs[port].casefold()
                                   for port in range(len(item.inputs))
                                   if (node, port) not in bound_ports)
                            and (node in outgoing or
                                 item.output.casefold() == original[node].output.casefold()))
    return nodes, edge_list, pools, original


def _min_fill_order(nodes, edges):
    adjacent = {node: set() for node in nodes}
    for source, target, _ in edges:
        adjacent[source].add(target)
        adjacent[target].add(source)
    order = []
    max_width = 0
    while adjacent:
        def score(node):
            neighbors = adjacent[node]
            missing = sum(b not in adjacent[a] for a in neighbors for b in neighbors if a < b)
            return missing, len(neighbors), node
        node = min(adjacent, key=score)
        neighbors = sorted(adjacent[node])
        max_width = max(max_width, len(neighbors))
        for index, first in enumerate(neighbors):
            for second in neighbors[index + 1:]:
                adjacent[first].add(second)
                adjacent[second].add(first)
        for other in neighbors:
            adjacent[other].remove(node)
        del adjacent[node]
        order.append(node)
    return order, max_width


def solve_ports(options, edges, failed, *, immutable=(), forced=None,
                require_function_match=True):
    """Return an exact repair; cost is (change cost, number of changes)."""
    nodes, edges, pools, original = _prepare(
        options, edges, failed, immutable, forced, require_function_match)
    order, width = _min_fill_order(nodes, edges)
    if any(not pools[node] for node in nodes):
        return PortResult(False, {}, frozenset(), None, 0, width)
    # Factor = (scope, {option-index tuple: (cost, changed-count)}).
    factors = []
    for node in nodes:
        factors.append(((node,), {(i,): (0 if item.original else item.change_cost,
                                         0 if item.original else 1)
                                  for i, item in enumerate(pools[node])}))
    for source, target, port in edges:
        scope = tuple(sorted((source, target)))
        table = {}
        for i, first in enumerate(pools[scope[0]]):
            for j, second in enumerate(pools[scope[1]]):
                chosen = {scope[0]: first, scope[1]: second}
                if chosen[source].output.casefold() == chosen[target].inputs[port].casefold():
                    table[(i, j)] = (0, 0)
        factors.append((scope, table))
    back = {}
    states = 0
    for node in order:
        bucket = [factor for factor in factors if node in factor[0]]
        factors = [factor for factor in factors if node not in factor[0]]
        union = tuple(sorted(set().union(*(set(scope) for scope, _ in bucket))))
        remaining = tuple(name for name in union if name != node)
        table, selector = {}, {}
        for combination in product(*(range(len(pools[name])) for name in union)):
            states += 1
            chosen = dict(zip(union, combination))
            costs = []
            for scope, values in bucket:
                value = values.get(tuple(chosen[name] for name in scope))
                if value is None:
                    break
                costs.append(value)
            else:
                total = (sum(value[0] for value in costs), sum(value[1] for value in costs))
                boundary = tuple(chosen[name] for name in remaining)
                option = chosen[node]
                if boundary not in table or (total, option) < (table[boundary], selector[boundary]):
                    table[boundary], selector[boundary] = total, option
        factors.append((remaining, table))
        back[node] = (remaining, selector)
    final = [table.get(()) for scope, table in factors if not scope]
    if len(final) != len(factors) or any(value is None for value in final):
        return PortResult(False, {}, frozenset(), None, states, width)
    selected = {}
    for node in reversed(order):
        scope, selector = back[node]
        key = tuple(selected[name] for name in scope)
        selected[node] = selector[key]
    assignment = {node: pools[node][selected[node]].name for node in nodes}
    changed = frozenset(node for node in nodes if not pools[node][selected[node]].original)
    return PortResult(True, assignment, changed, sum(value[0] for value in final),
                      states, width)


def exhaustive_ports(options, edges, failed, *, immutable=(), forced=None,
                     require_function_match=True):
    nodes, edges, pools, original = _prepare(
        options, edges, failed, immutable, forced, require_function_match)
    best, states = None, 0
    for items in product(*(pools[node] for node in nodes)):
        states += 1
        chosen = dict(zip(nodes, items))
        if any(chosen[source].output.casefold() != chosen[target].inputs[port].casefold()
               for source, target, port in edges):
            continue
        changed = frozenset(node for node in nodes if not chosen[node].original)
        value = (sum(chosen[node].change_cost for node in changed), len(changed),
                 tuple(chosen[node].name for node in nodes))
        if best is None or value < best[0]:
            best = (value, chosen, changed)
    if best is None:
        return PortResult(False, {}, frozenset(), None, states, 0)
    return PortResult(True, {node: item.name for node, item in best[1].items()},
                      best[2], best[0][0], states, 0)
