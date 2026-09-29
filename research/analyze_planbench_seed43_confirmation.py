"""Analyze the frozen seed-43 transfer, separating inspected and untouched tasks."""
from __future__ import annotations

import hashlib
import json
import random
from collections import Counter

from .analyze_planbench_online import ROOT, interval, load
from .analyze_planbench_r3_failure_forks import contrast


def recovery_events(row: dict) -> list[dict]:
    return [event for event in row["trace"] if event.get("action") == "icr_recovery"]


def cluster_interval(differences: dict[str, int], group_by: dict[str, str], seed: int) -> dict:
    groups: dict[str, list[int]] = {}
    for task, difference in differences.items():
        groups.setdefault(group_by[task], []).append(difference)
    cells = [(sum(values), len(values)) for values in groups.values()]
    rng = random.Random(seed)
    draws = []
    for _ in range(100_000):
        sampled = [cells[rng.randrange(len(cells))] for _ in cells]
        draws.append(sum(total for total, _ in sampled) / sum(n for _, n in sampled))
    draws.sort()
    return {"n_clusters": len(cells), "percentile_95": [draws[2499], draws[97499]]}


def main() -> None:
    data = ROOT / "research/continuation_repair"
    parent_path = data / "planbench_seed43_transfer_protocol.json"
    parent = json.loads(parent_path.read_text(encoding="utf-8"))
    protocol = json.loads((data / "planbench_seed43_confirmation72_protocol.json").read_text(encoding="utf-8"))
    if hashlib.sha256(parent_path.read_bytes()).hexdigest() != protocol["parent_protocol_sha256"]:
        raise RuntimeError("Parent cohort changed after confirmation freeze")
    ordered = [task.replace("task", "query") for task in parent["task_ids"]]
    if len(ordered) != 102 or len(set(ordered)) != 102 or len(ordered[30:]) != protocol["n_tasks"]:
        raise RuntimeError("Invalid frozen cohort partition")
    native = load(protocol["arms"]["native"])
    advice = load(protocol["arms"]["icr_advice"])
    if set(native) != set(ordered) or set(advice) != set(ordered):
        raise RuntimeError("Both arms must finish all 102 tasks before confirmation analysis")

    confirm = ordered[30:]
    primary = contrast(native, advice, confirm, seed=20261025)
    full = contrast(native, advice, ordered, seed=20261026)
    request_deltas = [advice[q]["steps"] - native[q]["steps"] for q in confirm]
    task_catalog = {task["task_id"]: task for task in json.loads((
        ROOT / "external/PlanBench-XL-main/src/data/retail/tasks.json"
    ).read_text(encoding="utf-8"))}
    differences = {q: int(advice[q]["status"] == "success") - int(native[q]["status"] == "success")
                   for q in confirm}
    by_path = {q: json.dumps(task_catalog[q.replace("query", "task")]["one_available_path"])
               for q in confirm}
    by_target = {q: task_catalog[q.replace("query", "task")]["target_datatype"]
                 for q in confirm}
    rows = []
    for q in confirm:
        events = recovery_events(advice[q])
        rows.append({
            "query_id": q,
            "native_status": native[q]["status"],
            "icr_status": advice[q]["status"],
            "native_steps": native[q]["steps"],
            "icr_steps": advice[q]["steps"],
            "icr_recovery_events": len(events),
            "icr_recovery_statuses": [event.get("status") for event in events],
        })
    gains = [row for row in rows if row["native_status"] != "success" and row["icr_status"] == "success"]
    losses = [row for row in rows if row["native_status"] == "success" and row["icr_status"] != "success"]
    result = {
        "protocol": "planbench_seed43_confirmation72_protocol.json",
        "primary_confirmation72": primary,
        "descriptive_all102": full,
        "decision_rule_met": (
            primary["advice_minus_native"] > 0
            and primary["mcnemar_two_sided_exact_p"] < 0.05
            and primary["paired_task_bootstrap_95"][0] > 0
        ),
        "cluster_sensitivity": {
            "released_reference_path": cluster_interval(differences, by_path, seed=20261028),
            "target_datatype": cluster_interval(differences, by_target, seed=20261029),
        },
        "mechanism_diagnostic": {
            "advice_event_statuses": dict(Counter(
                event.get("status") for q in confirm for event in recovery_events(advice[q])
            )),
            "gains_with_recovery_event": sum(row["icr_recovery_events"] > 0 for row in gains),
            "losses_with_recovery_event": sum(row["icr_recovery_events"] > 0 for row in losses),
            "note": "Event-conditioned counts are descriptive because events occur after treatment assignment."
        },
        "model_requests_confirmation72": {
            "native_mean": sum(native[q]["steps"] for q in confirm) / len(confirm),
            "icr_mean": sum(advice[q]["steps"] for q in confirm) / len(confirm),
            "paired_difference_mean": sum(request_deltas) / len(request_deltas),
            "paired_difference_bootstrap_95": interval(request_deltas, seed=20261027),
        },
        "task_rows": rows,
    }
    target = data / "planbench_seed43_confirmation72_analysis.json"
    target.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps({key: value for key, value in result.items() if key != "task_rows"}, indent=2))


if __name__ == "__main__":
    main()
