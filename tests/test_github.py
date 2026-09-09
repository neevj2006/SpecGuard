import base64
import hashlib
import hmac
import json
import threading

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from services.analysis.decompose import decompose
from services.api.store import Store
from services.integrations.github import GitHubClient, GitHubError, repository_name, verify_webhook
from services.integrations.routes import github_router


def transport(records):
    def handle(request):
        assert request.url.host == "api.github.com"
        records.append((request.method, request.url.path))
        path = request.url.path
        if path == "/installation/repositories":
            payload = {"repositories": [{"full_name": "acme/shop", "private": True}]}
        elif path == "/repos/acme/shop/pulls/1":
            payload = {
                "number": 1,
                "title": "Discount",
                "base": {"sha": "a" * 40},
                "head": {"sha": "b" * 40},
            }
        elif path.endswith("/files"):
            payload = [{"filename": "discount.ts", "status": "modified"}]
        elif "/git/trees/" in path:
            payload = {
                "truncated": False,
                "tree": [
                    {
                        "path": "discount.ts",
                        "mode": "100644",
                        "type": "blob",
                        "sha": "c" * 40,
                        "size": 40,
                    }
                ],
            }
        elif "/git/blobs/" in path:
            payload = {
                "encoding": "base64",
                "content": base64.b64encode(
                    b"export function discount() { return 10; }\n"
                ).decode(),
            }
        elif path.endswith("/comments") and request.method == "GET":
            payload = []
        elif path.endswith("/comments") and request.method == "POST":
            assert "specguard-run:" in json.loads(request.content)["body"]
            payload = {"html_url": "https://github.com/acme/shop/pull/1#issuecomment-1"}
        else:
            return httpx.Response(404, json={"message": "not found"})
        return httpx.Response(200, json=payload)

    return httpx.MockTransport(handle)


def test_snapshot_preserves_revision_and_exact_source():
    client = GitHubClient("test-token", transport=transport([]))
    index, pull = client.snapshot("acme/shop", 1)
    assert index["head_sha"] == "b" * 40
    assert index["chunks"][0].quote == "export function discount() { return 10; }"
    assert index["chunks"][0].changed
    assert pull["number"] == 1


def test_uninstalled_repository_and_remote_path_are_rejected():
    client = GitHubClient("test-token", transport=transport([]))
    with pytest.raises(GitHubError):
        client.snapshot("another/private", 1)
    with pytest.raises(GitHubError):
        client.request("GET", "//evil.example/secrets")
    with pytest.raises(GitHubError):
        repository_name("acme/../../private")


def test_signature_is_bound_to_raw_body():
    body = b'{"action":"opened"}'
    signature = "sha256=" + hmac.new(b"secret", body, hashlib.sha256).hexdigest()
    assert verify_webhook(body, signature, "secret")
    assert not verify_webhook(body + b" ", signature, "secret")
    assert not verify_webhook(body, signature, "")


def test_rate_limits_fail_without_disclosing_response():
    client = GitHubClient(
        "test-token",
        transport=httpx.MockTransport(lambda request: httpx.Response(429, text="sensitive")),
    )
    with pytest.raises(GitHubError, match="rate limit") as error:
        client.repositories()
    assert "sensitive" not in str(error.value)


def test_manual_analysis_preview_publication_and_replay(tmp_path, monkeypatch):
    records = []
    store = Store(tmp_path / "github.sqlite")
    store.allow_installation("alice", 12)
    app = FastAPI()
    app.include_router(
        github_router(
            store,
            lambda: "alice",
            threading.BoundedSemaphore(1),
            lambda identifier: GitHubClient("test-token", transport=transport(records)),
        )
    )
    client = TestClient(app)
    body = {
        "installation_id": 12,
        "repository": "acme/shop",
        "number": 1,
        "requirement": "discount",
        "criteria": [c.model_dump() for c in decompose("discount")],
    }
    response = client.post("/v1/github/runs", json=body)
    assert response.status_code == 201, response.text
    run = response.json()
    assert run["pull_number"] == 1 and run["repository"] == "acme/shop"
    publish = {"installation_id": 12, "repository": "acme/shop", "run_id": run["id"]}
    assert client.post("/v1/github/report", json=publish).json()["published"] is False
    assert not any(method == "POST" for method, _ in records)
    publish["confirmed"] = True
    assert client.post("/v1/github/report", json=publish).json()["published"] is True
    assert client.post("/v1/github/report", json=publish).json()["published"] is True
    assert sum(method == "POST" for method, _ in records) == 1
    body["installation_id"] = 999
    assert client.post("/v1/github/runs", json=body).status_code == 404
    monkeypatch.setenv("SPECGUARD_GITHUB_WEBHOOK_SECRET", "secret")
    payload = b"{}"
    signature = "sha256=" + hmac.new(b"secret", payload, hashlib.sha256).hexdigest()
    headers = {"X-Hub-Signature-256": signature, "X-GitHub-Delivery": "delivery-1"}
    assert (
        client.post("/v1/github/webhook", content=payload, headers=headers).json()["duplicate"]
        is False
    )
    assert (
        client.post("/v1/github/webhook", content=payload, headers=headers).json()["duplicate"]
        is True
    )
    assert client.post("/v1/github/webhook", content=payload).status_code == 401


def test_pagination_is_bounded():
    pages = []

    def handle(request):
        pages.append(request.url.params["page"])
        return httpx.Response(200, json=[{}] * 100)

    client = GitHubClient("test-token", transport=httpx.MockTransport(handle))
    with pytest.raises(GitHubError, match="pagination budget"):
        client.pages("/items", max_pages=2)
    assert pages == ["1", "2"]
