<div align="center">

# ICR · Interface-Closed Recovery

**Recover tool workflows without breaking the continuation.**

![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?style=flat-square)
![Version](https://img.shields.io/badge/version-0.1.0-0F766E?style=flat-square)
![Dependencies](https://img.shields.io/badge/core_dependencies-0-475569?style=flat-square)

**English** · [简体中文](README.zh-CN.md)

[Quick start](#quick-start) · [Workflow recovery](#workflow-recovery) · [Relational certificates](#relational-certificates) · [Documentation](#documentation) · [Reproduction](REPRODUCING.md)

</div>

---

ICR is a Python tool for recovering read-only tool workflows when an implementation
fails or a replacement changes an intermediate interface. It jointly selects
alternative implementations and the nodes that must change, so a locally valid
replacement does not break the remaining workflow.

For tools defined as unary projections over a JSON relation, ICR also finds and
executes an alternative route with an **observed-input certificate**: the route
must produce the trusted target value for the actual input on the bound snapshot.

## What you can do

| Workflow repair | Relational recovery | Application integration |
| :--- | :--- | :--- |
| Jointly select implementations and repair scope | Certify the actual input against a bound snapshot | Use Python APIs or JSON CLI packets |
| Preserve external input and terminal output interfaces | Reject ambiguous values and stale certificates | Register read-only Python or HTTP handlers |
| Replan after an implementation fails | Rank admitted routes by declared cost | Validate values before downstream execution |

## Quick start

Python 3.10 or newer. The tool has **no runtime dependencies**, GPU requirement,
model subscription or benchmark download.

```bash
git clone https://github.com/zhengyuancode/ICR.git
cd ICR
python -m pip install .
icr demo
```

Already cloned? Run the last two commands from the repository root.
`python -m icr demo` is equivalent to `icr demo`.

The demo actually executes two recoveries:

* A failed CSV producer is replaced by a JSON producer. ICR also replaces the
  consumer, preserving the final summary interface.
* A failed direct balance lookup is replaced by customer-to-account-to-balance
  projections. A sparse unrelated record prevents global certification, but the
  observed input has a valid common-record witness and returns the correct value.

## Workflow recovery

Describe each node's original implementation, approved alternatives, operation
identity, input/output schema IDs and change costs. Bind dependency edges to input
ports. Then plan a repair:

```bash
icr plan examples/workflow.json --failed fetch
icr plan examples/workflow.json --failed fetch --immutable summarize
```

The first command returns a minimum-cost joint assignment and changed region.
The second returns infeasible because the consumer cannot change. Plans are JSON
advice packets; planning does not call your tools.

For automatic read-only recovery, register your actual Python handlers and schema
validators:

```python
from icr import Workflow, recover

workflow = Workflow.from_file("examples/workflow.json")
# handlers: {(node, implementation): callable}
# validators: {schema_id: predicate}
# external_inputs: {node: [values for its input ports]}
outputs, plan, failures = recover(
    workflow, handlers, external_inputs, validators, max_attempts=3
)
```

A complete runnable handler example is [`icr/demo.py`](icr/demo.py); run it with `icr demo`.
[`examples/http_workflow.py`](examples/http_workflow.py) connects the same workflow to actual CSV/JSON HTTP
endpoints supplied through environment variables.
[`docs/workflows.md`](docs/workflows.md) explains how to integrate HTTP tools,
set execution budgets, freeze implementation choices and interpret failures.

## Relational certificates

```bash
icr repair examples/snapshot.json examples/catalog.json --source customer --target balance --input '"Ada"' --exclude direct_balance --execute
```

`--input` is a JSON value; quote strings as JSON strings. On Windows PowerShell,
Python is often simpler when shell quoting differs:

```python
from icr import Snapshot, Projection, RelationalRecovery

snapshot = Snapshot([
    {"customer": "Ada", "account": "A7", "balance": 42},
    {"customer": "Ben", "account": None, "balance": 10},
])
engine = RelationalRecovery(snapshot, [
    Projection("customer_account", "customer", "account"),
    Projection("account_balance", "account", "balance"),
])
admission, rejected = engine.repair("customer", "balance", "Ada")
if admission.admitted:
    value = engine.execute(admission.certificate, current_snapshot=snapshot)
    assert value == 42
```

Certificates include the snapshot/catalog digests, path, observed input, expected
output and witness rows. Execution recomputes evidence and refuses stale or altered
certificates. [`docs/relational.md`](docs/relational.md) describes equality, NULL,
search bounds, global certification and snapshot updates.

## Documentation

| Start here | Contents |
| :--- | :--- |
| [Workflow guide](docs/workflows.md) | Specification, planning, execution, HTTP handlers and agent integration |
| [Certificate guide](docs/relational.md) | Evidence, value equality, route search and snapshot updates |
| [HTTP example](examples/http_workflow.py) | Connect recovery to your own CSV/JSON endpoints |
| [Reproduction guide](REPRODUCING.md) | Data acquisition, experiment runners and recorded statistics |

<details>
<summary><strong>Public API reference at a glance</strong></summary>


| Need | API |
|---|---|
| Plan a multi-input DAG repair | `Workflow`, `plan_repair` |
| Execute registered read-only handlers after validation | `execute` |
| Run and recover after failures | `recover` |
| Find and execute a certified relation route | `RelationalRecovery` |
| Least region for a fixed assignment | `least_region`, `Edge` |
| Exact forest optimization | `solve_tree`, `Choice` |
| Exact port-bound constraint optimization | `solve_ports`, `PortChoice` |

</details>

## Execution contract

Operation equivalence and implementation schemas are application declarations.
ICR checks these declarations and does not infer semantic equivalence from tool
names. The workflow executor requires explicit read-only declarations and schema
validators. It reruns predecessors; it does not roll back or authorize writes.
Relational certificates cover the declared fixed-snapshot projection semantics,
not arbitrary remote API behavior or complete agent intent.

## Tests and experiment reproduction

```bash
python -m pip install ".[test]"
python -m pytest -q
python scripts/verify_claims.py
```

Tests exercise actual execution, failed-alternative exclusion, interface boundaries,
stale snapshots, ambiguous lookup values and exhaustive structural oracles.
`verify_claims.py` independently recomputes the recorded experiment statistics;
it neither calls a model nor downloads data.

The product is in `icr/`; practical examples are in `examples/`. The separate
`experiments/`, `research/` and `scripts/` directories contain experiment runners
and committed result records. [`REPRODUCING.md`](REPRODUCING.md) gives the complete
reproduction commands. Model API access is needed only to rerun online experiments.
Benchmark source datasets retain their upstream licenses and are fetched separately.
This repository contains no manuscript, figures or figure-generation sources.

---

<div align="center">

[Source](https://github.com/zhengyuancode/ICR) · [Report an issue](https://github.com/zhengyuancode/ICR/issues) · [中文文档](README.zh-CN.md)

</div>
