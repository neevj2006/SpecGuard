import time
from collections.abc import Callable
from pathlib import Path

from services.analysis.decompose import decompose
from services.analysis.domain import AnalysisRun, Criterion, stable_id
from services.analysis.repository import index_change, validate_citation
from services.analysis.retrieval import rank
from services.analysis.verifier import BaselineVerifier, Verifier


def analyze(
    repo: Path,
    base: str,
    head: str,
    requirement: str,
    criteria: list[Criterion] | None = None,
    verifier: Verifier | None = None,
    lookup: Callable[[str], AnalysisRun] | None = None,
) -> AnalysisRun:
    started = time.perf_counter()
    index = index_change(repo, base, head)
    return analyze_index(
        index,
        repo.name,
        str(repo.resolve()),
        requirement,
        criteria,
        verifier,
        lookup,
        started_at=started,
    )


def analyze_index(
    index: dict,
    repository: str,
    identity_scope: str,
    requirement: str,
    criteria: list[Criterion] | None = None,
    verifier: Verifier | None = None,
    lookup: Callable[[str], AnalysisRun] | None = None,
    *,
    started_at: float | None = None,
) -> AnalysisRun:
    started = time.perf_counter()
    total_started = started if started_at is None else started_at
    criteria = criteria if criteria is not None else decompose(requirement)
    if not 1 <= len(criteria) <= 50 or len({c.id for c in criteria}) != len(criteria):
        raise ValueError("Supply 1–50 uniquely identified criteria")
    verifier = verifier or BaselineVerifier()
    versions = {
        "parser": index["parser_version"],
        "index": "2",
        "retriever": "bm25/1",
        "verifier": verifier.version,
        "prompt": "1",
        "model": getattr(verifier, "model", "none"),
    }
    identity = f"{identity_scope}:{index['base_sha']}:{index['head_sha']}:{requirement}:{[c.model_dump() for c in criteria]}:{versions}"
    run_id = stable_id(identity)
    if lookup:
        try:
            return lookup(run_id)
        except KeyError:
            pass
    results = []
    for criterion in criteria:
        candidates = rank(criterion.text, index["chunks"])
        if time.perf_counter() - started > 45:
            result = BaselineVerifier().verify(criterion, candidates)
            result.uncertainty = (
                "Run time budget reached; this criterion was not sent to the verifier."
            )
        else:
            result = verifier.verify(criterion, candidates)
        candidate_ids = {e.id for e in candidates}
        if any(
            e.id not in candidate_ids
            or not validate_citation(e, index["sources"], index["head_sha"])
            for e in result.evidence
        ):
            raise ValueError("Verifier produced invalid source evidence")
        results.append(result)
    return AnalysisRun(
        id=run_id,
        repository=repository,
        base_sha=index["base_sha"],
        head_sha=index["head_sha"],
        requirement=requirement,
        results=results,
        versions=versions,
        excluded=index["excluded"],
        duration_ms=int((time.perf_counter() - total_started) * 1000),
        token_usage=None if getattr(verifier, "model", None) else 0,
        cost_usd=None if getattr(verifier, "model", None) else 0,
    )
