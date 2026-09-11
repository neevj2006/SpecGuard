"""Optional CPU encoder for trusted local sentence-transformer models."""

import importlib.metadata
import json
from pathlib import Path

from services.analysis.embedding_artifacts import model_fingerprint
from services.analysis.hybrid import text_key


class LocalSentenceEncoder:
    def __init__(self, directory: Path, model: str):
        fingerprint = model_fingerprint(directory)
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as error:
            raise ValueError("Install the optional sentence-transformers runtime") from error
        self.model = model
        self.runtime_versions = {
            name: importlib.metadata.version(name)
            for name in ("sentence-transformers", "transformers", "torch")
        }
        runtime = json.dumps(self.runtime_versions, sort_keys=True)
        self._encoder = SentenceTransformer(
            str(directory.resolve()),
            device="cpu",
            local_files_only=True,
            trust_remote_code=False,
            model_kwargs={"use_safetensors": True},
        )
        self.dimensions = self._encoder.get_sentence_embedding_dimension()
        self._max_tokens = self._encoder.max_seq_length
        self.revision = text_key(f"local-encoder/1:{fingerprint}:{runtime}:{self._max_tokens}")
        self._directory, self._fingerprint = directory, fingerprint

    def encode(self, texts: list[str]) -> list[list[float]]:
        tokens = self._encoder.tokenizer(texts, truncation=False, add_special_tokens=True)
        if any(len(ids) > self._max_tokens for ids in tokens["input_ids"]):
            raise ValueError("Input exceeds the model token limit; choose a longer-context encoder")
        return self._encoder.encode(
            texts,
            batch_size=len(texts),
            show_progress_bar=False,
            convert_to_numpy=True,
            normalize_embeddings=True,
            prompt="",
        ).tolist()

    def verify_unchanged(self):
        if model_fingerprint(self._directory) != self._fingerprint:
            raise ValueError("Model files changed during embedding generation")
