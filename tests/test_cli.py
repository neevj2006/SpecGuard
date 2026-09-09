import json
import sys

import pytest

from services.analysis.cli import main, read_criteria
from services.analysis.decompose import RuleDecomposer


def test_cli_model_decomposition_keeps_editable_list(tmp_path, monkeypatch, capsys):
    source = tmp_path / "requirement.txt"
    output = tmp_path / "criteria.json"
    source.write_text("Save receipts", encoding="utf-8")
    monkeypatch.setenv("SPECGUARD_MODEL", "test-model")
    monkeypatch.setenv("SPECGUARD_MODEL_KEY", "test-key")
    monkeypatch.setattr(
        "services.analysis.cli.ModelDecomposer.decompose",
        lambda self, text: RuleDecomposer().decompose(text),
    )
    monkeypatch.setattr(
        sys, "argv", ["specguard", "decompose", str(source), "--model", "--output", str(output)]
    )
    main()
    assert json.loads(output.read_text())[0]["source_text"] == "Save receipts"
    assert "Decomposer: explicit-lists/3" in capsys.readouterr().out


def test_detailed_export_keeps_review_context_and_loads_for_analysis(tmp_path, monkeypatch):
    source = tmp_path / "requirement.txt"
    output = tmp_path / "review.json"
    source.write_text("For café owners:\n- Save receipts", encoding="utf-8")
    monkeypatch.setattr(
        sys, "argv", ["specguard", "decompose", str(source), "--details", "--output", str(output)]
    )
    main()
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["context"] == "For café owners:"
    assert payload["questions"]
    assert payload["version"] == "explicit-lists/3"
    assert payload["usage"] is None
    detailed = read_criteria(output)
    output.write_text(json.dumps(payload["criteria"]), encoding="utf-8")
    assert read_criteria(output) == detailed


@pytest.mark.parametrize(
    "payload", [None, "criteria", {"criteria": []}, {"criteria": [], "version": "x"}]
)
def test_invalid_criteria_exports_fail_clearly(tmp_path, payload):
    source = tmp_path / "invalid.json"
    source.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises((ValueError, TypeError)):
        read_criteria(source)
