"""Deterministic CPU scaling audit for the fixed-assignment closure solver."""
from pathlib import Path
import json
import statistics
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'experiments'))
from repair_region import Edge, least_region  # noqa: E402


def main():
    rows = []
    for n in (100, 1000, 10000, 50000):
        nodes = [f'v{i}' for i in range(n)]
        edges = [Edge(nodes[i], nodes[i+1], ok_10=False) for i in range(n-1)]
        # All nodes become forced. Time includes input conversion, graph
        # indexing, closure propagation and final conflict verification.
        times = []
        for _ in range(20):
            start = time.perf_counter()
            result = least_region(nodes, edges, [nodes[0]])
            times.append((time.perf_counter()-start)*1000)
            assert result.feasible and len(result.nodes) == n
            assert result.edge_visits == 2*(n-1)
            assert len(result.witnesses) == n-1
        rows.append({'nodes': n, 'edges': n-1,
                     'median_ms': statistics.median(times),
                     'min_ms': min(times), 'max_ms': max(times),
                     'edge_visits': result.edge_visits})
    report = {'scenario': 'Worst-propagation chain, fixed replacement assignment, all crossing edges force next node',
              'repetitions': 20, 'clock': 'Python time.perf_counter, local CPU, wall time',
              'rows': rows}
    out = ROOT / 'research/continuation_repair/repair_region_scaling.json'
    out.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
