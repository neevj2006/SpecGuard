import json
import sys

import pytest

from scripts.prepare_labels import main, prepare_labels
from services.analysis.engine import analyze
from services.analysis.verdict_evaluation import VerdictBenchmark


def test_template_requires_review_and_does_not_copy_predictions(repository):
    repo, base, head = repository
    run = analyze(repo, base, head, "Apply discount").model_dump(mode="json")
    draft = prepare_labels({"run": run, "feedback": [{"note": "private note"}]}, "repo-one")
    assert draft == prepare_labels(run, "repo-one")
    assert draft["labels"][0]["expected"] is None
    assert draft["annotation_status"] is None
    assert set(draft["labels"][0]["citation_correctness"].values()) == {None}
    assert "private note" not in json.dumps(draft)
    with pytest.raises(ValueError):
        VerdictBenchmark.model_validate(draft)


def test_cli_preserves_existing_annotation_work(repository, tmp_path, monkeypatch):
    repo, base, head = repository
    source, output = tmp_path / "run.json", tmp_path / "labels.json"
    source.write_text(analyze(repo, base, head, "Apply discount").model_dump_json())
    monkeypatch.setattr(
        sys, "argv", ["prepare_labels", str(source), "--group", "repo", "--output", str(output)]
    )
    main()
    original = output.read_bytes()
    with pytest.raises(SystemExit) as error:
        main()
    assert error.value.code == 2
    assert output.read_bytes() == original
