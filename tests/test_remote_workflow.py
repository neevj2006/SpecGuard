import json

import httpx
import pytest
from fastapi.testclient import TestClient

from services.analysis.decompose import decompose
from services.analysis.embedding_artifacts import read_json
from services.analysis.remote_workflow import ApiClient, analyze_remote, api_origin, encode, prepare
from services.api.hybrid_routes import ChangeInput
from services.api.main import create_app
from tests.test_embeddings import FakeEncoder


@pytest.mark.parametrize(
    "origin",
    [
        "http://example.com",
        "https://u:p@example.com",
        "https://example.com/path",
        "https://example.com?token=secret",
        "file:///tmp",
        "https://example.com#fragment",
    ],
)
def test_unsafe_origins_rejected(origin):
    with pytest.raises(ValueError):
        api_origin(origin)


@pytest.mark.parametrize(
    "origin", ["http://127.0.0.1:8000", "http://[::1]:8000", "https://example.com"]
)
def test_supported_origins(origin):
    assert api_origin(origin + "/") == origin


def test_redirects_never_forward_credentials_and_errors_hide_body():
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(307, headers={"location": "https://other.example"}, text="private")

    client = ApiClient("https://api.example", "token", transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(ValueError, match="HTTP 307") as failure:
            client.post("/v1/embedding-inputs", {})
        assert len(requests) == 1 and "private" not in str(failure.value)
    finally:
        client.close()


@pytest.mark.parametrize("content", [b'{"x":1,"x":2}', b'{"x":NaN}', b"[]", b"not json"])
def test_invalid_server_json_is_rejected(content):
    client = ApiClient(
        "https://api.example",
        "token",
        transport=httpx.MockTransport(lambda request: httpx.Response(200, content=content)),
    )
    try:
        with pytest.raises((ValueError, TypeError)):
            client.post("/v1/embedding-inputs", {})
    finally:
        client.close()


def test_response_size_bound(monkeypatch):
    monkeypatch.setattr("services.analysis.remote_workflow.MAX_RESPONSE", 10)
    client = ApiClient(
        "https://api.example",
        "token",
        transport=httpx.MockTransport(lambda request: httpx.Response(200, content=b"x" * 11)),
    )
    try:
        with pytest.raises(ValueError, match="response exceeds"):
            client.post("/v1/embedding-inputs", {})
    finally:
        client.close()


def test_full_client_workflow_uses_real_api_and_pins_commits(repository, tmp_path, monkeypatch):
    repo, base, head = repository
    app = create_app(repo, tmp_path / "api.sqlite", "token")
    server = TestClient(app)
    calls = []

    def handler(request):
        calls.append((request.url.path, json.loads(request.content)))
        result = server.post(
            request.url.path,
            content=request.content,
            headers={
                "authorization": request.headers["authorization"],
                "content-type": "application/json",
            },
        )
        return httpx.Response(result.status_code, content=result.content)

    client = ApiClient("http://127.0.0.1:8000", "token", transport=httpx.MockTransport(handler))
    change = ChangeInput(
        repository=".",
        base=base,
        head="HEAD",
        requirement="Archive receipts",
        criteria=decompose("Archive receipts"),
    )
    directory = tmp_path / "workflow"
    monkeypatch.setattr(
        "services.analysis.remote_workflow.LocalSentenceEncoder", lambda *a: FakeEncoder()
    )
    try:
        assert prepare(client, change, directory)["head"] == head
        prepared = read_json(directory / "prepared.json")
        assert prepared["change"]["head"] == head
        assert "token" not in json.dumps(prepared)
        assert encode(directory, tmp_path / "model", "synthetic")["encoded"] > 0
        result = analyze_remote(client, directory)
        assert result["stage"] == "analyzed" and not result["model_verifier_requested"]
        run = read_json(directory / "run.json")
        assert run["versions"]["retriever"] == "hybrid-rrf/1"
        assert run["results"][0]["evidence"]
        assert calls[-1][1]["use_model"] is False
        previous = len(calls)
        with pytest.raises(ValueError, match="already exists"):
            analyze_remote(client, directory)
        assert len(calls) == previous
        with pytest.raises(ValueError, match="new workspace"):
            prepare(client, change, directory)
        with pytest.raises(ValueError, match="already exist"):
            encode(directory, tmp_path / "model", "synthetic")
    finally:
        client.close()
        server.close()
        app.state.store.engine.dispose()


def test_arbitrary_paths_cannot_receive_authorization():
    client = ApiClient(
        "https://api.example",
        "token",
        transport=httpx.MockTransport(lambda request: pytest.fail("Unexpected network request")),
    )
    try:
        with pytest.raises(ValueError, match="Unsupported"):
            client.post("https://other.example/collect", {})
    finally:
        client.close()


def test_network_failures_are_not_retried():
    calls = []

    def handler(request):
        calls.append(request)
        raise httpx.ReadTimeout("private details")

    client = ApiClient("https://api.example", "token", transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(ValueError, match="outcome may be unknown") as failure:
            client.post("/v1/runs", {})
        assert len(calls) == 1 and "private" not in str(failure.value)
    finally:
        client.close()


def test_tampered_workspace_is_rejected_before_network_or_encoding(tmp_path, monkeypatch):
    from services.analysis.embedding_artifacts import write_json
    from services.analysis.hybrid import text_key
    from services.analysis.remote_workflow import PreparedChange, fingerprint, load_prepared

    inputs = {text_key("original"): "original"}
    prepared = PreparedChange(
        api="https://api.example",
        change=ChangeInput(
            repository=".",
            base="a" * 40,
            head="b" * 40,
            requirement="original",
            criteria=decompose("original"),
        ),
        binding_sha256="c" * 64,
        inputs_sha256=fingerprint(inputs),
    )
    write_json(tmp_path / "prepared.json", prepared.model_dump())
    write_json(tmp_path / "inputs.json", {text_key("changed"): "changed"})
    monkeypatch.setattr(
        "services.analysis.remote_workflow.LocalSentenceEncoder",
        lambda *a: pytest.fail("Loaded model"),
    )
    with pytest.raises(ValueError, match="inputs changed"):
        load_prepared(tmp_path)
    with pytest.raises(ValueError, match="inputs changed"):
        encode(tmp_path, tmp_path / "model", "fixture")


def test_cli_encoding_does_not_create_api_client(tmp_path, monkeypatch, capsys):
    import sys

    from scripts.hybrid_review import main

    monkeypatch.setattr(
        "scripts.hybrid_review.ApiClient", lambda *a: pytest.fail("Connected to API")
    )
    monkeypatch.setattr("scripts.hybrid_review.encode", lambda *a: {"stage": "encoded"})
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "hybrid_review",
            "encode",
            str(tmp_path),
            "--model-dir",
            str(tmp_path / "model"),
            "--model",
            "fixture",
        ],
    )
    main()
    assert json.loads(capsys.readouterr().out) == {"stage": "encoded"}


def test_cli_errors_hide_credentials_and_source(tmp_path, monkeypatch, capsys):
    import sys

    from scripts.hybrid_review import main

    monkeypatch.setenv("SPECGUARD_API_TOKEN", "private-token")
    monkeypatch.setenv("SPECGUARD_API_URL", "https://api.example")
    monkeypatch.setattr(sys, "argv", ["hybrid_review", "analyze", str(tmp_path)])
    with pytest.raises(SystemExit) as failure:
        main()
    assert failure.value.code == 2
    output = capsys.readouterr()
    assert "private-token" not in output.err and output.out == ""
