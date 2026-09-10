import json

import pytest

from services.analysis.verdict_evaluation import VerdictBenchmark, evaluate_verdicts


@pytest.fixture
def manifest():
    predicted = ["satisfied", "partially_satisfied", "not_verifiable", "not_satisfied"]
    expected = ["satisfied", "satisfied", "partially_satisfied", "not_verifiable"]
    results, labels = [], []
    for i, verdict in enumerate(predicted):
        evidence = (
            []
            if i == 2
            else [
                {
                    "id": f"e{i}",
                    "revision": "a" * 40,
                    "path": "a.ts",
                    "start_line": 1,
                    "end_line": 1,
                    "quote": "return true;",
                    "symbol": "save",
                    "kind": "function",
                }
            ]
        )
        results.append(
            {
                "criterion": {"id": str(i), "text": "Save receipt", "source_text": "Save receipt"},
                "verdict": verdict,
                "rationale": "Synthetic test",
                "evidence": evidence,
                "uncertainty": "Synthetic uncertainty",
                "confidence": [0.9, 0.6, 0.99, None][i],
            }
        )
        labels.append(
            {
                "run_id": "run",
                "criterion_id": str(i),
                "group": "repo",
                "split": "test",
                "expected": expected[i],
                "reviewer": "synthetic-fixture",
                "source": "local fixture",
                "license": "MIT",
                "citation_correctness": {f"e{i}": i == 0} if i < 2 else {},
            }
        )
    return {
        "version": "fixture-1",
        "annotation_status": "synthetic",
        "labels": labels,
        "runs": [
            {
                "id": "run",
                "repository": "repo",
                "base_sha": "b" * 40,
                "head_sha": "a" * 40,
                "requirement": "Save receipts",
                "results": results,
                "duration_ms": 125,
                "versions": {"verifier": "synthetic"},
                "token_usage": None,
                "cost_usd": None,
            }
        ],
    }


def test_metrics_match_hand_calculated_values(manifest):
    report = evaluate_verdicts(VerdictBenchmark.model_validate(manifest))
    values = report["splits"]["test"]
    assert values["accuracy"] == 0.25
    assert values["macro_f1"] == pytest.approx(1 / 6)
    assert values["per_class"]["satisfied"]["recall"] == 0.5
    assert values["answer_coverage"] == 0.75
    assert values["answer_risk"] == pytest.approx(2 / 3)
    assert values["citation_correctness"] == 0.5
    assert values["citation_judgment_coverage"] == pytest.approx(2 / 3)
    assert values["missing_answer_confidence"] == 1
    assert values["coverage_risk"][0]["coverage"] == 0.5
    assert values["coverage_risk"][0]["risk"] == 0.5
    assert values["coverage_risk"][2]["risk"] == 0
    assert values["coverage_risk"][-1]["risk"] is None
    assert values["runs"] == 1 and values["total_duration_ms"] == 125
    assert values["runs_missing_token_usage"] == values["runs_missing_cost"] == 1


def test_unknown_judgments_are_not_reported_as_correct(manifest):
    for label in manifest["labels"]:
        label["citation_correctness"] = {}
    benchmark = VerdictBenchmark.model_validate(manifest)
    report = evaluate_verdicts(benchmark)
    assert report["splits"]["test"]["citation_correctness"] is None
    assert report == evaluate_verdicts(benchmark)
    assert report == evaluate_verdicts(VerdictBenchmark.model_validate(manifest))
    assert "Save receipt" not in json.dumps(report)


@pytest.mark.parametrize("problem", ["duplicate", "missing", "citation", "split", "run", "group"])
def test_invalid_label_associations_are_rejected(manifest, problem):
    if problem == "duplicate":
        manifest["labels"].append(manifest["labels"][0])
    elif problem == "missing":
        manifest["labels"].pop()
    elif problem == "citation":
        manifest["labels"][0]["citation_correctness"] = {"invented": True}
    elif problem == "split":
        manifest["labels"][0]["split"] = "development"
    elif problem == "group":
        manifest["labels"][0]["group"] = "another"
    else:
        manifest["runs"].append(manifest["runs"][0])
    with pytest.raises(ValueError):
        VerdictBenchmark.model_validate(manifest)


def test_all_abstaining_results_have_undefined_answer_risk(manifest):
    for result in manifest["runs"][0]["results"]:
        result.update(verdict="not_verifiable", evidence=[])
    for label in manifest["labels"]:
        label["citation_correctness"] = {}
    values = evaluate_verdicts(VerdictBenchmark.model_validate(manifest))["splits"]["test"]
    assert values["answer_coverage"] == 0
    assert values["answer_risk"] is None
    assert values["citation_judgment_coverage"] is None


def test_cli_generates_report_without_echoing_source(manifest, tmp_path, monkeypatch, capsys):
    import sys

    from scripts.evaluate_verdicts import main

    source, output = tmp_path / "labels.json", tmp_path / "report.json"
    source.write_text(json.dumps(manifest), encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["evaluate_verdicts", str(source), "--output", str(output)])
    main()
    assert json.loads(output.read_text())["annotation_status"] == "synthetic"
    assert "Save receipts" not in capsys.readouterr().out


def test_citation_judgments_require_actual_booleans(manifest):
    manifest["labels"][0]["citation_correctness"] = {"e0": "true"}
    with pytest.raises(ValueError):
        VerdictBenchmark.model_validate(manifest)
