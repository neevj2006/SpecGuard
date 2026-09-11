import math

import pytest

from services.analysis.embedding_artifacts import read_json
from services.analysis.embeddings import generate_bundle
from services.analysis.hybrid import VectorBundle, text_key


class FakeEncoder:
    model, revision, dimensions = "synthetic-encoder", "fixture-1", 2

    def __init__(self):
        self.calls = []

    def encode(self, texts):
        self.calls.append(texts)
        return [[len(text), 1.0] for text in texts]

    def verify_unchanged(self):
        pass


def inputs(*texts):
    return {text_key(text): text for text in texts}


def test_generation_is_batched_and_cache_is_exact(tmp_path):
    cache = tmp_path / "cache.json"
    encoder = FakeEncoder()
    source = inputs("first", "second", "third")
    bundle, stats = generate_bundle(source, encoder, batch_size=2, cache_path=cache)
    assert stats == {"inputs": 3, "cache_hits": 0, "encoded": 3, "batches": 2}
    assert [len(batch) for batch in encoder.calls] == [2, 1]
    again, stats = generate_bundle(source, encoder, cache_path=cache)
    assert again == bundle and stats["cache_hits"] == 3
    assert len(encoder.calls) == 2
    changed, stats = generate_bundle(inputs("first", "changed"), encoder, cache_path=cache)
    assert stats["cache_hits"] == 1 and stats["encoded"] == 1
    assert set(changed.vectors) == set(inputs("first", "changed"))
    assert "changed" not in cache.read_text()


def test_successful_batches_survive_later_failure(tmp_path):
    cache = tmp_path / "cache.json"
    encoder = FakeEncoder()
    original = encoder.encode

    def fail_second(texts):
        if encoder.calls:
            raise RuntimeError("simulated interrupted inference")
        return original(texts)

    encoder.encode = fail_second
    with pytest.raises(RuntimeError):
        generate_bundle(inputs("a", "b"), encoder, batch_size=1, cache_path=cache)
    assert len(VectorBundle.model_validate(read_json(cache)).vectors) == 1
    _, stats = generate_bundle(inputs("a", "b"), FakeEncoder(), cache_path=cache)
    assert stats["cache_hits"] == stats["encoded"] == 1


@pytest.mark.parametrize(
    "attribute,value", [("model", "other"), ("revision", "other"), ("dimensions", 3)]
)
def test_cache_cannot_cross_encoder_identity(tmp_path, attribute, value):
    cache = tmp_path / "cache.json"
    generate_bundle(inputs("a"), FakeEncoder(), cache_path=cache)
    original = cache.read_bytes()
    encoder = FakeEncoder()
    setattr(encoder, attribute, value)
    with pytest.raises(ValueError, match="do not match"):
        generate_bundle(inputs("a"), encoder, cache_path=cache)
    assert cache.read_bytes() == original


@pytest.mark.parametrize("vectors", [[], [[0, 0]], [[math.nan, 1]], [[1]], [[math.inf, 1]]])
def test_bad_encoder_output_never_enters_cache(tmp_path, vectors):
    encoder = FakeEncoder()
    encoder.encode = lambda _: vectors
    cache = tmp_path / "cache.json"
    with pytest.raises(ValueError):
        generate_bundle(inputs("a"), encoder, cache_path=cache)
    assert not cache.exists()


@pytest.mark.parametrize("size", [0, 129])
def test_batch_bounds_checked_before_inference(size):
    encoder = FakeEncoder()
    with pytest.raises(ValueError):
        generate_bundle(inputs("a"), encoder, batch_size=size)
    assert encoder.calls == []
