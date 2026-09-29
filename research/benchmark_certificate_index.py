"""Measure the committed observed-input certificate index locally."""
from __future__ import annotations

import gc
import hashlib
import json
import statistics
import time
import tracemalloc
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "research" / "continuation_repair"
RETAIL = ROOT / "external" / "PlanBench-XL-main" / "src" / "data" / "retail"


def input_digest(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def main() -> None:
    index_path = DATA / "planbench_instance_contracts.json"
    raw = index_path.read_bytes()
    tools = json.loads((RETAIL / "baseline_tools.json").read_text(encoding="utf-8"))
    rows = list(json.loads((RETAIL / "database.json").read_text(
        encoding="utf-8"))["order_cases"].values())
    by_name = {tool["name"]: tool for tool in tools}

    gc.collect()
    tracemalloc.start()
    payload = json.loads(raw)
    by_tool: dict[str, list[tuple[list[str], set[str]]]] = {}
    for item in payload["contracts"]:
        by_tool.setdefault(item["failed_tool"], []).append(
            (item["path"], set(item["input_hashes"])))
    current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    queries = []
    for failed, paths in by_tool.items():
        datatype = by_name[failed]["input_datatypes"][0]
        for row in rows:
            if row.get(datatype) is not None:
                queries.append((failed, row[datatype]))

    def lookup(query: tuple[str, object]) -> list[list[str]]:
        failed, value = query
        hashed = input_digest(value)
        return [path for path, support in by_tool.get(failed, ()) if hashed in support]

    for query in queries:
        lookup(query)
    repeats = []
    for _ in range(9):
        start = time.perf_counter_ns()
        for query in queries:
            lookup(query)
        repeats.append((time.perf_counter_ns() - start) / len(queries) / 1000)

    report = {
        "index_file_bytes": len(raw),
        "contracts": len(payload["contracts"]),
        "safe_path_input_pairs": payload["n_safe_path_input_pairs"],
        "query_cases": len(queries),
        "parsed_index_current_bytes": current,
        "parsed_index_peak_bytes": peak,
        "lookup_us_per_query_median": statistics.median(repeats),
        "lookup_us_repeats": repeats,
    }
    (DATA / "certificate_index_benchmark.json").write_text(
        json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()

