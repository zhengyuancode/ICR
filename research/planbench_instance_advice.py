"""Input-indexed effect-certified advice on the native PlanBench-XL runner.

The immutable contract index stores only hashes of inputs with a relational
support witness, never benchmark answers or reference paths. The same native
failure trigger, tool ledger, and packet renderer remain in use.
"""
from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

from .compile_planbench_instance_contracts import input_digest
from .planbench_controller import PlanBenchRecoveryRunner


ROOT = Path(__file__).resolve().parents[1]
CONTRACTS = ROOT / "research/continuation_repair/planbench_instance_contracts.json"


class InputIndexedPaths:
    def __init__(self, contracts: list[dict[str, Any]]) -> None:
        self.by_tool: dict[str, list[tuple[list[str], set[str]]]] = {}
        for item in contracts:
            self.by_tool.setdefault(item["failed_tool"], []).append(
                (item["path"], set(item["input_hashes"]))
            )
        for paths in self.by_tool.values():
            paths.sort(key=lambda row: (len(row[0]), row[0]))
        self.local = threading.local()

    def set_state(self, state: Any) -> None:
        self.local.state = state

    def clear_state(self) -> None:
        self.local.state = None

    def get(self, failed_tool: str, default: Any = None) -> Any:
        state = getattr(self.local, "state", None)
        if state is None or not state.steps_trace:
            return default
        last = state.steps_trace[-1]
        supplied = (last.get("request") or {}).get("arguments") or {}
        if last.get("action") != "call_tool" or len(supplied) != 1:
            return default
        digest = input_digest(next(iter(supplied.values())))
        return [path for path, support in self.by_tool.get(failed_tool, ()) if digest in support]


class PlanBenchInstanceAdviceRunner(PlanBenchRecoveryRunner):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        kwargs["recovery_mode"] = "advice"
        super().__init__(*args, **kwargs)
        index = json.loads(CONTRACTS.read_text(encoding="utf-8"))
        self.contracts_by_tool = InputIndexedPaths(index["contracts"])

    def _handle_tool_call(self, query: Any, raw_response: str, content: str,
                          step_id: int, state: Any, history: list[dict[str, str]]) -> dict[str, Any]:
        self.contracts_by_tool.set_state(state)
        try:
            return super()._handle_tool_call(query, raw_response, content, step_id, state, history)
        finally:
            self.contracts_by_tool.clear_state()
