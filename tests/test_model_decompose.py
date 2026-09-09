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


def response(monkeypatch, proposal):
    def send(method, url, **kwargs):
        assert kwargs["json"]["messages"][0]["role"] == "system"
        assert json.loads(kwargs["json"]["messages"][1]["content"]) == {
            "requirement": "Save receipts"
        }
        return nullcontext(
            httpx.Response(
                200,
                request=httpx.Request(method, url),
                json={"choices": [{"message": {"content": json.dumps(proposal)}}]},
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
