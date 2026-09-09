from fastapi.testclient import TestClient

from services.analysis.decompose import decompose
from services.analysis.engine import analyze
from services.api.main import create_app
from services.api.store import Store


def test_authenticated_lifecycle(repository, tmp_path):
    repo, base, head = repository
    app = create_app(repo, tmp_path / "data.sqlite", "secret")
    client = TestClient(app)
    assert client.get("/health").status_code == 200
    assert client.get("/v1/runs").status_code == 401
    client.headers["Authorization"] = "Bearer secret"
    criteria = client.post("/v1/criteria", json={"text": "Apply discount"}).json()["criteria"]
    body = {
        "repository": ".",
        "base": base,
        "head": head,
        "requirement": "Apply discount",
        "criteria": criteria,
    }
    response = client.post("/v1/runs", json=body)
    assert response.status_code == 201, response.text
    identifier = response.json()["id"]
    assert client.post("/v1/runs", json=body).json()["id"] == identifier
    assert len(client.get("/v1/runs").json()) == 1
    assert (
        client.post(
            f"/v1/runs/{identifier}/feedback",
            json={"criterion_id": criteria[0]["id"], "note": "Needs review"},
        ).status_code
        == 204
    )
    assert client.delete(f"/v1/runs/{identifier}").status_code == 204
    assert client.get(f"/v1/runs/{identifier}").status_code == 404
    body["repository"] = "../outside"
    assert client.post("/v1/runs", json=body).status_code == 404


def test_tenant_isolation(repository, tmp_path):
    repo, base, head = repository
    store = Store(tmp_path / "store.sqlite")
    run = analyze(repo, base, head, "discount", decompose("discount"))
    store.save("alice", run)
    assert store.list("bob") == []
    import pytest

    with pytest.raises(KeyError):
        store.delete("bob", run.id)
    assert store.get("alice", run.id).id == run.id
