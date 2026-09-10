"""Offline, content-addressed embedding experiments with reciprocal-rank fusion."""

import hashlib
import math

from pydantic import Field, model_validator

from services.analysis.domain import Contract, Evidence
from services.analysis.retrieval import rank


def text_key(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def document_text(chunk: Evidence) -> str:
    return f"{chunk.path}\n{chunk.symbol}\n{chunk.quote}"


class VectorBundle(Contract):
    model: str = Field(min_length=1, max_length=200)
    revision: str = Field(min_length=1, max_length=200)
    dimensions: int = Field(ge=1, le=4096)
    vectors: dict[str, list[float]] = Field(min_length=1, max_length=20000)

    @model_validator(mode="after")
    def valid_vectors(self):
        for key, vector in self.vectors.items():
            if len(key) != 64 or any(c not in "0123456789abcdef" for c in key):
                raise ValueError("Vector keys must be SHA-256 text hashes")
            if len(vector) != self.dimensions or not all(math.isfinite(v) for v in vector):
                raise ValueError("Vectors must have consistent dimensions and finite values")
            norm = math.hypot(*vector)
            if not norm or not math.isfinite(norm):
                raise ValueError("Vectors must have a finite nonzero norm")
        return self

    def unit_vector(self, text: str) -> list[float]:
        vector = self.vectors.get(text_key(text))
        if vector is None:
            raise ValueError("Embedding bundle is missing an exact input text hash")
        norm = math.hypot(*vector)
        return [v / norm for v in vector]


class HybridRetriever:
    version = "hybrid-rrf/1"

    def __init__(self, bundle: VectorBundle, *, window: int = 50, rrf_k: int = 60):
        if not 1 <= window <= 1000 or not 1 <= rrf_k <= 1000:
            raise ValueError("Fusion window and rank constant must be between 1 and 1000")
        self.bundle = bundle
        self.window = window
        self.rrf_k = rrf_k

    def dense(self, query: str, chunks: list[Evidence], limit: int = 6) -> list[Evidence]:
        if limit < 1:
            raise ValueError("Retrieval limit must be positive")
        if len({c.id for c in chunks}) != len(chunks):
            raise ValueError("Duplicate evidence identifiers")
        if not chunks:
            return []
        query_vector = self.bundle.unit_vector(query)
        scored = []
        for chunk in chunks:
            vector = self.bundle.unit_vector(document_text(chunk))
            cosine = max(-1.0, min(1.0, math.fsum(a * b for a, b in zip(query_vector, vector))))
            if cosine > 0:
                scored.append(
                    chunk.model_copy(
                        update={
                            "score": cosine,
                            "score_breakdown": {"cosine": cosine},
                        }
                    )
                )
        return sorted(scored, key=lambda c: (-c.score, c.path, c.start_line, c.id))[:limit]

    def rank(
        self,
        query: str,
        chunks: list[Evidence],
        limit: int = 6,
        *,
        neighbor_paths: set[str] | None = None,
    ) -> list[Evidence]:
        if not 1 <= limit <= self.window:
            raise ValueError("Retrieval limit must fit the fusion window")
        rankings = {
            "sparse_rrf": rank(query, chunks, self.window, neighbor_paths=neighbor_paths),
            "dense_rrf": self.dense(query, chunks, self.window),
        }
        by_id = {c.id: c for c in chunks}
        scores: dict[str, dict[str, float]] = {}
        for name, ranking in rankings.items():
            for position, chunk in enumerate(ranking, 1):
                scores.setdefault(chunk.id, {})[name] = 1 / (self.rrf_k + position)
        fused = [
            by_id[key].model_copy(
                update={
                    "score": sum(parts.values()),
                    "score_breakdown": parts,
                }
            )
            for key, parts in scores.items()
        ]
        return sorted(fused, key=lambda c: (-c.score, c.path, c.start_line, c.id))[:limit]
