"""Self-contained read-only examples; no benchmark data or model API needed."""
import json
from .workflow import Workflow, recover
from .relational import Snapshot, Projection, RelationalRecovery


def workflow_spec():
    def item(name, inputs, output, operation, original=False, cost=1):
        return dict(name=name, inputs=inputs, output=output, operation=operation,
                    original=original, cost=cost, read_only=True)
    return {"nodes": {
        "fetch": [item("csv", ["customer_id"], "csv_record", "fetch_record", True),
                  item("json", ["customer_id"], "json_record", "fetch_record")],
        "summarize": [item("csv", ["csv_record"], "summary", "summarize", True),
                      item("json", ["json_record"], "summary", "summarize")],
    }, "edges": [["fetch", "summarize", 0]]}


def workflow_demo():
    workflow = Workflow(workflow_spec())
    def unavailable(customer_id):
        raise ConnectionError("CSV endpoint unavailable")
    handlers = {
        ("fetch", "csv"): unavailable,
        ("fetch", "json"): lambda customer_id: {"id": customer_id, "orders": 3},
        ("summarize", "csv"): lambda row: f"Orders: {row.split(',')[1]}",
        ("summarize", "json"): lambda row: f"Orders: {row['orders']}",
    }
    validators = {"customer_id": lambda v: isinstance(v, str),
                  "csv_record": lambda v: isinstance(v, str) and "," in v,
                  "json_record": lambda v: isinstance(v, dict) and isinstance(v.get("orders"), int),
                  "summary": lambda v: isinstance(v, str)}
    outputs, plan, history = recover(workflow, handlers, {"fetch": ["customer-1"]}, validators)
    return {"outputs": outputs, "repair": plan.to_dict(), "failures": history}


def relational_demo():
    snapshot = Snapshot([{"customer": "Ada", "account": "A7", "balance": 42},
                         {"customer": "Ben", "account": None, "balance": 10}])
    recovery = RelationalRecovery(snapshot, [
        Projection("direct_balance", "customer", "balance"),
        Projection("customer_account", "customer", "account"),
        Projection("account_balance", "account", "balance")])
    observed, rejected = recovery.repair("customer", "balance", "Ada", excluded={"direct_balance"})
    global_check = recovery.certify("customer", "balance", "Ada", observed.certificate.path, mode="global")
    return {"observed": observed.to_dict(), "global": global_check.to_dict(),
            "result": recovery.execute(observed.certificate), "rejected": rejected}


def main():
    print(json.dumps({"workflow": workflow_demo(), "relational": relational_demo()}, indent=2))


if __name__ == "__main__":
    main()
