"""Explicit local-change embedding exchange under the API's existing authorization."""

import hashlib
import json
from contextlib import contextmanager
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import Field
from starlette.concurrency import run_in_threadpool

from services.analysis.analysis_retrieval import export_texts, prepare_hybrid, review_criteria
from services.analysis.domain import Contract, Criterion
from services.analysis.embedding_artifacts import decode_json
from services.analysis.hybrid import HybridRetriever, VectorBundle
from services.analysis.repository import index_change
from services.api.bundles import BundleStore

UPLOAD_LIMIT = 20_000_000


class ChangeInput(Contract):
    repository: str = Field(min_length=1, max_length=300)
    base: str = Field(min_length=1, max_length=200)
    head: str = Field(default="HEAD", min_length=1, max_length=200)
    requirement: str = Field(min_length=1, max_length=20000)
    criteria: list[Criterion] = Field(min_length=1, max_length=50)


class HybridSelection(Contract):
    bundle_id: str = Field(pattern="^[0-9a-f]{64}$")
    window: int = Field(default=50, ge=6, le=1000)
    rrf_k: int = Field(default=60, ge=1, le=1000)


class BundleUpload(Contract):
    change: ChangeInput
    binding_sha256: str = Field(pattern="^[0-9a-f]{64}$")
    bundle: VectorBundle


def parse_upload(content: bytes) -> BundleUpload:
    return BundleUpload.model_validate(decode_json(content))


class HybridWorkflow:
    def __init__(self, root: Path, bundles: BundleStore):
        self.root, self.bundles = root, bundles

    def prepare(self, change: ChangeInput):
        repo = (self.root / change.repository).resolve()
        if not repo.is_relative_to(self.root) or not (repo / ".git").exists():
            raise HTTPException(404, "Repository not found")
        criteria = review_criteria(change.requirement, change.criteria)
        index = index_change(repo, change.base, change.head)
        texts = export_texts(index, criteria)
        identity = {
            "repository": str(repo),
            "base": index["base_sha"],
            "head": index["head_sha"],
            "parser": index["parser_version"],
            "requirement": change.requirement,
            "criteria": [criterion.model_dump() for criterion in criteria],
            "inputs": sorted(texts),
        }
        binding = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
        return repo, index, texts, binding

    def export(self, change: ChangeInput):
        _, index, texts, binding = self.prepare(change)
        return {
            "binding_sha256": binding,
            "base_sha": index["base_sha"],
            "head_sha": index["head_sha"],
            "inputs": texts,
            "limitation": "Contains source text. Exporting does not run a model or establish quality.",
        }

    def register(self, owner: str, upload: BundleUpload):
        repo, index, texts, binding = self.prepare(upload.change)
        if binding != upload.binding_sha256:
            raise HTTPException(409, "Change no longer matches the exported inputs")
        if set(upload.bundle.vectors) != set(texts):
            raise ValueError("Bundle must contain exactly the exported input hashes")
        prepare_hybrid(HybridRetriever(upload.bundle), index, upload.change.criteria)
        return self.bundles.save(owner, repo.name, binding, upload.bundle)

    def resolve(self, owner: str, change: ChangeInput, selection: HybridSelection):
        summary, bundle = self.bundles.get(owner, selection.bundle_id)
        repo, index, _, binding = self.prepare(change)
        if binding != summary["binding_sha256"]:
            raise HTTPException(409, "Embedding bundle does not match this change and criteria")
        hybrid = HybridRetriever(bundle, window=selection.window, rrf_k=selection.rrf_k)
        return repo, index, hybrid


def hybrid_router(workflow: HybridWorkflow, authorize, slots):
    router = APIRouter()

    @contextmanager
    def capacity():
        if not slots.acquire(blocking=False):
            raise HTTPException(429, "Analysis capacity reached; retry later")
        try:
            yield
        except (ValueError, TypeError, OSError, RuntimeError) as error:
            raise HTTPException(
                422, "Invalid embedding inputs, vectors or repository change"
            ) from error
        finally:
            slots.release()

    @router.post("/v1/embedding-inputs")
    def export(body: ChangeInput, response: Response, owner: str = Depends(authorize)):
        response.headers["Cache-Control"] = "no-store"
        with capacity():
            return workflow.export(body)

    @router.post("/v1/embedding-bundles", status_code=201)
    async def register(request: Request, owner: str = Depends(authorize)):
        with capacity():
            if request.headers.get("content-type", "").split(";")[0].strip() != "application/json":
                raise HTTPException(415, "Send an application/json bundle")
            content = bytearray()
            async for chunk in request.stream():
                if len(content) + len(chunk) > UPLOAD_LIMIT:
                    raise HTTPException(413, "Embedding upload exceeds 20 MB")
                content.extend(chunk)
            upload = await run_in_threadpool(parse_upload, bytes(content))
            return await run_in_threadpool(workflow.register, owner, upload)

    @router.get("/v1/embedding-bundles")
    def listing(
        limit: int = Query(default=100, ge=1, le=100),
        offset: int = Query(default=0, ge=0),
        owner: str = Depends(authorize),
    ):
        return workflow.bundles.list(owner, limit, offset)

    @router.get("/v1/embedding-bundles/{identifier}/export")
    def export_bundle(identifier: str, response: Response, owner: str = Depends(authorize)):
        response.headers["Cache-Control"] = "no-store"
        summary, bundle = workflow.bundles.get(owner, identifier)
        return {"summary": summary, "bundle": bundle.model_dump()}

    @router.delete("/v1/embedding-bundles/{identifier}", status_code=204)
    def remove(identifier: str, owner: str = Depends(authorize)):
        workflow.bundles.delete(owner, identifier)

    return router
