from pathlib import Path

import pytest
from pydantic import ValidationError

from services.analysis.evaluation import FixtureBenchmark, evaluate


def test_fixture_manifest_is_consistent_and_ranking_is_reproducible():
    benchmark = FixtureBenchmark.model_validate_json(
        Path("tests/fixtures/retrieval-benchmark.json").read_text()
    )
    result = evaluate(benchmark)
    assert len(result["cases"]) == 10
    assert result["annotation_status"] == "not_human_adjudicated"
    for metrics in result["aggregates"].values():
        assert metrics["bm25_with_boosts"]["recall"] >= 0.8


def test_split_leakage_is_rejected():
    data = FixtureBenchmark.model_validate_json(
        Path("tests/fixtures/retrieval-benchmark.json").read_text()
    ).model_dump()
    data["cases"][0]["group"] = data["cases"][-1]["group"]
    with pytest.raises(ValidationError, match="cannot cross"):
        FixtureBenchmark.model_validate(data)
