"""Independent run-metadata and completeness audit for the paired transfer."""
from __future__ import annotations

import hashlib
import json

from .analyze_planbench_online import ROOT, load


def main() -> None:
    data = ROOT / "research/continuation_repair"
    protocol = json.loads((data / "planbench_seed43_transfer_protocol.json").read_text(encoding="utf-8"))
    run_root = ROOT / "external/PlanBench-XL-main/outputs/retail/ispa"
    ordered = [task.replace("task", "query") for task in protocol["task_ids"]]
    metadata = {arm: json.loads((run_root / protocol["arms"][arm] / "metadata.json").read_text(encoding="utf-8"))
                for arm in ("baseline", "instance_advice")}
    configs = {arm: dict(item["config"]) for arm, item in metadata.items()}
    for config in configs.values():
        config.pop("output", None)
        config.pop("run_id", None)
    if configs["baseline"] != configs["instance_advice"]:
        raise RuntimeError("Run configurations differ beyond output path and run ID")
    if any(item["query_count"] != 102 or item["model_name"] != "deepseek-flash"
           for item in metadata.values()):
        raise RuntimeError("Unexpected query count or model")
    if configs["baseline"]["blocker"]["seed"] != 43 or configs["baseline"]["runtime"]["max_steps"] != 100:
        raise RuntimeError("Frozen blocker seed or step cap changed")
    rows = {arm: load(protocol["arms"][arm]) for arm in metadata}
    if any(set(arm_rows) != set(ordered) for arm_rows in rows.values()):
        raise RuntimeError("Incomplete paired task IDs")
    if any(row["status"] not in ("success", "failed") for arm_rows in rows.values() for row in arm_rows.values()):
        raise RuntimeError("Unresolved infrastructure status in final results")
    source_mismatches = [name for name, digest in protocol["source_sha256"].items()
                         if hashlib.sha256((ROOT / name).read_bytes()).hexdigest() != digest]
    if source_mismatches:
        raise RuntimeError(f"Frozen code/data changed: {source_mismatches}")
    result = {
        "protocol": "planbench_seed43_transfer_protocol.json",
        "paired_task_count": len(ordered),
        "confirmation_task_count": len(ordered[30:]),
        "model_name": "deepseek-flash",
        "blocker_seed": 43,
        "max_steps": 100,
        "metadata_configuration_identical_except_output_and_run_id": True,
        "same_query_ids": True,
        "final_rows_have_no_infrastructure_status": True,
        "frozen_source_hashes_match": True,
        "source_mismatches": source_mismatches,
    }
    target = data / "planbench_seed43_fairness_audit.json"
    target.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
