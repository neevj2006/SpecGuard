import json
from contextlib import nullcontext

import httpx
import pytest

from services.analysis.decompose import decompose
from services.analysis.domain import Verdict
from services.analysis.repository import index_change
from services.analysis.verifier import BaselineVerifier, ModelVerifier


def test_empty_retrieval_does_not_claim_source_was_found():
    result = BaselineVerifier().verify(decompose("Send a receipt")[0], [])
    assert "No matching source" in result.rationale
    assert result.verdict == Verdict.UNKNOWN


@pytest.mark.parametrize("verdict", list(Verdict))
def test_structured_verdicts_keep_source_and_test_status(repository, monkeypatch, verdict):
    repo, base, head = repository
    evidence = index_change(repo, base, head)["chunks"]
    monkeypatch.setenv("SPECGUARD_MODEL", "test-model")
    monkeypatch.setenv("SPECGUARD_MODEL_KEY", "test-key")
    claim = {
        "verdict": verdict.value,
        "evidence_ids": [evidence[0].id],
        "rationale": "Synthetic contract response",
        "uncertainty": "Static reading only",
        "confidence": 0.7,
        "suggestion": "Add a test",
    }

    def post(method, url, **kwargs):
        packet = json.loads(kwargs["json"]["messages"][1]["content"])
        assert packet["evidence"][0]["quote"] == evidence[0].quote
        return nullcontext(
            httpx.Response(
                200,
                json={"choices": [{"message": {"content": json.dumps(claim)}}]},
                request=httpx.Request(method, url),
            )
        )

    monkeypatch.setattr(httpx, "stream", post)
    result = ModelVerifier().verify(decompose("Apply discount")[0], evidence)
    assert result.verdict == verdict
    assert result.tests.status == "not_run"
    assert result.evidence[0].quote == evidence[0].quote


def test_fabricated_model_citation_downgrades_to_abstention(repository, monkeypatch):
    repo, base, head = repository
    evidence = index_change(repo, base, head)["chunks"]
    monkeypatch.setenv("SPECGUARD_MODEL", "test-model")
    monkeypatch.setenv("SPECGUARD_MODEL_KEY", "test-key")
    claim = {
        "verdict": "satisfied",
        "evidence_ids": ["fabricated"],
        "rationale": "Trust me",
        "confidence": 1,
    }
    monkeypatch.setattr(
        httpx,
        "stream",
        lambda method, url, **kwargs: nullcontext(
            httpx.Response(
                200,
                json={"choices": [{"message": {"content": json.dumps(claim)}}]},
                request=httpx.Request(method, url),
            )
        ),
    )
    result = ModelVerifier().verify(decompose("Apply discount")[0], evidence)
    assert result.verdict == Verdict.UNKNOWN
    assert "failed evidence validation" in result.uncertainty
