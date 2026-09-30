"""Connect the recovery example to your actual read-only HTTP endpoints.

Set ICR_CSV_URL and ICR_JSON_URL, then run:
    python examples/http_workflow.py customer-1

Both endpoints must return the same logical record selected by customer_id.
CSV: id,orders header with exactly one record. JSON: {"id": "...", "orders": 3}.
Use only endpoints you have reviewed as read-only and operation-equivalent.
"""
import csv
import io
import json
import os
from pathlib import Path
import sys
from urllib.parse import urlencode, urlsplit
from urllib.request import urlopen
from icr import Workflow, recover


def request(url, customer_id):
    if urlsplit(url).scheme not in {"http", "https"}:
        raise ValueError("HTTP(S) endpoint required")
    query = urlencode({"customer_id": customer_id})
    with urlopen(url + ("&" if "?" in url else "?") + query, timeout=10) as response:
        payload = response.read(1_000_001)
        if len(payload) > 1_000_000:
            raise ValueError("endpoint response exceeds one megabyte")
        return payload.decode("utf-8")


def json_record(value):
    return (isinstance(value, dict) and isinstance(value.get("id"), str)
            and type(value.get("orders")) is int and value["orders"] >= 0)


def parse_csv(text):
    rows = list(csv.DictReader(io.StringIO(text)))
    if len(rows) != 1 or "id" not in rows[0] or "orders" not in rows[0]:
        raise ValueError("expected exactly one id/orders record")
    return {"id": rows[0]["id"], "orders": int(rows[0]["orders"])}


def csv_record(value):
    try:
        return isinstance(value, str) and json_record(parse_csv(value))
    except (ValueError, TypeError, csv.Error):
        return False


def main():
    csv_url, json_url = os.environ["ICR_CSV_URL"], os.environ["ICR_JSON_URL"]
    def fetch_csv(customer_id):
        text = request(csv_url, customer_id)
        if parse_csv(text)["id"] != customer_id:
            raise ValueError("CSV record does not match the requested customer")
        return text
    def fetch_json(customer_id):
        record = json.loads(request(json_url, customer_id))
        if not json_record(record) or record["id"] != customer_id:
            raise ValueError("JSON record does not match the requested customer")
        return record
    workflow = Workflow.from_file(Path(__file__).with_name("workflow.json"))
    outputs, plan, failures = recover(workflow, {
        ("fetch", "csv"): fetch_csv, ("fetch", "json"): fetch_json,
        ("summarize", "csv"): lambda text: f"Orders: {parse_csv(text)['orders']}",
        ("summarize", "json"): lambda record: f"Orders: {record['orders']}"},
        {"fetch": [sys.argv[1]]}, {
            "customer_id": lambda value: isinstance(value, str) and bool(value),
            "csv_record": csv_record, "json_record": json_record,
            "summary": lambda value: isinstance(value, str)})
    print(json.dumps({"summary": outputs["summarize"], "plan": plan.to_dict(), "failures": failures}, indent=2))


if __name__ == "__main__":
    main()
