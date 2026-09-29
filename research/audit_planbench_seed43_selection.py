"""Check the frozen seed-43 structural cohort against the actual run config."""
from __future__ import annotations

import json
import sys
from pathlib import Path

from .planbench_probe import ROOT as RETAIL
from .run_planbench_pilot import BENCH, load_config


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "research/continuation_repair"


def main() -> None:
    sys.path.insert(0, str(RETAIL.parents[1]))
    from env.events.blocker import generate_blocker_replacements_by_task  # type: ignore[import-not-found]

    protocol = json.loads((DATA / "planbench_seed43_transfer_protocol.json").read_text(encoding="utf-8"))
    config = load_config(
        BENCH / "src/env/config/runs/retail/gpt-5.4/retail_gpt5.4_blocker.yaml",
        cli_overrides={"blocker.seed": 43, "blocker.noise_mode": "fixed",
                       "blocker.fixed_noise_type": "explicit failures",
                       "blocker.fixed_noise_types": None},
    )
    b = config.blocker
    paths = json.loads((RETAIL / "paths_set_catalog.json").read_text(encoding="utf-8"))
    blocked = generate_blocker_replacements_by_task(
        paths_set_catalog=paths,
        baseline_tools_path=RETAIL / "baseline_tools.json",
        tasks_path=RETAIL / "tasks.json",
        selection_mode=b.selection_mode,
        block_n_per_task=b.block_n_per_task,
        target_remaining_paths=b.target_remaining_paths,
        target_remaining_ratio=b.target_remaining_ratio,
        remaining_tolerance=b.remaining_tolerance,
        min_remaining_paths=b.min_remaining_paths,
        remaining_path_length_objective=b.remaining_path_length_objective,
        blocking_edge_count_objective=b.blocking_edge_count_objective,
        seed=b.seed,
        noise_mode=b.noise_mode,
        fixed_noise_type=b.fixed_noise_type,
        fixed_noise_types=b.fixed_noise_types,
        multi_noise_count=b.multi_noise_count,
        max_combo_candidates=b.max_combo_candidates,
        max_cover_size=b.max_cover_size,
    )
    contracts = json.loads((DATA / "planbench_calibrated_contracts.json").read_text(encoding="utf-8"))["contracts"]
    by_failed: dict[str, list[list[str]]] = {}
    for item in contracts:
        by_failed.setdefault(item["failed_tool"], []).append(item["path"])
    mismatches = []
    for row in protocol["structural_options"]:
        task_id = row["task_id"]
        actual = set(blocked.get(task_id, {}))
        expected = {item["failed_tool"] for item in row["structural_options"]}
        if not expected.issubset(actual) or not any(
            path and all(name not in actual for name in path)
            for failed in expected for path in by_failed.get(failed, ())
        ):
            mismatches.append(task_id)
    report = {"frozen_tasks": len(protocol["task_ids"]),
              "runtime_blocker_seed": b.seed,
              "frozen_eligible_failed_tools_absent_from_runtime": mismatches}
    (DATA / "planbench_seed43_selection_audit.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report))
    if mismatches:
        raise AssertionError("Frozen structural selection differs from runtime blockers")


if __name__ == "__main__":
    main()
