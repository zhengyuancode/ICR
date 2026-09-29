"""Compare bounded, same-catalog route decisions on all defined retail inputs.

The decision policies see only the released signatures and the precompiled
global or observed-input contracts. The native executor is used afterward to
score their selected routes; task answers and reference paths are never read.
"""
from __future__ import annotations

import hashlib
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

from .compile_planbench_instance_contracts import input_digest
from .planbench_probe import ROOT as RETAIL, alternatives
from .relational_certificate_study import normalized

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "research/continuation_repair"
OUTPUT = DATA / "planbench_route_decisions.json"


def main() -> None:
    sys.path.insert(0, str(RETAIL.parents[1]))
    from env.domains.executor import RetailToolExecutor  # type: ignore[import-not-found]

    tools = json.loads((RETAIL / "baseline_tools.json").read_text(encoding="utf-8"))
    database = json.loads((RETAIL / "database.json").read_text(encoding="utf-8"))
    rows = list(database["order_cases"].values())
    specs = {item["name"]: {**item, "domain": "retail", "tool_type": "baseline"} for item in tools}
    executor = RetailToolExecutor(database)
    global_set = {(item["failed_tool"], tuple(item["path"])) for item in json.loads(
        (DATA / "planbench_relational_contracts.json").read_text(encoding="utf-8"))["contracts"]}
    instance_index = {(item["failed_tool"], tuple(item["path"])): set(item["input_hashes"])
                      for item in json.loads((DATA / "planbench_instance_contracts.json").read_text(
                          encoding="utf-8"))["contracts"]}
    totals = Counter()
    profiles: dict[str, Counter] = defaultdict(Counter)
    examples = []
    for failed in tools:
        if len(failed["input_datatypes"]) != 1:
            continue
        name = failed["name"]
        source = failed["input_datatypes"][0]
        candidates = sorted((tuple(path) for path in alternatives(tools, failed, max_steps=5)),
                            key=lambda path: (len(path), path))
        if not candidates:
            continue
        values = {normalized(row[source]): row[source] for row in rows if row.get(source) is not None}
        for value in values.values():
            try:
                original = executor.execute_tool(specs[name], {source: value}).output_value
            except Exception:
                continue
            if original is None:
                continue
            digest = input_digest(value)
            native_outputs = {}
            for path in candidates:
                actual = value
                try:
                    for tool_name in path:
                        spec = specs[tool_name]
                        actual = executor.execute_tool(spec, {
                            spec["input_datatypes"][0]: actual}).output_value
                        if actual is None:
                            break
                except Exception:
                    actual = None
                native_outputs[path] = actual
                totals["oracle_path_input_pairs"] += 1
                if actual != original:
                    totals["oracle_wrong_pairs"] += 1
            oracle_choice = next((path for path in candidates if native_outputs[path] == original), None)
            choices = {
                "type_only": candidates[0],
                "global": next((path for path in candidates if (name, path) in global_set), None),
                "input_indexed": next((path for path in candidates
                                        if digest in instance_index.get((name, path), ())), None),
            }
            if choices["input_indexed"] != oracle_choice:
                raise AssertionError(f"Input-indexed route differs from native shortest-safe oracle: {name}")
            totals["defined_decisions"] += 1
            for policy, path in choices.items():
                profile = profiles[policy]
                if path is None:
                    profile["no_route"] += 1
                    continue
                actual = native_outputs[path]
                profile["route_selected"] += 1
                profile["calls_selected"] += len(path)
                profile["native_correct" if actual == original else "native_wrong"] += 1
                if policy == "input_indexed" and actual != original:
                    raise AssertionError(f"Unsound input-indexed choice: {name}")
                if policy == "global" and actual != original:
                    raise AssertionError(f"Unsound global choice: {name}")
            if choices["global"] is None and choices["input_indexed"] is not None:
                totals["new_safe_decisions"] += 1
                if len(examples) < 5:
                    examples.append({"failed_tool": name, "input_datatype": source,
                                     "input": value, "input_indexed_route": choices["input_indexed"]})
            if choices["global"] is not None and choices["input_indexed"] is not None:
                difference = len(choices["global"]) - len(choices["input_indexed"])
                if difference > 0:
                    totals["shorter_safe_decisions"] += 1
                    totals["calls_saved_by_shorter_safe_decisions"] += difference
                elif difference < 0:
                    raise AssertionError("Input-indexed route longer than global on same options")
    payload = {
        "scope": "Every defined failed-tool input over public retail rows, all typed paths of length 2--5",
        "selection": "Shortest path, lexicographic tie break; identical typed candidates for all policies",
        "native_executor_only_for_scoring": True,
        "source_sha256": {
            str(path.relative_to(ROOT)).replace("\\", "/"): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in (RETAIL / "baseline_tools.json", RETAIL / "database.json",
                         DATA / "planbench_relational_contracts.json",
                         DATA / "planbench_instance_contracts.json", Path(__file__))
        },
        "totals": dict(totals),
        "policies": {name: dict(counter) for name, counter in profiles.items()},
        "first_new_safe_examples": examples,
    }
    OUTPUT.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in payload.items() if key != "first_new_safe_examples"}, indent=2))


if __name__ == "__main__":
    main()
