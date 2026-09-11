"""Batched embedding generation with resumable vector caching."""

from pathlib import Path
from typing import Protocol

from services.analysis.embedding_artifacts import read_json, validate_inputs, write_json
from services.analysis.hybrid import VectorBundle, text_key


class Encoder(Protocol):
    model: str
    revision: str
    dimensions: int

    def encode(self, texts: list[str]) -> list[list[float]]: ...


def generate_bundle(
    inputs: dict[str, str],
    encoder: Encoder,
    *,
    batch_size: int = 16,
    cache_path: Path | None = None,
) -> tuple[VectorBundle, dict]:
    inputs = validate_inputs(inputs)
    if not 1 <= batch_size <= 128:
        raise ValueError("Batch size must be between 1 and 128")
    # Validate metadata even when no inference will be necessary.
    if type(encoder.dimensions) is not int or not 1 <= encoder.dimensions <= 4096:
        raise ValueError("Encoder dimensions must be between 1 and 4096")
    identity = {
        "model": encoder.model,
        "revision": encoder.revision,
        "dimensions": encoder.dimensions,
    }
    VectorBundle.model_validate(
        identity | {"vectors": {text_key("validation"): [1.0] * encoder.dimensions}}
    )
    vectors: dict[str, list[float]] = {}
    if cache_path and cache_path.exists():
        cache = VectorBundle.model_validate(read_json(cache_path))
        if any(getattr(cache, key) != value for key, value in identity.items()):
            raise ValueError("Cache model, revision or dimensions do not match; use a new cache")
        vectors = {key: value for key, value in cache.vectors.items() if key in inputs}
    hits = len(vectors)
    missing = sorted(set(inputs) - vectors.keys())
    for start in range(0, len(missing), batch_size):
        keys = missing[start : start + batch_size]
        encoded = encoder.encode([inputs[key] for key in keys])
        if len(encoded) != len(keys):
            raise ValueError("Encoder returned an unexpected number of vectors")
        batch = VectorBundle.model_validate(
            identity | {"vectors": dict(zip(keys, encoded, strict=True))}
        )
        vectors.update(batch.vectors)
        if cache_path:
            write_json(
                cache_path,
                VectorBundle.model_validate(identity | {"vectors": vectors}).model_dump(),
                replace=True,
            )
    return VectorBundle.model_validate(identity | {"vectors": vectors}), {
        "inputs": len(inputs),
        "cache_hits": hits,
        "encoded": len(missing),
        "batches": (len(missing) + batch_size - 1) // batch_size,
    }
