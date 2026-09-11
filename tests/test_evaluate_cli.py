import sys
from pathlib import Path

import pytest

from scripts.evaluate import main, validate_paths
from services.analysis.embedding_artifacts import read_json, write_json
from services.analysis.embeddings import generate_bundle
from tests.test_embeddings import FakeEncoder


@pytest.fixture
def manifest(tmp_path):
    path = tmp_path / "manifest.json"
    path.write_bytes(Path("tests/fixtures/retrieval-benchmark.json").read_bytes())
    return path


def invoke(monkeypatch, manifest, output, *options):
    monkeypatch.setattr(
        sys, "argv", ["evaluate", "--manifest", str(manifest), "--output", str(output), *options]
    )
    main()


def test_export_encode_and_hybrid_evaluate(tmp_path, manifest, monkeypatch, capsys):
    exported, sparse, dense = [
        tmp_path / name for name in ("inputs.json", "sparse.json", "dense.json")
    ]
    invoke(monkeypatch, manifest, sparse, "--export-inputs", str(exported))
    texts = read_json(exported)
    bundle, _ = generate_bundle(texts, FakeEncoder())
    vectors = tmp_path / "vectors.json"
    write_json(vectors, bundle.model_dump())
    invoke(monkeypatch, manifest, dense, "--embeddings", str(vectors))
    report = read_json(dense)
    assert len(report["cases"]) == 10
    assert report["embedding_experiment"]["model"] == "synthetic-encoder"
    assert "hybrid_rrf" in report["aggregates"]["test"]
    assert "ranking" not in capsys.readouterr().out
    original = dense.read_bytes()
    with pytest.raises(SystemExit) as failure:
        invoke(monkeypatch, manifest, dense)
    assert failure.value.code == 2 and dense.read_bytes() == original


@pytest.mark.parametrize("target", ["manifest", "export", "existing"])
def test_collisions_fail_before_evaluation(tmp_path, manifest, monkeypatch, target):
    output, exported = tmp_path / "report.json", tmp_path / "inputs.json"
    if target == "manifest":
        output = manifest
    elif target == "export":
        exported = output
    else:
        output.write_text("keep me")
    original = manifest.read_bytes()

    def unexpected(*args, **kwargs):
        pytest.fail("Invalid paths reached evaluation")

    monkeypatch.setattr("scripts.evaluate.evaluate", unexpected)
    with pytest.raises(SystemExit):
        invoke(monkeypatch, manifest, output, "--export-inputs", str(exported))
    assert manifest.read_bytes() == original
    if target == "existing":
        assert output.read_text() == "keep me"


@pytest.mark.parametrize(
    "options",
    [
        ["--k", "0"],
        ["--k", "101"],
        ["--window", "0"],
        ["--rrf-k", "1001"],
        ["--k", "4", "--window", "3", "--embeddings", "missing.json"],
    ],
)
def test_invalid_parameters_do_not_parse_repository(tmp_path, manifest, monkeypatch, options):
    monkeypatch.setattr("scripts.evaluate.evaluate", lambda *a, **kw: pytest.fail("Evaluated"))
    output = tmp_path / "report.json"
    with pytest.raises(SystemExit) as failure:
        invoke(monkeypatch, manifest, output, *options)
    assert failure.value.code == 2 and not output.exists()


@pytest.mark.parametrize("content", ['{"private":1,"private":2}', "[", '{"private":NaN}'])
def test_invalid_json_has_no_traceback_or_source_echo(
    tmp_path, manifest, monkeypatch, capsys, content
):
    manifest.write_text(content)
    output = tmp_path / "report.json"
    with pytest.raises(SystemExit):
        invoke(monkeypatch, manifest, output)
    assert not output.exists()
    captured = capsys.readouterr()
    assert captured.out == "" and "private" not in captured.err
    assert "Traceback" not in captured.err


def test_size_bound_applies_to_manifest(tmp_path, manifest, monkeypatch):
    monkeypatch.setattr("services.analysis.embedding_artifacts.MAX_BYTES", 10)
    output = tmp_path / "report.json"
    with pytest.raises(SystemExit):
        invoke(monkeypatch, manifest, output)
    assert not output.exists()


def test_path_preflight_rejects_ancestor_and_file_parent(tmp_path):
    first = tmp_path / "report.json"
    with pytest.raises(ValueError, match="contain"):
        validate_paths([], [first, first / "inputs.json"])
    first.write_text("existing")
    with pytest.raises(ValueError, match="directory"):
        validate_paths([], [first / "child.json"])


def test_late_report_collision_preserves_winner_and_completed_export(
    tmp_path, manifest, monkeypatch
):
    output, exported = tmp_path / "report.json", tmp_path / "inputs.json"
    import scripts.evaluate as command

    original = command.evaluate

    def concurrent_writer(*args, **kwargs):
        result = original(*args, **kwargs)
        output.write_text("another writer won")
        return result

    monkeypatch.setattr(command, "evaluate", concurrent_writer)
    with pytest.raises(SystemExit):
        invoke(monkeypatch, manifest, output, "--export-inputs", str(exported))
    assert output.read_text() == "another writer won"
    assert read_json(exported)
    assert list(tmp_path.glob(".embedding-*")) == []


def test_export_failure_does_not_publish_report(tmp_path, manifest, monkeypatch):
    output, exported = tmp_path / "report.json", tmp_path / "inputs.json"

    def fail_publication(*args, **kwargs):
        raise OSError("private filesystem details")

    monkeypatch.setattr("scripts.evaluate.write_json", fail_publication)
    with pytest.raises(SystemExit):
        invoke(monkeypatch, manifest, output, "--export-inputs", str(exported))
    assert not output.exists() and not exported.exists()


@pytest.mark.parametrize("content", ['{"model":"a","model":"b"}', '{"vectors":{}}'])
def test_invalid_vectors_fail_before_evaluation(tmp_path, manifest, monkeypatch, content):
    vectors, output = tmp_path / "vectors.json", tmp_path / "report.json"
    vectors.write_text(content)
    monkeypatch.setattr("scripts.evaluate.evaluate", lambda *a, **kw: pytest.fail("Evaluated"))
    with pytest.raises(SystemExit):
        invoke(monkeypatch, manifest, output, "--embeddings", str(vectors))
    assert vectors.read_text() == content and not output.exists()


def test_normalized_path_aliases_are_rejected(tmp_path):
    source = tmp_path / "manifest.json"
    alias = tmp_path / "nested" / ".." / "manifest.json"
    with pytest.raises(ValueError, match="distinct"):
        validate_paths([source], [alias])


def test_missing_embedding_coverage_does_not_publish_artifacts(tmp_path, manifest, monkeypatch):
    output, exported, vectors = [
        tmp_path / name for name in ("report.json", "inputs.json", "v.json")
    ]
    from services.analysis.hybrid import text_key

    bundle, _ = generate_bundle({text_key("unrelated"): "unrelated"}, FakeEncoder())
    write_json(vectors, bundle.model_dump())
    with pytest.raises(SystemExit):
        invoke(
            monkeypatch,
            manifest,
            output,
            "--embeddings",
            str(vectors),
            "--export-inputs",
            str(exported),
        )
    assert not output.exists() and not exported.exists()
