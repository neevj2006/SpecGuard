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


@pytest.mark.parametrize(
    "content",
    ['{"key":1,"key":2}', '{"nested":{"x":1,"x":2}}', r'{"x":1,"\u0078":2}'],
)
def test_duplicate_keys_are_rejected_without_disclosing_keys(tmp_path, content):
    source = tmp_path / "input.json"
    source.write_text(content, encoding="utf-8")
    with pytest.raises(ValueError, match="Duplicate JSON") as failure:
        read_json(source)
    assert content not in str(failure.value)


@pytest.mark.parametrize("token", ["NaN", "Infinity", "-Infinity", "1e999", "-1e999"])
def test_nonfinite_numbers_are_rejected_inside_arrays(tmp_path, token):
    source = tmp_path / "input.json"
    source.write_text('{"vectors":[' + token + "]}", encoding="utf-8")
    with pytest.raises(ValueError):
        read_json(source)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf")])
def test_nonfinite_publication_preserves_existing_cache(tmp_path, value):
    cache = tmp_path / "cache.json"
    write_json(cache, {"valid": [1.0]})
    original = cache.read_bytes()
    with pytest.raises(ValueError):
        write_json(cache, {"invalid": [value]}, replace=True)
    assert cache.read_bytes() == original
    assert list(tmp_path.glob(".embedding-*")) == []


def test_json_nesting_failure_is_a_validation_error(tmp_path):
    source = tmp_path / "input.json"
    source.write_text("[" * 10000 + "0" + "]" * 10000)
    with pytest.raises(ValueError, match="nesting"):
        read_json(source)


def test_repeated_names_in_separate_objects_and_finite_numbers_round_trip(tmp_path):
    source = tmp_path / "input.json"
    payload = {"rows": [{"score": 0.25}, {"score": 1e-200}], "label": "café"}
    write_json(source, payload)
    assert read_json(source) == payload
