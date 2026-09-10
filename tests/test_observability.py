import json
import logging
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from services.api.main import create_app
from services.api.observability import RequestMetrics


def test_request_logs_exclude_inputs_and_group_parameterized_routes(tmp_path, caplog):
    client = TestClient(create_app(tmp_path, tmp_path / "db", "secret-token"))
    caplog.set_level(logging.INFO, logger="specguard.requests")
    assert client.get("/v1/metrics").status_code == 401
    client.headers["Authorization"] = "Bearer secret-token"
    first = client.get(
        "/v1/runs/private-run-id?private-query=secret", headers={"X-Request-ID": "spoof"}
    )
    second = client.get("/v1/runs/another-private-id")
    client.post("/v1/criteria", json={"text": "private requirement"})
    client.get("/private-unknown-path")
    records = [json.loads(r.message) for r in caplog.records if r.name == "specguard.requests"]
    rendered = json.dumps(records)
    for secret in (
        "secret-token",
        "private-run-id",
        "private-query",
        "private requirement",
        "private-unknown-path",
        "another-private-id",
        "spoof",
    ):
        assert secret not in rendered
    assert first.headers["x-request-id"] != second.headers["x-request-id"]
    assert len(first.headers["x-request-id"]) == 32
    assert any(r["request_id"] == first.headers["x-request-id"] for r in records)
    rows = client.get("/v1/metrics").json()["routes"]
    grouped = next(row for row in rows if row["route"] == "/v1/runs/{identifier}")
    assert grouped["requests"] == 2 and grouped["status_class"] == 4
    assert grouped["errors"] == 0
    assert any(row["route"] == "<unmatched>" for row in rows)


def test_failures_are_counted_without_exception_text(tmp_path, caplog):
    app = create_app(tmp_path, tmp_path / "db", "token")

    @app.get("/broken")
    def broken():
        raise RuntimeError("private exception details")

    caplog.set_level(logging.INFO, logger="specguard.requests")
    client = TestClient(app, raise_server_exceptions=False)
    assert client.get("/broken").status_code == 500
    client.headers["Authorization"] = "Bearer token"
    row = next(r for r in client.get("/v1/metrics").json()["routes"] if r["route"] == "/broken")
    assert row["errors"] == row["requests"] == 1
    records = [r.message for r in caplog.records if r.name == "specguard.requests"]
    assert "private exception details" not in str(records)


def test_metrics_are_thread_safe_and_snapshots_are_detached():
    metrics = RequestMetrics()
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda _: metrics.record("GET", "/health", 200, 2.5, False), range(500)))
    snapshot = metrics.snapshot()
    assert snapshot["routes"][0]["requests"] == 500
    assert snapshot["routes"][0]["mean_ms"] == pytest.approx(2.5)
    snapshot["routes"][0]["requests"] = 0
    assert metrics.snapshot()["routes"][0]["requests"] == 500
    for i in range(300):
        metrics.record("GET", str(i), 200, 1, False)
    assert len(metrics.snapshot()["routes"]) <= 201
