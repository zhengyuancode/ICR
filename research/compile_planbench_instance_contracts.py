"""Compile input-indexed read-only path-effect certificates without task labels."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .planbench_probe import ROOT as DATA_ROOT, alternatives
from .relational_certificate_study import functional_dependencies, normalized


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "research/continuation_repair/planbench_instance_contracts.json"


def input_digest(value: object) -> str:
    return hashlib.sha256(normalized(value).encode("utf-8")).hexdigest()


def main() -> None:
    if OUTPUT.exists():
        raise FileExistsError(OUTPUT)
    tool_path = DATA_ROOT / "baseline_tools.json"
    database_path = DATA_ROOT / "database.json"
    tools = json.loads(tool_path.read_text(encoding="utf-8"))
    database = json.loads(database_path.read_text(encoding="utf-8"))
    rows = list(database["order_cases"].values())
    by_name = {tool["name"]: tool for tool in tools}
    unary = [tool for tool in tools if len(tool["input_datatypes"]) == 1]
    signatures = {(tool["input_datatypes"][0], tool["output_datatype"]) for tool in unary}
    fds = functional_dependencies(rows, signatures)
    contracts = []
    for failed in unary:
        source, target = failed["input_datatypes"][0], failed["output_datatype"]
        if not fds[(source, target)]:
            continue
        for path in alternatives(tools, failed, max_steps=5):
            if not all(fds[(by_name[name]["input_datatypes"][0], by_name[name]["output_datatype"])] for name in path):
                continue
            intermediate = tuple(by_name[name]["output_datatype"] for name in path[:-1])
            support = {input_digest(row[source]) for row in rows
                       if row.get(source) is not None and row.get(target) is not None
                       and all(row.get(dtype) is not None for dtype in intermediate)}
            if support:
                contracts.append({"failed_tool": failed["name"], "path": path,
                                  "input_hashes": sorted(support)})
    contracts.sort(key=lambda row: (row["failed_tool"], len(row["path"]), row["path"]))
    payload = {
        "scope": "Public fixed retail relation; deterministic read-only projection tools",
        "certificate": "For the observed input, original and path edges have functional dependencies and a common non-null row witness",
        "task_reference_paths_or_answers_used": False,
        "tool_catalog_sha256": hashlib.sha256(tool_path.read_bytes()).hexdigest(),
        "database_sha256": hashlib.sha256(database_path.read_bytes()).hexdigest(),
        "n_paths_with_safe_input": len(contracts),
        "n_safe_path_input_pairs": sum(len(item["input_hashes"]) for item in contracts),
        "contracts": contracts,
    }
    OUTPUT.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps({key: value for key, value in payload.items() if key != "contracts"}, indent=2))


if __name__ == "__main__":
    main()
