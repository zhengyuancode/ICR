"""Stop a native PlanBench-XL run at its first input-only recovery opportunity.

This stage spends model calls only to obtain an authentic failure prefix. It
does not run either treatment arm or inspect a task-success verdict.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

from . import run_planbench_pilot as pilot
from .compile_planbench_instance_contracts import input_digest

from env.core.types import RetrievalResult  # type: ignore[import-not-found]

ROOT = Path(__file__).resolve().parents[1]
PLAN = ROOT / "research/continuation_repair/planbench_prefix_exposure_plan.json"
DATA = ROOT / "research/continuation_repair"


class OpportunityCaptureRunner(pilot.EnvRunner):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        baseline = [tool for tool in self.tool_registry.values()
                    if tool.get("tool_type") == "baseline"]
        signatures: dict[tuple[tuple[str, ...], str], list[str]] = defaultdict(list)
        for tool in baseline:
            signatures[(tuple(tool["input_datatypes"]), tool["output_datatype"])].append(tool["name"])
        self.original_by_signature = {key: value[0] for key, value in signatures.items()
                                      if len(value) == 1}
        self.baseline_by_name = {tool["name"]: tool for tool in baseline}
        global_pairs = json.loads((DATA / "planbench_calibrated_contracts.json").read_text(
            encoding="utf-8"))["contracts"]
        self.global_paths = {(row["failed_tool"], tuple(row["path"]))
                             for row in global_pairs}
        indexed = json.loads((DATA / "planbench_instance_contracts.json").read_text(
            encoding="utf-8"))["contracts"]
        self.indexed_paths: dict[str, list[tuple[tuple[str, ...], set[str]]]] = defaultdict(list)
        for row in indexed:
            self.indexed_paths[row["failed_tool"]].append(
                (tuple(row["path"]), set(row["input_hashes"])))

    def _usable(self, query: Any, path: tuple[str, ...]) -> bool:
        for name in path:
            tool = self.baseline_by_name[name]
            disclosed = self.event_controller.augment_retrieval_result(
                query.query_id, query.task_id,
                RetrievalResult(request={"name": name}, tools=[tool]),
            )
            if len(disclosed) != 1 or disclosed[0].get("tool_type") != "baseline":
                return False
        return True

    def _handle_tool_call(self, query: Any, raw_response: str, content: str,
                          step_id: int, state: Any,
                          history: list[dict[str, str]]) -> dict[str, Any]:
        before = len(state.steps_trace)
        prior_trusted_types = {name for name, values in
                               state.trusted_values_by_datatype.items() if values}
        handled = super()._handle_tool_call(query, raw_response, content,
                                             step_id, state, history)
        if handled["done"]:
            return handled
        for event in state.steps_trace[before:]:
            result = event.get("tool_result") or {}
            if (event.get("action") != "call_tool" or result.get("success") is not False
                    or result.get("tool_type") != "blocker_misleading"):
                continue
            request = event.get("request") or {}
            attempted = self.tool_registry.get(request.get("name"))
            supplied = request.get("arguments") or {}
            if attempted is None or len(supplied) != 1:
                continue
            signature = (tuple(attempted["input_datatypes"]),
                         attempted["output_datatype"])
            original = self.original_by_signature.get(signature)
            if original is None:
                continue
            target_type = self.baseline_by_name[original]["output_datatype"]
            if target_type in prior_trusted_types:
                continue
            digest = input_digest(next(iter(supplied.values())))
            supported = [path for path, inputs in self.indexed_paths[original]
                         if digest in inputs and self._usable(query, path)]
            if not supported or any((original, path) in self.global_paths
                                    for path in supported):
                continue
            # The just-completed failed action and state are already persisted
            # by EnvRunner. Its full prefix can be replayed identically in both
            # advice arms without another native-model call.
            captured = self._finalize_query(
                query, state, None, "captured_input_only_failure")
            return {"done": True, "result": captured,
                    "history": handled["history"]}
        return handled


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    plan = json.loads(PLAN.read_text(encoding="utf-8"))
    protocol = json.loads((DATA / "planbench_prefix_trial_protocol.json").read_text(
        encoding="utf-8"))
    for name, expected in protocol["source_sha256"].items():
        if hashlib.sha256((ROOT / name).read_bytes()).hexdigest() != expected:
            raise RuntimeError(f"Frozen capture source changed: {name}")
    tasks = [row["task_id"] for row in plan["schedule"]
             if row["blocker_seed"] == args.seed]
    if not tasks or len(tasks) != len(set(tasks)):
        raise ValueError("Seed has no unique scheduled tasks")
    if args.dry_run:
        print(json.dumps({"seed": args.seed, "tasks": len(tasks),
                          "plan_sha256": hashlib.sha256(PLAN.read_bytes()).hexdigest()}))
        return
    original_config = pilot.load_config

    def load_seed(path: Path, *, cli_overrides: dict[str, Any]) -> Any:
        overrides = dict(cli_overrides)
        overrides["blocker.seed"] = args.seed
        config = original_config(path, cli_overrides=overrides)
        if config.blocker.seed != args.seed:
            raise RuntimeError("Blocker seed override failed")
        return config

    pilot.load_config = load_seed
    pilot.EnvRunner = OpportunityCaptureRunner
    sys.argv = ["run_planbench_pilot", "--variant", "baseline",
                "--run-id", f"prefix_capture_seed{args.seed}",
                "--task-ids", ",".join(tasks), "--max-steps", "100",
                "--workers", str(args.workers)]
    pilot.main()


if __name__ == "__main__":
    main()
