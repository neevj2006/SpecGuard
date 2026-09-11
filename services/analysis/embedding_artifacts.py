"""Bounded embedding artifacts and content-based model identity."""

import hashlib
import json
import os
import tempfile
from pathlib import Path

from services.analysis.hybrid import text_key

MAX_BYTES = 20_000_000


def read_json(path: Path):
    with path.open("rb") as source:
        content = source.read(MAX_BYTES + 1)
    if len(content) > MAX_BYTES:
        raise ValueError("Embedding artifact exceeds 20 MB")
    return json.loads(content)


def validate_inputs(payload: object) -> dict[str, str]:
    if not isinstance(payload, dict) or not 1 <= len(payload) <= 20000:
        raise ValueError("Supply between 1 and 20000 hashed input texts")
    total = 0
    for key, value in payload.items():
        if not isinstance(value, str) or not value.strip() or key != text_key(value):
            raise ValueError("Every input must have its exact SHA-256 key and nonempty text")
        total += len(value.encode("utf-8"))
    if total > MAX_BYTES:
        raise ValueError("Input texts exceed 20 MB")
    return payload


def model_fingerprint(directory: Path) -> str:
    if not directory.is_dir() or directory.is_symlink():
        raise ValueError("Supply a trusted local model directory")
    digest = hashlib.sha256()
    count = 0
    for path in sorted(directory.rglob("*")):
        if path.is_symlink():
            raise ValueError("Model directories must not contain symbolic links")
        if not path.is_file():
            continue
        count += 1
        if count > 20000:
            raise ValueError("Model directory contains too many files")
        name = path.relative_to(directory).as_posix().encode("utf-8")
        digest.update(len(name).to_bytes(8, "big") + name)
        digest.update(path.stat().st_size.to_bytes(8, "big"))
        with path.open("rb") as source:
            while chunk := source.read(1_048_576):
                digest.update(chunk)
    if not count:
        raise ValueError("Model directory is empty")
    return digest.hexdigest()


def write_json(path: Path, payload: dict, *, replace: bool = False):
    content = (json.dumps(payload, sort_keys=True) + "\n").encode("utf-8")
    if len(content) > MAX_BYTES:
        raise ValueError("Generated embedding artifact exceeds 20 MB")
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix=".embedding-", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "wb") as output:
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
        if replace:
            os.replace(temporary, path)
        else:
            # Linking publishes a complete file without overwriting an existing artifact.
            os.link(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
