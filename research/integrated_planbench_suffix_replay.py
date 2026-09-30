"""Audit unchanged native-executor continuations after integrated repair.

Enumerate every one-call downstream consumer of the already enumerated
integration workflows. Selection uses tool signatures; executor outputs are
read only after enumeration. This is exploratory and has no model API calls.
"""
from __future__ import annotations

from collections import Counter
import json
from pathlib import Path
import sys

from research.certify_planbench_paths import _path_output
from research.compile_planbench_instance_contracts import input_digest


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "external/PlanBench-XL-main/src/data/retail"
INTEGRATED = ROOT / "research/continuation_repair/integrated_replay_20260930.json"
OUTPUT = ROOT / "research/continuation_repair/integrated_suffix_replay_20260930.json"


def read(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> None:
    sys.path.insert(0, str(DATA.parents[1]))
    from env.domains.executor import RetailToolExecutor  # type: ignore[import-not-found]

    database = read(DATA / "database.json")
    tools = read(DATA / "baseline_tools.json")
    by_name = {t["name"]: {**t, "domain": "retail", "tool_type": "baseline"}
               for t in tools if len(t["input_datatypes"]) == 1}
    rows = list(database["order_cases"].values())
    certs = read(ROOT / "research/continuation_repair/planbench_instance_contracts.json")
    support = {(c["failed_tool"], tuple(c["path"])): set(c["input_hashes"])
               for c in certs["contracts"]}
    executor = RetailToolExecutor(database)
    totals = Counter()
    details = []
    for config in read(INTEGRATED)["workflows"]:
        original = config["original"]
        replacement = config["replacement"]
        source, _, _, target = config["types"]
        downstream = sorted(t["name"] for t in by_name.values()
                            if t["input_datatypes"] == [target]
                            and t["name"] not in {*original, *replacement})
        inputs = {input_digest(row[source]): row[source]
                  for row in rows if row.get(source) is not None}
        admitted = support[(config["failed_direct_tool"], tuple(replacement))]
        for consumer in downstream:
            local = Counter()
            for digest, value in inputs.items():
                try:
                    original_out = _path_output(
                        executor, by_name, original + [consumer], value)
                except Exception:
                    continue
                if original_out is None:
                    continue
                local["defined_original"] += 1
                if digest not in admitted:
                    local["certificate_rejected"] += 1
                    continue
                local["admitted"] += 1
                try:
                    repaired_out = _path_output(
                        executor, by_name, replacement + [consumer], value)
                except Exception:
                    repaired_out = None
                local["same_final_value"] += repaired_out == original_out
                local["wrong_or_undefined_final_value"] += repaired_out != original_out
            totals.update(local)
            details.append({"original": original, "replacement": replacement,
                            "unchanged_consumer": consumer, "counts": dict(local)})
    totals["three_call_configurations"] = len(details)
    totals["distinct_downstream_tools"] = len({d["unchanged_consumer"] for d in details})
    OUTPUT.write_text(json.dumps({"role": "Post-review exploratory continuation audit",
                                  "counts": dict(totals), "configurations": details}, indent=2),
                      encoding="utf-8")
    print(json.dumps(dict(totals), indent=2))


if __name__ == "__main__":
    main()
