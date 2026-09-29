"""Interface-closed recovery adapter for the released PlanBench-XL runtime.

The failed endpoint is identified by its unique public type signature, not
injector metadata. The controller does not read reference paths, answers, or
the injector's replacement map. Native availability checks keep other blocked
tools blocked during automatic execution.
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from env.core.types import AgentState, QuerySpec, RetrievalResult  # type: ignore[import-not-found]
from env.runtime.runner import EnvRunner  # type: ignore[import-not-found]

class PlanBenchRecoveryRunner(EnvRunner):
    def __init__(self, *args: Any, recovery_mode: str, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        if recovery_mode not in {"advice", "singleton", "dispatch"}:
            raise ValueError(recovery_mode)
        self.recovery_mode = recovery_mode
        self.baseline_tools = [
            spec for spec in self.tool_registry.values() if spec.get("tool_type") == "baseline"
        ]
        self.baseline_by_name = {spec["name"]: spec for spec in self.baseline_tools}
        by_signature: dict[tuple[tuple[str, ...], str], list[dict[str, Any]]] = defaultdict(list)
        for spec in self.baseline_tools:
            by_signature[(tuple(spec["input_datatypes"]), spec["output_datatype"])].append(spec)
        self.baseline_by_signature = {
            signature: specs[0] for signature, specs in by_signature.items() if len(specs) == 1
        }
        contract_file = Path(__file__).resolve().parent / "continuation_repair" / "planbench_calibrated_contracts.json"
        contracts = json.loads(contract_file.read_text(encoding="utf-8"))["contracts"]
        self.contracts_by_tool: dict[str, list[list[str]]] = {}
        for item in contracts:
            self.contracts_by_tool.setdefault(item["failed_tool"], []).append(item["path"])
        for paths in self.contracts_by_tool.values():
            paths.sort(key=lambda path: (len(path), path))

    def _handle_tool_call(
        self,
        query: QuerySpec,
        raw_response: str,
        content: str,
        step_id: int,
        state: AgentState,
        history: list[dict[str, str]],
    ) -> dict[str, Any]:
        prior_count = len(state.steps_trace)
        handled = super()._handle_tool_call(query, raw_response, content, step_id, state, history)
        if handled["done"] or len(state.steps_trace) <= prior_count:
            return handled
        failed_trace = state.steps_trace[-1]
        result = failed_trace.get("tool_result") or {}
        if failed_trace.get("action") != "call_tool" or result.get("success") is not False:
            return handled
        request = failed_trace.get("request") or {}
        attempted_name = request.get("name")
        attempted = self.tool_registry.get(attempted_name) if isinstance(attempted_name, str) else None
        if attempted is None:
            return handled
        signature = (tuple(attempted["input_datatypes"]), attempted["output_datatype"])
        original = self.baseline_by_signature.get(signature)
        if original is None or len(original["input_datatypes"]) != 1:
            return handled
        supplied = request.get("arguments") or {}
        if len(supplied) != 1:
            return handled
        input_type = original["input_datatypes"][0]
        canonical = {input_type: next(iter(supplied.values()))}
        baseline_name = original["name"]
        attempt_key = json.dumps([query.query_id, baseline_name, canonical[input_type]], sort_keys=True, default=str)
        if any(
            trace.get("action") == "icr_recovery" and trace.get("attempt_key") == attempt_key
            for trace in state.steps_trace
        ):
            return handled

        paths = self.contracts_by_tool.get(baseline_name, [])
        if not paths:
            return handled
        usable = []
        for candidate_path in paths:
            effective = []
            for name in candidate_path:
                candidate = self.baseline_by_name[name]
                disclosed = self.event_controller.augment_retrieval_result(
                    query.query_id,
                    query.task_id,
                    RetrievalResult(request={"name": name}, tools=[candidate]),
                )
                if len(disclosed) != 1 or disclosed[0].get("tool_type") != "baseline":
                    break
                effective.append(disclosed[0])
            if len(effective) == len(candidate_path):
                usable.append((candidate_path, effective))
        if not usable:
            return handled
        path, effective_tools = usable[0]

        # The same candidate specifications enter both arms and become callable
        # through the benchmark's normal discovered-tool ledger.
        state.discovered_tool_names.update(spec["name"] for spec in effective_tools)
        program_specs = [
            {
                "name": spec["name"],
                "description": spec["description"],
                "input_datatypes": spec["input_datatypes"],
                "output_datatype": spec["output_datatype"],
                "parameters": spec["parameters"],
            }
            for spec in effective_tools
        ]
        completed = []
        status = "advised"
        auto_execute = self.recovery_mode == "dispatch" or (self.recovery_mode == "singleton" and len(usable) == 1)
        if auto_execute:
            value = canonical[input_type]
            status = "completed"
            for substep, spec in enumerate(effective_tools, 1):
                if len(spec["input_datatypes"]) != 1 or spec.get("tool_type") != "baseline":
                    status = "unavailable"
                    break
                canonical_arguments = {spec["input_datatypes"][0]: value}
                outcome = self.tool_executor.execute_tool(spec, canonical_arguments)
                state.tool_call_attempt_count += 1
                state.tool_call_exec_count += 1
                self._record_execution_output(state, outcome)
                state.steps_trace.append(
                    {
                        "step_id": step_id,
                        "substep": substep,
                        "action": "call_tool",
                        "parse_ok": True,
                        "request": {"name": spec["name"], "arguments": canonical_arguments},
                        "tool_result": {
                            "success": outcome.success,
                            "output_datatype": outcome.output_datatype,
                            "output_value": outcome.output_value,
                            "tool_type": outcome.tool_type,
                            "output_provenance": outcome.output_provenance,
                        },
                        "icr_automatic": True,
                    }
                )
                completed.append({"tool": spec["name"], "output_datatype": outcome.output_datatype, "output_value": outcome.output_value})
                if not outcome.success or outcome.output_value is None or outcome.output_provenance != "trusted":
                    status = "execution_failed"
                    break
                value = outcome.output_value
        state.steps_trace.append(
            {
                "step_id": step_id,
                "action": "icr_recovery",
                "attempt_key": attempt_key,
                "mode": self.recovery_mode,
                "failed_tool": attempted_name,
                "original_tool": baseline_name,
                "path": path,
                "usable_program_count": len(usable),
                "status": status,
            }
        )
        feedback = {
            "feedback_type": "interface_closed_recovery",
            "mode": self.recovery_mode,
            "status": status,
            "failed_tool": attempted_name,
            "input_datatype": input_type,
            "input_value": canonical[input_type],
            "target_datatype": original["output_datatype"],
            "program": program_specs,
            "usable_program_count": len(usable),
            "executed_calls": completed,
        }
        extra = "Recovery controller:\n```json\n" + json.dumps(feedback, ensure_ascii=False, default=str) + "\n```"
        revised_history = handled["history"] + [{"role": "user", "content": extra}]
        self._mark_turn_completed(
            query.query_id,
            step_id,
            raw_response,
            {"action": "tool_call", "parse_ok": True, "request": request},
            extra,
            state,
            revised_history,
        )
        return {"done": False, "result": None, "history": revised_history}
