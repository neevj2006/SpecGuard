import hashlib
import json
import sys
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from scripts.report_usage import load_runs, main
from services.analysis.domain import AnalysisRun, CriterionResult
from services.analysis.usage_report import distribution, summarize_usage
from services.api.main import create_app


def result(status="accepted", tokens=12, elapsed=10, *, attempted=True):
    return CriterionResult.model_validate(
        {
            "criterion": {
                "id": "private-id",
                "text": "private requirement",
                "source_text": "private source",
            },
            "verdict": "not_verifiable",
            "rationale": "private rationale",
            "uncertainty": "private uncertainty",
            "verification_usage": {
                "requested_model": "private-model",
                "status": status,
                "request_attempted": attempted,
                "elapsed_ms": elapsed,
                "total_tokens": tokens,
            },
        }
    )


def run(identifier="one", results=None, **overrides):
    return AnalysisRun.model_validate(
        {
            "id": identifier,
            "repository": "private/repository",
            "base_sha": "a" * 40,
            "head_sha": "b" * 40,
            "requirement": "private requirement",
            "created_at": datetime(2026, 1, 1, tzinfo=UTC),
            "results": results if results is not None else [result()],
            "duration_ms": 100,
            "versions": {"verifier": "private-version"},
            "token_usage": 12,
            "cost_usd": None,
            **overrides,
        }
    )


def save_json(path, payload):
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_empty_report_has_no_latency_observations():
    report = summarize_usage([])
    assert report["runs"] == report["criteria"]["total"] == 0
    assert report["run_latency"]["p95_ms"] is None
    assert report["period"]["oldest_created_at"] is None
    assert report["verification"]["total_tokens"] == 0
    assert report["verification"]["request_latency"]["samples"] == 0


def test_mixed_outcomes_preserve_unknown_tokens_and_skip_counts():
    report = summarize_usage(
        [
            run(
                results=[
                    result(),
                    result("provider_error", None, 80),
                    result("request_budget", None, 0, attempted=False),
                    result("time_budget", None, 4, attempted=False),
                    result("invalid_response", 8, 20),
                ]
            )
        ]
    )
    usage = report["verification"]
    assert usage["attempted_requests"] == 3
    assert usage["skipped_requests"] == 2
    assert usage["known_tokens"] == 20
    assert usage["requests_with_known_tokens"] == 2
    assert usage["requests_with_unknown_tokens"] == 1
    assert usage["total_tokens"] is None
    assert usage["budget_outcomes"] == 2
    assert usage["outcomes"]["accepted"] == 1
    assert usage["request_latency"] == {
        "samples": 3,
        "mean_ms": 36.67,
        "p50_ms": 20,
        "p95_ms": 80,
        "max_ms": 80,
    }
    assert report["criteria"]["verdicts"]["not_verifiable"] == 5


def test_missing_legacy_instrumentation_is_not_a_free_request():
    legacy = result().model_copy(update={"verification_usage": None})
    usage = summarize_usage([run(results=[legacy, result(tokens=0)])])["verification"]
    assert usage["uninstrumented_criteria"] == 1
    assert usage["instrumented_criteria"] == 1
    assert usage["attempted_requests"] == 1
    assert usage["requests_with_unknown_tokens"] == 0
    assert usage["total_tokens"] is None


def test_known_zero_usage_and_skips_are_distinct_from_unknown():
    usage = summarize_usage(
        [
            run(
                results=[
                    result(tokens=0),
                    result("no_evidence", None, 0, attempted=False),
                ]
            )
        ]
    )["verification"]
    assert usage["total_tokens"] == 0
    assert usage["requests_with_known_tokens"] == 1
    assert usage["skipped_requests"] == 1


def test_recorded_run_usage_is_separate_and_decimal_cost_is_exact():
    report = summarize_usage(
        [
            run(cost_usd=0.1, token_usage=40),
            run("two", cost_usd=0.2, token_usage=50),
        ]
    )
    assert report["recorded_run_usage"]["total_cost_usd"] == "0.3"
    assert report["recorded_run_usage"]["total_tokens"] == 90
    assert report["verification"]["total_tokens"] == 24
    partial = summarize_usage([run(cost_usd=0.1), run("two", token_usage=None)])
    recorded = partial["recorded_run_usage"]
    assert recorded["known_cost_usd"] == "0.1"
    assert recorded["total_cost_usd"] is None
    assert recorded["total_tokens"] is None
    assert recorded["runs_with_unknown_cost"] == recorded["runs_with_unknown_tokens"] == 1


def test_percentiles_use_nearest_rank_and_do_not_mutate_input():
    values = list(range(100, 0, -1))
    assert distribution(values) == {
        "samples": 100,
        "mean_ms": 50.5,
        "p50_ms": 50,
        "p95_ms": 95,
        "max_ms": 100,
    }
    assert values[0] == 100
    assert distribution([0])["p95_ms"] == 0


def test_time_range_is_utc_and_independent_of_input_order():
    older = run(created_at="2026-01-01T01:00:00+02:00")
    newer = run("two", created_at="2026-01-02T00:00:00Z")
    assert summarize_usage([newer, older])["period"] == {
        "oldest_created_at": "2025-12-31T23:00:00+00:00",
        "newest_created_at": "2026-01-02T00:00:00+00:00",
    }


def test_no_content_or_identifiers_are_copied_into_report():
    serialized = json.dumps(summarize_usage([run()]))
    assert "private" not in serialized
    assert "a" * 40 not in serialized
    assert "b" * 40 not in serialized
    assert "one" not in serialized


@pytest.mark.parametrize("cost", [float("inf"), float("nan")])
def test_nonfinite_recorded_cost_is_rejected(cost):
    invalid = run().model_copy(update={"cost_usd": cost})
    with pytest.raises(ValueError, match="finite"):
        summarize_usage([invalid])


def test_ambiguous_dates_duplicates_and_oversized_sets_are_rejected():
    with pytest.raises(ValueError, match="timezone"):
        summarize_usage([run(created_at="2026-01-01T00:00:00")])
    with pytest.raises(ValueError, match="unique"):
        summarize_usage([run(), run()])
    with pytest.raises(ValueError, match="1000"):
        summarize_usage([run()] * 1001)


@pytest.mark.parametrize(
    "status",
    [
        "no_evidence",
        "secret_withheld",
        "input_budget",
        "request_budget",
        "time_budget",
    ],
)
def test_preflight_statuses_do_not_pollute_provider_latency(status):
    usage = summarize_usage([run(results=[result(status, None, 5, attempted=False)])])[
        "verification"
    ]
    assert usage["outcomes"][status] == 1
    assert usage["request_latency"]["samples"] == 0
    assert usage["attempted_requests"] == 0


def test_evidence_and_test_counts_are_criterion_records():
    item = result().model_dump()
    item["verdict"] = "satisfied"
    item["evidence"] = [
        {
            "id": "private-evidence",
            "revision": "b" * 40,
            "path": "private.ts",
            "start_line": 1,
            "end_line": 1,
            "quote": "private code",
            "symbol": "private",
            "kind": "function",
        }
    ]
    item["tests"] = {
        "status": "passed",
        "command": ["private-test"],
        "revision": "b" * 40,
        "exit_code": 0,
        "duration_ms": 20,
        "environment": "private-env",
    }
    report = summarize_usage([run(results=[CriterionResult.model_validate(item), result()])])
    assert report["criteria"]["with_citations"] == 1
    assert report["criteria"]["without_citations"] == 1
    assert report["criteria"]["test_states"]["passed"] == 1
    assert report["criteria"]["test_states"]["not_run"] == 1
    assert "private" not in json.dumps(report)


def test_offline_loader_supports_plain_run_and_api_export(tmp_path):
    first = save_json(tmp_path / "one.json", run().model_dump(mode="json"))
    second = save_json(
        tmp_path / "two.json",
        {
            "run": run("two").model_dump(mode="json"),
            "feedback": {"private": "note"},
        },
    )
    assert summarize_usage(load_runs([first, second]))["runs"] == 2
    with pytest.raises(ValueError, match="unique"):
        summarize_usage(load_runs([first, first]))


def test_offline_loader_rejects_unexpected_envelope_and_excess_size(tmp_path):
    path = save_json(tmp_path / "bad.json", {"run": {}, "feedback": {}, "unexpected": True})
    with pytest.raises(ValueError, match="envelope"):
        load_runs([path])
    with path.open("wb") as stream:
        stream.truncate(20_000_001)
    with pytest.raises(ValueError, match="20 MB"):
        load_runs([path])
    with pytest.raises(ValueError, match="1000"):
        load_runs([])


def test_offline_cli_prints_summary_and_preserves_existing_files(tmp_path, monkeypatch, capsys):
    path = save_json(tmp_path / "run.json", run().model_dump(mode="json"))
    monkeypatch.setattr(sys, "argv", ["report_usage", str(path)])
    main()
    assert json.loads(capsys.readouterr().out)["runs"] == 1
    output = tmp_path / "report.json"
    monkeypatch.setattr(sys, "argv", ["report_usage", str(path), "--output", str(output)])
    main()
    before = output.read_bytes()
    with pytest.raises(SystemExit) as error:
        main()
    assert error.value.code == 2
    assert output.read_bytes() == before
    assert "private" not in capsys.readouterr().err


def test_invalid_cli_payload_does_not_echo_private_validation_input(tmp_path, monkeypatch, capsys):
    path = save_json(tmp_path / "bad.json", {"private": "secret"})
    monkeypatch.setattr(sys, "argv", ["report_usage", str(path)])
    with pytest.raises(SystemExit):
        main()
    assert "secret" not in capsys.readouterr().err


def test_api_usage_is_authenticated_owner_scoped_bounded_and_uncached(tmp_path, monkeypatch):
    monkeypatch.delenv("SPECGUARD_OWNER_ID", raising=False)
    app = create_app(tmp_path, tmp_path / "usage.db", "token")
    store = app.state.store
    owner = hashlib.sha256(b"token").hexdigest()
    store.save(owner, run())
    store.save(owner, run("two", created_at=datetime(2026, 1, 2, tzinfo=UTC), token_usage=99))
    store.save("someone-else", run("hidden", token_usage=9999))
    client = TestClient(app)
    assert client.get("/v1/usage").status_code == 401
    client.headers["Authorization"] = "Bearer token"
    response = client.get("/v1/usage?limit=1")
    assert response.headers["cache-control"] == "no-store"
    report = response.json()
    assert report["runs"] == 1
    assert report["selection"]["has_more"] is True
    assert report["recorded_run_usage"]["total_tokens"] == 99
    assert "private" not in response.text and "hidden" not in response.text
    report = client.get("/v1/usage").json()
    assert report["runs"] == 2 and report["selection"]["has_more"] is False
    assert client.get("/v1/usage?limit=101").status_code == 422
    assert client.get("/v1/usage?limit=0").status_code == 422
    store.delete(owner, "two")
    assert client.get("/v1/usage").json()["runs"] == 1
    store.expire(owner, 1)
    assert client.get("/v1/usage").json()["runs"] == 0


def test_reports_are_deterministic_for_reordered_runs():
    first = run()
    second = run("two", duration_ms=200, created_at=first.created_at + timedelta(days=1))
    assert summarize_usage([first, second]) == summarize_usage([second, first])
