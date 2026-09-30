# Workflow integration

## Specification

`Workflow` accepts a JSON object with `nodes` and `edges`. Each node maps to a list
of implementations. Exactly one is `original: true`.

```json
{
  "nodes": {
    "fetch": [
      {"name": "csv", "inputs": ["request"], "output": "csv",
       "operation": "fetch_record", "original": true, "read_only": true},
      {"name": "json", "inputs": ["request"], "output": "json",
       "operation": "fetch_record", "cost": 1, "read_only": true}
    ],
    "render": [
      {"name": "csv", "inputs": ["csv"], "output": "summary",
       "operation": "render_record", "original": true, "read_only": true},
      {"name": "json", "inputs": ["json"], "output": "summary",
       "operation": "render_record", "cost": 1, "read_only": true}
    ]
  },
  "edges": [["fetch", "render", 0]]
}
```

An edge is `[source_node, target_node, target_input_port]`. Each target port can
have at most one dependency. Unbound ports are external inputs. Terminal output
schemas and external input schemas must stay equal to their original schemas.
The graph must be acyclic; implementations at a node must have the same port count.
Schema compatibility follows the existing solver's case-insensitive ID comparison;
use a single consistent spelling and register validators for every declared ID.

`operation` is your reviewed identity for the node's logical operation. Only
implementations sharing the original operation ID are eligible. Do not assign the
same operation ID merely because tools have matching argument types.

## Planning

```python
from icr import Workflow, plan_repair
workflow = Workflow(spec)
plan = plan_repair(workflow, failed={"fetch"}, immutable=set(),
                   max_width=8, max_states=1_000_000)
print(plan.to_dict())
```

`failed` disallows original implementations at those nodes; `immutable` fixes nodes
to their original implementations. `forced={"node": "implementation"}` pins a
particular choice. Immutable here refers to implementation selection, not a promise
to cache previously committed outputs. `execute` reruns all nodes and is read-only.
To exclude a failed nonoriginal implementation, remove it from the alternatives;
`recover` does this automatically while retaining the original boundary reference.

Costs are nonnegative and additive over changed nodes. The exact solver minimizes
cost, then the number of changed nodes, with deterministic local tie-breaking.
The changed region is the set of nodes selecting nonoriginal implementations;
it may also include an otherwise unnecessary zero-cost change only if required
by compatibility (the secondary objective minimizes change count).

The solver uses variable elimination. `max_width` caps induced width, and
`max_states` caps a conservative bound on enumerated factor combinations before
allocation. Exceeding either limit raises `ValueError`: this means the problem
was not solved, not that a repair cannot exist. A returned infeasible plan means
no assignment satisfies the supplied finite catalog and boundary constraints.
The low-level `solve_ports` API has no resource caps and is intended for callers
who manage their own budgets. `solve_tree` is a specialized forest solver.

## Execution and HTTP integration

`execute(workflow, plan, handlers, external_inputs, validators)` requires:

* `handlers[(node, implementation)]`: a callable accepting input ports in order.
* `validators[schema_id]`: a callable returning whether a value satisfies its schema.
* `external_inputs[node]`: a full-length list of port values for nodes with unbound
  ports. Entries on dependency-bound ports are overwritten.
* Explicit `read_only: true` for every selected implementation.

All handler availability, validator availability, interface constraints and external
inputs are checked before any handler is called. Runtime outputs are validated
before reaching a consumer. Handler/validator failures are reported as
`ExecutionError` with the node and implementation. Port values are copied to avoid
accidental mutation shared across consumers.

For a read-only JSON HTTP endpoint, register an adapter such as:

```python
import json
from urllib.parse import urlencode
from urllib.request import urlopen

def fetch_json(customer_id):
    url = base_url + "?" + urlencode({"customer_id": customer_id})
    with urlopen(url, timeout=10) as response:
        return json.load(response)

handlers[("fetch", "json")] = fetch_json
validators["json_record"] = lambda value: (
    isinstance(value, dict) and isinstance(value.get("orders"), int)
)
```

You supply `base_url`, credentials outside the repository, and the adapter's actual
operation contract. The adapter must be read-only even if its transport uses POST.
The flag is a trusted declaration, not a network sandbox or proof of remote effects.

`examples/http_workflow.py` is a complete HTTP integration. Set `ICR_CSV_URL` and
`ICR_JSON_URL` to your reviewed endpoints and run `python examples/http_workflow.py
customer-1` after installing ICR. The CSV endpoint supplies a single `id,orders`
record; the JSON endpoint supplies the same record as an object. Both are queried
with `customer_id`. The example checks record identity, validates data, applies a
10-second request timeout, and switches both fetcher and consumer after failure.

`recover` first runs the original minimum-change plan. After an execution failure
it excludes the failed implementation, replans jointly and reruns the workflow.
`max_attempts` includes the first execution. It returns `(outputs, successful_plan,
failure_history)`; history records node, implementation and exception class, not
potentially secret response content. Infeasibility and invalid configuration raise
`ValueError`; exhausting attempts raises `RuntimeError`. Application handlers
should configure their own timeouts; ICR does not forcibly interrupt Python calls.

## Agent integration

Use `plan.to_dict()` or a relational `Admission.to_dict()` as structured recovery
advice in your agent's existing tool-selection loop. Do not execute untrusted Python
or install generated tool implementations. Register reviewed alternatives yourself.
For writes, payments or externally visible actions, implement a separate authority
and transaction policy; this executor deliberately refuses write-capable options.
