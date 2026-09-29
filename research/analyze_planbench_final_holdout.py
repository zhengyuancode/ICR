"""Prospectively specified paired analysis of the final 21 untouched tasks."""
from __future__ import annotations

import json
from collections import Counter

from .analyze_planbench_online import ROOT, interval, load
from .analyze_planbench_r3_failure_forks import contrast


def main() -> None:
    data = ROOT / "research/continuation_repair"
    cohort = json.loads((data / "planbench_final_untouched_holdout.json").read_text(encoding="utf-8"))
    protocol = json.loads((data / "planbench_final_holdout_protocol.json").read_text(encoding="utf-8"))
    ordered = [task.replace("task", "query") for task in cohort["task_ids"]]
    if len(ordered) != 21 or len(set(ordered)) != 21:
        raise ValueError("Invalid final holdout")
    runs = {arm: load(run_id) for arm, run_id in protocol["run_ids"].items()}
    for arm, rows in runs.items():
        if set(rows) != set(ordered):
            raise ValueError(f"Incomplete final arm: {arm}")
    primary = contrast(runs["global_advice"], runs["instance_advice"], ordered, seed=20261014)
    secondary = {
        "instance_minus_native": contrast(runs["baseline"], runs["instance_advice"], ordered, seed=20261015),
        "instance_minus_type_only": contrast(runs["type_only_advice"], runs["instance_advice"], ordered, seed=20261016),
        "global_minus_native": contrast(runs["baseline"], runs["global_advice"], ordered, seed=20261017),
    }
    requests = {arm: sum(rows[q]["steps"] for q in ordered) / len(ordered) for arm, rows in runs.items()}
    request_diff = [runs["instance_advice"][q]["steps"] - runs["global_advice"][q]["steps"] for q in ordered]
    result = {
        "protocol": "planbench_final_holdout_protocol.json",
        "n_untouched_tasks": len(ordered),
        "primary_instance_minus_global": primary,
        "secondary": secondary,
        "model_requests_mean": requests,
        "instance_minus_global_requests": {
            "mean": sum(request_diff) / len(request_diff),
            "paired_task_bootstrap_95": interval(request_diff, seed=20261018),
        },
        "recovery_events": {arm: dict(Counter(
            event.get("status") for q in ordered for event in rows[q]["trace"]
            if event.get("action") == "icr_recovery"
        )) for arm, rows in runs.items()},
        "task_rows": [{"query_id": q,
                       "statuses": {arm: runs[arm][q]["status"] for arm in runs},
                       "steps": {arm: runs[arm][q]["steps"] for arm in runs}}
                      for q in ordered],
    }
    target = data / "planbench_final_holdout_analysis.json"
    target.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps({key: value for key, value in result.items() if key != "task_rows"}, indent=2))


if __name__ == "__main__":
    main()
