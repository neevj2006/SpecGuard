import pytest
from fastapi.testclient import TestClient

from services.api.main import create_app


@pytest.fixture
def client(tmp_path, monkeypatch):
    for key in (
        "MODEL",
        "MODEL_KEY",
        "GITHUB_APP_ID",
        "GITHUB_PRIVATE_KEY_FILE",
        "GITHUB_INSTALLATIONS",
        "GITHUB_WEBHOOK_SECRET",
        "OWNER_ID",
    ):
        monkeypatch.delenv(f"SPECGUARD_{key}", raising=False)
    return TestClient(create_app(tmp_path, tmp_path / "readiness.sqlite", "private-token"))


def test_readiness_requires_authentication_and_reports_missing_config(client):
    assert client.get("/v1/readiness").status_code == 401
    client.headers["Authorization"] = "Bearer private-token"
    result = client.get("/v1/readiness").json()
    assert not any(result["checks"].values())
    assert result["scope"] == "configuration_only"
    assert result["external_services_verified"] is False


def test_readiness_does_not_expose_secrets_or_other_owners(client, monkeypatch, tmp_path):
    key = tmp_path / "private.pem"
    key.write_text("not a real key")
    for name, value in {
        "MODEL": "private-model",
        "MODEL_KEY": "private-credential",
        "GITHUB_APP_ID": "123",
        "GITHUB_PRIVATE_KEY_FILE": str(key),
        "GITHUB_WEBHOOK_SECRET": "private-hook",
        "OWNER_ID": "alice",
    }.items():
        monkeypatch.setenv(f"SPECGUARD_{name}", value)
    client.app.state.store.allow_installation("bob", 7)
    client.headers["Authorization"] = "Bearer private-token"
    response = client.get("/v1/readiness")
    checks = response.json()["checks"]
    assert checks["model_identifier"] and checks["model_credential"]
    assert checks["github_key_file_present"] and checks["webhook_secret"]
    assert not checks["github_installation_assigned"]
    assert "private" not in response.text and str(key) not in response.text
    client.app.state.store.allow_installation("alice", 8)
    assert client.get("/v1/readiness").json()["checks"]["github_installation_assigned"]
    monkeypatch.setenv("SPECGUARD_GITHUB_PRIVATE_KEY_FILE", str(tmp_path))
    assert not client.get("/v1/readiness").json()["checks"]["github_key_file_present"]
