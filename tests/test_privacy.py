import json
from contextlib import nullcontext

import httpx
import pytest

from services.analysis.decompose import decompose
from services.analysis.domain import Evidence, Verdict
from services.analysis.verifier import ModelVerifier


@pytest.mark.parametrize(
    "secret",
    [
        "-----BEGIN PRIVATE KEY-----",
        "ghp_" + "a" * 36,
        'password = "a-realistic-secret-value"',
        "provider-credential-for-this-test",
    ],
)
def test_secret_packet_never_reaches_provider(secret, monkeypatch):
    monkeypatch.setenv("SPECGUARD_MODEL", "test-model")
    monkeypatch.setenv("SPECGUARD_MODEL_KEY", "provider-credential-for-this-test")

    def forbidden(*args, **kwargs):
        pytest.fail("Secret-bearing packet reached network transport")

    monkeypatch.setattr("httpx.stream", forbidden)
    monkeypatch.setattr("httpx.post", forbidden)
    evidence = Evidence(
        id="source",
        revision="a" * 40,
        path="source.ts",
        start_line=1,
        end_line=1,
        quote=f'const value = "{secret}";',
        symbol="value",
        kind="variable",
    )
    result = ModelVerifier().verify(decompose("Read value")[0], [evidence])
    assert result.verdict == Verdict.UNKNOWN
    assert "secret" in result.uncertainty.lower()
    assert result.evidence[0].quote == evidence.quote


@pytest.mark.parametrize(
    "payload,expected_usage",
    [
        (
            {"usage": {"total_tokens": 42}, "choices": [{"message": {"content": "invalid claim"}}]},
            42,
        ),
        ({"choices": []}, None),
        (["invalid response shape"], None),
    ],
)
def test_usage_and_malformed_responses(payload, expected_usage, monkeypatch):
    monkeypatch.setenv("SPECGUARD_MODEL", "test-model")
    monkeypatch.setenv("SPECGUARD_MODEL_KEY", "test-key")
    monkeypatch.setattr(
        httpx,
        "stream",
        lambda method, url, **kwargs: nullcontext(
            httpx.Response(200, content=json.dumps(payload), request=httpx.Request(method, url))
        ),
    )
    evidence = Evidence(
        id="source",
        revision="a" * 40,
        path="source.ts",
        start_line=1,
        end_line=1,
        quote="export const value = 10;",
        symbol="value",
        kind="variable",
    )
    verifier = ModelVerifier()
    assert verifier.verify(decompose("Read value")[0], [evidence]).verdict == Verdict.UNKNOWN
    assert verifier.token_usage == expected_usage


def test_streaming_output_stops_at_budget(monkeypatch):
    monkeypatch.setenv("SPECGUARD_MODEL", "test-model")
    monkeypatch.setenv("SPECGUARD_MODEL_KEY", "test-key")

    class Flood(httpx.SyncByteStream):
        def __iter__(self):
            yield b"x" * 100_001
            pytest.fail("Read past the response budget")

    monkeypatch.setattr(
        httpx,
        "stream",
        lambda method, url, **kwargs: nullcontext(
            httpx.Response(200, stream=Flood(), request=httpx.Request(method, url))
        ),
    )
    evidence = Evidence(
        id="source",
        revision="a" * 40,
        path="source.ts",
        start_line=1,
        end_line=1,
        quote="export const value = 10;",
        symbol="value",
        kind="variable",
    )
    verifier = ModelVerifier()
    result = verifier.verify(decompose("Read value")[0], [evidence])
    assert result.verdict == Verdict.UNKNOWN
    assert verifier.token_usage is None
