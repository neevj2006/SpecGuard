import json
import sys

import pytest

from services.analysis.cli import main
from services.analysis.domain import AnalysisRun, Criterion, Verdict
from services.analysis.embedding_artifacts import read_json, write_json
from services.analysis.embeddings import generate_bundle
from services.analysis.repository import validate_citation
from tests.test_embeddings import FakeEncoder


def invoke(monkeypatch, command, repo, base, head, requirement, *options):
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "specguard",
            command,
            str(repo),
            "--base",
            base,
            "--head",
            head,
            "--requirement",
            str(requirement),
            *options,
        ],
    )
    main()


def test_export_encode_analyze_committed_change(repository, tmp_path, monkeypatch, capsys):
    repo, base, head = repository
    requirement, exported, vectors = [
        tmp_path / name for name in ("requirement.txt", "inputs.json", "vectors.json")
    ]
    requirement.write_text("Archive the receipt", encoding="utf-8")
    invoke(monkeypatch, "export-inputs", repo, base, head, requirement, "--output", str(exported))
    summary = json.loads(capsys.readouterr().out)
    assert summary["base"] == base and summary["head"] == head
    texts = read_json(exported)
    assert summary["inputs"] == len(texts)
    bundle, _ = generate_bundle(texts, FakeEncoder())
    write_json(vectors, bundle.model_dump())
    invoke(
        monkeypatch,
        "analyze",
        repo,
        base,
        head,
        requirement,
        "--embeddings",
        str(vectors),
        "--json",
    )
    run = AnalysisRun.model_validate_json(capsys.readouterr().out)
    assert run.versions["retriever"] == "hybrid-rrf/1"
    assert run.results[0].verdict == Verdict.UNKNOWN
    assert run.results[0].tests.status == "not_run"
    assert run.results[0].evidence
    sources = {"discount.ts": (repo / "discount.ts").read_text()}
    assert all(validate_citation(e, sources, head) for e in run.results[0].evidence)
    invoke(monkeypatch, "analyze", repo, base, head, requirement, "--json")
    sparse = AnalysisRun.model_validate_json(capsys.readouterr().out)
    assert sparse.versions["retriever"] == "bm25/2"
    assert sparse.id != run.id
    assert sparse.results[0].evidence == []


def test_export_uses_edited_criteria_and_preserves_existing_output(
    repository, tmp_path, monkeypatch, capsys
):
    repo, base, head = repository
    requirement, criteria, output = [
        tmp_path / name for name in ("req.txt", "criteria.json", "inputs.json")
    ]
    requirement.write_text("Original request")
    edited = Criterion(id="edited", text="Apply a discount", source_text="Original request")
    criteria.write_text(json.dumps([edited.model_dump()]))
    invoke(
        monkeypatch,
        "export-inputs",
        repo,
        base,
        head,
        requirement,
        "--criteria",
        str(criteria),
        "--output",
        str(output),
    )
    assert "Apply a discount" in read_json(output).values()
    assert "Original request" not in read_json(output).values()
    original = output.read_bytes()
    with pytest.raises(SystemExit):
        invoke(
            monkeypatch,
            "export-inputs",
            repo,
            base,
            head,
            requirement,
            "--criteria",
            str(criteria),
            "--output",
            str(output),
        )
    assert output.read_bytes() == original
    assert "Apply a discount" not in capsys.readouterr().out


@pytest.mark.parametrize("option", ["--window", "--rrf-k"])
def test_fusion_options_require_explicit_bundle(tmp_path, monkeypatch, option):
    requirement = tmp_path / "req.txt"
    requirement.write_text("Save receipt")
    monkeypatch.setattr("services.analysis.cli.analyze", lambda *a, **kw: pytest.fail("Analyzed"))
    with pytest.raises(SystemExit) as failure:
        invoke(monkeypatch, "analyze", tmp_path, "base", "head", requirement, option, "10")
    assert failure.value.code == 2


def test_invalid_bundle_does_not_construct_model_verifier(tmp_path, monkeypatch, capsys):
    requirement, vectors = tmp_path / "req.txt", tmp_path / "vectors.json"
    requirement.write_text("Save receipt")
    vectors.write_text('{"private-field":1,"private-field":2}')
    monkeypatch.setattr(
        "services.analysis.cli.ModelVerifier", lambda: pytest.fail("Constructed verifier")
    )
    with pytest.raises(SystemExit):
        invoke(
            monkeypatch,
            "analyze",
            tmp_path,
            "base",
            "head",
            requirement,
            "--embeddings",
            str(vectors),
            "--model",
        )
    assert "private-field" not in capsys.readouterr().err


def test_export_cannot_overwrite_requirement_before_indexing(tmp_path, monkeypatch):
    requirement = tmp_path / "req.txt"
    requirement.write_text("Keep this requirement")
    monkeypatch.setattr("services.analysis.cli.index_change", lambda *a: pytest.fail("Indexed"))
    with pytest.raises(SystemExit):
        invoke(
            monkeypatch,
            "export-inputs",
            tmp_path,
            "base",
            "head",
            requirement,
            "--output",
            str(requirement),
        )
    assert requirement.read_text() == "Keep this requirement"
