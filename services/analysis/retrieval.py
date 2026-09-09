"""Inspectable BM25 ranking with explicit change and symbol boosts."""

import math
import re
from collections import Counter

from services.analysis.domain import Evidence


def tokenize(text: str) -> list[str]:
    expanded = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", text)
    return re.findall(r"[a-z0-9]+", expanded.lower())


def rank(
    query: str, chunks: list[Evidence], limit: int = 6, *, neighbor_paths: set[str] | None = None
) -> list[Evidence]:
    if not chunks:
        return []
    documents = [Counter(tokenize(f"{c.path} {c.symbol} {c.quote}")) for c in chunks]
    terms = set(tokenize(query))
    frequencies = Counter(term for document in documents for term in document)
    mean_length = sum(sum(d.values()) for d in documents) / len(documents)
    scored = []
    for chunk, document in zip(chunks, documents, strict=True):
        score = 0.0
        for term in terms:
            frequency = document[term]
            count = frequencies[term]
            idf = math.log(1 + (len(documents) - count + 0.5) / (count + 0.5))
            score += (
                idf
                * frequency
                * 2.2
                / (frequency + 1.2 * (0.25 + 0.75 * sum(document.values()) / mean_length))
            )
        if score:
            breakdown = {
                "bm25": score,
                "changed": score * 0.2 if chunk.changed else 0,
                "symbol": 0.2 * len(terms.intersection(tokenize(chunk.symbol))),
                "import_neighbor": score * 0.15 if chunk.path in (neighbor_paths or set()) else 0,
            }
            scored.append(
                chunk.model_copy(
                    update={
                        "score": round(sum(breakdown.values()), 5),
                        "score_breakdown": breakdown,
                    }
                )
            )
    return sorted(scored, key=lambda c: (-c.score, c.path, c.start_line))[:limit]


def ranking_metrics(expected: set[str], retrieved: list[str], k: int) -> dict[str, float]:
    if not expected or k < 1:
        raise ValueError("Evaluation needs relevance labels and positive K")
    ranking = list(dict.fromkeys(retrieved))[:k]
    hits = [int(item in expected) for item in ranking]
    dcg = sum(hit / math.log2(i + 2) for i, hit in enumerate(hits))
    ideal = sum(1 / math.log2(i + 2) for i in range(min(k, len(expected))))
    return {
        "recall": sum(hits) / len(expected),
        "mrr": next((1 / (i + 1) for i, hit in enumerate(hits) if hit), 0),
        "ndcg": dcg / ideal,
    }
