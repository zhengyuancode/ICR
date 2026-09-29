"""Run paired PlanBench continuations from identical observed failure prefixes.

The first model action after each copied prefix is replayed verbatim from the
native baseline and causes the same explicit blocker failure. The advice and
dispatch adapters then receive the same state. Only subsequent model turns
call the configured API. Frozen cohort hashes guard every copied prefix.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import threading
from pathlib import Path
from typing import Any

from .run_planbench_pilot import (
    ROOT, BENCH, load_config, load_all_baseline_tools, load_all_datatypes,
    load_noisy_tools_file, load_all_blocker_tools, load_paths_set_catalog,
    generate_blocker_replacements_by_task, LLMClient, SemanticRetriever,
    EventController, NoisyToolAugmenter, DomainToolExecutor,
    load_all_databases, PromptManager, load_queries,
)
from .planbench_controller import PlanBenchRecoveryRunner

from env.core.utils import compute_signature, dump_json, now_utc_iso  # type: ignore[import-not-found]


DATA = ROOT / "research" / "continuation_repair"
BASELINE = BENCH / "outputs" / "retail" / "ispa" / "heldout_r1_baseline" / "progress" / "queries"


def digest(value: object) -> str:
    raw = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class ReplayFirstClient:
    def __init__(self, delegate: Any, fixed: dict[str, str], failed_turns: dict[str, int]) -> None:
        self.delegate = delegate
        self.fixed = fixed
        self.failed_turns = failed_turns
        self.local = threading.local()
        self.used: set[str] = set()
        self.lock = threading.Lock()

    def set_query(self, query_id: str, next_turn_id: int) -> None:
        self.local.query_id = query_id
        if next_turn_id > self.failed_turns[query_id]:
            with self.lock:
                self.used.add(query_id)

    def generate(self, history: list[dict[str, str]]) -> str:
        query_id = self.local.query_id
        with self.lock:
            if query_id not in self.used:
                self.used.add(query_id)
                return self.fixed[query_id]
        return self.delegate.generate(history)


class ForkRunner(PlanBenchRecoveryRunner):
    def run_single_query(self, query: Any, paths_set_catalog: list[dict[str, Any]]) -> dict[str, Any] | None:
        progress_path = self.config.output.output_dir / "progress" / "queries" / f"{query.query_id}.json"
        progress = json.loads(progress_path.read_text(encoding="utf-8"))
        self.llm_client.set_query(query.query_id, self._next_turn_id(progress))
        return super().run_single_query(query, paths_set_catalog)


def prepare_progress(runner: ForkRunner, queries: list[Any], entries: list[dict[str, Any]]) -> None:
    output = runner.config.output.output_dir
    metadata = output / "metadata.json"
    index_path = output / "progress" / "index.json"
    if metadata.exists() or index_path.exists():
        if not (metadata.exists() and index_path.exists()):
            raise RuntimeError("Partial fork output initialization")
        saved_metadata = json.loads(metadata.read_text(encoding="utf-8"))
        if saved_metadata.get("fork_variant") not in (None, runner.recovery_mode):
            raise RuntimeError("Existing fork output belongs to a different recovery arm")
        existing = json.loads(index_path.read_text(encoding="utf-8"))
        if {item["query_id"] for item in existing["queries"]} != {entry["query_id"] for entry in entries}:
            raise RuntimeError("Existing fork output has a different cohort")
        return
    (output / "progress" / "queries").mkdir(parents=True, exist_ok=True)
    signature = compute_signature(runner.config.merged_config)
    dump_json(metadata, {
        "domain": runner.config.domain,
        "model_name": runner.config.model.model_name,
        "config": runner.config.merged_config,
        "config_signature": signature,
        "created_at": now_utc_iso(),
        "query_count": len(queries),
        "fork_source": "heldout_r1_baseline",
        "fork_variant": runner.recovery_mode,
    })
    index = runner._initialize_progress_index(queries, signature)
    by_id = {entry["query_id"]: entry for entry in entries}
    for item in index["queries"]:
        entry = by_id[item["query_id"]]
        source = BASELINE / f"{item['query_id']}.json"
        if hashlib.sha256(source.read_bytes()).hexdigest() != entry["baseline_progress_sha256"]:
            raise AssertionError(f"Baseline progress changed: {source.name}")
        baseline = json.loads(source.read_text(encoding="utf-8"))
        turn_id = entry["failed_turn_id"]
        prior_count = turn_id - 1
        prefix = baseline["resume_checkpoint"]["effective_history"][: 2 + 2 * prior_count]
        prior_state = baseline["turns"][prior_count - 1]["state_after_turn"]
        fixed = baseline["turns"][prior_count]["llm_raw_response"]
        if (digest(prefix) != entry["history_prefix_sha256"]
            or digest(prior_state) != entry["prior_state_sha256"]
            or digest(fixed) != entry["fixed_failed_action_sha256"]):
            raise AssertionError(f"Frozen fork witness changed: {source.name}")
        progress = {
            "query_id": item["query_id"],
            "status": "pending",
            "truncate_history": baseline["truncate_history"],
            "latest_state": prior_state,
            "resume_checkpoint": {"effective_history": prefix, "raw_history_tail": prefix[-4:]},
            "turns": baseline["turns"][:prior_count],
            "final_result": None,
        }
        dump_json(output / item["query_progress_path"], progress)
        item["last_turn_id"] = prior_count
    dump_json(index_path, index)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--variant", choices=("advice", "dispatch"), required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--query-id", default="", help="One frozen query for an API-free preflight")
    parser.add_argument("--preflight", action="store_true", help="Stop after the fixed failed action, before any live API call")
    args = parser.parse_args()
    cohort = json.loads((DATA / "planbench_failure_fork_cohort.json").read_text(encoding="utf-8"))
    entries = [entry for entry in cohort["entries"] if not args.query_id or entry["query_id"] == args.query_id]
    if not entries or (args.preflight and len(entries) != 1):
        raise ValueError("Preflight requires exactly one frozen query")
    max_steps = entries[0]["failed_turn_id"] if args.preflight else 100
    local = json.loads((ROOT / "experiments" / "config.local.json").read_text(encoding="utf-8"))
    config = load_config(
        BENCH / "src" / "env" / "config" / "runs" / "retail" / "gpt-5.4" / "retail_gpt5.4_blocker.yaml",
        cli_overrides={
            "run_id": args.run_id,
            "model_ref": "openai_deepseek_v4_flash",
            "model.model_name": local["model"],
            "model.request.max_tokens": 4096,
            "model.request.max_retries": 0,
            "model.request.timeout_seconds": 75,
            "blocker.noise_mode": "fixed",
            "blocker.fixed_noise_type": "explicit failures",
            "blocker.fixed_noise_types": None,
            "runtime.max_steps": max_steps,
            "runtime.max_concurrency": args.workers,
            "query_sample.size": None,
            "query_sample.seed": 20260925,
            "output.output_dir": f"retail/ispa/{args.run_id}",
        },
    )
    data_root = BENCH / "src" / "data"
    baseline = load_all_baseline_tools(data_root)
    datatypes = load_all_datatypes(data_root)
    noisy, noisy_by_domain = load_noisy_tools_file(config.data.noisy_tools_file, domain=config.domain)
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
    delegate.config_env = {"OPENAI_API_KEY": local["api_key"], "OPENAI_BASE_URL": local["base_url"]}
    fixed = {}
    for entry in entries:
        source = json.loads((BASELINE / f"{entry['query_id']}.json").read_text(encoding="utf-8"))
        fixed[entry["query_id"]] = source["turns"][entry["failed_turn_id"] - 1]["llm_raw_response"]
    replay_client = ReplayFirstClient(
        delegate, fixed, {entry["query_id"]: entry["failed_turn_id"] for entry in entries}
    )
    runner = ForkRunner(
        config=config,
        llm_client=replay_client,
        retriever=SemanticRetriever(baseline, datatypes, config.retriever.embedding_model),
        event_controller=EventController(blockers_by_domain, True, replacement_map),
        noisy_tool_augmenter=NoisyToolAugmenter(
            noisy_by_domain, config.noise.mode, max_total_tools=config.noise.max_total_tools,
        ),
        tool_executor=DomainToolExecutor(load_all_databases(data_root)),
        prompt_manager=PromptManager(config.prompt.prompt_dir),
        tool_registry=registry,
        recovery_mode=args.variant,
    )
    selected = {entry["query_id"] for entry in entries}
    queries = [query for query in load_queries(config.data.query_file) if query.query_id in selected]
    if len(queries) != len(entries):
        raise AssertionError("Frozen queries missing from dataset")
    prepare_progress(runner, queries, entries)
    results = runner.run(queries, paths)
    if len(results) != len(queries):
        raise SystemExit(f"Incomplete fork run: {len(results)}/{len(queries)}; resume with the same run ID")
    print(json.dumps({"run_id": args.run_id, "variant": args.variant, "queries": len(results), "successes": sum(r["status"] == "success" for r in results)}, indent=2))


if __name__ == "__main__":
    main()
