"""Observed-input evidence for unary projections over a fixed JSON relation.

None and missing cells are unavailable. Values use typed canonical JSON equality.
No model, tool description or type match is used to infer operation equivalence.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, asdict
from hashlib import sha256
import json
import math


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


class Snapshot:
    """Private copy of JSON records; the digest binds data and column semantics."""
    def __init__(self, rows):
        self._rows = json.loads(canonical(rows))
        if not isinstance(self._rows, list) or not all(isinstance(row, dict) for row in self._rows):
            raise ValueError("snapshot must be a list of JSON objects")
        self.digest = sha256(canonical(self._rows).encode()).hexdigest()
        self._index = {}
        for number, row in enumerate(self._rows):
            for column, value in row.items():
                if value is not None:
                    self._index.setdefault((column, canonical(value)), set()).add(number)

    def rows(self):
        return deepcopy(self._rows)

    def lookup(self, source, target, value):
        """Require one unique non-null result; duplicate identical values are OK."""
        if value is None:
            raise ValueError("null_input")
        witnesses = self._index.get((source, canonical(value)), set())
        outputs = {canonical(self._rows[i][target]): self._rows[i][target]
                   for i in witnesses if self._rows[i].get(target) is not None}
        if len(outputs) != 1:
            raise ValueError("missing_value" if not outputs else "ambiguous_value")
        return deepcopy(next(iter(outputs.values())))


@dataclass(frozen=True)
class Projection:
    name: str
    source: str
    target: str
    cost: float = 1

    def __post_init__(self):
        if not all(isinstance(x, str) and x for x in (self.name, self.source, self.target)):
            raise ValueError("projection IDs and columns must be nonempty strings")
        if isinstance(self.cost, bool) or not isinstance(self.cost, (int, float)) or not math.isfinite(self.cost) or self.cost < 0:
            raise ValueError("projection cost must be finite and nonnegative")


@dataclass(frozen=True)
class Certificate:
    snapshot_digest: str
    catalog_digest: str
    source: str
    target: str
    input_json: str
    output_json: str
    path: tuple[str, ...]
    witness_rows: tuple[int, ...]
    mode: str

    def to_dict(self):
        result = asdict(self)
        result["input"] = json.loads(result.pop("input_json"))
        result["output"] = json.loads(result.pop("output_json"))
        result["authority"] = "read-only projection execution on the bound snapshot"
        return result


@dataclass(frozen=True)
class Admission:
    admitted: bool
    reason: str
    certificate: Certificate | None = None

    def to_dict(self):
        return {"admitted": self.admitted, "reason": self.reason,
                "certificate": self.certificate.to_dict() if self.certificate else None}


class RelationalRecovery:
    """Find, rank, certify and execute projection routes on one snapshot.

    Catalog entries are trusted unary relation projections, not arbitrary APIs.
    The target operation is explicitly defined by its source/target columns.
    Bounded search considers simple column paths. Hitting the candidate limit
    raises instead of presenting a partial search as an optimal solution.
    """
    def __init__(self, snapshot, tools):
        self.snapshot = snapshot
        pool = tuple(tools)
        if len({tool.name for tool in pool}) != len(pool):
            raise ValueError("duplicate tool ID")
        self.tools = {tool.name: tool for tool in pool}
        self.catalog_digest = sha256(canonical([asdict(tool) for tool in sorted(pool, key=lambda t: t.name)]).encode()).hexdigest()

    def _path(self, source, target, path):
        if not path:
            raise ValueError("empty_path")
        current = source
        for name in path:
            if name not in self.tools:
                raise ValueError("unknown_tool")
            tool = self.tools[name]
            if tool.source != current:
                raise ValueError("incompatible_path")
            current = tool.target
        if current != target:
            raise ValueError("wrong_target_operation")

    def _evidence(self, source, target, value, path):
        expected = self.snapshot.lookup(source, target, value)
        current, column = value, source
        witnesses = set(self.snapshot._index.get((source, canonical(value)), ()))
        for name in path:
            tool = self.tools[name]
            current = self.snapshot.lookup(tool.source, tool.target, current)
            column = tool.target
            witnesses &= self.snapshot._index.get((column, canonical(current)), set())
        if canonical(current) != canonical(expected):
            raise ValueError("target_value_mismatch")
        if not witnesses:
            raise ValueError("no_common_record_witness")
        return expected, tuple(sorted(witnesses))

    def certify(self, source, target, value, path, *, mode="observed"):
        if mode not in {"observed", "global"}:
            raise ValueError("mode must be observed or global")
        path = tuple(path)
        try:
            self._path(source, target, path)
            output, witnesses = self._evidence(source, target, value, path)
            if mode == "global":
                # A global certificate additionally checks unary FDs at each edge
                # and route coverage for every non-null source in this snapshot.
                for name in path:
                    tool = self.tools[name]
                    values = {canonical(row[tool.source]) for row in self.snapshot._rows
                              if row.get(tool.source) is not None}
                    for key in values:
                        self.snapshot.lookup(tool.source, tool.target, json.loads(key))
                inputs = {canonical(row[source]) for row in self.snapshot._rows
                          if row.get(source) is not None}
                for key in inputs:
                    self._evidence(source, target, json.loads(key), path)
            return Admission(True, "admitted", Certificate(
                self.snapshot.digest, self.catalog_digest, source, target,
                canonical(value), canonical(output), path, witnesses, mode))
        except ValueError as error:
            return Admission(False, str(error))

    def candidates(self, source, target, *, excluded=(), max_hops=4, max_candidates=1000, max_expansions=100_000):
        if max_hops < 1 or max_candidates < 1 or max_expansions < 1:
            raise ValueError("positive search limits required")
        excluded = set(excluded)
        if not excluded <= self.tools.keys():
            raise ValueError("unknown excluded tool")
        found, stack, expansions = [], [(source, (), frozenset({source}))], 0
        while stack:
            column, path, seen = stack.pop()
            expansions += 1
            if expansions > max_expansions:
                raise ValueError("search expansion limit reached; increase limit or restrict catalog")
            if len(path) >= max_hops:
                continue
            for tool in sorted(self.tools.values(), key=lambda t: t.name):
                if tool.name in excluded or tool.source != column or tool.target in seen:
                    continue
                new = (*path, tool.name)
                if tool.target == target:
                    found.append(new)
                    if len(found) > max_candidates:
                        raise ValueError("candidate limit reached; increase limit or restrict catalog")
                else:
                    stack.append((tool.target, new, seen | {tool.target}))
        return sorted(found, key=lambda path: (sum(self.tools[name].cost for name in path), len(path), path))

    def repair(self, source, target, value, *, excluded=(), mode="observed", max_hops=4, max_candidates=1000, max_expansions=100_000):
        """Return least-cost admitted route within the declared search bounds."""
        rejected = []
        for path in self.candidates(source, target, excluded=excluded, max_hops=max_hops,
                                    max_candidates=max_candidates, max_expansions=max_expansions):
            admission = self.certify(source, target, value, path, mode=mode)
            if admission.admitted:
                return admission, rejected
            rejected.append({"path": list(path), "reason": admission.reason})
        return Admission(False, "no_admitted_route_within_search_bounds"), rejected

    def execute(self, certificate, *, current_snapshot=None):
        """Revalidate and execute read-only projections; reject stale/altered packets.

        current_snapshot must be supplied by the application if its data may
        change. Execution uses that immutable snapshot object throughout.
        """
        snapshot = current_snapshot if current_snapshot is not None else self.snapshot
        if snapshot.digest != certificate.snapshot_digest:
            raise ValueError("stale_snapshot: obtain a new certificate")
        checked = RelationalRecovery(snapshot, self.tools.values()).certify(
            certificate.source, certificate.target, json.loads(certificate.input_json),
            certificate.path, mode=certificate.mode)
        if not checked.admitted or checked.certificate != certificate:
            raise ValueError("certificate revalidation failed")
        value = json.loads(certificate.input_json)
        for name in certificate.path:
            tool = self.tools[name]
            value = snapshot.lookup(tool.source, tool.target, value)
        if canonical(value) != certificate.output_json:
            raise ValueError("execution result differs from certified value")
        return value
