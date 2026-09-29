"""Replay one frozen failure-prefix seed under either certificate rule."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from .run_planbench_failure_forks import ReplayFirstClient, digest
from .run_planbench_pilot import (
    ROOT, BENCH, load_config, load_all_baseline_tools, load_all_datatypes,
    load_noisy_tools_file, load_all_blocker_tools, load_paths_set_catalog,
    generate_blocker_replacements_by_task, LLMClient, SemanticRetriever,
    EventController, NoisyToolAugmenter, DomainToolExecutor,
    load_all_databases, PromptManager, load_queries,
)
from .planbench_controller import PlanBenchRecoveryRunner
from .planbench_instance_advice import PlanBenchInstanceAdviceRunner

from env.core.utils import compute_signature, dump_json, now_utc_iso  # type: ignore[import-not-found]

DATA = ROOT / "research/continuation_repair"
RUNS = BENCH / "outputs/retail/ispa"


class ForkMixin:
    def run_single_query(self, query: Any,
                         paths_set_catalog: list[dict[str, Any]]) -> dict[str, Any] | None:
        progress_path = self.config.output.output_dir / "progress/queries" / f"{query.query_id}.json"
        progress = json.loads(progress_path.read_text(encoding="utf-8"))
        self.llm_client.set_query(query.query_id, self._next_turn_id(progress))
        return super().run_single_query(query, paths_set_catalog)


class GlobalForkRunner(ForkMixin, PlanBenchRecoveryRunner):
    pass


class InstanceForkRunner(ForkMixin, PlanBenchInstanceAdviceRunner):
    pass


def prepare_progress(runner: Any, entries: list[dict[str, Any]],
                     queries: list[Any], cohort: str, variant: str) -> None:
    output = runner.config.output.output_dir
    metadata = output / "metadata.json"
    index_path = output / "progress/index.json"
    if metadata.exists() or index_path.exists():
        if not (metadata.exists() and index_path.exists()):
            raise RuntimeError("Partial output initialization")
        saved = json.loads(metadata.read_text(encoding="utf-8"))
        if saved.get("prefix_cohort") != cohort or saved.get("prefix_variant") != variant:
            raise RuntimeError("Output belongs to another prefix study")
        existing = json.loads(index_path.read_text(encoding="utf-8"))
        if {row["query_id"] for row in existing["queries"]} != {
                entry["query_id"] for entry in entries}:
            raise RuntimeError("Output has another cohort")
        return
    (output / "progress/queries").mkdir(parents=True, exist_ok=True)
    signature = compute_signature(runner.config.merged_config)
    dump_json(metadata, {
        "domain": runner.config.domain,
        "model_name": runner.config.model.model_name,
        "config": runner.config.merged_config,
        "config_signature": signature,
        "created_at": now_utc_iso(),
        "query_count": len(queries),
        "prefix_cohort": cohort,
        "prefix_variant": variant,
    })
    index = runner._initialize_progress_index(queries, signature)
    by_id = {entry["query_id"]: entry for entry in entries}
    for item in index["queries"]:
        entry = by_id[item["query_id"]]
        source = RUNS / entry["source_run"] / "progress/queries" / f"{item['query_id']}.json"
        if hashlib.sha256(source.read_bytes()).hexdigest() != entry["capture_progress_sha256"]:
            raise AssertionError(f"Capture progress changed: {source.name}")
        capture = json.loads(source.read_text(encoding="utf-8"))
        prior_count = entry["failed_turn_id"] - 1
        history = capture["resume_checkpoint"]["effective_history"]
        prefix = history[:2 + 2 * prior_count]
        prior_state = capture["turns"][prior_count - 1]["state_after_turn"]
        fixed = capture["turns"][prior_count]["llm_raw_response"]
        if (digest(prefix) != entry["history_prefix_sha256"]
                or digest(prior_state) != entry["prior_state_sha256"]
                or digest(fixed) != entry["fixed_failed_action_sha256"]):
            raise AssertionError(f"Frozen prefix changed: {source.name}")
        progress = {
            "query_id": item["query_id"],
            "status": "pending",
            "truncate_history": capture["truncate_history"],
            "latest_state": prior_state,
            "resume_checkpoint": {"effective_history": prefix,
                                  "raw_history_tail": prefix[-4:]},
            "turns": capture["turns"][:prior_count],
            "final_result": None,
        }
        dump_json(output / item["query_progress_path"], progress)
        item["last_turn_id"] = prior_count
    dump_json(index_path, index)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cohort", choices=("pilot", "confirmation"), required=True)
    parser.add_argument("--variant", choices=("global", "instance"), required=True)
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    cohort_path = DATA / f"planbench_prefix_{args.cohort}_cohort.json"
    cohort = json.loads(cohort_path.read_text(encoding="utf-8"))
    protocol_path = DATA / "planbench_prefix_trial_protocol.json"
    if hashlib.sha256(protocol_path.read_bytes()).hexdigest() != cohort[
            "prospective_protocol_sha256"]:
        raise RuntimeError("Prospective protocol changed")
    for name, expected in cohort["source_sha256"].items():
        if hashlib.sha256((ROOT / name).read_bytes()).hexdigest() != expected:
            raise RuntimeError(f"Frozen source changed: {name}")
    entries = [entry for entry in cohort["entries"]
               if entry["blocker_seed"] == args.seed]
    if not entries:
        raise ValueError("No frozen entries for this seed")
    if args.dry_run:
        print(json.dumps({"cohort": args.cohort, "variant": args.variant,
                          "seed": args.seed, "n": len(entries)}))
        return
    local = json.loads((ROOT / "experiments/config.local.json").read_text(
        encoding="utf-8"))
    run_id = f"prefix_{args.cohort}_{args.variant}_seed{args.seed}"
    config = load_config(
        BENCH / "src/env/config/runs/retail/gpt-5.4/retail_gpt5.4_blocker.yaml",
        cli_overrides={
            "run_id": run_id,
            "model_ref": "openai_deepseek_v4_flash",
            "model.model_name": local["model"],
            "model.request.max_tokens": 4096,
            "model.request.max_retries": 0,
            "model.request.timeout_seconds": 75,
            "blocker.seed": args.seed,
            "blocker.noise_mode": "fixed",
            "blocker.fixed_noise_type": "explicit failures",
            "blocker.fixed_noise_types": None,
            "runtime.max_steps": 100,
            "runtime.max_concurrency": args.workers,
            "query_sample.size": None,
            "query_sample.seed": 20260925,
            "output.output_dir": f"retail/ispa/{run_id}",
        },
    )
    data_root = BENCH / "src/data"
    baseline = load_all_baseline_tools(data_root)
    datatypes = load_all_datatypes(data_root)
    noisy, noisy_by_domain = load_noisy_tools_file(config.data.noisy_tools_file,
                                                    domain=config.domain)
    blockers, blockers_by_domain = load_all_blocker_tools(data_root)
    registry = {**baseline, **noisy, **blockers}
    paths = load_paths_set_catalog(config.data.paths_set_catalog_file)
    replacement_map = generate_blocker_replacements_by_task(
        paths_set_catalog=paths,
        baseline_tools_path=config.data.baseline_tools_file,
        tasks_path=config.data.task_file,
        selection_mode=config.blocker.selection_mode,
        block_n_per_task=config.blocker.block_n_per_task,
        target_remaining_paths=config.blocker.target_remaining_paths,
        target_remaining_ratio=config.blocker.target_remaining_ratio,
        remaining_tolerance=config.blocker.remaining_tolerance,
        min_remaining_paths=config.blocker.min_remaining_paths,
        remaining_path_length_objective=config.blocker.remaining_path_length_objective,
        blocking_edge_count_objective=config.blocker.blocking_edge_count_objective,
        seed=config.blocker.seed,
        noise_mode=config.blocker.noise_mode,
        fixed_noise_type=config.blocker.fixed_noise_type,
        fixed_noise_types=config.blocker.fixed_noise_types,
        multi_noise_count=config.blocker.multi_noise_count,
        max_combo_candidates=config.blocker.max_combo_candidates,
        max_cover_size=config.blocker.max_cover_size,
    )
    delegate = LLMClient(config.model)
    delegate.config_env = {"OPENAI_API_KEY": local["api_key"],
                           "OPENAI_BASE_URL": local["base_url"]}
    fixed = {entry["query_id"]: json.loads((RUNS / entry["source_run"] /
              "progress/queries" / f"{entry['query_id']}.json").read_text(
                  encoding="utf-8"))["turns"][entry["failed_turn_id"] - 1][
                      "llm_raw_response"] for entry in entries}
    replay = ReplayFirstClient(delegate, fixed,
                               {entry["query_id"]: entry["failed_turn_id"]
                                for entry in entries})
    runner_cls = GlobalForkRunner if args.variant == "global" else InstanceForkRunner
    runner = runner_cls(
        config=config,
        llm_client=replay,
        retriever=SemanticRetriever(baseline, datatypes,
                                    config.retriever.embedding_model),
        event_controller=EventController(blockers_by_domain, True,
                                         replacement_map),
        noisy_tool_augmenter=NoisyToolAugmenter(
            noisy_by_domain, config.noise.mode,
            max_total_tools=config.noise.max_total_tools),
        tool_executor=DomainToolExecutor(load_all_databases(data_root)),
        prompt_manager=PromptManager(config.prompt.prompt_dir),
        tool_registry=registry,
        **({"recovery_mode": "advice"} if args.variant == "global" else {}),
    )
    selected = {entry["query_id"] for entry in entries}
    queries = [query for query in load_queries(config.data.query_file)
               if query.query_id in selected]
    if len(queries) != len(entries):
        raise AssertionError("Frozen queries missing")
    prepare_progress(runner, entries, queries, args.cohort, args.variant)
    results = runner.run(queries, paths)
    if len(results) != len(queries):
        raise SystemExit(f"Incomplete matched run: {len(results)}/{len(queries)}")
    print(json.dumps({"run_id": run_id, "queries": len(results),
                      "whole_task_pass": sum(r["status"] == "success"
                                             for r in results)}))


if __name__ == "__main__":
    main()
