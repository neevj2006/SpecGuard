import copy

import pytest

from services.analysis.analysis_retrieval import export_texts, load_hybrid, review_criteria
from services.analysis.decompose import decompose
from services.analysis.domain import AnalysisRun, Evidence, Verdict
from services.analysis.embedding_artifacts import write_json
from services.analysis.engine import analyze_index
from services.analysis.hybrid import HybridRetriever, VectorBundle, document_text, text_key
from services.analysis.verifier import BaselineVerifier


@pytest.fixture
def context():
    source = "export function persist() { return true; }"
    chunk = Evidence(
        id="persist",
        revision="a" * 40,
        path="store.ts",
        start_line=1,
        end_line=1,
        quote=source,
        symbol="persist",
        kind="function",
        changed=True,
    )
    index = {
        "base_sha": "b" * 40,
        "head_sha": "a" * 40,
        "parser_version": "fixture",
        "chunks": [chunk],
        "sources": {"store.ts": source},
        "imports": [],
        "excluded": [],
    }
    criteria = decompose("- Archive the receipt\n- Preserve the receipt")
    bundle = VectorBundle(
        model="synthetic",
        revision="fixture",
        dimensions=2,
        vectors={key: [1, 0] for key in export_texts(index, criteria)},
    )
    return index, criteria, HybridRetriever(bundle)


def run(context, **kwargs):
    index, criteria, hybrid = context
    return analyze_index(
        index, "fixture", "owner/repo", "Receipt storage", criteria, hybrid=hybrid, **kwargs
    )


def test_hybrid_brings_dense_evidence_into_normal_analysis(context):
    index, criteria, _ = context
    sparse = analyze_index(index, "fixture", "owner/repo", "Receipt storage", criteria)
    result = run(context)
    assert sparse.results[0].evidence == []
    assert result.results[0].evidence[0].id == "persist"
    assert result.results[0].evidence[0].score_breakdown == {"dense_rrf": 1 / 61}
    assert all(
        item.verdict == Verdict.UNKNOWN and item.tests.status == "not_run"
        for item in result.results
    )
    assert result.versions["retriever"] == "hybrid-rrf/1"
    assert result.versions["embedding_model"] == "synthetic"
    assert result.versions["embedding_dimensions"] == "2"
    assert len(result.versions["embedding_bundle_sha256"]) == 64
    assert result.id != sparse.id
    assert AnalysisRun.model_validate_json(result.model_dump_json()) == result


@pytest.mark.parametrize("change", ["model", "revision", "vectors", "window", "rrf_k"])
def test_retrieval_identity_changes_run_cache_key(context, change):
    first = run(context)
    hybrid = context[2]
    if change in ("model", "revision"):
        setattr(hybrid.bundle, change, "different")
    elif change == "vectors":
        hybrid.bundle.vectors[next(iter(hybrid.bundle.vectors))] = [0.5, 0.5]
    else:
        setattr(hybrid, change, 70)
    assert run(context).id != first.id


def test_identical_hybrid_run_uses_existing_cache(context):
    first = run(context)

    class NoCalls(BaselineVerifier):
        def verify(self, *args):
            pytest.fail("Cached run invoked verifier")

    def lookup(identifier):
        assert identifier == first.id
        return first

    assert run(context, verifier=NoCalls(), lookup=lookup) is first


@pytest.mark.parametrize("missing", ["query", "document"])
def test_missing_vectors_fail_before_lookup_or_model_call(context, missing):
    index, criteria, hybrid = context
    text = criteria[-1].text if missing == "query" else document_text(index["chunks"][0])
    del hybrid.bundle.vectors[text_key(text)]

    class NoCalls(BaselineVerifier):
        def verify(self, *args):
            pytest.fail("Incomplete bundle reached verifier")

    with pytest.raises(ValueError, match="missing"):
        run(context, verifier=NoCalls(), lookup=lambda _: pytest.fail("Reached cache"))


def test_current_source_text_is_required_even_with_same_evidence_identifier(context):
    index, _, _ = context
    index["chunks"][0].quote = "export function persist() { return false; }"
    index["sources"]["store.ts"] = index["chunks"][0].quote
    with pytest.raises(ValueError, match="missing"):
        run(context)


def test_run_snapshots_vectors_before_verification(context):
    class MutatingVerifier(BaselineVerifier):
        def verify(self, criterion, evidence):
            context[2].bundle.vectors.clear()
            context[2].window = 1
            return super().verify(criterion, evidence)

    result = run(context, verifier=MutatingVerifier())
    assert all(item.evidence for item in result.results)
    assert result.versions["retrieval_window"] == "50"


def test_hybrid_cannot_bypass_citation_validation(context):
    class TamperingVerifier(BaselineVerifier):
        def verify(self, criterion, evidence):
            result = super().verify(criterion, evidence)
            result.evidence[0] = result.evidence[0].model_copy(update={"quote": "invented"})
            return result

    with pytest.raises(ValueError, match="invalid source"):
        run(context, verifier=TamperingVerifier())


def test_invalid_window_fails_before_verification(context):
    context[2].window = 5
    with pytest.raises(ValueError, match="at least six"):
        run(context)


def test_empty_head_index_is_an_abstention(context):
    context[0]["chunks"] = []
    result = run(context)
    assert all(not item.evidence and item.verdict == Verdict.UNKNOWN for item in result.results)


def test_input_export_is_exact_and_criteria_validation_matches_analysis(context):
    index, criteria, _ = context
    original = copy.deepcopy(index)
    texts = export_texts(index, criteria)
    assert set(texts.values()) == {
        criteria[0].text,
        criteria[1].text,
        document_text(index["chunks"][0]),
    }
    assert index == original
    assert review_criteria("- Archive the receipt\n- Preserve the receipt", None) == criteria
    for invalid in ([], [criteria[0], criteria[0]]):
        with pytest.raises(ValueError, match="uniquely"):
            review_criteria("ignored", invalid)


def test_vector_loading_uses_strict_json_and_generic_errors(context, tmp_path):
    path = tmp_path / "vectors.json"
    write_json(path, context[2].bundle.model_dump())
    assert load_hybrid(path).bundle == context[2].bundle
    path.write_text('{"private-value":1,"private-value":2}')
    with pytest.raises(ValueError, match="Unable to load") as failure:
        load_hybrid(path)
    assert "private-value" not in str(failure.value)


def test_source_owner_still_separates_identical_hybrid_runs(context):
    index, criteria, hybrid = context
    first = run(context)
    other = analyze_index(
        index, "fixture", "other-owner/repo", "Receipt storage", criteria, hybrid=hybrid
    )
    assert first.id != other.id
