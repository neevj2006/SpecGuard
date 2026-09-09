import os
import re
import time

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import Field

from services.analysis.domain import Contract, Criterion
from services.analysis.engine import analyze_index
from services.analysis.verifier import ModelVerifier
from services.api.store import Store
from services.integrations.github import (
    AppConfig,
    GitHubClient,
    GitHubError,
    source_url,
    verify_webhook,
)


class RepositoryInput(Contract):
    installation_id: int = Field(ge=1)
    repository: str = Field(min_length=3, max_length=201)


class PullInput(RepositoryInput):
    number: int = Field(ge=1)


class GitHubRunInput(PullInput):
    requirement: str = Field(min_length=1, max_length=20000)
    criteria: list[Criterion] = Field(min_length=1, max_length=50)
    use_model: bool = False


class PublishInput(RepositoryInput):
    run_id: str = Field(pattern=r"^[0-9a-f]{24}$")
    confirmed: bool = False


def render_report(run) -> str:
    lines = ["## SpecGuard requirement review", f"Revision: `{run.head_sha}`", ""]
    for result in run.results:
        lines.extend(
            [
                f"### {result.verdict.replace('_', ' ')}",
                result.criterion.text,
                "",
                result.rationale,
                "",
            ]
        )
        for evidence in result.evidence:
            url = source_url(
                run.repository,
                evidence.revision,
                evidence.path,
                evidence.start_line,
                evidence.end_line,
            )
            lines.append(f"- [Source lines {evidence.start_line}–{evidence.end_line}]({url})")
        lines.extend(
            [
                f"Tests: {result.tests.status}. Confidence: {result.confidence if result.confidence is not None else 'unavailable'}.",
                result.uncertainty,
                "",
            ]
        )
    lines.append(
        "Static inference is not executed proof. Review source and uncertainty before deciding."
    )
    return "\n".join(lines)


def github_router(store: Store, authorize, slots, client_factory=None) -> APIRouter:
    router = APIRouter(prefix="/v1/github", tags=["GitHub"])

    def client(owner: str, installation_id: int):
        if installation_id not in store.installation_ids(owner):
            raise HTTPException(404, "Installation not found")
        if client_factory:
            return client_factory(installation_id)
        try:
            return GitHubClient(AppConfig.from_env().token(installation_id))
        except (GitHubError, OSError) as error:
            raise HTTPException(
                503, "GitHub App is not configured or installation is unavailable"
            ) from error

    @router.get("/installations")
    def installations(owner: str = Depends(authorize)):
        return [{"id": identifier} for identifier in store.installation_ids(owner)]

    @router.get("/installations/{installation_id}/repositories")
    def repositories(installation_id: int, owner: str = Depends(authorize)):
        return [
            {"full_name": item["full_name"], "private": item["private"]}
            for item in client(owner, installation_id).repositories()
        ]

    @router.post("/pulls")
    def pulls(body: RepositoryInput, owner: str = Depends(authorize)):
        return [
            {
                "number": item["number"],
                "title": item["title"],
                "body": item.get("body") or "",
                "base": item["base"]["sha"],
                "head": item["head"]["sha"],
            }
            for item in client(owner, body.installation_id).pulls(body.repository)
        ]

    @router.post("/issue")
    def issue(body: PullInput, owner: str = Depends(authorize)):
        issue = client(owner, body.installation_id).issue(body.repository, body.number)
        return {"number": issue["number"], "title": issue["title"], "body": issue.get("body") or ""}

    @router.post("/runs", status_code=201)
    def analyze_pull(body: GitHubRunInput, owner: str = Depends(authorize)):
        github = client(owner, body.installation_id)
        if not slots.acquire(blocking=False):
            raise HTTPException(429, "Analysis capacity reached")
        try:
            started = time.perf_counter()
            index, _pull = github.snapshot(body.repository, body.number)
            run = analyze_index(
                index,
                body.repository,
                f"github:{body.repository}#{body.number}",
                body.requirement,
                body.criteria,
                ModelVerifier() if body.use_model else None,
                lambda identifier: store.get(owner, identifier),
                started_at=started,
            )
            run.pull_number = body.number
            return store.save(owner, run)
        except GitHubError:
            raise
        except ValueError as error:
            raise HTTPException(
                422, "Invalid analysis input or missing model configuration"
            ) from error
        finally:
            slots.release()

    @router.post("/report")
    def report(body: PublishInput, owner: str = Depends(authorize)):
        github = client(owner, body.installation_id)
        run = store.get(owner, body.run_id)
        if run.repository.lower() != body.repository.lower() or run.pull_number is None:
            raise HTTPException(404, "GitHub run not found for this repository")
        github.assert_repository(body.repository)
        text = render_report(run)
        if not body.confirmed:
            return {"preview": text, "published": False}
        previous = store.publication(owner, run.id)
        if previous:
            return {"url": previous, "published": True}
        pull = github.request("GET", f"/repos/{body.repository}/pulls/{run.pull_number}")
        if pull["head"]["sha"] != run.head_sha:
            raise HTTPException(
                409, "Pull request changed; analyze the latest revision before publishing"
            )
        url = github.publish(body.repository, run.pull_number, run.id, text)
        store.record_publication(owner, run.id, body.repository, run.pull_number, url)
        return {"url": url, "published": True}

    @router.post("/webhook")
    async def webhook(
        request: Request,
        x_hub_signature_256: str = Header(default=""),
        x_github_delivery: str = Header(default=""),
    ):
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > 1_000_000:
                raise HTTPException(413, "Webhook exceeds size limit")
        if not verify_webhook(
            bytes(body), x_hub_signature_256, os.environ.get("SPECGUARD_GITHUB_WEBHOOK_SECRET", "")
        ):
            raise HTTPException(401, "Invalid webhook signature")
        if not re.fullmatch(r"[a-zA-Z0-9-]{1,128}", x_github_delivery):
            raise HTTPException(422, "Invalid delivery ID")
        first = store.claim_delivery(x_github_delivery)
        return {"accepted": True, "duplicate": not first, "analysis_triggered": False}

    return router
