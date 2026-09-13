import json
from contextlib import nullcontext

import httpx
import pytest

from services.analysis.decompose import decompose
from services.analysis.domain import CriterionResult, Evidence, Verdict, VerificationUsage
from services.analysis.verification_limits import VerificationLimits
from services.analysis.verifier import ModelVerifier


@pytest.fixture(autouse=True)
def configuration(monkeypatch):
    monkeypatch.setenv("SPECGUARD_MODEL", "fixture-model")
    monkeypatch.setenv("SPECGUARD_MODEL_KEY", "fixture-key")
    for key in ("MAX_REQUESTS", "SECONDS", "OUTPUT_TOKENS"):
        monkeypatch.delenv(f"SPECGUARD_VERIFIER_{key}", raising=False)


@pytest.fixture
def packet():
    evidence = Evidence(
        id="source",
        revision="a" * 40,
        path="source.ts",
        start_line=1,
        end_line=1,
        quote="export const receipt = true;",
        symbol="receipt",
        kind="variable",
    )
    return decompose("Save receipt")[0], [evidence]


def install_response(monkeypatch, *, tokens=42, status=200, finish="stop", ids=None):
    calls = []
    claim = {
        "verdict": "satisfied",
        "evidence_ids": ["source"] if ids is None else ids,
        "rationale": "Synthetic evidence response",
        "confidence": 0.8,
    }

    def stream(method, url, **kwargs):
        calls.append(kwargs)
        return nullcontext(
            httpx.Response(
                status,
                request=httpx.Request(method, url),
                json={
                    "usage": {"total_tokens": tokens},
                    "choices": [
                        {"finish_reason": finish, "message": {"content": json.dumps(claim)}}
                    ],
                },
            )
        )

    monkeypatch.setattr(httpx, "stream", stream)
    return calls


def test_request_limit_is_exact_and_reported_per_criterion(packet, monkeypatch):
    monkeypatch.setenv("SPECGUARD_VERIFIER_MAX_REQUESTS", "2")
    calls = install_response(monkeypatch)
    verifier = ModelVerifier()
    results = [verifier.verify(*packet) for _ in range(4)]
    assert len(calls) == verifier.request_count == 2
    assert verifier.token_usage == 84
    assert [r.verification_usage.status for r in results] == [
        "accepted",
        "accepted",
        "request_budget",
        "request_budget",
    ]
    assert results[2].verdict == Verdict.UNKNOWN and results[2].tests.status == "not_run"
    assert results[0].verification_usage.total_tokens == 42
    assert results[2].verification_usage.total_tokens is None
    assert not results[2].verification_usage.request_attempted
    assert CriterionResult.model_validate_json(results[0].model_dump_json()) == results[0]


def test_failed_requests_consume_slots_but_do_not_invent_token_usage(packet, monkeypatch):
    monkeypatch.setenv("SPECGUARD_VERIFIER_MAX_REQUESTS", "1")
    calls = install_response(monkeypatch, status=429)
    verifier = ModelVerifier()
    first, second = verifier.verify(*packet), verifier.verify(*packet)
    assert len(calls) == 1
    assert first.verification_usage.status == "provider_error"
    assert first.verification_usage.request_attempted
    assert second.verification_usage.status == "request_budget"
    assert verifier.token_usage is None


def test_preflight_skips_do_not_consume_requests(packet, monkeypatch):
    calls = install_response(monkeypatch)
    verifier = ModelVerifier()
    criterion, evidence = packet
    empty = verifier.verify(criterion, [])
    secret = verifier.verify(criterion.model_copy(update={"text": "fixture-key"}), evidence)
    large = verifier.verify(criterion, [evidence[0].model_copy(update={"quote": "x" * 41000})])
    assert [r.verification_usage.status for r in (empty, secret, large)] == [
        "no_evidence",
        "secret_withheld",
        "input_budget",
    ]
    assert verifier.request_count == 0 and calls == [] and verifier.token_usage == 0


def test_expired_time_budget_skips_without_a_request(packet, monkeypatch):
    clock = [0.0]
    monkeypatch.setattr("services.analysis.verifier.perf_counter", lambda: clock[0])
    calls = install_response(monkeypatch)
    verifier = ModelVerifier()
    clock[0] = 46
    result = verifier.verify(*packet)
    assert result.verification_usage.status == "time_budget"
    assert not result.verification_usage.request_attempted and calls == []


def test_timeout_is_limited_to_remaining_time_and_output_cap(packet, monkeypatch):
    clock = [0.0]
    monkeypatch.setattr("services.analysis.verifier.perf_counter", lambda: clock[0])
    monkeypatch.setenv("SPECGUARD_VERIFIER_OUTPUT_TOKENS", "300")
    calls = install_response(monkeypatch)
    verifier = ModelVerifier()
    clock[0] = 40
    assert verifier.verify(*packet).verification_usage.status == "accepted"
    assert calls[0]["timeout"] == 5
    assert calls[0]["json"]["max_completion_tokens"] == 300


def test_stream_stops_when_cooperative_time_budget_expires(packet, monkeypatch):
    clock = [0.0]
    monkeypatch.setattr("services.analysis.verifier.perf_counter", lambda: clock[0])

    class Slow(httpx.SyncByteStream):
        def __iter__(self):
            clock[0] = 46
            yield b"{}"
            pytest.fail("Read beyond deadline")

    monkeypatch.setattr(
        httpx,
        "stream",
        lambda method, url, **kw: nullcontext(
            httpx.Response(200, stream=Slow(), request=httpx.Request(method, url))
        ),
    )
    result = ModelVerifier().verify(*packet)
    assert result.verification_usage.status == "time_budget"
    assert (
        result.verification_usage.request_attempted
        and result.verification_usage.elapsed_ms == 46000
    )


@pytest.mark.parametrize("finish", ["length", "content_filter", "tool_calls"])
def test_incomplete_outputs_abstain_but_preserve_reported_usage(packet, monkeypatch, finish):
    install_response(monkeypatch, finish=finish)
    result = ModelVerifier().verify(*packet)
    assert result.verdict == Verdict.UNKNOWN
    assert result.verification_usage.status == "invalid_response"
    assert result.verification_usage.total_tokens == 42


def test_duplicate_citations_are_invalid_output(packet, monkeypatch):
    install_response(monkeypatch, ids=["source", "source"])
    assert ModelVerifier().verify(*packet).verification_usage.status == "invalid_response"


@pytest.mark.parametrize("value", [None, True, -1, "42"])
def test_unknown_usage_stays_unknown(packet, monkeypatch, value):
    install_response(monkeypatch, tokens=value)
    verifier = ModelVerifier()
    result = verifier.verify(*packet)
    assert result.verification_usage.status == "accepted"
    assert result.verification_usage.total_tokens is None and verifier.token_usage is None


@pytest.mark.parametrize(
    "name,value",
    [
        ("MAX_REQUESTS", "0"),
        ("MAX_REQUESTS", "51"),
        ("SECONDS", "0"),
        ("SECONDS", "301"),
        ("OUTPUT_TOKENS", "99"),
        ("OUTPUT_TOKENS", "3001"),
        ("SECONDS", "private-invalid-setting"),
    ],
)
def test_invalid_configuration_fails_without_echoing_values(monkeypatch, name, value):
    monkeypatch.setenv(f"SPECGUARD_VERIFIER_{name}", value)
    with pytest.raises(ValueError, match="Invalid verifier limit configuration") as failure:
        ModelVerifier()
    assert "private-invalid-setting" not in str(failure.value)


def test_limit_changes_participate_in_verifier_identity(monkeypatch):
    first = ModelVerifier().version
    monkeypatch.setenv("SPECGUARD_VERIFIER_MAX_REQUESTS", "3")
    assert ModelVerifier().version != first
    assert VerificationLimits().identity() == "requests-10/seconds-45/output-1500"


@pytest.mark.parametrize(
    "fields",
    [
        {"status": "accepted", "request_attempted": False},
        {"status": "request_budget", "request_attempted": True},
        {"status": "no_evidence", "request_attempted": False, "total_tokens": 42},
    ],
)
def test_telemetry_rejects_contradictory_states(fields):
    with pytest.raises(ValueError):
        VerificationUsage(requested_model="fixture", elapsed_ms=0, **fields)


def test_engine_deadline_records_an_unattempted_criterion(packet, monkeypatch):
    from services.analysis.engine import analyze_index

    criterion, evidence = packet
    index = {
        "base_sha": "b" * 40,
        "head_sha": "a" * 40,
        "parser_version": "fixture",
        "chunks": evidence,
        "sources": {"source.ts": evidence[0].quote},
        "excluded": [],
    }
    times = iter([0.0, 46.0, 46.0])
    monkeypatch.setattr("services.analysis.engine.time.perf_counter", lambda: next(times))
    calls = install_response(monkeypatch)
    run = analyze_index(index, "repo", "owner/repo", criterion.text, [criterion], ModelVerifier())
    assert calls == []
    usage = run.results[0].verification_usage
    assert usage.status == "time_budget" and not usage.request_attempted


def test_api_persists_usage_and_limit_changes_avoid_cached_results(
    repository, tmp_path, monkeypatch
):
    from fastapi.testclient import TestClient

    from services.api.main import create_app

    repo, base, head = repository
    monkeypatch.setenv("SPECGUARD_VERIFIER_MAX_REQUESTS", "1")
    calls = install_response(monkeypatch, ids=[])
    app = create_app(repo, tmp_path / "usage.sqlite", "token")
    try:
        with TestClient(app, headers={"Authorization": "Bearer token"}) as client:
            body = {
                "repository": ".",
                "base": base,
                "head": head,
                "requirement": "Apply discount",
                "criteria": [
                    c.model_dump() for c in decompose("- Apply discount\n- Return discounted total")
                ],
                "use_model": True,
            }
            response = client.post("/v1/runs", json=body)
            assert response.status_code == 201, response.text
            first = response.json()
            assert [r["verification_usage"]["status"] for r in first["results"]] == [
                "invalid_response",
                "request_budget",
            ]
            assert first["token_usage"] == 42 and len(calls) == 1
            saved = client.get(f"/v1/runs/{first['id']}/export").json()["run"]
            assert saved["results"] == first["results"]
            assert client.post("/v1/runs", json=body).json()["id"] == first["id"]
            assert len(calls) == 1
            monkeypatch.setenv("SPECGUARD_VERIFIER_MAX_REQUESTS", "2")
            second = client.post("/v1/runs", json=body).json()
            assert second["id"] != first["id"] and len(calls) == 3
    finally:
        app.state.store.engine.dispose()


def test_cli_prints_verification_outcome_separately_from_verdict(
    packet, tmp_path, monkeypatch, capsys
):
    import sys

    from services.analysis.cli import main
    from services.analysis.domain import AnalysisRun

    install_response(monkeypatch)
    result = ModelVerifier().verify(*packet)
    run = AnalysisRun(
        id="run",
        repository="repo",
        base_sha="a" * 40,
        head_sha="b" * 40,
        requirement="Save receipt",
        results=[result],
        duration_ms=1,
        versions={"retriever": "bm25/2"},
    )
    requirement = tmp_path / "requirement.txt"
    requirement.write_text("Save receipt")
    monkeypatch.setattr("services.analysis.cli.analyze", lambda *a, **kw: run)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "specguard",
            "analyze",
            str(tmp_path),
            "--base",
            "base",
            "--requirement",
            str(requirement),
        ],
    )
    main()
    assert "Verification: accepted | Attempted: True | Tokens: 42" in capsys.readouterr().out
