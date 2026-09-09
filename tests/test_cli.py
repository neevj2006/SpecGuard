import json
import sys

from services.analysis.cli import main
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
