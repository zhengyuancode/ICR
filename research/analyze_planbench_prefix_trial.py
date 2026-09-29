"""Judge the frozen same-prefix experiment from native execution records."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
from collections import defaultdict
from pathlib import Path

from .run_planbench_pilot import (
    ROOT, BENCH, DomainToolExecutor, load_all_databases,
    load_all_baseline_tools,
)
from .analyze_planbench_seed44_opportunity import follows_packet

DATA = ROOT / "research/continuation_repair"
RUNS = BENCH / "outputs/retail/ispa"


def exact_mcnemar(gains: int, losses: int) -> float:
    n = gains + losses
    if n == 0:
        return 1.0
    tail = sum(math.comb(n, k) for k in range(min(gains, losses) + 1))
    return min(1.0, 2 * tail / (2 ** n))


def contrast(rows: list[dict], field: str, seed: int) -> dict:
    gains = sum(row[f"instance_{field}"] and not row[f"global_{field}"]
                for row in rows)
    losses = sum(row[f"global_{field}"] and not row[f"instance_{field}"]
                 for row in rows)
    diffs = [int(row[f"instance_{field}"]) - int(row[f"global_{field}"])
             for row in rows]
    rng = random.Random(seed)
    n = len(rows)
    draws = sorted(sum(diffs[rng.randrange(n)] for _ in range(n)) / n
                   for _ in range(100_000))
    return {"n": n, "global_success": sum(row[f"global_{field}"] for row in rows),
            "instance_success": sum(row[f"instance_{field}"] for row in rows),
            "paired_gains": gains, "paired_losses": losses,
            "risk_difference": sum(diffs) / n,
            "paired_bootstrap_95": [draws[2500], draws[97500]],
            "mcnemar_two_sided_exact_p": exact_mcnemar(gains, losses)}


def tool_cluster_sensitivity(rows: list[dict], seed: int) -> dict:
    groups: dict[str, list[int]] = defaultdict(list)
    for row in rows:
        groups[row["original_tool"]].append(
            int(row["instance_local"]) - int(row["global_local"]))
    means = [sum(values) / len(values) for values in groups.values()]
    rng = random.Random(seed)
    k = len(means)
    draws = sorted(sum(means[rng.randrange(k)] for _ in range(k)) / k
                   for _ in range(100_000))
    return {"n_tool_clusters": k,
            "equal_tool_mean_difference": sum(means) / k,
            "equal_tool_cluster_bootstrap_95": [draws[2500], draws[97500]]}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cohort", choices=("pilot", "confirmation"), required=True)
    args = parser.parse_args()
    cohort = json.loads((DATA / f"planbench_prefix_{args.cohort}_cohort.json").read_text(
        encoding="utf-8"))
    protocol_path = DATA / "planbench_prefix_trial_protocol.json"
    if hashlib.sha256(protocol_path.read_bytes()).hexdigest() != cohort[
            "prospective_protocol_sha256"]:
        raise RuntimeError("Prospective protocol changed")
    tools = list(load_all_baseline_tools(BENCH / "src/data").values())
    blockers = {row["name"]: row for row in json.loads((BENCH /
        "src/data/retail/blocker_tools.json").read_text(encoding="utf-8"))}
    signatures: dict[tuple[tuple[str, ...], str], list[dict]] = defaultdict(list)
    for tool in tools:
        signatures[(tuple(tool["input_datatypes"]), tool["output_datatype"])].append(tool)
    executor = DomainToolExecutor(load_all_databases(BENCH / "src/data"))
    rows = []
    for entry in cohort["entries"]:
        q = entry["query_id"]
        capture_path = RUNS / entry["source_run"] / "progress/queries" / f"{q}.json"
        if hashlib.sha256(capture_path.read_bytes()).hexdigest() != entry[
                "capture_progress_sha256"]:
            raise AssertionError(f"Capture changed: {q}")
        capture = json.loads(capture_path.read_text(encoding="utf-8"))
        failed_turn = entry["failed_turn_id"]
        events = [event for event in capture["turns"][failed_turn - 1][
            "state_after_turn"]["steps_trace"]
            if event.get("step_id") == failed_turn
            and event.get("action") == "call_tool"
            and (event.get("tool_result") or {}).get("tool_type") == "blocker_misleading"
            and (event.get("tool_result") or {}).get("success") is False]
        if len(events) != 1:
            raise AssertionError(f"Ambiguous fixed failure: {q}")
        request = events[0]["request"]
        attempted = blockers[request["name"]]
        original_options = signatures[(tuple(attempted["input_datatypes"]),
                                       attempted["output_datatype"])]
        if len(original_options) != 1:
            raise AssertionError(f"Ambiguous original signature: {q}")
        original = original_options[0]
        supplied = request["arguments"]
        if len(supplied) != 1:
            raise AssertionError(f"Ambiguous failed input: {q}")
        observed_input = next(iter(supplied.values()))
        expected = executor.execute_tool(
            original, {original["input_datatypes"][0]: observed_input})
        if not expected.success or expected.output_value is None:
            raise AssertionError(f"Original output undefined: {q}")
        result = {"query_id": q, "task_id": entry["task_id"],
                  "blocker_seed": entry["blocker_seed"],
                  "original_tool": original["name"], "failed_turn_id": failed_turn}
        for variant in ("global", "instance"):
            run_id = f"prefix_{args.cohort}_{variant}_seed{entry['blocker_seed']}"
            path = RUNS / run_id / "progress/queries" / f"{q}.json"
            progress = json.loads(path.read_text(encoding="utf-8"))
            if progress["status"] != "completed":
                raise RuntimeError(f"Incomplete matched arm: {path}")
            final = progress["final_result"]
            trace = final["trace"]
            packet = [event for event in trace if event.get("action") == "icr_recovery"
                      and event.get("step_id") == failed_turn]
            if variant == "global" and packet:
                raise AssertionError(f"Global packet on input-only opportunity: {q}")
            if variant == "instance" and len(packet) != 1:
                raise AssertionError(f"Missing indexed packet: {q}")
            if variant == "instance":
                packet_index = next(i for i, event in enumerate(trace)
                                    if event is packet[0])
                result["instance_packet_fully_followed"] = follows_packet(
                    trace, packet_index)
            matching = [event for event in trace
                        if event.get("action") == "call_tool"
                        and failed_turn < event.get("step_id", -1) <= failed_turn + 12
                        and (event.get("tool_result") or {}).get("success") is True
                        and (event.get("tool_result") or {}).get("output_provenance") == "trusted"
                        and (event.get("tool_result") or {}).get("output_datatype")
                        == original["output_datatype"]
                        and (event.get("tool_result") or {}).get("output_value")
                        == expected.output_value]
            result[f"{variant}_local"] = bool(matching)
            result[f"{variant}_whole"] = final["status"] == "success"
            result[f"{variant}_requests_after_failure"] = max(
                0, final["steps"] - failed_turn)
        rows.append(result)
    primary = contrast(rows, "local", 20260928)
    secondary = contrast(rows, "whole", 20260929)
    pilot_gate = (args.cohort == "pilot" and
                  primary["paired_gains"] - primary["paired_losses"] >= 2)
    report = {"cohort": args.cohort, "primary_local_recovery": primary,
              "secondary_whole_task": secondary,
              "tool_cluster_sensitivity": tool_cluster_sensitivity(rows, 20260930),
              "input_only_packets_fully_followed": sum(
                  row["instance_packet_fully_followed"] for row in rows),
              "pilot_gate": pilot_gate if args.cohort == "pilot" else None,
              "rows": rows}
    target = DATA / f"planbench_prefix_{args.cohort}_analysis.json"
    target.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items() if key != "rows"},
                     indent=2))


if __name__ == "__main__":
    main()
