import copy
import json
import sys

import pytest

from scripts.compare_reviews import main
from services.analysis.domain import Verdict
from services.analysis.review_agreement import (
    Adjudication,
    adjudicate,
    compare_reviews,
    decision_template,
)
from services.analysis.verdict_evaluation import VerdictBenchmark, evaluate_verdicts


@pytest.fixture
def reviews():
    run = {
        "id": "r",
        "repository": "repo",
        "base_sha": "a" * 40,
        "head_sha": "b" * 40,
        "requirement": "private requirement",
        "duration_ms": 1,
        "versions": {},
        "results": [],
    }
    labels = []
    for i, expected in enumerate(["satisfied", "not_satisfied", "satisfied", "not_satisfied"]):
        run["results"].append(
            {
                "criterion": {"id": str(i), "text": "Save receipt", "source_text": "Save receipt"},
                "verdict": "not_verifiable",
                "rationale": "unknown",
                "uncertainty": "unknown",
                "evidence": [
                    {
                        "id": "e",
                        "revision": "b" * 40,
                        "path": "a.ts",
                        "start_line": 1,
                        "end_line": 1,
                        "quote": "save();",
                        "symbol": "save",
                        "kind": "function",
                    }
                ],
            }
        )
        labels.append(
            {
                "run_id": "r",
                "criterion_id": str(i),
                "group": "repo",
                "split": "test",
                "expected": expected,
                "reviewer": "alice",
                "source": "fixture",
                "license": "MIT",
                "citation_correctness": {"e": True},
            }
        )
    left = {"version": "1", "annotation_status": "synthetic", "runs": [run], "labels": labels}
    right = copy.deepcopy(left)
    for label, expected in zip(
        right["labels"], ["satisfied", "satisfied", "not_satisfied", "not_satisfied"]
    ):
        label.update(reviewer="bob", expected=expected)
    right["labels"][0]["citation_correctness"] = {"e": False}
    right["labels"][1]["citation_correctness"] = {}
    return VerdictBenchmark.model_validate(left), VerdictBenchmark.model_validate(right)


def test_agreement_matches_hand_calculation_without_source_disclosure(reviews):
    report = compare_reviews(*reviews)
    summary = report["splits"]["test"]
    assert summary["verdict_agreement"] == 0.5
    assert summary["cohens_kappa"] == 0
    assert summary["jointly_judged_citations"] == 3
    assert summary["citation_agreement"] == pytest.approx(2 / 3)
    assert summary["citations_judged_by_one_reviewer"] == 1
    assert len(report["disagreements"]) == 3
    assert "private requirement" not in json.dumps(report)
    assert "alice" not in json.dumps(report)
    assert compare_reviews(*reviews) == report


@pytest.mark.parametrize(
    "field,value",
    [("reviewer", " ALICE "), ("group", "other"), ("source", "other"), ("license", "other")],
)
def test_mismatched_provenance_or_reviewer_is_rejected(reviews, field, value):
    left, right = reviews
    for label in right.labels:
        setattr(label, field, value)
    with pytest.raises(ValueError):
        compare_reviews(left, right)


def test_changed_runs_are_rejected(reviews):
    left, right = reviews
    right.runs[0].results[0].evidence[0].quote = "evil();"
    with pytest.raises(ValueError, match="same saved runs"):
        compare_reviews(left, right)


def test_single_class_kappa_is_undefined(reviews):
    for benchmark in reviews:
        for label in benchmark.labels:
            label.expected = Verdict.SATISFIED
    summary = compare_reviews(*reviews)["splits"]["test"]
    assert summary["verdict_agreement"] == 1
    assert summary["cohens_kappa"] is None


def resolved(reviews):
    draft = decision_template(*reviews)
    assert all(d["expected"] is None and d["reviewer"] is None for d in draft["decisions"])
    with pytest.raises(ValueError):
        Adjudication.model_validate(draft)
    draft["annotation_status"] = "synthetic"
    for decision in draft["decisions"]:
        decision.update(expected="not_verifiable", reviewer="adjudicator")
    return draft


def test_explicit_adjudication_produces_evaluable_labels(reviews):
    resolution = Adjudication.model_validate(resolved(reviews))
    result = adjudicate(*reviews, resolution)
    assert evaluate_verdicts(result)["splits"]["test"]["accuracy"] == 1
    assert all(label.reviewer == "adjudicator" for label in result.labels)
    assert reviews[0].labels[0].expected == "satisfied"


@pytest.mark.parametrize("problem", ["stale", "missing", "duplicate", "synthetic", "provenance"])
def test_invalid_adjudication_is_rejected(reviews, problem):
    draft = resolved(reviews)
    if problem == "stale":
        draft["left_sha256"] = "0" * 64
    elif problem == "missing":
        draft["decisions"].pop()
    elif problem == "duplicate":
        draft["decisions"].append(draft["decisions"][0])
    elif problem == "synthetic":
        draft["annotation_status"] = "human_adjudicated"
    else:
        draft["decisions"][0]["source"] = "changed"
    with pytest.raises(ValueError):
        adjudicate(*reviews, Adjudication.model_validate(draft))


def test_cli_comparison_and_completed_decisions(reviews, tmp_path, monkeypatch):
    left, right, decisions = [tmp_path / name for name in ("a.json", "b.json", "decisions.json")]
    for path, benchmark in zip((left, right), reviews):
        path.write_text(benchmark.model_dump_json(), encoding="utf-8")
    # Fingerprints bind the serialized review artifacts actually supplied to the CLI.
    saved = [VerdictBenchmark.model_validate_json(path.read_text()) for path in (left, right)]
    decisions.write_text(json.dumps(resolved(saved)), encoding="utf-8")
    for args, filename in [
        ([], "report.json"),
        (["--template"], "draft.json"),
        (["--decisions", str(decisions)], "final.json"),
    ]:
        output = tmp_path / filename
        monkeypatch.setattr(
            sys, "argv", ["compare_reviews", str(left), str(right), "--output", str(output), *args]
        )
        main()
        assert output.is_file()
        with pytest.raises(SystemExit):
            main()
    VerdictBenchmark.model_validate_json((tmp_path / "final.json").read_text())
