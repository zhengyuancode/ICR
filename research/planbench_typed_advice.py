"""Type-only recovery-advice ablation for the native PlanBench-XL agent.

It uses the same failure trigger, packet, disclosed tools, and model as
certificate advice, but admits every boundary-typed path up to five calls.
The shortest lexicographic path is shown to the model without an effect test.
"""
from __future__ import annotations

from .planbench_controller import PlanBenchRecoveryRunner
from .planbench_probe import alternatives


class PlanBenchTypedAdviceRunner(PlanBenchRecoveryRunner):
    def __init__(self, *args, **kwargs):
        kwargs["recovery_mode"] = "advice"
        super().__init__(*args, **kwargs)
        tools = self.baseline_tools
        self.contracts_by_tool = {
            failed["name"]: sorted(
                alternatives(tools, failed, max_steps=5),
                key=lambda path: (len(path), path),
            )
            for failed in tools
            if len(failed["input_datatypes"]) == 1
        }
