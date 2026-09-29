"""Run the unmodified PlanBench-XL agent with the existing DeepSeek account.

Credentials are read from experiments/config.local.json into memory and are not
placed in command-line arguments, benchmark configs, progress logs, or outputs.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BENCH = ROOT / "external" / "PlanBench-XL-main"
sys.path.insert(0, str(BENCH / "src"))

from env.core.config import load_config  # type: ignore[import-not-found]
from env.core.sampling import sample_sequence  # type: ignore[import-not-found]
from env.domains.executor import DomainToolExecutor  # type: ignore[import-not-found]
from env.events.blocker import generate_blocker_replacements_by_task  # type: ignore[import-not-found]
from env.events.controller import EventController  # type: ignore[import-not-found]
from env.events.noisy import NoisyToolAugmenter  # type: ignore[import-not-found]
from env.retriever.semantic import SemanticRetriever  # type: ignore[import-not-found]
from env.runtime.llm import LLMClient  # type: ignore[import-not-found]
from env.runtime.prompts import PromptManager  # type: ignore[import-not-found]
from env.runtime.runner import (  # type: ignore[import-not-found]
    EnvRunner,
    load_all_baseline_tools,
    load_all_blocker_tools,
    load_all_databases,
    load_all_datatypes,
    load_noisy_tools_file,
    load_paths_set_catalog,
    load_queries,
)
from .planbench_controller import PlanBenchRecoveryRunner


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--size", type=int, default=2)
    parser.add_argument("--seed", type=int, default=20260925)
    parser.add_argument("--max-steps", type=int, default=35)
    parser.add_argument("--run-id", default="smoke_baseline")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--variant", choices=("baseline", "advice", "singleton", "dispatch"), default="baseline")
    parser.add_argument("--task-ids", default="", help="Comma-separated frozen task IDs; overrides random sampling")
    parser.add_argument("--cohort", choices=("", "pilot", "heldout", "multicandidate", "confirmatory"), default="")
    args = parser.parse_args()
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
            "runtime.max_steps": args.max_steps,
            "runtime.max_concurrency": args.workers,
            "query_sample.size": None if args.task_ids or args.cohort else args.size,
            "query_sample.seed": args.seed,
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
    client = LLMClient(config.model)
    client.config_env = {"OPENAI_API_KEY": local["api_key"], "OPENAI_BASE_URL": local["base_url"]}
    runner_cls = EnvRunner if args.variant == "baseline" else PlanBenchRecoveryRunner
    runner_kwargs = {} if args.variant == "baseline" else {"recovery_mode": args.variant}
    runner = runner_cls(
        config=config,
        llm_client=client,
        retriever=SemanticRetriever(baseline, datatypes, config.retriever.embedding_model),
        event_controller=EventController(blockers_by_domain, True, replacement_map),
        noisy_tool_augmenter=NoisyToolAugmenter(
            noisy_by_domain,
            config.noise.mode,
            max_total_tools=config.noise.max_total_tools,
        ),
        tool_executor=DomainToolExecutor(load_all_databases(data_root)),
        prompt_manager=PromptManager(config.prompt.prompt_dir),
        tool_registry=registry,
        **runner_kwargs,
    )
    all_queries = load_queries(config.data.query_file)
    if args.task_ids or args.cohort:
        if args.task_ids:
            selected = set(args.task_ids.split(","))
        elif args.cohort in {"multicandidate", "confirmatory"}:
            cohort_file = (
                "planbench_multicandidate_cohort.json"
                if args.cohort == "multicandidate"
                else "planbench_confirmatory_cohort.json"
            )
            selected = set(
                json.loads((ROOT / "research" / "continuation_repair" / cohort_file).read_text(encoding="utf-8"))["task_ids"]
            )
        else:
            selected = set(
                json.loads((ROOT / "research" / "continuation_repair" / "planbench_online_cohort.json").read_text(encoding="utf-8"))[
                    "pilot_task_ids" if args.cohort == "pilot" else "heldout_task_ids"
                ]
            )
        queries = [query for query in all_queries if query.task_id in selected]
        if len(queries) != len(selected):
            raise ValueError("Some requested task IDs are absent from the released dataset")
    else:
        queries = sample_sequence(all_queries, args.size, args.seed)
    print("task_ids:", [query.task_id for query in queries], flush=True)
    results = runner.run(queries, paths)
    print("results:", [(result.get("query_id"), result.get("status"), result.get("failure_reason_detail")) for result in results])
    if len(results) != len(queries):
        raise SystemExit(
            f"Incomplete run: {len(results)}/{len(queries)} finished; resume with the same --run-id after resolving the recorded errors"
        )


if __name__ == "__main__":
    main()
