"""Trace-level diagnostics for the published confirmation cohorts (post hoc)."""
from __future__ import annotations

from collections import Counter
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "research/continuation_repair"
RUNS = ROOT / "external/PlanBench-XL-main/outputs/retail/ispa"
OUTPUT = DATA / "review_mechanism_audit_20260930.json"


def read(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def run(run_id: str):
    return {row["query_id"]: row for row in map(json.loads,
            (RUNS / run_id / "result.jsonl").read_text(encoding="utf-8").splitlines())}


def main() -> None:
    analysis = read(DATA / "planbench_seed43_confirmation72_analysis.json")
    native, icr = run("seed43_native"), run("seed43_instance_advice")
    rows = []
    counts = Counter()
    for source in analysis["task_rows"]:
        q = source["query_id"]
        n, r = native[q], icr[q]
        if n["status"] == r["status"]:
            continue
        outcome = "gain" if r["status"] == "success" else "loss"
        events = [e for e in r["trace"] if e.get("action") == "icr_recovery"]
        key = f"{outcome}_{'packet' if events else 'no_packet'}"
        counts[key] += 1
        rows.append({
            "query_id": q,
            "outcome": outcome,
            "recovery_events": len(events),
            "native_steps": n["steps"],
            "icr_steps": r["steps"],
            "native_executed_tools": n["final_state"]["tool_call_exec_count"],
            "icr_executed_tools": r["final_state"]["tool_call_exec_count"],
            "icr_successful_tool_names": [e["request"]["name"] for e in r["trace"]
                if e.get("action") == "call_tool" and e.get("request")
                and (e.get("tool_result") or {}).get("success") is True],
        })
    prefix = read(DATA / "planbench_prefix_confirmation_analysis.json")
    cohort = read(DATA / "planbench_prefix_confirmation_cohort.json")
    by_query = {entry["query_id"]: entry for entry in cohort["entries"]}
    pcounts = Counter()
    overlaps = Counter()
    for row in prefix["rows"]:
        if row["instance_local"] and not row["global_local"]:
            pcounts["gains"] += 1
            pcounts["full_path"] += row["instance_packet_fully_followed"]
            pcounts["partial_path"] += not row["instance_packet_fully_followed"]
            entry = by_query[row["query_id"]]
            failed = entry["failed_turn_id"]
            trace = read(RUNS / f"prefix_confirmation_instance_seed{entry['blocker_seed']}"
                         / "progress/queries" / f"{row['query_id']}.json")["final_result"]["trace"]
            packet = next(event for event in trace if event.get("action") == "icr_recovery"
                          and event.get("step_id") == failed)
            invoked = {event.get("request", {}).get("name") for event in trace
                       if event.get("action") == "call_tool"
                       and failed < event.get("step_id", -1) <= failed + 12}
            overlap = len(invoked.intersection(packet["path"]))
            overlaps[overlap] += 1
            pcounts["gains_using_packet_tool"] += overlap > 0
    output = {
        "role": "Post hoc trace diagnostic, not a causal mediation estimate",
        "confirmation72_discordant_counts": dict(counts),
        "confirmation72_discordant_rows": rows,
        "same_prefix20_local_gain_counts": dict(pcounts),
        "same_prefix20_gain_packet_tool_overlap": dict(overlaps),
    }
    OUTPUT.write_text(json.dumps(output, indent=2), encoding="utf-8")
    print(json.dumps({"confirmation72": dict(counts),
                      "same_prefix20": dict(pcounts)}, indent=2))


if __name__ == "__main__":
    main()
