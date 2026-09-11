"""Reproducible synthetic retrieval regression measurements."""

import hashlib
import json
import time
from statistics import mean

from pydantic import Field, model_validator

from services.analysis.domain import Contract
from services.analysis.graph import neighbors
from services.analysis.hybrid import HybridRetriever, document_text, text_key
from services.analysis.repository import parse_sources
from services.analysis.retrieval import rank, ranking_metrics


class RetrievalCase(Contract):
    id: str
    group: str
    split: str = Field(pattern="^(development|test)$")
    query: str = Field(min_length=1, max_length=4000)
    files: dict[str, str]
    relevant_symbols: list[str] = Field(min_length=1)
    changed_paths: list[str] = Field(default_factory=list)


class FixtureBenchmark(Contract):
    version: str
    license: str = Field(pattern="^MIT$")
    origin: str = Field(pattern="^synthetic$")
    annotation_status: str = Field(pattern="^not_human_adjudicated$")
    cases: list[RetrievalCase] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def independent_groups(self):
        if len({case.id for case in self.cases}) != len(self.cases):
            raise ValueError("Duplicate case identifiers")
        groups: dict[str, str] = {}
        for case in self.cases:
            if case.group in groups and groups[case.group] != case.split:
                raise ValueError("A repository group cannot cross development and test splits")
            groups[case.group] = case.split
            if (
                len(case.files) > 50
                or sum(len(text.encode()) for text in case.files.values()) > 500_000
            ):
                raise ValueError("Fixture exceeds source budget")
        return self


def evaluate(
    benchmark: FixtureBenchmark,
    k: int = 3,
    *,
    hybrid: HybridRetriever | None = None,
    embedding_inputs: dict[str, str] | None = None,
) -> dict:
    if not 1 <= k <= 100:
        raise ValueError("K must be between 1 and 100")
    rows: list[dict] = []
    for case in benchmark.cases:
        started = time.perf_counter()
        revision = hashlib.sha256(json.dumps(case.files, sort_keys=True).encode()).hexdigest()
        index = parse_sources(
            [{"path": path, "source": source} for path, source in case.files.items()],
            revision,
            revision,
            set(case.changed_paths),
            [],
        )
        relevant = {chunk.id for chunk in index["chunks"] if chunk.symbol in case.relevant_symbols}
        if embedding_inputs is not None:
            for text in [case.query, *[document_text(c) for c in index["chunks"]]]:
                embedding_inputs[text_key(text)] = text
        found = {chunk.symbol for chunk in index["chunks"]}
        if not set(case.relevant_symbols) <= found:
            raise ValueError(f"Case {case.id} labels missing symbols")
        adjacent = neighbors(index["imports"], set(case.changed_paths))
        ablations = {}
        rankings = {
            "bm25_with_boosts": rank(case.query, index["chunks"], k),
            "with_import_neighbors": rank(case.query, index["chunks"], k, neighbor_paths=adjacent),
        }
        if hybrid:
            rankings["dense"] = hybrid.dense(case.query, index["chunks"], k)
            rankings["hybrid_rrf"] = hybrid.rank(
                case.query, index["chunks"], k, neighbor_paths=adjacent
            )
        for name, retrieved in rankings.items():
            ablations[name] = {
                **ranking_metrics(relevant, [chunk.id for chunk in retrieved], k),
                "ranking": [
                    {
                        "symbol": chunk.symbol,
                        "path": chunk.path,
                        "score": chunk.score,
                        "breakdown": chunk.score_breakdown,
                    }
                    for chunk in retrieved
                ],
            }
        rows.append(
            {
                "id": case.id,
                "group": case.group,
                "split": case.split,
                "ablations": ablations,
                "duration_ms": round((time.perf_counter() - started) * 1000),
            }
        )
    aggregates = {}
    for split in sorted({row["split"] for row in rows}):
        aggregates[split] = {
            name: {
                metric: mean(
                    row["ablations"][name][metric] for row in rows if row["split"] == split
                )
                for metric in ("recall", "mrr", "ndcg")
            }
            for name in rows[0]["ablations"]
        }
    return {
        "benchmark_version": benchmark.version,
        "retriever": "bm25/2",
        "embedding_experiment": {
            "version": hybrid.version,
            "model": hybrid.bundle.model,
            "revision": hybrid.bundle.revision,
            "dimensions": hybrid.bundle.dimensions,
            "window": hybrid.window,
            "rrf_k": hybrid.rrf_k,
            "bundle_sha256": hashlib.sha256(
                json.dumps(hybrid.bundle.model_dump(), sort_keys=True).encode()
            ).hexdigest(),
        }
        if hybrid
        else None,
        "k": k,
        "origin": benchmark.origin,
        "annotation_status": benchmark.annotation_status,
        "limitation": "Synthetic retrieval regression fixtures; no real-repository quality, semantic verdict accuracy, or human agreement claim.",
        "aggregates": aggregates,
        "cases": rows,
    }
