"""Run the frozen never-used task cohort under an independent blocker seed."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

from . import run_planbench_pilot as pilot
from .planbench_instance_advice import PlanBenchInstanceAdviceRunner


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "research/continuation_repair"
PROTOCOL = DATA / "planbench_seed43_transfer_protocol.json"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--variant", choices=("baseline", "global_advice", "instance_advice"), required=True)
    args = parser.parse_args()
    protocol = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    for name, digest in protocol["source_sha256"].items():
        if hashlib.sha256((ROOT / name).read_bytes()).hexdigest() != digest:
            raise RuntimeError(f"Frozen source changed: {name}")
    if len(protocol["task_ids"]) != protocol["n_tasks"] or len(set(protocol["task_ids"])) != protocol["n_tasks"]:
        raise RuntimeError("Frozen cohort changed")

    original_load_config = pilot.load_config

    def load_seed43(path: Path, *, cli_overrides: dict[str, Any]) -> Any:
        overrides = dict(cli_overrides)
        overrides["blocker.seed"] = protocol["blocker_seed"]
        config = original_load_config(path, cli_overrides=overrides)
        if config.blocker.seed != 43:
            raise RuntimeError("Blocker seed override failed")
        return config

    pilot.load_config = load_seed43
    if args.variant == "instance_advice":
        pilot.PlanBenchRecoveryRunner = PlanBenchInstanceAdviceRunner
        catalog = json.loads((DATA / "planbench_instance_contracts.json").read_text(encoding="utf-8"))
        retail = ROOT / "external/PlanBench-XL-main/src/data/retail"
        if hashlib.sha256((retail / "database.json").read_bytes()).hexdigest() != catalog["database_sha256"]:
            raise RuntimeError("Instance certificate database snapshot changed")
        if hashlib.sha256((retail / "baseline_tools.json").read_bytes()).hexdigest() != catalog["tool_catalog_sha256"]:
            raise RuntimeError("Instance certificate tool catalog changed")
    native_variant = "baseline" if args.variant == "baseline" else "advice"
    sys.argv = ["run_planbench_pilot", "--variant", native_variant,
                "--run-id", protocol["arms"][args.variant],
                "--task-ids", ",".join(protocol["task_ids"]),
                "--max-steps", str(protocol["runtime"]["max_steps"]),
                "--workers", str(protocol["runtime"]["workers_per_arm"])]
    pilot.main()


if __name__ == "__main__":
    main()
