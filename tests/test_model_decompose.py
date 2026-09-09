import json
from contextlib import nullcontext

import httpx
import pytest

from services.analysis.model_decompose import ModelDecomposer


@pytest.fixture
def model(monkeypatch):
    monkeypatch.setenv("SPECGUARD_MODEL", "test-model")
    monkeypatch.setenv("SPECGUARD_MODEL_KEY", "private-test-key")
    return ModelDecomposer()


def response(monkeypatch, proposal, usage=None):
    def send(method, url, **kwargs):
        assert kwargs["json"]["messages"][0]["role"] == "system"
        assert json.loads(kwargs["json"]["messages"][1]["content"]) == {
            "requirement": "Save receipts"
        }
        return nullcontext(
            httpx.Response(
                200,
                request=httpx.Request(method, url),
                json={
                    "choices": [{"message": {"content": json.dumps(proposal)}}],
                    "usage": usage or {},
                },
            )
        )

    monkeypatch.setattr(httpx, "stream", send)


def test_model_criteria_keep_exact_source(model, monkeypatch):
    response(
        monkeypatch, {"criteria": [{"text": "Persist receipts", "source_text": "Save receipts"}]}
    )
    result = model.decompose("Save receipts")
    assert result.criteria[0].source_text == "Save receipts"
    assert result.criteria[0].text == "Persist receipts"
    assert result.version == model.version
    assert "original requirement" in result.questions[-1]


@pytest.mark.parametrize(
    "proposal",
    [
        {"criteria": [{"text": "Send email", "source_text": "Email customers"}]},
        {"criteria": []},
        {"criteria": [{"text": "Save", "source_text": " "}]},
        None,
    ],
)
def test_invalid_proposal_falls_back(model, monkeypatch, proposal):
    response(monkeypatch, proposal)
    result = model.decompose("Save receipts")
    assert result.version == "explicit-lists/3"
    assert result.criteria[0].text == "Save receipts"
    assert "invalid" in result.questions[0]


def test_secret_never_reaches_transport(model, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Secret must not be transmitted")

    monkeypatch.setattr(httpx, "stream", forbidden)
    assert "not sent" in model.decompose("Use private-test-key").questions[0]


@pytest.mark.parametrize(
    "status,content", [(429, b"busy"), (200, b"x" * 100_001)], ids=["rate-limit", "oversized"]
)
def test_transport_failures_keep_offline_criteria(model, monkeypatch, status, content):
    monkeypatch.setattr(
        httpx,
        "stream",
        lambda method, url, **kwargs: nullcontext(
            httpx.Response(status, content=content, request=httpx.Request(method, url))
        ),
    )
    result = model.decompose("Save receipts")
    assert result.version == "explicit-lists/3"
    assert result.criteria[0].source_text == "Save receipts"


def test_timeout_falls_back(model, monkeypatch):
    def timeout(*args, **kwargs):
        raise httpx.ReadTimeout("private provider details")

    monkeypatch.setattr(httpx, "stream", timeout)
    result = model.decompose("Save receipts")
    assert "private provider details" not in result.model_dump_json()
    assert "unavailable" in result.questions[0]


@pytest.mark.parametrize("tokens", [0, 123, None, -1, True, "123"])
def test_usage_records_only_valid_provider_counts(model, monkeypatch, tokens):
    response(
        monkeypatch,
        {"criteria": [{"text": "Save", "source_text": "Save receipts"}]},
        {"total_tokens": tokens},
    )
    result = model.decompose("Save receipts")
    assert result.usage.request_attempted
    assert result.usage.requested_model == "test-model"
    expected = tokens if type(tokens) is int and tokens >= 0 else None
    assert result.usage.total_tokens == expected
    assert result.usage.elapsed_ms >= 0


def test_usage_survives_rejected_proposal(model, monkeypatch):
    response(monkeypatch, {"criteria": []}, {"total_tokens": 87})
    result = model.decompose("Save receipts")
    assert result.version == "explicit-lists/3"
    assert result.usage.total_tokens == 87
    withheld = model.decompose("Use private-test-key")
    assert not withheld.usage.request_attempted
    assert withheld.usage.total_tokens is None
