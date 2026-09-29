# Interface-Closed Recovery (ICR)

This repository provides the reference implementation of **Interface-Closed
Recovery (ICR)**, together with tests, experiment drivers, and the paper source
for **Interface-Closed Recovery: Joint Workflow Repair with Observed-Input
Certificates**.

ICR repairs a failed tool workflow in two coupled steps: it selects replacement
implementations together with the least region that reconnects to unchanged
work, then admits a relational recovery path only when its boundary value is
certified for the observed input.

## Install and verify

The commands below do not call a language model or download a benchmark.

```bash
python -m pip install -r requirements.txt
python scripts/verify_claims.py
python -m pytest experiments/test_repair_region.py \
  experiments/test_joint_repair.py experiments/test_port_joint_repair.py
python paper/figure_sources/generate_figures.py
```

`verify_claims.py` recomputes the reported denominators, paired contrasts, and
exact McNemar tests from the committed graph-level and task-level records. It
writes `reproduced_claims.json` and exits with a nonzero status if a paper claim
does not match its frozen evidence.

## Use the solvers

The implementation is ordinary Python source and does not require package
installation. Run code from the repository root. For example:

```python
from experiments.repair_region import Edge, least_region

region = least_region(
    nodes=["producer", "consumer", "context"],
    edges=[
        Edge("producer", "consumer", ok_10=False),
        Edge("consumer", "context"),
    ],
    failed={"producer"},
    immutable={"context"},
)
print(region.feasible, sorted(region.nodes))
```

Joint implementation and scope selection is exposed through
`experiments.joint_repair.solve_tree`; port-bound DAG optimization is exposed
through `experiments.port_joint_repair.solve_ports`. Their oracle-backed tests
show complete input constructions.

## Repository map

| Paper result | Code | Frozen evidence |
|---|---|---|
| Least interface-closed repair region | `experiments/repair_region.py` | `research/continuation_repair/taskbench_*_multinode_results*.json` |
| Joint implementation/scope optimization | `experiments/joint_repair.py` | `joint_taskbench_results*.json`, `joint_beam_*.json` |
| Port-bound DAG optimization | `experiments/port_joint_repair.py` | `port_dag_taskbench_*.json` |
| Observed-input certificate | `research/relational_certificate_study.py`, `research/compile_planbench_instance_contracts.py` | `planbench_*contracts.json`, `planbench_route_decisions.json` |
| 72-task system confirmation | `research/analyze_planbench_seed43_confirmation.py` | `planbench_seed43_*protocol.json`, `planbench_seed43_confirmation72_analysis.json` |
| 21-task matched policy control | `research/analyze_planbench_final_holdout.py` | `planbench_final_*` |
| 20-prefix matched-state control | `research/analyze_planbench_prefix_trial.py` | `planbench_prefix_*` |
| Paper figures | `paper/figure_sources/generate_figures.py` | the same frozen result records |

The evidence directory contains graph-level records for the structural studies
and task-level rows for every online denominator used in the paper. Large
provider-generated conversation traces are not required to reproduce the
reported statistics; the online runners recreate them when supplied with an
API configuration.

## Reproducing the paper

Run the public-data fetcher once:

```bash
python scripts/fetch_public_data.py
```

It downloads the six TaskBench files used by the paper, clones PlanBench-XL at
the recorded commit, and verifies every source SHA-256 digest. Then follow
[`REPRODUCING.md`](REPRODUCING.md) for the structural, certificate, and online
experiments.

All structural and certificate experiments are local and require no GPU or
model API. Online reruns require an OpenAI-compatible endpoint. Copy
`experiments/config.example.json` to `experiments/config.local.json`, fill in
the three values, and keep that file untracked. The repository contains no API
credentials.

## Scope

The certificate result is a finite-snapshot guarantee for PlanBench-XL's fixed,
read-only retail relation under the declared projection semantics. The 72-task
comparison evaluates the complete ICR advice system against the native agent;
it is not presented as an isolated causal estimate of the certificate alone.

TaskBench and PlanBench-XL remain subject to their upstream licenses. This
repository does not redistribute their source datasets; the fetcher retrieves
the exact public files and checks their recorded hashes.
