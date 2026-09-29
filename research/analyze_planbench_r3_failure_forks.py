"""Frozen paired analysis of same-prefix native versus certificate-advice recovery."""
from __future__ import annotations

import json
from collections import Counter
from math import comb

from .analyze_planbench_online import ROOT, interval, load


def contrast(native: dict, advice: dict, ordered: list[str], seed: int) -> dict:
    differences = [int(advice[q]["status"] == "success") - int(native[q]["status"] == "success") for q in ordered]
    improved = sum(d > 0 for d in differences)
    worsened = sum(d < 0 for d in differences)
    discordant = improved + worsened
    p = (min(1.0, 2 * sum(comb(discordant, i) for i in range(min(improved, worsened) + 1)) / 2**discordant)
         if discordant else 1.0)
    return {
        "n": len(ordered),
        "native_successes": sum(native[q]["status"] == "success" for q in ordered),
        "advice_successes": sum(advice[q]["status"] == "success" for q in ordered),
        "advice_minus_native": sum(differences) / len(ordered),
        "paired_task_bootstrap_95": interval(differences, seed=seed),
        "mcnemar_two_sided_exact_p": p,
        "improved": improved,
        "worsened": worsened,
        "tied": len(ordered) - discordant,
    }


def main() -> None:
    data = ROOT / "research/continuation_repair"
    protocol = json.loads((data / "planbench_r3_failure_fork_protocol.json").read_text(encoding="utf-8"))
    cohort = json.loads((data / "planbench_r3_failure_fork_cohort.json").read_text(encoding="utf-8"))
    preflight = json.loads((data / "planbench_r3_failure_fork_preflight.json").read_text(encoding="utf-8"))
    all_ids = {entry["query_id"] for entry in cohort["entries"]}
    primary = sorted(preflight["primary_activated_query_ids"])
    if len(all_ids) != cohort["n_forks"] or set(primary) | set(preflight["negative_control_query_ids"]) != all_ids:
        raise ValueError("Frozen fork partition mismatch")
    native = load(protocol["run_ids"]["baseline"])
    advice = load(protocol["run_ids"]["advice"])
    if set(native) != all_ids or set(advice) != all_ids:
        raise ValueError("Incomplete fork arms")
    by_id = {entry["query_id"]: entry for entry in cohort["entries"]}
    request_diffs = [advice[q]["steps"] - native[q]["steps"] for q in primary]
    result = {
        "protocol": "planbench_r3_failure_fork_protocol.json",
        "primary_activated_forks": contrast(native, advice, primary, seed=20261005),
        "all_frozen_forks": contrast(native, advice, sorted(all_ids), seed=20261006),
        "primary_model_request_difference": {
            "advice_minus_native_mean": sum(request_diffs) / len(request_diffs),
            "paired_task_bootstrap_95": interval(request_diffs, seed=20261007),
        },
        "advice_recovery_statuses": dict(Counter(
            event.get("status") for q in primary for event in advice[q]["trace"]
            if event.get("action") == "icr_recovery"
        )),
        "task_rows": [{
            "query_id": q,
            "primary_activated": q in primary,
            "failed_turn_id": by_id[q]["failed_turn_id"],
            "native_status": native[q]["status"],
            "advice_status": advice[q]["status"],
            "native_steps": native[q]["steps"],
            "advice_steps": advice[q]["steps"],
        } for q in sorted(all_ids)],
    }
    target = data / "planbench_r3_failure_fork_analysis.json"
    target.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k != "task_rows"}, indent=2))


if __name__ == "__main__":
    main()
