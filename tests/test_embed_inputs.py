import json
import sys

import pytest

from scripts.embed_inputs import main
from services.analysis.embedding_artifacts import read_json
from services.analysis.embeddings import generate_bundle
from services.analysis.evaluation import FixtureBenchmark, evaluate
from services.analysis.hybrid import HybridRetriever, VectorBundle
from tests.test_embeddings import FakeEncoder, inputs


def test_cli_bundle_cache_and_report_work_end_to_end(tmp_path, monkeypatch, capsys):
    source, output, cache, report = [
        tmp_path / name for name in ("inputs.json", "vectors.json", "cache.json", "report.json")
    ]
    source.write_text(json.dumps(inputs("private requirement")), encoding="utf-8")
    monkeypatch.setattr("scripts.embed_inputs.LocalSentenceEncoder", lambda *_: FakeEncoder())
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "embed_inputs",
            str(source),
            "--model-dir",
            str(tmp_path / "model"),
            "--model",
            "fixture",
            "--output",
            str(output),
            "--cache",
            str(cache),
            "--report",
            str(report),
        ],
    )
    main()
    bundle = VectorBundle.model_validate(read_json(output))
    assert HybridRetriever(bundle).bundle == bundle
    assert read_json(report)["encoded"] == 1
    assert "private requirement" not in capsys.readouterr().out
    original = output.read_bytes()
    with pytest.raises(SystemExit):
        main()
    assert output.read_bytes() == original


def test_cli_rejects_path_collisions_before_loading_model(tmp_path, monkeypatch):
    source = tmp_path / "inputs.json"
    source.write_text(json.dumps(inputs("private source")))
    original = source.read_bytes()
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "embed_inputs",
            str(source),
            "--model-dir",
            str(tmp_path),
            "--model",
            "fixture",
            "--output",
            str(source),
        ],
    )
    with pytest.raises(SystemExit) as error:
        main()
    assert error.value.code == 2 and source.read_bytes() == original


def test_generated_vectors_feed_the_benchmark_comparison(tmp_path):
    benchmark = FixtureBenchmark.model_validate(
        {
            "version": "smoke",
            "license": "MIT",
            "origin": "synthetic",
            "annotation_status": "not_human_adjudicated",
            "cases": [
                {
                    "id": "one",
                    "group": "repo",
                    "split": "development",
                    "query": "persist receipt",
                    "files": {"receipt.ts": "export function persist() { return true; }"},
                    "relevant_symbols": ["persist"],
                }
            ],
        }
    )
    texts = {}
    evaluate(benchmark, embedding_inputs=texts)
    bundle, stats = generate_bundle(texts, FakeEncoder(), cache_path=tmp_path / "cache.json")
    report = evaluate(benchmark, hybrid=HybridRetriever(bundle))
    assert report["aggregates"]["development"]["hybrid_rrf"]["recall"] == 1
    assert report["embedding_experiment"]["model"] == "synthetic-encoder"
    assert stats["encoded"] == len(texts)
