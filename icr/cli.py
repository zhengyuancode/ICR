"""JSON CLI: planning emits advice; --execute enables local read-only projections."""
import argparse
import json
import sys
from .workflow import Workflow, plan_repair
from .relational import Snapshot, Projection, RelationalRecovery


def _load(path):
    with open(path, encoding="utf-8") as stream:
        return json.load(stream)


def main(argv=None):
    parser = argparse.ArgumentParser(prog="icr", description="Interface-closed workflow recovery")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("demo", help="run both local read-only recovery examples")
    planning = sub.add_parser("plan", help="emit an exact joint repair plan for a workflow JSON")
    planning.add_argument("workflow")
    planning.add_argument("--failed", nargs="+", default=[])
    planning.add_argument("--immutable", nargs="+", default=[])
    planning.add_argument("--max-width", type=int, default=8)
    planning.add_argument("--max-states", type=int, default=1_000_000)
    relational = sub.add_parser("repair", help="certify an alternative relation-projection route")
    relational.add_argument("snapshot", help="JSON array of row objects")
    relational.add_argument("catalog", help="JSON array of projection definitions")
    relational.add_argument("--source", required=True)
    relational.add_argument("--target", required=True)
    relational.add_argument("--input", required=True, help="JSON value (strings must include JSON quotes)")
    relational.add_argument("--exclude", nargs="+", default=[])
    relational.add_argument("--mode", choices=["observed", "global"], default="observed")
    relational.add_argument("--max-hops", type=int, default=4)
    relational.add_argument("--max-candidates", type=int, default=1000)
    relational.add_argument("--max-expansions", type=int, default=100_000)
    relational.add_argument("--execute", action="store_true", help="execute certified read-only snapshot projections")
    args = parser.parse_args(argv)
    try:
        if args.command == "demo":
            from .demo import workflow_demo, relational_demo
            result = {"workflow": workflow_demo(), "relational": relational_demo()}
            status = 0
        elif args.command == "plan":
            plan = plan_repair(Workflow.from_file(args.workflow), args.failed,
                               immutable=args.immutable, max_width=args.max_width, max_states=args.max_states)
            result, status = plan.to_dict(), 0 if plan.feasible else 2
        else:
            snapshot = Snapshot(_load(args.snapshot))
            engine = RelationalRecovery(snapshot, [Projection(**item) for item in _load(args.catalog)])
            admission, rejected = engine.repair(args.source, args.target, json.loads(args.input),
                excluded=args.exclude, mode=args.mode, max_hops=args.max_hops, max_candidates=args.max_candidates,
                max_expansions=args.max_expansions)
            result = admission.to_dict()
            result["rejected_routes"] = rejected
            result["search"] = {"max_hops": args.max_hops, "max_candidates": args.max_candidates,
                                "ranking": "total cost, hop count, tool IDs"}
            if args.execute and admission.admitted:
                result["execution_result"] = engine.execute(admission.certificate, current_snapshot=snapshot)
            status = 0 if admission.admitted else 2
        print(json.dumps(result, indent=2, allow_nan=False))
        return status
    except (ValueError, KeyError, TypeError, OSError) as error:
        print(json.dumps({"error": str(error), "status": "invalid_input_or_resource_limit"}), file=sys.stderr)
        return 1
