"""Check compositional path certificates against PlanBench-XL's native executor.

The certificate uses only the released tool signatures and finite retail table.
It does not inspect task reference paths, query answers, or blocker assignments.
"""

from __future__ import annotations

import collections
import hashlib
import json
import random
import sys
from pathlib import Path
from time import perf_counter

from .certify_planbench_paths import _observe, _path_output
from .planbench_probe import ROOT as DATA_ROOT, alternatives


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "research" / "continuation_repair" / "relational_certificate_study.json"
CONTRACTS = ROOT / "research" / "continuation_repair" / "planbench_relational_contracts.json"


def normalized(value: object) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False)


def functional_dependencies(rows: list[dict], signatures: set[tuple[str, str]]) -> dict[tuple[str, str], bool]:
    result = {}
    for source, target in signatures:
        mapping: dict[str, set[str]] = collections.defaultdict(set)
        for row in rows:
            if row.get(source) is not None and row.get(target) is not None:
                mapping[normalized(row[source])].add(normalized(row[target]))
        result[(source, target)] = bool(mapping) and all(len(outputs) == 1 for outputs in mapping.values())
    return result


def co_supports(
    rows: list[dict], source: str, target: str, intermediate: tuple[str, ...]
) -> bool:
    defined = {
        normalized(row[source])
        for row in rows
        if row.get(source) is not None and row.get(target) is not None
    }
    witnessed = {
        normalized(row[source])
        for row in rows
        if row.get(source) is not None
        and row.get(target) is not None
        and all(row.get(dtype) is not None for dtype in intermediate)
    }
    return bool(defined) and defined <= witnessed


def main() -> None:
    sys.path.insert(0, str(DATA_ROOT.parents[1]))
    from env.domains.executor import RetailToolExecutor  # type: ignore[import-not-found]

    tools = json.loads((DATA_ROOT / "baseline_tools.json").read_text(encoding="utf-8"))
    database = json.loads((DATA_ROOT / "database.json").read_text(encoding="utf-8"))
    rows = list(database["order_cases"].values())
    executor = RetailToolExecutor(database)
    by_name = {tool["name"]: {**tool, "domain": "retail", "tool_type": "baseline"} for tool in tools}
    unary = [tool for tool in tools if len(tool["input_datatypes"]) == 1]
    signatures = {(tool["input_datatypes"][0], tool["output_datatype"]) for tool in unary}
    compile_start = perf_counter()
    fds = functional_dependencies(rows, signatures)
    certificates = []
    for failed in unary:
        source, target = failed["input_datatypes"][0], failed["output_datatype"]
        for path in alternatives(tools, failed, max_steps=5):
            path_tools = [by_name[name] for name in path]
            intermediate = tuple(tool["output_datatype"] for tool in path_tools[:-1])
            edge_fds = all(fds[(tool["input_datatypes"][0], tool["output_datatype"])] for tool in path_tools)
            if fds[(source, target)] and edge_fds and co_supports(rows, source, target, intermediate):
                certificates.append({"failed_tool": failed["name"], "path": path})
    compile_seconds = perf_counter() - compile_start
    CONTRACTS.write_text(json.dumps({
        "admission": "Finite-relation projection, functional dependencies, and common row support",
        "contracts": certificates,
    }, indent=2), encoding="utf-8")
    admitted = {(item["failed_tool"], tuple(item["path"])) for item in certificates}
    calibration_only = {}
    for seed in (20260925, 20260926, 20260927):
        selected = set()
        for failed in unary:
            source, target = failed["input_datatypes"][0], failed["output_datatype"]
            values = sorted({str(row[source]): row[source] for row in rows if row.get(source) is not None}.items())
            split_seed = seed + int.from_bytes(hashlib.sha256(failed["name"].encode()).digest()[:4], "big")
            random.Random(split_seed).shuffle(values)
            chosen_inputs = {normalized(value) for _, value in values[: len(values) // 2]}
            visible_rows = [row for row in rows if row.get(source) is not None
                            and normalized(row[source]) in chosen_inputs]
            observed_fds = functional_dependencies(visible_rows, signatures)
            comparable = len({normalized(row[source]) for row in visible_rows
                              if row.get(target) is not None})
            if comparable < 10 or not observed_fds[(source, target)]:
                continue
            for path in alternatives(tools, failed, max_steps=5):
                path_tools = [by_name[name] for name in path]
                intermediate = tuple(tool["output_datatype"] for tool in path_tools[:-1])
                if all(observed_fds[(tool["input_datatypes"][0], tool["output_datatype"])]
                       for tool in path_tools) and co_supports(visible_rows, source, target, intermediate):
                    selected.add((failed["name"], tuple(path)))
        calibration_only[str(seed)] = {
            "admitted_paths": len(selected),
            "agreement_with_full_static": len(selected & admitted),
            "false_admitted_on_full_relation": len(selected - admitted),
            "missed_full_static": len(admitted - selected),
        }
    confusion = collections.Counter()
    comparisons = collections.Counter()
    counterexamples = []
    for failed in unary:
        source, target = failed["input_datatypes"][0], failed["output_datatype"]
        values = {normalized(row[source]): row[source] for row in rows if row.get(source) is not None}
        for path in alternatives(tools, failed, max_steps=5):
            certified = (failed["name"], tuple(path)) in admitted
            defined = mismatches = 0
            for value in values.values():
                try:
                    expected = _observe(executor, by_name[failed["name"]], value)
                except Exception:
                    continue
                if expected is None:
                    continue
                defined += 1
                try:
                    actual = _path_output(executor, by_name, path, value)
                except Exception:
                    actual = None
                mismatches += actual != expected
            equivalent = defined > 0 and mismatches == 0
            confusion[(certified, equivalent)] += 1
            comparisons["path_input"] += defined
            comparisons["path_input_mismatch"] += mismatches
            if certified and not equivalent:
                counterexamples.append({"failed": failed["name"], "path": path, "mismatches": mismatches})
    report = {
        "setting": "Native PlanBench-XL finite retail database; all public unary tool paths of length <=5",
        "assumptions": [
            "Each tool is a projection over the same underlying row relation.",
            "The original and every path edge satisfy the indicated functional dependency.",
            "Every defined original input has a row witness with all intermediate columns present.",
        ],
        "rows": len(rows),
        "unary_tools": len(unary),
        "distinct_edge_signatures": len(signatures),
        "functional_edge_signatures": sum(fds.values()),
        "static_compilation_seconds": compile_seconds,
        "static_tool_calls": 0,
        "calibration_rows_only": calibration_only,
        "certificate_vs_native_exact": {
            "certified_equivalent": confusion[(True, True)],
            "certified_inequivalent": confusion[(True, False)],
            "rejected_equivalent": confusion[(False, True)],
            "rejected_inequivalent": confusion[(False, False)],
        },
        "native_comparisons": dict(comparisons),
        "certificate_counterexamples": counterexamples,
    }
    OUTPUT.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
