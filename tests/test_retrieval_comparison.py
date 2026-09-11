import copy
import json
import sys
from pathlib import Path

import pytest

from scripts.compare_retrieval import main
from services.analysis.evaluation import FixtureBenchmark, evaluate
from services.analysis.retrieval_comparison import compare_retrieval, percentile


def case(identifier, group, left, right, split="development"):
    return {
        "id": identifier,
        "group": group,
        "split": split,
        "ablations": {
            name: dict.fromkeys(("recall", "mrr", "ndcg"), value)
            for name, value in (("baseline", left), ("candidate", right))
        },
    }


def report(*rows):
    return {
        "origin": "synthetic",
        "annotation_status": "not_human_adjudicated",
        "cases": list(rows),
    }


def compare(payload, **options):
    return compare_retrieval(payload, "baseline", "candidate", samples=100, **options)


def test_paired_constant_improvement_has_exact_interval_and_split_isolation():
    payload = report(
        case("a", "one", 0, 0.5), case("b", "two", 0.5, 1), case("c", "three", 1, 0, "test")
    )
    result = compare(payload)
    metric = result["splits"]["development"]["metrics"]["recall"]
    assert metric["delta"] == 0.5
    assert metric["interval"] == {"lower": 0.5, "upper": 0.5}
    assert metric["groups_improved"] == 2
    held_out = result["splits"]["test"]
    assert held_out["interval_status"] == "insufficient_groups"
    assert held_out["metrics"]["recall"]["interval"] is None
    assert held_out["metrics"]["recall"]["delta"] == -1


def test_groups_have_equal_weight_despite_unequal_case_counts():
    payload = report(case("a", "one", 0, 1), case("b", "one", 0, 1), case("c", "two", 1, 0))
    result = compare(payload)
    metric = result["splits"]["development"]["metrics"]["mrr"]
    assert metric["baseline"] == metric["candidate"] == 0.5
    assert metric["delta"] == 0
    assert metric["groups_improved"] == metric["groups_regressed"] == 1
    assert metric["interval"] == {"lower": -1, "upper": 1}


def test_reproducible_order_independent_and_does_not_mutate_input():
    payload = report(case("a", "one", 0, 0.5), case("b", "two", 1, 0))
    original = copy.deepcopy(payload)
    first = compare(payload, seed=7)
    assert payload == original
    payload["cases"].reverse()
    payload["cases"][0]["duration_ms"] = 123
    payload["cases"][0]["ablations"]["baseline"]["ranking"] = ["private source"]
    assert compare(payload, seed=7) == first
    assert "private source" not in json.dumps(first)
    payload["cases"][0]["ablations"]["baseline"]["mrr"] = 0.25
    assert compare(payload)["measurements_sha256"] != first["measurements_sha256"]


@pytest.mark.parametrize(
    "value", [None, True, -0.1, 1.1, float("nan"), float("inf"), 10**400, "0.5"]
)
def test_invalid_metrics_are_rejected(value):
    payload = report(case("a", "one", value, 1))
    with pytest.raises(ValueError, match="finite"):
        compare(payload)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda p: p["cases"].append(copy.deepcopy(p["cases"][0])),
        lambda p: p["cases"].append(case("b", "one", 0, 1, "test")),
        lambda p: p["cases"][0].pop("group"),
        lambda p: p["cases"][0]["ablations"].pop("candidate"),
        lambda p: p.update(annotation_status="human_adjudicated"),
        lambda p: p.update(cases=[]),
    ],
)
def test_incomplete_or_leaking_reports_are_rejected(mutation):
    payload = report(case("a", "one", 0, 1))
    mutation(payload)
    with pytest.raises((ValueError, TypeError)):
        compare(payload)


@pytest.mark.parametrize(
    "options",
    [
        {"samples": 99},
        {"samples": 10001},
        {"seed": -1},
        {"confidence": float("nan")},
        {"confidence": 1},
    ],
)
def test_invalid_resampling_options(options):
    with pytest.raises(ValueError):
        compare_retrieval(report(case("a", "one", 0, 1)), "baseline", "candidate", **options)


def test_percentile_interpolates_between_observations():
    assert percentile([1, -1, 0], 0.25) == -0.5
    assert percentile([1, -1, 0], 0.75) == 0.5


def test_cli_consumes_evaluator_report_and_preserves_existing_files(tmp_path, monkeypatch, capsys):
    benchmark = FixtureBenchmark.model_validate_json(
        Path("tests/fixtures/retrieval-benchmark.json").read_text()
    )
    source, output = tmp_path / "evaluation.json", tmp_path / "comparison.json"
    source.write_text(json.dumps(evaluate(benchmark)), encoding="utf-8")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "compare_retrieval",
            str(source),
            "--candidate",
            "with_import_neighbors",
            "--output",
            str(output),
            "--samples",
            "100",
        ],
    )
    main()
    saved = output.read_bytes()
    result = json.loads(saved)
    assert set(result["splits"]) == {"development", "test"}
    assert result["origin"] == "synthetic"
    assert json.loads(capsys.readouterr().out) == result
    with pytest.raises(SystemExit) as failure:
        main()
    assert failure.value.code == 2 and output.read_bytes() == saved
    output.unlink()
    source.write_text('{"cases": "private invalid report"}')
    with pytest.raises(SystemExit):
        main()
    assert not output.exists()
    assert "private invalid report" not in capsys.readouterr().err
