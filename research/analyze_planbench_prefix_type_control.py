"""Audit the post-review type-only arm against frozen confirmation prefixes."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .analyze_planbench_prefix_trial import DATA, RUNS, exact_mcnemar
from .compile_planbench_instance_contracts import input_digest
from .run_planbench_pilot import (ROOT, BENCH, DomainToolExecutor,
                                  load_all_databases, load_all_baseline_tools)


def read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def contrast(rows: list[dict], a: str, b: str, field: str) -> dict:
    gains = sum(row[f"{a}_{field}"] and not row[f"{b}_{field}"] for row in rows)
    losses = sum(row[f"{b}_{field}"] and not row[f"{a}_{field}"] for row in rows)
    return {"first_arm": a, "second_arm": b, "endpoint": field,
            "first_success": sum(row[f"{a}_{field}"] for row in rows),
            "second_success": sum(row[f"{b}_{field}"] for row in rows),
            "paired_gains": gains, "paired_losses": losses,
            "risk_difference": (gains - losses) / len(rows),
            "mcnemar_two_sided_exact_p": exact_mcnemar(gains, losses)}


def main() -> None:
    cohort_path = DATA / "planbench_prefix_confirmation_cohort.json"
    cohort = read(cohort_path)
    protocol = read(DATA / "planbench_prefix_type_control_protocol.json")
    assert hashlib.sha256(cohort_path.read_bytes()).hexdigest() == protocol["cohort_sha256"]
    for name, expected in protocol["source_sha256"].items():
        assert hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == expected
    original = read(DATA / "planbench_prefix_confirmation_analysis.json")
    original_rows = {r["query_id"]: r for r in original["rows"]}
    assert len(cohort["entries"]) == len(original_rows) == 20

    tools = load_all_baseline_tools(BENCH / "src/data")
    blockers = {row["name"]: row for row in read(BENCH / "src/data/retail/blocker_tools.json")}
    by_signature: dict[tuple, list[dict]] = {}
    for tool in tools.values():
        by_signature.setdefault((tuple(tool["input_datatypes"]),
                                 tool["output_datatype"]), []).append(tool)
    executor = DomainToolExecutor(load_all_databases(BENCH / "src/data"))
    certificates = read(DATA / "planbench_instance_contracts.json")
    certified = {(c["failed_tool"], tuple(c["path"]), h)
                 for c in certificates["contracts"] for h in c["input_hashes"]}
    rows = []
    for entry in cohort["entries"]:
        query, failed, seed = (entry["query_id"], entry["failed_turn_id"],
                               entry["blocker_seed"])
        capture_path = (RUNS / entry["source_run"] / "progress/queries"
                        / f"{query}.json")
        assert hashlib.sha256(capture_path.read_bytes()).hexdigest() == entry[
            "capture_progress_sha256"]
        capture = read(capture_path)
        typed = read(RUNS / f"prefix_confirmation_typed_seed{seed}"
                     / "progress/queries" / f"{query}.json")
        assert typed["status"] == "completed" and typed["final_result"]["steps"] <= 100
        prior = failed - 1
        prefix_len = 2 + 2 * prior
        assert typed["resume_checkpoint"]["effective_history"][:prefix_len] == (
            capture["resume_checkpoint"]["effective_history"][:prefix_len])
        assert typed["turns"][prior - 1]["state_after_turn"] == (
            capture["turns"][prior - 1]["state_after_turn"])
        assert typed["turns"][prior]["llm_raw_response"] == (
            capture["turns"][prior]["llm_raw_response"])
        def failure_event(progress: dict) -> dict:
            events = [e for e in progress["turns"][prior]["state_after_turn"]["steps_trace"]
                      if e.get("step_id") == failed and e.get("action") == "call_tool"]
            assert len(events) == 1
            return events[0]
        event = failure_event(capture)
        assert failure_event(typed) == event
        request = event["request"]
        blocker = blockers[request["name"]]
        originals = by_signature[(tuple(blocker["input_datatypes"]),
                                  blocker["output_datatype"])]
        assert len(originals) == 1
        original_tool = originals[0]
        assert len(request["arguments"]) == 1
        observed = next(iter(request["arguments"].values()))
        expected = executor.execute_tool(
            original_tool, {original_tool["input_datatypes"][0]: observed})
        assert expected.success and expected.output_value is not None
        final = typed["final_result"]
        trace = final["trace"]
        packets = [e for e in trace if e.get("action") == "icr_recovery"
                   and e.get("step_id") == failed]
        assert len(packets) == 1
        path = tuple(packets[0]["path"])
        instance = read(RUNS / f"prefix_confirmation_instance_seed{seed}"
                        / "progress/queries" / f"{query}.json")
        instance_packets = [e for e in instance["final_result"]["trace"]
                            if e.get("action") == "icr_recovery"
                            and e.get("step_id") == failed]
        assert len(instance_packets) == 1
        matches = [e for e in trace
                   if e.get("action") == "call_tool"
                   and failed < e.get("step_id", -1) <= failed + 12
                   and (e.get("tool_result") or {}).get("success") is True
                   and (e.get("tool_result") or {}).get("output_provenance") == "trusted"
                   and (e.get("tool_result") or {}).get("output_datatype")
                   == original_tool["output_datatype"]
                   and (e.get("tool_result") or {}).get("output_value")
                   == expected.output_value]
        row = dict(original_rows[query])
        row.update({"typed_local": bool(matches),
                    "typed_whole": final["status"] == "success",
                    "typed_packet_path": list(path),
                    "typed_packet_effect_certified": (
                        original_tool["name"], path, input_digest(observed)) in certified,
                    "typed_same_path_as_instance": path == tuple(instance_packets[0]["path"]),
                    "typed_requests_after_failure": max(0, final["steps"] - failed)})
        rows.append(row)

    results = [contrast(rows, a, b, endpoint)
               for a, b in (("instance", "typed"), ("typed", "global"))
               for endpoint in ("local", "whole")]
    report = {"role": "post_review_ancillary_type_only_control",
              "n": len(rows),
              "identical_prefixes_prior_states_failed_actions_and_tool_events": len(rows),
              "typed_effect_certified_packets": sum(r["typed_packet_effect_certified"]
                                                     for r in rows),
              "typed_same_path_as_instance": sum(r["typed_same_path_as_instance"]
                                                 for r in rows),
              "typed_local_success": sum(r["typed_local"] for r in rows),
              "typed_whole_success": sum(r["typed_whole"] for r in rows),
              "contrasts": results, "rows": rows}
    out = DATA / "planbench_prefix_type_control_analysis.json"
    out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "rows"}, indent=2))


if __name__ == "__main__":
    main()
