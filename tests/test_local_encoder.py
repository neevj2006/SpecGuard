import sys
from types import SimpleNamespace

import pytest

from services.analysis.local_encoder import LocalSentenceEncoder


def test_local_adapter_uses_offline_safe_loading_and_rejects_truncation(tmp_path, monkeypatch):
    model_dir = tmp_path / "model"
    model_dir.mkdir()
    (model_dir / "config.json").write_text("{}")
    calls = []

    class LocalModel:
        max_seq_length = 3

        def __init__(self, path, **kwargs):
            calls.append(kwargs)

        def get_sentence_embedding_dimension(self):
            return 2

        def tokenizer(self, texts, **kwargs):
            assert kwargs == {"truncation": False, "add_special_tokens": True}
            return {"input_ids": [list(range(len(text))) for text in texts]}

        def encode(self, texts, **kwargs):
            assert kwargs["prompt"] == "" and kwargs["normalize_embeddings"]
            return SimpleNamespace(tolist=lambda: [[1.0, 0.0] for _ in texts])

    monkeypatch.setitem(
        sys.modules, "sentence_transformers", SimpleNamespace(SentenceTransformer=LocalModel)
    )
    monkeypatch.setattr("importlib.metadata.version", lambda _: "test-version")
    encoder = LocalSentenceEncoder(model_dir, "fixture")
    assert calls[0]["local_files_only"] and not calls[0]["trust_remote_code"]
    assert calls[0]["model_kwargs"] == {"use_safetensors": True}
    assert encoder.encode(["abc"]) == [[1, 0]]
    with pytest.raises(ValueError, match="token limit"):
        encoder.encode(["abcd"])
    encoder.verify_unchanged()
    same = LocalSentenceEncoder(model_dir, "fixture")
    assert same.revision == encoder.revision
    monkeypatch.setattr("importlib.metadata.version", lambda _: "different-version")
    upgraded = LocalSentenceEncoder(model_dir, "fixture")
    assert upgraded.revision != encoder.revision
    (model_dir / "config.json").write_text('{"changed":true}')
    with pytest.raises(ValueError, match="changed"):
        encoder.verify_unchanged()
