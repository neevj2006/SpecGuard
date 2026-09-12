"""Exact embedding inputs and provenance for opt-in hybrid analysis."""

import hashlib
import json
from pathlib import Path

from services.analysis.decompose import decompose
from services.analysis.domain import Criterion
from services.analysis.embedding_artifacts import read_json, validate_inputs
from services.analysis.hybrid import HybridRetriever, VectorBundle, document_text, text_key


def review_criteria(requirement: str, criteria: list[Criterion] | None) -> list[Criterion]:
    selected = criteria if criteria is not None else decompose(requirement)
    if not 1 <= len(selected) <= 50 or len({item.id for item in selected}) != len(selected):
        raise ValueError("Supply 1-50 uniquely identified criteria")
    return selected


def export_texts(index: dict, criteria: list[Criterion]) -> dict[str, str]:
    texts = [item.text for item in criteria]
    texts.extend(document_text(chunk) for chunk in index["chunks"])
    return validate_inputs({text_key(text): text for text in texts})


def load_hybrid(path: Path, *, window: int = 50, rrf_k: int = 60) -> HybridRetriever:
    try:
        return HybridRetriever(
            VectorBundle.model_validate(read_json(path)), window=window, rrf_k=rrf_k
        )
    except (ValueError, TypeError, OSError) as error:
        raise ValueError(
            "Unable to load hybrid vectors; check the bundle and fusion options"
        ) from error


def prepare_hybrid(
    hybrid: HybridRetriever, index: dict, criteria: list[Criterion]
) -> tuple[HybridRetriever, dict[str, str]]:
    # Isolate the run from subsequent edits to the caller's bundle or configuration.
    snapshot = HybridRetriever(
        VectorBundle.model_validate(hybrid.bundle.model_dump()),
        window=hybrid.window,
        rrf_k=hybrid.rrf_k,
    )
    if snapshot.window < 6:
        raise ValueError("Hybrid analysis requires a fusion window of at least six")
    for text in export_texts(index, criteria).values():
        snapshot.bundle.unit_vector(text)
    digest = hashlib.sha256(
        json.dumps(snapshot.bundle.model_dump(), sort_keys=True).encode()
    ).hexdigest()
    return snapshot, {
        "retriever": snapshot.version,
        "embedding_model": snapshot.bundle.model,
        "embedding_revision": snapshot.bundle.revision,
        "embedding_dimensions": str(snapshot.bundle.dimensions),
        "embedding_bundle_sha256": digest,
        "retrieval_window": str(snapshot.window),
        "retrieval_rrf_k": str(snapshot.rrf_k),
    }
