import hashlib
import os
import secrets
import threading
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import Field

from services.analysis.decompose import Decomposition, RuleDecomposer
from services.analysis.domain import Contract, Criterion
from services.analysis.engine import analyze
from services.analysis.verifier import ModelVerifier
from services.api.store import Store
from services.integrations.github import GitHubError
from services.integrations.routes import github_router


class RequirementInput(Contract):
    text: str = Field(min_length=1, max_length=20000)


class RunInput(Contract):
    repository: str = Field(min_length=1, max_length=300)
    base: str = Field(min_length=1, max_length=200)
    head: str = Field(default="HEAD", min_length=1, max_length=200)
    requirement: str = Field(min_length=1, max_length=20000)
    criteria: list[Criterion] = Field(min_length=1, max_length=50)
    use_model: bool = False


class FeedbackInput(Contract):
    criterion_id: str = Field(min_length=1, max_length=80)
    note: str = Field(min_length=1, max_length=2000)


def create_app(
    root: Path | None = None,
    database: Path | None = None,
    token: str | None = None,
    *,
    github_client_factory=None,
):
    root = (root or Path(os.environ.get("SPECGUARD_REPOSITORY_ROOT", "."))).resolve()
    store = Store(
        database
        or os.environ.get("SPECGUARD_DATABASE_URL")
        or Path(os.environ.get("SPECGUARD_DATABASE", ".specguard/runs.sqlite3"))
    )
    token = token if token is not None else os.environ.get("SPECGUARD_API_TOKEN", "")
    app = FastAPI(title="SpecGuard", version="0.1.0")
    slots = threading.BoundedSemaphore(2)

    def authorize(authorization: str = Header(default="")) -> str:
        if not token:
            raise HTTPException(503, "Configure an API token before using the service")
        if not secrets.compare_digest(authorization, f"Bearer {token}"):
            raise HTTPException(401, "Authentication required")
        owner = os.environ.get("SPECGUARD_OWNER_ID") or hashlib.sha256(token.encode()).hexdigest()
        return owner

    app.state.store = store
    configured_owner = (
        os.environ.get("SPECGUARD_OWNER_ID") or hashlib.sha256(token.encode()).hexdigest()
    )
    for identifier in os.environ.get("SPECGUARD_GITHUB_INSTALLATIONS", "").split(","):
        if identifier.strip():
            store.allow_installation(configured_owner, int(identifier))
    app.include_router(github_router(store, authorize, slots, github_client_factory))

    @app.exception_handler(GitHubError)
    async def github_error(_request, error):
        return JSONResponse(status_code=502, content={"detail": str(error)})

    @app.exception_handler(KeyError)
    async def missing_object(_request, _error):
        return JSONResponse(status_code=404, content={"detail": "Object not found"})

    @app.get("/health")
    def health():
        return {"status": "ok", "version": "0.1.0"}

    @app.post("/v1/criteria", response_model=Decomposition)
    def criteria(body: RequirementInput, owner: str = Depends(authorize)):
        try:
            return RuleDecomposer().decompose(body.text)
        except ValueError as error:
            raise HTTPException(422, str(error)) from error

    @app.get("/v1/repositories")
    def repositories(owner: str = Depends(authorize)):
        candidates = [root] if (root / ".git").exists() else sorted(root.iterdir())
        return [
            {"name": p.name, "path": p.relative_to(root).as_posix() or "."}
            for p in candidates
            if p.is_dir() and not p.is_symlink() and (p / ".git").exists()
        ]

    @app.post("/v1/runs", status_code=201)
    def start(body: RunInput, owner: str = Depends(authorize)):
        repo = (root / body.repository).resolve()
        if not repo.is_relative_to(root) or not (repo / ".git").exists():
            raise HTTPException(404, "Repository not found")
        if not slots.acquire(blocking=False):
            raise HTTPException(
                429, "Analysis capacity reached; retry after an active run finishes"
            )
        try:
            run = analyze(
                repo,
                body.base,
                body.head,
                body.requirement,
                body.criteria,
                ModelVerifier() if body.use_model else None,
                lambda identifier: store.get(owner, identifier),
            )
            return store.save(owner, run)
        except ValueError as error:
            raise HTTPException(422, str(error)) from error
        finally:
            slots.release()

    @app.get("/v1/runs")
    def history(
        limit: int = Query(default=100, ge=1, le=100),
        offset: int = Query(default=0, ge=0),
        owner: str = Depends(authorize),
    ):
        return store.list(owner, limit, offset)

    @app.get("/v1/runs/{identifier}/feedback")
    def notes(identifier: str, owner: str = Depends(authorize)):
        return store.notes(owner, identifier)

    @app.get("/v1/runs/{identifier}/export")
    def export(identifier: str, owner: str = Depends(authorize)):
        return {"run": store.get(owner, identifier), "feedback": store.notes(owner, identifier)}

    @app.delete("/v1/retention")
    def retention(days: int = Query(ge=1, le=3650), owner: str = Depends(authorize)):
        return {"deleted_runs": store.expire(owner, days)}

    @app.get("/v1/runs/{identifier}")
    def detail(identifier: str, owner: str = Depends(authorize)):
        try:
            return store.get(owner, identifier)
        except KeyError as error:
            raise HTTPException(404, "Run not found") from error

    @app.delete("/v1/runs/{identifier}", status_code=204)
    def delete(identifier: str, owner: str = Depends(authorize)):
        try:
            store.delete(owner, identifier)
        except KeyError as error:
            raise HTTPException(404, "Run not found") from error

    @app.post("/v1/runs/{identifier}/feedback", status_code=204)
    def feedback(identifier: str, body: FeedbackInput, owner: str = Depends(authorize)):
        try:
            store.feedback(owner, identifier, body.criterion_id, body.note)
        except KeyError as error:
            raise HTTPException(404, "Run or criterion not found") from error

    return app


app = create_app()
