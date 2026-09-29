"""Audit public PlanBench-XL tool interfaces without reading reference paths."""

from __future__ import annotations

import collections
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1] / "external" / "PlanBench-XL-main" / "src" / "data" / "retail"


def alternatives(tools: list[dict], failed: dict, max_steps: int = 5) -> list[list[str]]:
    by_input: dict[str, list[dict]] = collections.defaultdict(list)
    for tool in tools:
        inputs = tool["input_datatypes"]
        if len(inputs) == 1 and tool["name"] != failed["name"]:
            by_input[inputs[0]].append(tool)
    start, goal = failed["input_datatypes"][0], failed["output_datatype"]
    queue = collections.deque([(start, [])])
    found: list[list[str]] = []
    while queue:
        node, path = queue.popleft()
        if len(path) >= max_steps:
            continue
        for tool in by_input[node]:
            output = tool["output_datatype"]
            if output in (start, *(t["output_datatype"] for t in path)):
                continue
            new_path = path + [tool]
            if output == goal:
                found.append([t["name"] for t in new_path])
            else:
                queue.append((output, new_path))
    return found


def main() -> None:
    tools = json.loads((ROOT / "baseline_tools.json").read_text(encoding="utf-8"))
    counts = collections.Counter()
    examples = []
    for failed in tools:
        if len(failed["input_datatypes"]) != 1:
            continue
        paths = alternatives(tools, failed)
        counts[(len(paths), min(map(len, paths), default=0))] += 1
        if paths and len(examples) < 8:
            examples.append((failed["name"], failed["input_datatypes"], failed["output_datatype"], len(paths), paths[:2]))
    print("tools:", len(tools))
    print("alternative route count / shortest length:", dict(sorted(counts.items())))
    print("examples:")
    for row in examples:
        print(row)


if __name__ == "__main__":
    main()
