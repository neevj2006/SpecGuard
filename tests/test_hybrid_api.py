import copy

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import update

from services.analysis.decompose import decompose
from services.analysis.embeddings import generate_bundle
from services.analysis.hybrid import text_key
from services.api.main import create_app
from services.api.schema import embedding_bundles
from tests.test_embeddings import FakeEncoder


@pytest.fixture
def exchange(repository, tmp_path, monkeypatch):
    monkeypatch.delenv("SPECGUARD_OWNER_ID", raising=False)
    repo, base, head = repository
    database = tmp_path / "api.sqlite"
    app = create_app(repo, database, "alice-token")
    client = TestClient(app, headers={"Authorization": "Bearer alice-token"})
    change = {
        "repository": ".",
        "base": base,
        "head": head,
        "requirement": "Archive receipts",
        "criteria": [c.model_dump() for c in decompose("Archive receipts")],
    }
    response = client.post("/v1/embedding-inputs", json=change)
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    exported = response.json()
    bundle, _ = generate_bundle(exported["inputs"], FakeEncoder())
    upload = {
        "change": change,
        "binding_sha256": exported["binding_sha256"],
        "bundle": bundle.model_dump(),
    }
    yield client, change, upload, app, repo, database
    client.close()
    app.state.store.engine.dispose()


def register(exchange):
    response = exchange[0].post("/v1/embedding-bundles", json=exchange[2])
    assert response.status_code == 201, response.text
    return response.json()


def test_api_full_export_registration_analysis_and_deletion(exchange):
    client, change, upload, _, _, _ = exchange
    summary = register(exchange)
    identifier = summary["id"]
    assert "vectors" not in summary and "inputs" not in summary
    assert register(exchange) == summary
    assert client.get("/v1/embedding-bundles").json() == [summary]
    exported = client.get(f"/v1/embedding-bundles/{identifier}/export").json()
    response = client.get(f"/v1/embedding-bundles/{identifier}/export")
    assert response.headers["cache-control"] == "no-store"
    exported = response.json()
    assert exported["bundle"] == upload["bundle"]
    body = change | {"hybrid": {"bundle_id": identifier}}
    response = client.post("/v1/runs", json=body)
    assert response.status_code == 201, response.text
    run = response.json()
    assert run["versions"]["retriever"] == "hybrid-rrf/1"
    assert run["versions"]["embedding_bundle_sha256"] == summary["bundle_sha256"]
    assert run["results"][0]["evidence"]
    assert run["results"][0]["verdict"] == "not_verifiable"
    assert run["results"][0]["tests"]["status"] == "not_run"
    assert client.post("/v1/runs", json=body).json()["created_at"] == run["created_at"]
    sparse = client.post("/v1/runs", json=change).json()
    assert sparse["versions"]["retriever"] == "bm25/2" and sparse["id"] != run["id"]
    changed = client.post(
        "/v1/runs", json=change | {"hybrid": {"bundle_id": identifier, "rrf_k": 70}}
    )
    assert changed.status_code == 201 and changed.json()["id"] != run["id"]
    assert client.delete(f"/v1/embedding-bundles/{identifier}").status_code == 204
    assert client.get("/v1/embedding-bundles").json() == []
    assert client.post("/v1/runs", json=body).status_code == 404
    assert client.get(f"/v1/runs/{run['id']}").status_code == 200


def test_cross_owner_cannot_list_export_delete_or_use_vectors(exchange):
    _, change, _, _, repo, database = exchange
    identifier = register(exchange)["id"]
    other_app = create_app(repo, database, "bob-token")
    with TestClient(other_app, headers={"Authorization": "Bearer bob-token"}) as other:
        assert other.get("/v1/embedding-bundles").json() == []
        assert other.get(f"/v1/embedding-bundles/{identifier}/export").status_code == 404
        assert other.delete(f"/v1/embedding-bundles/{identifier}").status_code == 404
        assert (
            other.post("/v1/runs", json=change | {"hybrid": {"bundle_id": identifier}}).status_code
            == 404
        )
        registered = other.post("/v1/embedding-bundles", json=exchange[2])
        assert registered.status_code == 201
        assert other.delete(f"/v1/embedding-bundles/{identifier}").status_code == 204
    assert exchange[0].get(f"/v1/embedding-bundles/{identifier}/export").status_code == 200
    other_app.state.store.engine.dispose()


@pytest.mark.parametrize("field", ["base", "requirement", "criteria"])
def test_registered_bundle_is_bound_to_change_before_model_construction(
    exchange, monkeypatch, field
):
    client, change, _, _, _, _ = exchange
    identifier = register(exchange)["id"]
    body = copy.deepcopy(change)
    if field == "base":
        body["base"] = body["head"]
    elif field == "criteria":
        body["criteria"][0]["text"] = "Different criterion"
    else:
        body[field] = "Changed request"
    monkeypatch.setattr(
        "services.api.main.ModelVerifier", lambda: pytest.fail("Constructed verifier")
    )
    response = client.post(
        "/v1/runs", json=body | {"use_model": True, "hybrid": {"bundle_id": identifier}}
    )
    assert response.status_code == 409


def test_registration_rejects_stale_binding_and_vector_coverage(exchange):
    client, _, upload, _, _, _ = exchange
    altered = copy.deepcopy(upload)
    altered["binding_sha256"] = "0" * 64
    assert client.post("/v1/embedding-bundles", json=altered).status_code == 409
    for extra in (True, False):
        altered = copy.deepcopy(upload)
        vectors = altered["bundle"]["vectors"]
        if extra:
            vectors[text_key("unrelated")] = [1, 0]
        else:
            vectors.pop(next(iter(vectors)))
        assert client.post("/v1/embedding-bundles", json=altered).status_code == 422
    assert client.get("/v1/embedding-bundles").json() == []
    assert register(exchange)


def test_registration_limits_and_errors_release_capacity(exchange, monkeypatch):
    client = exchange[0]
    monkeypatch.setattr("services.api.hybrid_routes.UPLOAD_LIMIT", 30)
    for _ in range(3):
        response = client.post(
            "/v1/embedding-bundles", content=b"x" * 31, headers={"Content-Type": "application/json"}
        )
        assert response.status_code == 413
    response = client.post(
        "/v1/embedding-bundles",
        content='{"private":1,"private":2}',
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 422 and "private" not in response.text
    assert client.post("/v1/embedding-bundles", content="{}").status_code == 415
    monkeypatch.setattr("services.api.hybrid_routes.UPLOAD_LIMIT", 20_000_000)
    assert register(exchange)


def test_unauthenticated_upload_and_export_are_rejected(exchange):
    client, change, _, _, _, _ = exchange
    client.headers.pop("Authorization")
    assert client.post("/v1/embedding-inputs", json=change).status_code == 401
    assert client.post("/v1/embedding-bundles", content="invalid").status_code == 401
    assert client.get("/v1/embedding-bundles").status_code == 401


def test_invalid_repository_cannot_be_exported(exchange):
    client, change, _, _, _, _ = exchange
    assert (
        client.post("/v1/embedding-inputs", json=change | {"repository": "../outside"}).status_code
        == 404
    )
    assert client.post("/v1/embedding-inputs", json=change | {"criteria": []}).status_code == 422


def test_registered_vectors_survive_service_restart(exchange):
    _, change, _, _, repo, database = exchange
    identifier = register(exchange)["id"]
    restarted = create_app(repo, database, "alice-token")
    with TestClient(restarted, headers={"Authorization": "Bearer alice-token"}) as client:
        assert client.get("/v1/embedding-bundles").json()[0]["id"] == identifier
        assert (
            client.post("/v1/runs", json=change | {"hybrid": {"bundle_id": identifier}}).status_code
            == 201
        )
    restarted.state.store.engine.dispose()


def test_retention_removes_old_bundle_but_keeps_analysis(exchange):
    client, _, _, app, _, _ = exchange
    identifier = register(exchange)["id"]
    with app.state.store.engine.begin() as db:
        db.execute(
            update(embedding_bundles)
            .where(embedding_bundles.c.id == identifier)
            .values(created_at="2020-01-01T00:00:00+00:00")
        )
    response = client.delete("/v1/retention?days=1")
    assert response.status_code == 200 and response.json() == {"deleted_runs": 0}
    assert client.get("/v1/embedding-bundles").json() == []


def test_bundle_listing_has_bounded_pagination(exchange):
    client = exchange[0]
    register(exchange)
    assert len(client.get("/v1/embedding-bundles?limit=1&offset=0").json()) == 1
    assert client.get("/v1/embedding-bundles?limit=1&offset=1").json() == []
    assert client.get("/v1/embedding-bundles?limit=0").status_code == 422
    assert client.get("/v1/embedding-bundles?offset=-1").status_code == 422
