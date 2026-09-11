import pytest

from services.analysis.embedding_artifacts import (
    model_fingerprint,
    read_json,
    validate_inputs,
    write_json,
)
from services.analysis.hybrid import text_key


@pytest.mark.parametrize(
    "payload", [{}, [], {"bad": "text"}, {text_key("x"): "y"}, {text_key(" "): " "}, {"x": 3}]
)
def test_invalid_inputs_rejected(payload):
    with pytest.raises(ValueError):
        validate_inputs(payload)


def test_model_fingerprint_tracks_contents_and_relative_names(tmp_path):
    model = tmp_path / "model"
    model.mkdir()
    with pytest.raises(ValueError, match="empty"):
        model_fingerprint(model)
    file = model / "config.json"
    file.write_text("first")
    first = model_fingerprint(model)
    assert first == model_fingerprint(model)
    file.write_text("other")
    assert model_fingerprint(model) != first
    file.write_text("first")
    file.rename(model / "renamed.json")
    assert model_fingerprint(model) != first


def test_atomic_publication_does_not_overwrite_reviewed_output(tmp_path):
    output = tmp_path / "output.json"
    write_json(output, {"original": True})
    with pytest.raises(FileExistsError):
        write_json(output, {"original": False})
    assert read_json(output) == {"original": True}
    assert list(tmp_path.glob(".embedding-*")) == []
    write_json(output, {"new": True}, replace=True)
    assert read_json(output) == {"new": True}


def test_artifact_size_limits(tmp_path, monkeypatch):
    monkeypatch.setattr("services.analysis.embedding_artifacts.MAX_BYTES", 10)
    output = tmp_path / "large.json"
    with pytest.raises(ValueError, match="exceeds"):
        write_json(output, {"too_long": "text"})
    assert not output.exists()
    output.write_text("x" * 11)
    with pytest.raises(ValueError, match="exceeds"):
        read_json(output)
