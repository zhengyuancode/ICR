"""Paired development analysis of input-indexed versus global certificates."""
from __future__ import annotations

import json
from collections import Counter

from .analyze_planbench_online import ROOT, load
from .analyze_planbench_r3_failure_forks import contrast


def first_event(row: dict) -> dict | None:
    return next((event for event in row["trace"] if event.get("action") == "icr_recovery"), None)


def main() -> None:
    data = ROOT / "research/continuation_repair"
    protocol = json.loads((data / "planbench_r3_instance_fork_protocol.json").read_text(encoding="utf-8"))
    opportunity = json.loads((data / "planbench_instance_effect_opportunity.json").read_text(encoding="utf-8"))
    cohort = json.loads((data / "planbench_r3_failure_fork_cohort.json").read_text(encoding="utf-8"))
    ids = {entry["query_id"] for entry in cohort["entries"]}
    exposed = sorted(row["query_id"] for row in opportunity["failure_rows"] if row["extra_input_safe_paths"] > 0)
    if len(ids) != 29 or len(exposed) != 11 or not set(exposed) <= ids:
        raise ValueError("Frozen failure/exposure cohort changed")
    native = load(protocol["comparison_run_ids"]["native"])
    global_advice = load(protocol["comparison_run_ids"]["global_advice"])
    instance = load(protocol["run_ids"]["instance_advice"])
    typed = load(protocol["comparison_run_ids"]["type_only_advice"])
    if any(set(rows) != ids for rows in (native, global_advice, instance, typed)):
        raise ValueError("One run is incomplete or has a different task set")
    pairs = Counter()
    for q in sorted(ids):
        old = first_event(global_advice[q])
        new = first_event(instance[q])
        pairs[(bool(old), bool(new), bool(old and new and old["path"] == new["path"]))] += 1
    result = {
        "role": protocol["role"],
        "primary_all_frozen_failures": contrast(global_advice, instance, sorted(ids), seed=20261010),
        "secondary_vs_native": contrast(native, instance, sorted(ids), seed=20261011),
        "secondary_vs_type_only": contrast(typed, instance, sorted(ids), seed=20261012),
        "structural_exposure_descriptive": contrast(global_advice, instance, exposed, seed=20261013),
        "first_recovery_event_pairs": [
            {"global_event": key[0], "instance_event": key[1],
             "same_first_path_if_both": key[2], "tasks": n}
            for key, n in sorted(pairs.items())
        ],
        "task_rows": [{"query_id": q, "exposed": q in exposed,
                       "global": global_advice[q]["status"],
                       "instance": instance[q]["status"],
                       "native": native[q]["status"],
                       "type_only": typed[q]["status"],
                       "global_path": (first_event(global_advice[q]) or {}).get("path"),
                       "instance_path": (first_event(instance[q]) or {}).get("path")}
                      for q in sorted(ids)],
    }
    target = data / "planbench_r3_instance_fork_analysis.json"
    target.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps({key: value for key, value in result.items() if key != "task_rows"}, indent=2))


if __name__ == "__main__":
    main()
