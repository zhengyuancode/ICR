"""Application-facing planning and execution for declared read-only DAGs.

Operation identities and schema validators are supplied by the application.
An interface-compatible assignment is not by itself a semantic certificate.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
import math
from collections import deque
from copy import deepcopy
from .ports import PortChoice, solve_ports, _min_fill_order


def _digest(value):
    return sha256(json.dumps(value, sort_keys=True, allow_nan=False,
                             separators=(",", ":")).encode()).hexdigest()


class Workflow:
    """Copy and validate a JSON workflow specification (see docs/workflows.md)."""

    def __init__(self, spec):
        self._spec = json.loads(json.dumps(spec, allow_nan=False))
        self.options = {}
        self.read_only = {}
        for node, items in self._spec["nodes"].items():
            if not isinstance(node, str) or not node or not items:
                raise ValueError("nodes require nonempty names and option lists")
            pool = []
            for item in items:
                name, operation = item["name"], item["operation"]
                inputs, output = item["inputs"], item["output"]
                if not isinstance(inputs, list):
                    raise ValueError("inputs must be a list of schema IDs")
                cost = item.get("cost", 1)
                if not all(isinstance(x, str) and x for x in [name, operation, output, *inputs]):
                    raise ValueError("implementation, operation and schema IDs must be strings")
                if isinstance(cost, bool) or not isinstance(cost, (int, float)) or not math.isfinite(cost) or cost < 0:
                    raise ValueError("cost must be a finite nonnegative number")
                if not isinstance(item.get("original", False), bool) or not isinstance(item.get("read_only", False), bool):
                    raise ValueError("original and read_only must be boolean")
                pool.append(PortChoice(name, tuple(inputs), output, cost,
                                       item.get("original", False), operation))
                self.read_only[node, name] = item.get("read_only", False)
            self.options[node] = tuple(pool)
        self.edges = tuple(tuple(edge) for edge in self._spec.get("edges", []))
        # Solver preparation validates originals, ports and interfaces.
        from .ports import _prepare
        _prepare(self.options, self.edges, (), (), {}, True)
        incoming = {node: 0 for node in self.options}
        adjacent = {node: [] for node in self.options}
        for source, target, _ in self.edges:
            incoming[target] += 1
            adjacent[source].append(target)
        ready = deque(sorted(node for node, degree in incoming.items() if degree == 0))
        order = []
        while ready:
            node = ready.popleft()
            order.append(node)
            for target in sorted(adjacent[node]):
                incoming[target] -= 1
                if incoming[target] == 0:
                    ready.append(target)
        if len(order) != len(incoming):
            raise ValueError("execution requires a directed acyclic workflow")
        self.order = tuple(order)
        self.digest = _digest(self._spec)

    @classmethod
    def from_file(cls, path):
        with open(path, encoding="utf-8") as stream:
            return cls(json.load(stream))


@dataclass(frozen=True)
class RepairPlan:
    workflow_digest: str
    assignment: tuple[tuple[str, str], ...]
    changed: tuple[str, ...]
    cost: float | None
    feasible: bool
    states: int
    max_width: int
    reason: str = ""

    def to_dict(self):
        return {"workflow_digest": self.workflow_digest, "assignment": dict(self.assignment),
                "changed": list(self.changed), "cost": self.cost, "feasible": self.feasible,
                "states": self.states, "max_width": self.max_width, "reason": self.reason,
                "authority": "advice; execution requires registered read-only handlers"}


def plan_repair(workflow, failed, *, immutable=(), forced=None, max_width=8, max_states=1_000_000):
    """Exact joint repair with an upfront upper bound on factor enumeration.

    immutable fixes implementation choice; it does not authorize reusing outputs.
    A resource-limit exception means not solved, rather than infeasible.
    """
    _, width = _min_fill_order(workflow.options, workflow.edges)
    if width > max_width:
        raise ValueError(f"induced width {width} exceeds limit {max_width}")
    # Simulate elimination scopes to bound the actual enumeration before allocation.
    scopes = [{node} for node in workflow.options] + [{u, v} for u, v, _ in workflow.edges]
    order, _ = _min_fill_order(workflow.options, workflow.edges)
    bound = 0
    for node in order:
        bucket = [scope for scope in scopes if node in scope]
        scopes = [scope for scope in scopes if node not in scope]
        union = set().union(*bucket)
        bound += math.prod(len(workflow.options[name]) for name in union)
        if bound > max_states:
            raise ValueError(f"factor enumeration bound exceeds {max_states} states")
        scopes.append(union - {node})
    result = solve_ports(workflow.options, workflow.edges, failed,
                         immutable=immutable, forced=forced)
    return RepairPlan(workflow.digest, tuple(sorted(result.assignment.items())),
                      tuple(sorted(result.changed)), result.cost, result.feasible,
                      result.states, result.max_width,
                      "" if result.feasible else "no operation-eligible, boundary-compatible assignment")


class ExecutionError(RuntimeError):
    def __init__(self, node, implementation, cause):
        super().__init__(f"{node}/{implementation}: {cause}")
        self.node, self.implementation, self.cause = node, implementation, cause


def execute(workflow, plan, handlers, external_inputs, validators):
    """Execute registered read-only handlers with input/output validation.

    Inputs map each node with external ports to a full list of port values;
    dependency-bound entries are overwritten. All nodes are rerun. Preflight
    rejects missing handlers/validators and write-capable declarations before
    calling any handler. Handler keys are (node, implementation).
    """
    if plan.workflow_digest != workflow.digest or not plan.feasible:
        raise ValueError("infeasible or mismatched repair plan")
    assignment = dict(plan.assignment)
    if len(assignment) != len(plan.assignment) or set(assignment) != set(workflow.options):
        raise ValueError("plan must assign every node exactly once")
    # Recheck public/mutable structures and assignment, not just a supplied hash.
    rebuilt = Workflow(workflow._spec)
    if (rebuilt.digest != workflow.digest or rebuilt.options != workflow.options
            or rebuilt.edges != workflow.edges or rebuilt.order != workflow.order
            or rebuilt.read_only != workflow.read_only):
        raise ValueError("workflow specification changed")
    from .ports import _prepare
    _, _, eligible, _ = _prepare(workflow.options, workflow.edges, (), (), assignment, True)
    chosen = {}
    for node, pool in eligible.items():
        if len(pool) != 1:
            raise ValueError(f"invalid selected implementation for {node}")
        item = pool[0]
        if not workflow.read_only[node, item.name]:
            raise ValueError(f"execution refuses non-read-only implementation: {node}/{item.name}")
        if not callable(handlers.get((node, item.name))):
            raise ValueError(f"missing handler for {node}/{item.name}")
        if any(not callable(validators.get(schema)) for schema in (*item.inputs, item.output)):
            raise ValueError(f"missing schema validator for {node}/{item.name}")
        chosen[node] = item
    for source, target, port in workflow.edges:
        if chosen[source].output.casefold() != chosen[target].inputs[port].casefold():
            raise ValueError("plan contains incompatible ports")
    bound = {(target, port): source for source, target, port in workflow.edges}
    arguments = {}
    for node, item in chosen.items():
        external = [port for port in range(len(item.inputs)) if (node, port) not in bound]
        values = external_inputs.get(node, [None] * len(item.inputs))
        if not isinstance(values, (list, tuple)) or len(values) != len(item.inputs):
            raise ValueError(f"external input arity mismatch at {node}")
        if external and node not in external_inputs:
            raise ValueError(f"external inputs missing at {node}")
        for port in external:
            if not validators[item.inputs[port]](values[port]):
                raise ValueError(f"external input violates {item.inputs[port]} at {node}:{port}")
        arguments[node] = deepcopy(list(values))
    outputs = {}
    for node in workflow.order:
        item, values = chosen[node], arguments[node]
        try:
            for port, schema in enumerate(item.inputs):
                if (node, port) in bound:
                    values[port] = deepcopy(outputs[bound[node, port]])
                if not validators[schema](values[port]):
                    raise ValueError(f"input port {port} violates schema {schema}")
            output = handlers[node, item.name](*values)
            if not validators[item.output](output):
                raise ValueError(f"output violates schema {item.output}")
            outputs[node] = output
        except Exception as error:
            raise ExecutionError(node, item.name, error) from error
    return outputs


def recover(workflow, handlers, external_inputs, validators, *, max_attempts=3, **limits):
    """Run, then replan after handler failures; never reuse the failed implementation.

    max_attempts counts original execution and subsequent attempts. Recovery
    reruns read-only predecessors. Returns (outputs, plan, failure history).
    """
    if max_attempts < 1:
        raise ValueError("max_attempts must be positive")
    failed, removed, history = set(), {}, []
    original_spec = workflow._spec
    current = workflow
    for _ in range(max_attempts):
        plan = plan_repair(current, failed, **limits)
        if not plan.feasible:
            raise ValueError(f"recovery is infeasible after {history}")
        try:
            outputs = execute(current, plan, handlers, external_inputs, validators)
            return outputs, plan, history
        except ExecutionError as error:
            history.append({"node": error.node, "implementation": error.implementation,
                            "error_type": type(error.cause).__name__})
            failed.add(error.node)
            removed.setdefault(error.node, set()).add(error.implementation)
            spec = json.loads(json.dumps(original_spec))
            for node, names in removed.items():
                # Keep originals for interface/operation reference; failed excludes them.
                spec["nodes"][node] = [item for item in spec["nodes"][node]
                                       if item.get("original") or item["name"] not in names]
            current = Workflow(spec)
    raise RuntimeError(f"recovery attempt limit reached: {history}")
