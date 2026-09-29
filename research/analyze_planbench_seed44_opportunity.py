"""Analyze a frozen seed-44 opportunity cohort after both arms finish."""
from __future__ import annotations

import argparse
import hashlib
import json
import random
from collections import Counter

from .analyze_planbench_online import ROOT, load
from .analyze_planbench_r3_failure_forks import contrast
from .compile_planbench_instance_contracts import input_digest

DATA = ROOT / "research/continuation_repair"


def follows_packet(trace: list[dict], event_index: int) -> bool:
    event = trace[event_index]
    value = json.loads(event["attempt_key"])[2]
    cursor = event_index + 1
    for expected_name in event["path"]:
        match = None
        for index in range(cursor, len(trace)):
            step = trace[index]
            if step.get("action") != "call_tool":
                continue
            request = step.get("request") or {}
            arguments = request.get("arguments") or {}
            outcome = step.get("tool_result") or {}
            if (request.get("name") == expected_name and len(arguments) == 1
                    and next(iter(arguments.values())) == value
                    and outcome.get("success") is True):
                match = index, outcome.get("output_value")
                break
        if match is None:
            return False
        cursor, value = match[0] + 1, match[1]
    return True


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cohort", choices=("pilot", "confirmation"), required=True)
    args = parser.parse_args()
    protocol = json.loads((DATA / "planbench_seed44_opportunity_protocol.json").read_text(encoding="utf-8"))
    if hashlib.sha256((DATA / "planbench_new_seed_opportunities.json").read_bytes()).hexdigest() != protocol["census_sha256"]:
        raise RuntimeError("Frozen opportunity census changed")
    for name, expected in protocol["source_sha256"].items():
        if hashlib.sha256((ROOT / name).read_bytes()).hexdigest() != expected:
            raise RuntimeError(f"Frozen source changed: {name}")
    ordered = [task.replace("task", "query") for task in protocol["cohorts"][args.cohort]]
    arms = {name: load(run_id) for name, run_id in protocol["run_ids"][args.cohort].items()}
    if any(set(rows) != set(ordered) for rows in arms.values()):
        raise RuntimeError("Both arms must finish every frozen task")
    global_set = {(item["failed_tool"], tuple(item["path"])) for item in json.loads(
        (DATA / "planbench_calibrated_contracts.json").read_text(encoding="utf-8"))["contracts"]}
    instance_index = {(item["failed_tool"], tuple(item["path"])): set(item["input_hashes"])
                      for item in json.loads((DATA / "planbench_instance_contracts.json").read_text(
                          encoding="utf-8"))["contracts"]}
    rows = []
    for q in ordered:
        instance_trace = arms["instance_advice"][q]["trace"]
        global_events = [event for event in arms["global_advice"][q]["trace"]
                         if event.get("action") == "icr_recovery"]
        events = [event for event in instance_trace
                  if event.get("action") == "icr_recovery"]
        for event in events:
            pair = event.get("original_tool"), tuple(event.get("path") or ())
            support = instance_index.get(pair)
            key = json.loads(event["attempt_key"])
            if support is None or len(key) != 3 or input_digest(key[2]) not in support:
                raise RuntimeError(f"Uncertified event in {q}")
        input_only = [event for event in events
                      if (event.get("original_tool"), tuple(event.get("path") or ())) not in global_set]
        followed = sum(follows_packet(instance_trace, index)
                       for index, event in enumerate(instance_trace)
                       if event in input_only)
        rows.append({"query_id": q,
                     "global_status": arms["global_advice"][q]["status"],
                     "instance_status": arms["instance_advice"][q]["status"],
                     "global_steps": arms["global_advice"][q]["steps"],
                     "instance_steps": arms["instance_advice"][q]["steps"],
                     "global_packets": len(global_events),
                     "input_only_packets": len(input_only),
                     "input_only_packets_fully_followed": followed,
                     "all_packet_statuses": [event.get("status") for event in events]})
    primary = contrast(arms["global_advice"], arms["instance_advice"], ordered,
                       seed=20260927 if args.cohort == "pilot" else 20260928)
    addendum = json.loads((DATA / "planbench_seed44_cluster_sensitivity.json").read_text(encoding="utf-8"))
    protocol_path = DATA / "planbench_seed44_opportunity_protocol.json"
    if hashlib.sha256(protocol_path.read_bytes()).hexdigest() != addendum["primary_protocol_sha256"]:
        raise RuntimeError("Cluster sensitivity protocol mismatch")
    for name, expected in addendum["source_sha256"].items():
        if hashlib.sha256((ROOT / name).read_bytes()).hexdigest() != expected:
            raise RuntimeError(f"Cluster source changed: {name}")
    labels = {task.replace("task", "query"): label
              for task, label in addendum["groups"][args.cohort].items()}
    if set(labels) != set(ordered):
        raise RuntimeError("Cluster labels do not match frozen tasks")
    by_tool: dict[str, list[int]] = {}
    for q in ordered:
        diff = int(arms["instance_advice"][q]["status"] == "success") - int(
            arms["global_advice"][q]["status"] == "success")
        by_tool.setdefault(labels[q], []).append(diff)
    cluster_means = {tool: sum(values) / len(values) for tool, values in by_tool.items()}
    rng = random.Random(20260929 if args.cohort == "pilot" else 20260930)
    mean_values = list(cluster_means.values())
    k = len(mean_values)
    cluster_draws = sorted(sum(mean_values[rng.randrange(k)] for _ in range(k)) / k
                           for _ in range(100_000))
    cluster_sensitivity = {
        "n_structural_tool_clusters": k,
        "equal_tool_mean_difference": sum(mean_values) / k,
        "equal_tool_cluster_bootstrap_95": [cluster_draws[2500], cluster_draws[97500]],
        "tool_means": cluster_means,
    }
    packet_count = sum(row["input_only_packets"] for row in rows)
    result = {
        "protocol": "planbench_seed44_opportunity_protocol.json",
        "cohort": args.cohort,
        "primary": primary,
        "input_only_packets": packet_count,
        "global_packets": sum(row["global_packets"] for row in rows),
        "tasks_with_input_only_packet": sum(row["input_only_packets"] > 0 for row in rows),
        "input_only_packets_fully_followed": sum(row["input_only_packets_fully_followed"] for row in rows),
        "packet_statuses": dict(Counter(status for row in rows for status in row["all_packet_statuses"])),
        "structural_tool_cluster_sensitivity": cluster_sensitivity,
        "pilot_gate_met": (packet_count >= 3 and primary["advice_minus_native"] > 0)
        if args.cohort == "pilot" else None,
        "task_rows": rows,
    }
    target = DATA / f"planbench_seed44_{args.cohort}_analysis.json"
    target.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in result.items() if key != "task_rows"}, indent=2))


if __name__ == "__main__":
    main()
