import math

import pytest

from services.analysis.domain import Evidence
from services.analysis.evaluation import FixtureBenchmark, evaluate
from services.analysis.hybrid import HybridRetriever, VectorBundle, document_text, text_key
from services.analysis.retrieval import rank


def chunk(name, quote):
    return Evidence(
        id=name,
        revision="a" * 40,
        path=f"{name}.ts",
        start_line=1,
        end_line=1,
        quote=quote,
        symbol=name,
        kind="function",
    )


@pytest.fixture
def corpus():
    query = "save customer"
    chunks = [chunk("persist", "database.insert(person)"), chunk("save", "save unrelated data")]
    vectors = {
        text_key(query): [1.0, 0.0],
        text_key(document_text(chunks[0])): [1.0, 0.0],
        text_key(document_text(chunks[1])): [0.0, 1.0],
    }
    bundle = VectorBundle(
        model="synthetic-test-vectors", revision="1", dimensions=2, vectors=vectors
    )
    return query, chunks, HybridRetriever(bundle)


def test_dense_recovers_vocabulary_mismatch_and_fusion_preserves_citations(corpus):
    query, chunks, retriever = corpus
    assert rank(query, chunks)[0].id == "save"
    assert retriever.dense(query, chunks)[0].id == "persist"
    fused = retriever.rank(query, chunks)
    assert {c.id for c in fused} == {"save", "persist"}
    for result in fused:
        original = next(c for c in chunks if c.id == result.id)
        assert result.quote == original.quote and result.revision == original.revision
        assert result.score == pytest.approx(sum(result.score_breakdown.values()))
    assert all(c.score == 0 for c in chunks)
    assert retriever.rank(query, list(reversed(chunks))) == fused


@pytest.mark.parametrize("vector", [[0, 0], [1], [math.nan, 0], [math.inf, 0]])
def test_invalid_vectors_are_rejected(vector):
    with pytest.raises(ValueError):
        VectorBundle(model="test", revision="1", dimensions=2, vectors={text_key("x"): vector})


def test_missing_or_stale_vectors_fail_explicitly(corpus):
    query, chunks, retriever = corpus
    chunks[0] = chunks[0].model_copy(update={"quote": "changed source"})
    with pytest.raises(ValueError, match="missing an exact"):
        retriever.rank(query, chunks)
    assert retriever.rank(query, []) == []


def test_bounds_duplicates_and_nonpositive_similarity(corpus):
    query, chunks, retriever = corpus
    with pytest.raises(ValueError):
        retriever.rank(query, chunks, 51)
    with pytest.raises(ValueError, match="Duplicate"):
        retriever.dense(query, [chunks[0], chunks[0]])
    assert retriever.dense(query, [chunks[1]]) == []
    with pytest.raises(ValueError):
        HybridRetriever(retriever.bundle, rrf_k=0)


def test_benchmark_compares_all_rankers_with_model_provenance():
    benchmark = FixtureBenchmark(
        version="test",
        license="MIT",
        origin="synthetic",
        annotation_status="not_human_adjudicated",
        cases=[
            {
                "id": "one",
                "group": "one",
                "split": "development",
                "query": "save customer",
                "files": {"a.ts": "export function persist() { return 1; }"},
                "relevant_symbols": ["persist"],
            }
        ],
    )
    inputs = {}
    baseline = evaluate(benchmark, embedding_inputs=inputs)
    bundle = VectorBundle(
        model="synthetic-test-vectors",
        revision="1",
        dimensions=2,
        vectors={key: [1, 0] for key in inputs},
    )
    report = evaluate(benchmark, hybrid=HybridRetriever(bundle))
    scores = report["aggregates"]["development"]
    assert scores["bm25_with_boosts"] == baseline["aggregates"]["development"]["bm25_with_boosts"]
    assert scores["dense"]["recall"] == 1 and scores["hybrid_rrf"]["recall"] == 1
    assert report["embedding_experiment"]["model"] == "synthetic-test-vectors"
    assert len(report["embedding_experiment"]["bundle_sha256"]) == 64
    assert all(text_key(text) == key for key, text in inputs.items())
