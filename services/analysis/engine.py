import time
from collections.abc import Callable
from pathlib import Path

from services.analysis.analysis_retrieval import prepare_hybrid, review_criteria
from services.analysis.domain import AnalysisRun, Criterion, stable_id
from services.analysis.graph import neighbors
from services.analysis.hybrid import HybridRetriever
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
    *,
    hybrid: HybridRetriever | None = None,
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
        hybrid=hybrid,
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
    hybrid: HybridRetriever | None = None,
) -> AnalysisRun:
    started = time.perf_counter()
    total_started = started if started_at is None else started_at
    criteria = review_criteria(requirement, criteria)
    verifier = verifier or BaselineVerifier()
    versions = {
        "parser": index["parser_version"],
        "index": "3",
        "retriever": "bm25/2",
        "verifier": verifier.version,
        "prompt": "1",
        "model": getattr(verifier, "model", "none"),
    }
    if hybrid is not None:
        hybrid, retrieval_versions = prepare_hybrid(hybrid, index, criteria)
        versions.update(retrieval_versions)
    identity = f"{identity_scope}:{index['base_sha']}:{index['head_sha']}:{requirement}:{[c.model_dump() for c in criteria]}:{versions}"
    run_id = stable_id(identity)
    if lookup:
        try:
            return lookup(run_id)
        except KeyError:
            pass
    results = []
    neighbor_paths = neighbors(
        index.get("imports", []), {chunk.path for chunk in index["chunks"] if chunk.changed}
    )
    for criterion in criteria:
        retrieve = hybrid.rank if hybrid is not None else rank
        candidates = retrieve(criterion.text, index["chunks"], neighbor_paths=neighbor_paths)
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
        token_usage=getattr(verifier, "token_usage", None)
        if getattr(verifier, "model", None)
        else 0,
        cost_usd=None if getattr(verifier, "model", None) else 0,
    )
