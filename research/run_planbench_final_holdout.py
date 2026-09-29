"""Run a frozen untouched-task comparison of native and recovery policies."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

from . import run_planbench_pilot
from .planbench_instance_advice import PlanBenchInstanceAdviceRunner
from .planbench_typed_advice import PlanBenchTypedAdviceRunner


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "research/continuation_repair"
COHORT = DATA / "planbench_final_untouched_holdout.json"
PROTOCOL = DATA / "planbench_final_holdout_protocol.json"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--variant", choices=("baseline", "global_advice", "instance_advice", "type_only_advice"), required=True)
    args = parser.parse_args()
    cohort = json.loads(COHORT.read_text(encoding="utf-8"))
    protocol = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    if cohort["task_ids"] != protocol["task_ids"] or len(cohort["task_ids"]) != 21:
        raise RuntimeError("Frozen final cohort changed")
    for relative, expected in protocol["source_sha256"].items():
        if hashlib.sha256((ROOT / relative).read_bytes()).hexdigest() != expected:
            raise RuntimeError(f"Frozen final source changed: {relative}")
    catalog = json.loads((DATA / "planbench_instance_contracts.json").read_text(encoding="utf-8"))
    bench = ROOT / "external/PlanBench-XL-main/src/data/retail"
    if hashlib.sha256((bench / "database.json").read_bytes()).hexdigest() != catalog["database_sha256"]:
        raise RuntimeError("Instance certificate database snapshot is stale")
    if hashlib.sha256((bench / "baseline_tools.json").read_bytes()).hexdigest() != catalog["tool_catalog_sha256"]:
        raise RuntimeError("Instance certificate tool catalog is stale")
    variant = args.variant
    if variant == "instance_advice":
        run_planbench_pilot.PlanBenchRecoveryRunner = PlanBenchInstanceAdviceRunner
    elif variant == "type_only_advice":
        run_planbench_pilot.PlanBenchRecoveryRunner = PlanBenchTypedAdviceRunner
    native_variant = "baseline" if variant == "baseline" else "advice"
    sys.argv = ["run_planbench_pilot", "--variant", native_variant,
                "--run-id", protocol["run_ids"][variant],
                "--task-ids", ",".join(cohort["task_ids"]),
                "--max-steps", "100", "--workers", "4"]
    run_planbench_pilot.main()


if __name__ == "__main__":
    main()
