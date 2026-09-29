"""Recompute the numerical claims reported in the paper from frozen records."""
from __future__ import annotations

import json
import math
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "research" / "continuation_repair"


def read(name: str) -> dict:
    return json.loads((DATA / name).read_text(encoding="utf-8"))


def exact_mcnemar(gains: int, losses: int) -> float:
    discordant = gains + losses
    if discordant == 0:
        return 1.0
    tail = sum(math.comb(discordant, k) for k in range(min(gains, losses) + 1))
    return min(1.0, 2 * tail / (2 ** discordant))


def paired(rows: list[dict], left, right) -> dict:
    left_values = [bool(left(row)) for row in rows]
    right_values = [bool(right(row)) for row in rows]
    gains = sum(r and not l for l, r in zip(left_values, right_values))
    losses = sum(l and not r for l, r in zip(left_values, right_values))
    return {
        "n": len(rows),
        "left_success": sum(left_values),
        "right_success": sum(right_values),
        "gains": gains,
        "losses": losses,
        "difference": (sum(right_values) - sum(left_values)) / len(rows),
        "mcnemar_two_sided_exact_p": exact_mcnemar(gains, losses),
    }


def total_counts(report: dict) -> dict[str, int]:
    keys = next(iter(report["domains"].values()))["counts"].keys()
    return {key: sum(domain["counts"][key] for domain in report["domains"].values())
            for key in keys}


def main() -> None:
    reproduced: dict[str, object] = {}

    closure = read("taskbench_multinode_analysis.json")["combined"]
    counts = closure["counts"]
    assert closure["graphs"] == 1901
    assert counts["assignments"] == 892800
    assert counts["changed_feasible"] == 28933
    assert counts["changed_feasible"] - counts["changed_one_hop_admitted"] == 3338
    assert counts["changed_feasible"] - counts["changed_two_hop_admitted"] == 218
    reproduced["fixed_assignment_closure"] = {
        "graphs": closure["graphs"],
        "assignments": counts["assignments"],
        "changed_feasible": counts["changed_feasible"],
        "one_round_misses": 3338,
        "two_round_misses": 218,
        "one_round_gap": closure["fractions"]["one_hop_miss_among_changed_feasible"],
        "one_round_ci95": closure["graph_bootstrap_95ci"]["one_hop_miss_among_changed_feasible"],
    }

    joint = read("joint_taskbench_analysis.json")["seeds"]["20260924"]
    joint_counts = joint["counts"]
    beam = read("joint_beam_analysis.json")["20260924"]
    assert joint_counts["instances"] == 6975
    assert joint_counts["dp_feasible"] == 3933
    assert joint_counts["greedy_feasible"] == 3449
    assert joint_counts["greedy_false_negative"] == 484
    assert beam["2"]["beam_feasible"] == 3745
    assert beam["4"]["beam_feasible"] == 3914
    assert beam["8"]["beam_feasible"] == 3933
    reproduced["joint_tree_choice"] = {
        "instances": joint_counts["instances"],
        "dp_feasible": joint_counts["dp_feasible"],
        "greedy_feasible": joint_counts["greedy_feasible"],
        "additional_repairs": joint_counts["greedy_false_negative"],
        "absolute_gain": joint["feasibility_gap"],
        "gain_ci95": joint["feasibility_gap_ci95"],
        "beam_feasible": {width: beam[width]["beam_feasible"] for width in ("2", "4", "8")},
    }

    dag = read("port_dag_taskbench_seed20260924.json")
    dag_counts = total_counts(dag)
    assert sum(domain["graphs"] for domain in dag["domains"].values()) == 157
    assert dag_counts["oracle_checked"] == 568
    variants4 = []
    for seed in (20260924, 20260925, 20260926):
        report = read(f"port_dag_taskbench_seed{seed}_variants4.json")
        variants4.append(total_counts(report)["beam8_miss"])
    assert variants4 == [4, 4, 1]
    reproduced["port_bound_dag"] = {
        "graphs": 157,
        "oracle_checked": dag_counts["oracle_checked"],
        "exact_oracle_disagreements": 0,
        "width8_misses_four_choices": variants4,
    }

    static = read("planbench_route_decisions.json")
    assert static["totals"]["oracle_path_input_pairs"] == 31565
    assert static["totals"]["defined_decisions"] == 9250
    assert static["policies"]["input_indexed"]["native_correct"] == 9124
    assert static["policies"]["input_indexed"]["no_route"] == 126
    assert static["policies"]["global"]["native_correct"] == 8350
    assert static["policies"]["type_only"]["native_wrong"] == 126
    assert static["totals"]["new_safe_decisions"] == 774
    observed_contracts = read("planbench_instance_contracts.json")
    global_contracts = read("planbench_relational_contracts.json")
    global_paths = {
        (item["failed_tool"], tuple(item["path"]))
        for item in global_contracts["contracts"]
    }
    global_safe_pairs = sum(
        len(item["input_hashes"])
        for item in observed_contracts["contracts"]
        if (item["failed_tool"], tuple(item["path"])) in global_paths
    )
    observed_safe_pairs = observed_contracts["n_safe_path_input_pairs"]
    assert len(global_paths) == 282
    assert len(observed_contracts["contracts"]) == 341
    assert global_safe_pairs == 25665
    assert observed_safe_pairs == 30739
    assert observed_safe_pairs - global_safe_pairs == 5074
    reproduced["observed_input_certificate"] = {
        "path_input_pairs": static["totals"]["oracle_path_input_pairs"],
        "globally_certified_paths": len(global_paths),
        "observed_input_certified_paths": len(observed_contracts["contracts"]),
        "global_safe_path_input_pairs": global_safe_pairs,
        "observed_safe_path_input_pairs": observed_safe_pairs,
        "additional_safe_path_input_pairs": observed_safe_pairs - global_safe_pairs,
        "failed_tool_input_decisions": static["totals"]["defined_decisions"],
        "observed_input_safe": static["policies"]["input_indexed"]["native_correct"],
        "global_safe": static["policies"]["global"]["native_correct"],
        "additional_safe_decisions": static["totals"]["new_safe_decisions"],
        "type_only_errors": static["policies"]["type_only"]["native_wrong"],
    }

    seed43 = read("planbench_seed43_confirmation72_analysis.json")
    rows72 = seed43["task_rows"]
    comparison72 = paired(
        rows72,
        lambda row: row["native_status"] == "success",
        lambda row: row["icr_status"] == "success",
    )
    assert comparison72["n"] == 72
    assert comparison72["left_success"] == 39
    assert comparison72["right_success"] == 58
    assert comparison72["gains"] == 20 and comparison72["losses"] == 1
    assert math.isclose(comparison72["mcnemar_two_sided_exact_p"], 2.09808349609375e-05)
    mean_requests = sum(row["icr_steps"] - row["native_steps"] for row in rows72) / 72
    assert math.isclose(mean_requests, -0.3194444444444444)
    stage30 = read("planbench_seed43_stage30_analysis.json")["rows"]
    all102_native = comparison72["left_success"] + sum(
        row["native_status"] == "success" for row in stage30)
    all102_icr = comparison72["right_success"] + sum(
        row["advice_status"] == "success" for row in stage30)
    assert (all102_native, all102_icr) == (54, 79)
    reproduced["system_confirmation_72"] = comparison72 | {
        "mean_model_request_difference": mean_requests,
        "paired_bootstrap_ci95": seed43["primary_confirmation72"]["paired_task_bootstrap_95"],
        "descriptive_all_102": {"native_success": all102_native, "icr_success": all102_icr},
    }

    development = read("planbench_r3_instance_fork_analysis.json")["primary_all_frozen_failures"]
    assert (development["n"], development["native_successes"], development["advice_successes"]) == (29, 20, 26)
    assert (development["improved"], development["worsened"]) == (6, 0)
    reproduced["development_prefixes_29"] = development

    holdout = read("planbench_final_holdout_analysis.json")
    rows21 = holdout["task_rows"]
    successes21 = {
        arm: sum(row["statuses"][arm] == "success" for row in rows21)
        for arm in ("baseline", "global_advice", "type_only_advice", "instance_advice")
    }
    assert successes21 == {
        "baseline": 8, "global_advice": 15,
        "type_only_advice": 15, "instance_advice": 15,
    }
    reproduced["matched_holdout_21"] = successes21

    prefix = read("planbench_prefix_confirmation_analysis.json")
    rows20 = prefix["rows"]
    local20 = paired(rows20, lambda row: row["global_local"], lambda row: row["instance_local"])
    whole20 = paired(rows20, lambda row: row["global_whole"], lambda row: row["instance_whole"])
    assert (local20["left_success"], local20["right_success"], local20["gains"], local20["losses"]) == (7, 19, 12, 0)
    assert (whole20["left_success"], whole20["right_success"], whole20["gains"], whole20["losses"]) == (6, 19, 13, 0)
    typed = read("planbench_prefix_type_control_analysis.json")
    assert typed["typed_local_success"] == 19
    assert typed["typed_same_path_as_instance"] == 20
    reproduced["same_prefix_20"] = {
        "local_global_vs_observed": local20,
        "whole_task_global_vs_observed": whole20,
        "type_only_local_success": typed["typed_local_success"],
        "type_only_same_path_as_observed": typed["typed_same_path_as_instance"],
    }

    scaling = read("joint_scaling.json")["rows"]
    repair_scaling = read("repair_region_scaling.json")["rows"]
    index = read("certificate_index_benchmark.json")
    assert index["index_file_bytes"] == 2478118
    assert index["contracts"] == 341
    assert index["query_cases"] == 9850
    reproduced["local_scaling"] = {
        "joint_dp_10000_nodes_ms": next(row for row in scaling if row["nodes"] == 10000)["dp_median_seconds"] * 1000,
        "exhaustive_11_nodes_ms": next(row for row in scaling if row["nodes"] == 11)["oracle_median_seconds"] * 1000,
        "closure_50000_nodes_ms": next(row for row in repair_scaling if row["nodes"] == 50000)["median_ms"],
        "certificate_index_bytes": index["index_file_bytes"],
        "certificate_index_peak_bytes": index["parsed_index_peak_bytes"],
        "certificate_lookup_us_median": index["lookup_us_per_query_median"],
    }

    output = ROOT / "reproduced_claims.json"
    output.write_text(json.dumps(reproduced, indent=2), encoding="utf-8")
    print(json.dumps(reproduced, indent=2))
    print(f"\nAll checks passed. Wrote {output.name}.")


if __name__ == "__main__":
    main()
