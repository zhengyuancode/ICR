"""Calibrate and hold out extensional tool-path contracts on PlanBench-XL.

The compiler uses only public interface metadata to enumerate candidate paths.
Calibration cases establish an empirical equivalence class. The disjoint test
cases are used only for evaluating that class, never for admission or ranking.
"""

from __future__ import annotations

import argparse
import collections
import hashlib
import json
import random
import sys
from pathlib import Path
from typing import Any

from .planbench_probe import ROOT, alternatives


def _observe(executor: Any, spec: dict[str, Any], value: Any) -> Any:
    result = executor.execute_tool(spec, {spec["input_datatypes"][0]: value})
    return result.output_value


def _path_output(executor: Any, by_name: dict[str, dict[str, Any]], path: list[str], value: Any) -> Any:
    for name in path:
        value = _observe(executor, by_name[name], value)
        if value is None:
            return None
    return value


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=20260925)
    args = parser.parse_args()
    sys.path.insert(0, str(ROOT.parents[1]))
    from env.domains.executor import RetailToolExecutor  # type: ignore[import-not-found]

    tools = json.loads((ROOT / "baseline_tools.json").read_text(encoding="utf-8"))
    database = json.loads((ROOT / "database.json").read_text(encoding="utf-8"))
    executor = RetailToolExecutor(database)
    by_name = {tool["name"]: {**tool, "domain": "retail", "tool_type": "baseline"} for tool in tools}
    rows = list(database["order_cases"].values())
    certificates = []
    rejections = []
    stats = collections.Counter()
    for failed in tools:
        if len(failed["input_datatypes"]) != 1:
            continue
        input_type = failed["input_datatypes"][0]
        distinct_values = {str(row[input_type]): row[input_type] for row in rows if row.get(input_type) is not None}
        values = sorted(distinct_values.items())
        split_seed = args.seed + int.from_bytes(hashlib.sha256(failed["name"].encode()).digest()[:4], "big")
        random.Random(split_seed).shuffle(values)
        calibration_values = [value for _, value in values[: len(values) // 2]]
        test_values = [value for _, value in values[len(values) // 2 :]]
        paths = alternatives(tools, failed, max_steps=5)
        for path in paths:
            calibration_comparable = 0
            calibration_errors = 0
            for value in calibration_values:
                try:
                    expected = _observe(executor, by_name[failed["name"]], value)
                except Exception:
                    continue  # Original contract is undefined on this input.
                if expected is None:
                    continue
                calibration_comparable += 1
                try:
                    actual = _path_output(executor, by_name, path, value)
                except Exception:
                    actual = None
                if actual != expected:
                    calibration_errors += 1
            stats["candidate_paths"] += 1
            if calibration_comparable < 10 or calibration_errors:
                stats["rejected_paths"] += 1
                stats["rejected_low_coverage" if calibration_comparable < 10 else "rejected_mismatch"] += 1
                rejected_test_comparable = 0
                rejected_test_matches = 0
                for value in test_values:
                    try:
                        expected = _observe(executor, by_name[failed["name"]], value)
                    except Exception:
                        continue
                    if expected is None:
                        continue
                    rejected_test_comparable += 1
                    try:
                        actual = _path_output(executor, by_name, path, value)
                    except Exception:
                        actual = None
                    rejected_test_matches += actual == expected
                stats["rejected_test_comparisons"] += rejected_test_comparable
                stats["rejected_test_matches"] += rejected_test_matches
                rejections.append(
                    {
                        "failed_tool": failed["name"],
                        "path": path,
                        "calibration_comparable": calibration_comparable,
                        "calibration_errors": calibration_errors,
                        "test_comparable": rejected_test_comparable,
                        "test_matches": rejected_test_matches,
                    }
                )
                continue
            test_comparable = 0
            test_matches = 0
            test_errors = 0
            for value in test_values:
                try:
                    expected = _observe(executor, by_name[failed["name"]], value)
                except Exception:
                    continue
                if expected is None:
                    continue
                test_comparable += 1
                try:
                    actual = _path_output(executor, by_name, path, value)
                except Exception:
                    actual = None
                test_matches += actual == expected
                test_errors += actual != expected
            stats["certified_paths"] += 1
            stats["test_comparisons"] += test_comparable
            stats["test_matches"] += test_matches
            stats["test_errors"] += test_errors
            certificates.append(
                {
                    "failed_tool": failed["name"],
                    "path": path,
                    "calibration_comparable": calibration_comparable,
                    "calibration_errors": calibration_errors,
                    "test_comparable": test_comparable,
                    "test_matches": test_matches,
                }
            )
    by_failed = collections.defaultdict(list)
    for item in certificates:
        by_failed[item["failed_tool"]].append(item)
    stats["certified_failed_tools"] = len(by_failed)
    stats["multicandidate_failed_tools"] = sum(len(items) > 1 for items in by_failed.values())
    stats["unique_candidate_failed_tools"] = sum(len(items) == 1 for items in by_failed.values())
    output = {
        "split_seed": args.seed,
        "split_rule": "For each failed tool, unique observed input values are shuffled with a name-derived seed, then split 50/50; no input value appears in both halves.",
        "stats": dict(stats),
        "certificates": certificates,
        "rejections": rejections,
    }
    suffix = "" if args.seed == 20260925 else f"_seed{args.seed}"
    out = Path(__file__).resolve().parent / "continuation_repair" / f"planbench_path_certificates{suffix}.json"
    out.write_text(json.dumps(output, indent=2), encoding="utf-8")
    runtime_out = out.with_name(f"planbench_calibrated_contracts{suffix}.json")
    runtime_out.write_text(
        json.dumps(
            {
                "split_seed": args.seed,
                "admission": "At least 10 defined, comparable calibration inputs and zero output mismatches.",
                "contracts": [
                    {
                        "failed_tool": item["failed_tool"],
                        "path": item["path"],
                        "calibration_comparable": item["calibration_comparable"],
                    }
                    for item in certificates
                ],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(json.dumps(stats, indent=2))
    print("output:", out)
    print("runtime contracts:", runtime_out)


if __name__ == "__main__":
    main()
