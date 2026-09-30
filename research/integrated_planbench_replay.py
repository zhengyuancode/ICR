"""Executor-backed, post-review integration of joint scope and input certificates.

Selection uses frozen public tool signatures and precompiled certificate support,
never task reference paths or native-executor outcomes. Native outputs are used
only after candidate/workflow enumeration for an independent implementation audit.
"""
from __future__ import annotations

from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
import sys

from experiments.joint_repair import Choice, solve_tree
from research.certify_planbench_paths import _observe, _path_output
from research.compile_planbench_instance_contracts import input_digest


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "external/PlanBench-XL-main/src/data/retail"
RESULT = ROOT / "research/continuation_repair/integrated_replay_20260930.json"


def read(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> None:
    sys.path.insert(0, str(DATA.parents[1]))
    from env.domains.executor import RetailToolExecutor  # type: ignore[import-not-found]

    tools = read(DATA / "baseline_tools.json")
    database = read(DATA / "database.json")
    rows = list(database["order_cases"].values())
    unary = [t for t in tools if len(t["input_datatypes"]) == 1]
    by_name = {t["name"]: {**t, "domain": "retail", "tool_type": "baseline"} for t in unary}
    global_cert = read(ROOT / "research/continuation_repair/planbench_relational_contracts.json")
    observed_cert = read(ROOT / "research/continuation_repair/planbench_instance_contracts.json")
    global_paths = {(r["failed_tool"], tuple(r["path"])) for r in global_cert["contracts"]}
    executor = RetailToolExecutor(database)
    counts = Counter()
    workflow_rows = []
    for cert in observed_cert["contracts"]:
        failed = by_name[cert["failed_tool"]]
        path = cert["path"]
        if (cert["failed_tool"], tuple(path)) in global_paths:
            continue
        source, target = failed["input_datatypes"][0], failed["output_datatype"]
        replacement_intermediate = by_name[path[0]]["output_datatype"]
        support = set(cert["input_hashes"])
        for f in unary:
            if f["input_datatypes"][0] != source:
                continue
            original_intermediate = f["output_datatype"]
            if original_intermediate == replacement_intermediate:
                continue
            for c in unary:
                if c["input_datatypes"][0] != original_intermediate or c["output_datatype"] != target:
                    continue
                if f["name"] in path or c["name"] in path:
                    continue
                counts["structural_workflows"] += 1
                choices = {
                    "f": [
                        Choice("original_f", source, original_intermediate, original=True),
                        Choice("replacement_f", source, replacement_intermediate),
                    ],
                    "c": [
                        Choice("original_c", original_intermediate, target, original=True),
                        Choice("replacement_c", replacement_intermediate, target),
                    ],
                }
                joint = solve_tree(choices, [("f", "c")], {"f"}, require_function_match=False)
                producer_only = solve_tree({"f": choices["f"], "c": choices["c"][:1]},
                                           [("f", "c")], {"f"}, require_function_match=False)
                if not joint.feasible or joint.changed != {"f", "c"} or producer_only.feasible:
                    raise AssertionError("joint-scope solver does not force the two-node repair")
                local = Counter()
                inputs = {input_digest(r[source]): r[source] for r in rows if r.get(source) is not None}
                for digest, value in inputs.items():
                    try:
                        original = _path_output(executor, by_name, [f["name"], c["name"]], value)
                        direct = _observe(executor, by_name[cert["failed_tool"]], value)
                    except Exception:
                        continue
                    if original is None or direct is None:
                        continue
                    # A valid original workflow must match the published direct operation.
                    if original != direct:
                        local["original_chain_mismatch"] += 1
                        continue
                    local["defined_original_inputs"] += 1
                    admitted = digest in support
                    local["observed_admitted"] += admitted
                    local["observed_rejected"] += not admitted
                    try:
                        replacement = _path_output(executor, by_name, path, value)
                    except Exception:
                        replacement = None
                    equal = replacement == original
                    local["observed_correct"] += admitted and equal
                    local["observed_wrong"] += admitted and not equal
                    local["type_only_wrong"] += not equal
                    local["globally_rejected_but_correct"] += equal
                counts.update(local)
                workflow_rows.append({
                    "original": [f["name"], c["name"]],
                    "replacement": path,
                    "failed_direct_tool": cert["failed_tool"],
                    "types": [source, original_intermediate, replacement_intermediate, target],
                    "structural_region": sorted(joint.changed),
                    "counts": dict(local),
                })
    output = {
        "protocol": "integrated_replay_protocol_20260930.json",
        "scope": "Post-review exploratory replay; PlanBench-XL released native retail executor",
        "catalog_sha256": sha256((DATA / "baseline_tools.json").read_bytes()).hexdigest(),
        "relation_sha256": sha256((DATA / "database.json").read_bytes()).hexdigest(),
        "counts": dict(counts),
        "workflows": workflow_rows,
    }
    RESULT.write_text(json.dumps(output, indent=2), encoding="utf-8")
    print(json.dumps({"counts": output["counts"], "n_workflows": len(workflow_rows)}, indent=2))


if __name__ == "__main__":
    main()
