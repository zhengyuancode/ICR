"""Paired analysis of frozen, native PlanBench-XL online cohorts."""

from __future__ import annotations

import argparse
import collections
import json
import random
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUNS = ROOT / "external" / "PlanBench-XL-main" / "outputs" / "retail" / "ispa"
ARMS = ("baseline", "advice", "dispatch")


def load(run_id: str) -> dict[str, dict]:
    path = RUNS / run_id / "result.jsonl"
    if not path.exists():
        raise FileNotFoundError(path)
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if len({row["query_id"] for row in rows}) != len(rows):
        raise ValueError(f"duplicate query IDs in {path}")
    return {row["query_id"]: row for row in rows}


def interval(values: list[float], seed: int = 20260925, draws: int = 100_000) -> list[float]:
    rng = random.Random(seed)
    n = len(values)
    sampled = sorted(sum(values[rng.randrange(n)] for _ in range(n)) / n for _ in range(draws))
    return [sampled[int(0.025 * draws)], sampled[int(0.975 * draws)]]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cohort", choices=("pilot", "heldout", "multicandidate"), required=True)
    parser.add_argument("--prefix", required=True, help="Run ID stem, e.g. heldout_r1")
    for arm in ARMS:
        parser.add_argument(f"--{arm}-run-id", default="")
    parser.add_argument("--output", default="")
    args = parser.parse_args()
    cohort_file = "planbench_multicandidate_cohort.json" if args.cohort == "multicandidate" else "planbench_online_cohort.json"
    cohort = json.loads((ROOT / "research" / "continuation_repair" / cohort_file).read_text(encoding="utf-8"))
    task_ids = cohort["task_ids"] if args.cohort == "multicandidate" else cohort[f"{args.cohort}_task_ids"]
    expected = {task.replace("task", "query") for task in task_ids}
    arms = {arm: load(getattr(args, f"{arm}_run_id") or f"{args.prefix}_{arm}") for arm in ARMS}
    for arm, rows in arms.items():
        if set(rows) != expected:
            raise ValueError(f"{arm}: got {len(rows)} rows, expected {len(expected)}")
    ordered = sorted(expected)
    summary: dict[str, object] = {"cohort": args.cohort, "run_prefix": args.prefix, "n_tasks": len(ordered)}
    for arm, rows in arms.items():
        successes = sum(rows[q]["status"] == "success" for q in ordered)
        recoveries = [trace for q in ordered for trace in rows[q]["trace"] if trace.get("action") == "icr_recovery"]
        summary[arm] = {
            "successes": successes,
            "total": len(ordered),
            "rate": successes / len(ordered),
            "steps": sum(rows[q]["steps"] for q in ordered),
            "tool_calls": sum(rows[q]["final_state"]["tool_call_exec_count"] for q in ordered),
            "recovery_events": len(recoveries),
            "recovery_tasks": sum(any(t.get("action") == "icr_recovery" for t in rows[q]["trace"]) for q in ordered),
            "recovery_statuses": dict(collections.Counter(t["status"] for t in recoveries)),
        }
    comparisons = {}
    for arm in ("advice", "dispatch"):
        for comparator in ("baseline", "advice"):
            if arm == comparator:
                continue
            values = [float(arms[arm][q]["status"] == "success") - float(arms[comparator][q]["status"] == "success") for q in ordered]
            comparisons[f"{arm}_minus_{comparator}"] = {
                "difference": sum(values) / len(values),
                "paired_task_bootstrap_95": interval(values),
                "improved_tasks": sum(v > 0 for v in values),
                "worsened_tasks": sum(v < 0 for v in values),
                "tied_tasks": sum(v == 0 for v in values),
            }
    summary["comparisons"] = comparisons
    summary["task_rows"] = [
        {
            "query_id": q,
            "statuses": {arm: arms[arm][q]["status"] for arm in ARMS},
            "steps": {arm: arms[arm][q]["steps"] for arm in ARMS},
            "recovery_events": {
                arm: sum(t.get("action") == "icr_recovery" for t in arms[arm][q]["trace"]) for arm in ARMS
            },
        }
        for q in ordered
    ]
    output = Path(args.output) if args.output else ROOT / "research" / "continuation_repair" / f"{args.prefix}_analysis.json"
    output.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in summary.items() if k != "task_rows"}, indent=2))
    print("output:", output)


if __name__ == "__main__":
    main()
