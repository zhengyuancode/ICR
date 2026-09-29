"""Least interface-closed repair region for a FIXED replacement assignment.

The compatibility oracle must describe sound public contracts. This module does
not infer semantic equivalence, replacement assignments, or rollback authority.
"""
from collections import defaultdict,deque
from dataclasses import dataclass


@dataclass(frozen=True)
class Edge:
    source: str
    target: str
    # ok_xy: edge valid when source uses x and target uses y (0 old, 1 new).
    ok_00: bool=True
    ok_10: bool=True
    ok_01: bool=True
    ok_11: bool=True


@dataclass
class Region:
    nodes: frozenset
    feasible: bool
    reasons: list
    witnesses: list
    edge_visits: int


def least_region(nodes,edges,failed,*,immutable=()):
    """Compute the least feasible region, or a certificate of infeasibility.

    Fixed one-to-one node replacements; unchanged topology. A False original
    edge is an invalid input graph. Previously committed nodes can be immutable.
    Feasible=False rules out this assignment, not all possible repairs.
    """
    nodes=set(nodes);failed=set(failed);immutable=set(immutable)
    if not failed<=nodes or not immutable<=nodes:raise ValueError('unknown node')
    incident=defaultdict(list)
    for e in edges:
        if e.source not in nodes or e.target not in nodes:raise ValueError('unknown edge endpoint')
        if not e.ok_00:raise ValueError('original workflow must be interface valid')
        incident[e.source].append(e)
        if e.target!=e.source:incident[e.target].append(e)
    region=set(failed);queue=deque(sorted(failed));witnesses=[];visits=0
    while queue:
        v=queue.popleft()
        for e in incident[v]:
            visits+=1
            if e.source in region and e.target not in region and not e.ok_10:
                added=e.target;direction='outgoing'
            elif e.target in region and e.source not in region and not e.ok_01:
                added=e.source;direction='incoming'
            else:continue
            region.add(added);queue.append(added)
            witnesses.append({'added':added,'edge':[e.source,e.target],'boundary':direction})
    reasons=[]
    if region&immutable:reasons.append({'immutable_required':sorted(region&immutable)})
    for e in edges:
        if e.source in region and e.target in region and not e.ok_11:
            reasons.append({'incompatible_internal_edge':[e.source,e.target]})
    return Region(frozenset(region),not reasons,reasons,witnesses,visits)


def minimum_assignment(nodes,assignments,failed,*,immutable=()):
    """Exact minimum region among an explicitly supplied finite candidate set.

    assignments is an iterable of (stable_id, edges). Costs are region cardinality.
    This enumerates assignments; it does NOT claim polynomial global synthesis.
    """
    feasible=[]
    for name,edges in assignments:
        region=least_region(nodes,edges,failed,immutable=immutable)
        if region.feasible:feasible.append((len(region.nodes),name,region))
    return min(feasible,key=lambda item:(item[0],item[1])) if feasible else None
