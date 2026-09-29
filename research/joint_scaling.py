"""Deterministic chain scaling for the joint-choice dynamic program."""
from pathlib import Path
from statistics import median
from time import perf_counter
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from experiments.joint_repair import Choice, exhaustive_oracle, solve_tree


def instance(length):
    options = {}
    for i in range(length):
        name = str(i)
        function = f"operation_{i}"
        options[name] = [Choice(f"{name}:old", "plain", "plain", original=True,
                                function_id=function),
                         Choice(f"{name}:encode", "plain", "coded", function_id=function),
                         Choice(f"{name}:decode", "coded", "plain", function_id=function)]
    edges = [(str(i), str(i + 1)) for i in range(length - 1)]
    return options, edges


def time_call(call, repeat):
    times = []
    answer = None
    for _ in range(repeat):
        start = perf_counter()
        answer = call()
        times.append(perf_counter() - start)
    return median(times), answer


def main():
    rows = []
    for n in (3, 5, 7, 9, 11, 100, 1000, 10000):
        options, edges = instance(n)
        dp_time, dp = time_call(lambda: solve_tree(options, edges, {"0"}), 5)
        row = {"nodes": n, "options_per_node": 3,
               "dp_median_seconds": dp_time, "dp_cost": dp.cost,
               "compatibility_checks": dp.compatibility_checks}
        if n <= 11:
            oracle_time, oracle = time_call(
                lambda: exhaustive_oracle(options, edges, {"0"}), 3)
            assert (dp.feasible, dp.cost, len(dp.changed)) == (
                oracle.feasible, oracle.cost, len(oracle.changed))
            row.update(oracle_median_seconds=oracle_time,
                       oracle_assignments=oracle.states)
        rows.append(row)
    report = {"construction": "Chain with original plain/plain operation and two "
                               "function-preserving representation variants per node",
              "rows": rows}
    output = ROOT / "research/continuation_repair/joint_scaling.json"
    output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(rows, indent=2))


if __name__ == "__main__":
    main()
