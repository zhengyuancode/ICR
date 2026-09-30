import json
import subprocess
import sys
import unittest
import os
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from dataclasses import replace
from icr import Workflow, plan_repair, execute, recover, Snapshot, Projection, RelationalRecovery
from icr.demo import workflow_spec, workflow_demo, relational_demo
from icr import Edge, least_region, ExecutionError


class WorkflowTests(unittest.TestCase):
    def test_real_http_adapter_recovers_after_503(self):
        requests = []
        class Endpoint(BaseHTTPRequestHandler):
            def do_GET(self):
                requests.append(self.path)
                if self.path.startswith("/csv"):
                    self.send_response(503)
                    self.end_headers()
                else:
                    self.send_response(200)
                    self.end_headers()
                    self.wfile.write(b'{"id":"customer-1","orders":3}')
            def log_message(self, *args):
                pass
        server = ThreadingHTTPServer(("127.0.0.1", 0), Endpoint)
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        env = dict(os.environ)
        env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1])
        base = f"http://127.0.0.1:{server.server_port}"
        env["ICR_CSV_URL"], env["ICR_JSON_URL"] = base + "/csv", base + "/json"
        try:
            result = subprocess.run([sys.executable, "examples/http_workflow.py", "customer-1"],
                                    env=env, capture_output=True, text=True, timeout=15)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)
        self.assertEqual(result.returncode, 0, result.stderr)
        record = json.loads(result.stdout)
        self.assertEqual(record["summary"], "Orders: 3")
        self.assertEqual(record["plan"]["changed"], ["fetch", "summarize"])
        self.assertEqual(len(requests), 2)

    def test_multi_input_join_execution(self):
        spec = {"nodes": {
            "left": [dict(name="v1", inputs=["num"], output="num", operation="identity", original=True, read_only=True)],
            "right": [dict(name="v1", inputs=["num"], output="num", operation="identity", original=True, read_only=True)],
            "join": [dict(name="v1", inputs=["num", "num"], output="num", operation="add", original=True, read_only=True)]},
            "edges": [["left", "join", 0], ["right", "join", 1]]}
        workflow = Workflow(spec)
        result = execute(workflow, plan_repair(workflow, ()), {
            ("left", "v1"): lambda x: x, ("right", "v1"): lambda x: x,
            ("join", "v1"): lambda a, b: a + b}, {"left": [2], "right": [3]},
            {"num": lambda value: isinstance(value, int)})
        self.assertEqual(result["join"], 5)

    def test_invalid_output_never_reaches_consumer(self):
        workflow = Workflow(workflow_spec())
        calls = []
        with self.assertRaises(ExecutionError) as context:
            execute(workflow, plan_repair(workflow, {"fetch"}), {
                ("fetch", "json"): lambda customer: "wrong format",
                ("summarize", "json"): lambda row: calls.append(row)}, {"fetch": ["Ada"]}, {
                "customer_id": lambda x: isinstance(x, str), "json_record": lambda x: isinstance(x, dict),
                "summary": lambda x: isinstance(x, str)})
        self.assertEqual(context.exception.node, "fetch")
        self.assertEqual(calls, [])

    def test_invalid_plan_and_mutated_workflow_rejected(self):
        workflow = Workflow(workflow_spec())
        plan = plan_repair(workflow, {"fetch"})
        with self.assertRaisesRegex(ValueError, "every node"):
            execute(workflow, replace(plan, assignment=()), {}, {}, {})
        workflow.read_only["fetch", "json"] = False
        with self.assertRaisesRegex(ValueError, "changed"):
            execute(workflow, plan, {}, {}, {})

    def test_fixed_assignment_generator_checks_internal_edge(self):
        region = least_region(["a", "b"], iter([Edge("a", "b", ok_10=False, ok_11=False)]), {"a"})
        self.assertFalse(region.feasible)
        self.assertEqual(region.nodes, {"a", "b"})

    def test_cli_plan(self):
        result = subprocess.run([sys.executable, "-m", "icr", "plan", "examples/workflow.json", "--failed", "fetch"], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["changed"], ["fetch", "summarize"])
        result = subprocess.run([sys.executable, "-m", "icr", "plan", "examples/workflow.json", "--failed", "fetch", "--immutable", "summarize"], capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)

    def test_actual_failure_requires_joint_replacement(self):
        result = workflow_demo()
        self.assertEqual(result["outputs"]["summarize"], "Orders: 3")
        self.assertEqual(result["repair"]["changed"], ["fetch", "summarize"])
        self.assertEqual(result["failures"], [{"node": "fetch", "implementation": "csv", "error_type": "ConnectionError"}])

    def test_immutable_consumer_makes_repair_infeasible(self):
        result = plan_repair(Workflow(workflow_spec()), {"fetch"}, immutable={"summarize"})
        self.assertFalse(result.feasible)

    def test_wrong_operation_is_not_eligible(self):
        spec = workflow_spec()
        spec["nodes"]["fetch"][1]["operation"] = "different_operation"
        self.assertFalse(plan_repair(Workflow(spec), {"fetch"}).feasible)

    def test_missing_validator_or_write_handler_never_called(self):
        for readonly in [True, False]:
            spec = workflow_spec()
            spec["nodes"]["fetch"][1]["read_only"] = readonly
            workflow = Workflow(spec)
            calls = []
            handlers = {(node, item.name): lambda *args: calls.append(args)
                        for node, pool in workflow.options.items() for item in pool}
            with self.assertRaises(ValueError):
                execute(workflow, plan_repair(workflow, {"fetch"}), handlers, {"fetch": ["Ada"]}, {})
            self.assertEqual(calls, [])

    def test_recovery_does_not_retry_failed_alternative(self):
        spec = {"nodes": {"lookup": [
            dict(name=name, inputs=["str"], output="str", operation="lookup", original=(name == "original"), cost=cost, read_only=True)
            for name, cost in [("original", 0), ("backup1", 1), ("backup2", 2)]]}, "edges": []}
        def fail(value):
            raise ConnectionError("offline")
        outputs, _, history = recover(Workflow(spec), {
            ("lookup", "original"): fail, ("lookup", "backup1"): fail,
            ("lookup", "backup2"): lambda value: "ok:" + value},
            {"lookup": ["Ada"]}, {"str": lambda value: isinstance(value, str)})
        self.assertEqual(outputs["lookup"], "ok:Ada")
        self.assertEqual([record["implementation"] for record in history], ["original", "backup1"])

    def test_cycle_rejected(self):
        spec = {"nodes": {node: [dict(name="v1", inputs=["str"], output="str", operation=node, original=True)] for node in ["a", "b"]},
                "edges": [["a", "b", 0], ["b", "a", 0]]}
        with self.assertRaisesRegex(ValueError, "acyclic"):
            Workflow(spec)

    def test_resource_limit_is_not_infeasibility(self):
        with self.assertRaisesRegex(ValueError, "bound"):
            plan_repair(Workflow(workflow_spec()), {"fetch"}, max_states=1)


class RelationalTests(unittest.TestCase):
    def engine(self, rows=None):
        return RelationalRecovery(Snapshot(rows or [{"x": "a", "y": "u", "z": 42},
                                                   {"x": "b", "y": None, "z": 10}]),
            [Projection("xy", "x", "y"), Projection("yz", "y", "z")])

    def test_observed_certificate_executes_where_global_rejects(self):
        engine = self.engine()
        local = engine.certify("x", "z", "a", ["xy", "yz"])
        self.assertTrue(local.admitted)
        self.assertFalse(engine.certify("x", "z", "a", ["xy", "yz"], mode="global").admitted)
        self.assertEqual(engine.execute(local.certificate), 42)
        self.assertFalse(engine.certify("x", "z", "b", ["xy", "yz"]).admitted)

    def test_changed_snapshot_rejected_even_if_input_result_unchanged(self):
        engine = self.engine()
        cert = engine.certify("x", "z", "a", ["xy", "yz"]).certificate
        changed = Snapshot([{ "x": "a", "y": "u", "z": 42}, {"x": "b", "y": "v", "z": 10}])
        with self.assertRaisesRegex(ValueError, "stale_snapshot"):
            engine.execute(cert, current_snapshot=changed)
        new_engine = RelationalRecovery(changed, engine.tools.values())
        new = new_engine.certify("x", "z", "a", cert.path).certificate
        self.assertEqual(new_engine.execute(new), 42)

    def test_ambiguous_dependency_and_wrong_target_rejected(self):
        engine = self.engine([{"x": "a", "y": "u", "z": 42}, {"x": "a", "y": "v", "z": 42}])
        self.assertEqual(engine.certify("x", "z", "a", ["xy", "yz"]).reason, "ambiguous_value")
        self.assertEqual(engine.certify("x", "z", "a", ["xy"]).reason, "wrong_target_operation")

    def test_cheaper_invalid_route_does_not_hide_valid_route(self):
        engine = RelationalRecovery(Snapshot([{"x": "a", "y": None, "q": "u", "z": 42}]), [
            Projection("xy", "x", "y", 0), Projection("yz", "y", "z", 0),
            Projection("xq", "x", "q", 2), Projection("qz", "q", "z", 2)])
        admission, rejected = engine.repair("x", "z", "a")
        self.assertEqual(admission.certificate.path, ("xq", "qz"))
        self.assertEqual(rejected[0]["reason"], "missing_value")

    def test_tampered_certificate_is_revalidated(self):
        engine = self.engine()
        cert = engine.certify("x", "z", "a", ["xy", "yz"]).certificate
        for bad in [replace(cert, output_json="99"), replace(cert, witness_rows=()), replace(cert, catalog_digest="bad")]:
            with self.assertRaisesRegex(ValueError, "revalidation"):
                engine.execute(bad)

    def test_snapshot_is_a_copy_and_equality_preserves_types(self):
        rows = [{"x": True, "y": "bool"}, {"x": 1, "y": "integer"}]
        snapshot = Snapshot(rows)
        rows[0]["y"] = "changed"
        exported = snapshot.rows()
        exported[0]["y"] = "also changed"
        self.assertEqual(snapshot.lookup("x", "y", True), "bool")
        self.assertEqual(snapshot.lookup("x", "y", 1), "integer")

    def test_duplicate_rows_allowed_missing_and_null_rejected(self):
        snapshot = Snapshot([{"x": "a", "y": 42}, {"x": "a", "y": 42}, {"x": "b"}])
        self.assertEqual(snapshot.lookup("x", "y", "a"), 42)
        for value in [None, "b", "unknown"]:
            with self.assertRaises(ValueError):
                snapshot.lookup("x", "y", value)

    def test_catalog_and_limits_rejected(self):
        with self.assertRaisesRegex(ValueError, "duplicate"):
            RelationalRecovery(Snapshot([]), [Projection("dup", "x", "y"), Projection("dup", "y", "z")])
        engine = RelationalRecovery(Snapshot([]), [Projection("p1", "x", "z"), Projection("p2", "x", "z")])
        with self.assertRaisesRegex(ValueError, "candidate limit"):
            engine.candidates("x", "z", max_candidates=1)
        with self.assertRaisesRegex(ValueError, "expansion"):
            self.engine().candidates("x", "z", max_expansions=1)

    def test_cli_relational_execution(self):
        result = subprocess.run([sys.executable, "-m", "icr", "repair", "examples/snapshot.json", "examples/catalog.json",
                                 "--source", "customer", "--target", "balance", "--input", '"Ada"',
                                 "--exclude", "direct_balance", "--execute"], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["execution_result"], 42)

    def test_cli_demo(self):
        result = subprocess.run([sys.executable, "-m", "icr", "demo"], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["relational"]["result"], 42)


if __name__ == "__main__":
    unittest.main()
