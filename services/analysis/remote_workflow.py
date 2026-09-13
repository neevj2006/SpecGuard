"""Explicit, restartable client stages for registered hybrid API analysis."""

import hashlib
import ipaddress
import json
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from pydantic import Field

from services.analysis.domain import AnalysisRun, Contract
from services.analysis.embedding_artifacts import (
    decode_json,
    read_json,
    validate_inputs,
    write_json,
)
from services.analysis.embeddings import generate_bundle
from services.analysis.hybrid import VectorBundle
from services.analysis.local_encoder import LocalSentenceEncoder
from services.api.hybrid_routes import ChangeInput

MAX_RESPONSE = 20_000_000


def api_origin(value: str) -> str:
    url = urlsplit(value)
    if (
        url.scheme not in ("https", "http")
        or not url.hostname
        or url.username is not None
        or url.password is not None
        or url.query
        or url.fragment
        or url.path not in ("", "/")
    ):
        raise ValueError("Use an API origin without credentials, query or path")
    if url.scheme == "http":
        try:
            loopback = ipaddress.ip_address(url.hostname).is_loopback
        except ValueError:
            loopback = url.hostname == "localhost"
        if not loopback:
            raise ValueError("Non-local API connections require HTTPS")
    if url.port is not None and not 1 <= url.port <= 65535:
        raise ValueError("Invalid API port")
    return value.rstrip("/")


class ApiClient:
    def __init__(self, origin: str, token: str, *, transport=None):
        self.origin = api_origin(origin)
        if not token.strip() or any(char.isspace() for char in token):
            raise ValueError("Configure a nonempty API token without whitespace")
        self.http = httpx.Client(
            base_url=self.origin,
            headers={"Authorization": f"Bearer {token}"},
            timeout=60,
            follow_redirects=False,
            trust_env=False,
            transport=transport,
        )

    def close(self):
        self.http.close()

    def post(self, path: str, payload: dict) -> dict:
        if path not in ("/v1/embedding-inputs", "/v1/embedding-bundles", "/v1/runs"):
            raise ValueError("Unsupported workflow API path")
        encoded = json.dumps(payload, allow_nan=False).encode()
        if len(encoded) > MAX_RESPONSE:
            raise ValueError("API request exceeds 20 MB")
        try:
            with self.http.stream(
                "POST", path, content=encoded, headers={"Content-Type": "application/json"}
            ) as response:
                if response.status_code not in (200, 201):
                    raise ValueError(
                        f"API rejected request (HTTP {response.status_code}); inspect server state before retrying"
                    )
                content = bytearray()
                for chunk in response.iter_bytes():
                    if len(content) + len(chunk) > MAX_RESPONSE:
                        raise ValueError("API response exceeds 20 MB")
                    content.extend(chunk)
            result = decode_json(bytes(content))
            if not isinstance(result, dict):
                raise TypeError("Expected a JSON response object")
            return result
        except httpx.HTTPError as error:
            raise ValueError("API request failed; its remote outcome may be unknown") from error


class PreparedChange(Contract):
    version: str = Field(default="hybrid-client/1", pattern="^hybrid-client/1$")
    api: str
    change: ChangeInput
    binding_sha256: str = Field(pattern="^[0-9a-f]{64}$")
    inputs_sha256: str = Field(pattern="^[0-9a-f]{64}$")


def fingerprint(payload: dict) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def prepare(client: ApiClient, change: ChangeInput, directory: Path) -> dict:
    if directory.exists() or directory.is_symlink():
        raise ValueError("Prepare requires a new workspace directory")
    exported = client.post("/v1/embedding-inputs", change.model_dump())
    inputs = validate_inputs(exported.get("inputs"))
    base, head = exported.get("base_sha"), exported.get("head_sha")
    for revision in (base, head):
        if (
            not isinstance(revision, str)
            or len(revision) != 40
            or any(c not in "0123456789abcdef" for c in revision)
        ):
            raise ValueError("API did not return resolved Git commits")
    pinned = change.model_copy(update={"base": base, "head": head})
    prepared = PreparedChange.model_validate(
        {
            "api": client.origin,
            "change": pinned,
            "binding_sha256": exported.get("binding_sha256"),
            "inputs_sha256": fingerprint(inputs),
        }
    )
    directory.mkdir(parents=True, exist_ok=False)
    write_json(directory / "inputs.json", inputs)
    # This marker is published last; a partial prepare is never accepted by later stages.
    write_json(directory / "prepared.json", prepared.model_dump())
    return {"stage": "prepared", "inputs": len(inputs), "base": base, "head": head}


def load_prepared(directory: Path) -> tuple[PreparedChange, dict[str, str]]:
    prepared = PreparedChange.model_validate(read_json(directory / "prepared.json"))
    inputs = validate_inputs(read_json(directory / "inputs.json"))
    if fingerprint(inputs) != prepared.inputs_sha256:
        raise ValueError("Prepared inputs changed; prepare a fresh workspace")
    return prepared, inputs


def encode(directory: Path, model_directory: Path, model: str, batch_size: int = 16) -> dict:
    _, inputs = load_prepared(directory)
    if directory.resolve().is_relative_to(model_directory.resolve()):
        raise ValueError("Keep workflow artifacts outside the model directory")
    output = directory / "vectors.json"
    if output.exists() or output.is_symlink():
        raise ValueError("Vectors already exist; use a fresh workspace for another encoder")
    if not 1 <= batch_size <= 128:
        raise ValueError("Batch size must be between 1 and 128")
    encoder = LocalSentenceEncoder(model_directory, model)
    bundle, stats = generate_bundle(
        inputs, encoder, batch_size=batch_size, cache_path=directory / "vector-cache.json"
    )
    encoder.verify_unchanged()
    write_json(output, bundle.model_dump())
    return {"stage": "encoded", "model": bundle.model, "revision": bundle.revision, **stats}


def analyze_remote(
    client: ApiClient,
    directory: Path,
    *,
    use_model: bool = False,
    window: int = 50,
    rrf_k: int = 60,
) -> dict:
    prepared, inputs = load_prepared(directory)
    if client.origin != prepared.api:
        raise ValueError("Workspace belongs to a different API origin")
    if not 6 <= window <= 1000 or not 1 <= rrf_k <= 1000:
        raise ValueError("Invalid hybrid fusion configuration")
    output = directory / "run.json"
    if output.exists() or output.is_symlink():
        raise ValueError("A completed run already exists in this workspace")
    bundle = VectorBundle.model_validate(read_json(directory / "vectors.json"))
    if set(bundle.vectors) != set(inputs):
        raise ValueError("Vectors do not cover exactly the prepared inputs")
    registered = client.post(
        "/v1/embedding-bundles",
        {
            "change": prepared.change.model_dump(),
            "binding_sha256": prepared.binding_sha256,
            "bundle": bundle.model_dump(),
        },
    )
    identifier = registered.get("id")
    if (
        not isinstance(identifier, str)
        or len(identifier) != 64
        or any(c not in "0123456789abcdef" for c in identifier)
        or registered.get("binding_sha256") != prepared.binding_sha256
        or registered.get("bundle_sha256") != fingerprint(bundle.model_dump())
    ):
        raise ValueError("Registration response does not match the prepared vectors")
    response = client.post(
        "/v1/runs",
        prepared.change.model_dump()
        | {
            "hybrid": {"bundle_id": identifier, "window": window, "rrf_k": rrf_k},
            "use_model": use_model,
        },
    )
    run = AnalysisRun.model_validate(response)
    if (
        run.base_sha != prepared.change.base
        or run.head_sha != prepared.change.head
        or run.requirement != prepared.change.requirement
        or [r.criterion for r in run.results] != prepared.change.criteria
        or run.versions.get("embedding_bundle_sha256") != registered["bundle_sha256"]
        or run.versions.get("retriever") != "hybrid-rrf/1"
        or run.versions.get("retrieval_window") != str(window)
        or run.versions.get("retrieval_rrf_k") != str(rrf_k)
    ):
        raise ValueError("Returned analysis does not match the prepared change")
    write_json(output, run.model_dump(mode="json"))
    return {
        "stage": "analyzed",
        "run_id": run.id,
        "bundle_id": identifier,
        "criteria": len(run.results),
        "model_verifier_requested": use_model,
    }
