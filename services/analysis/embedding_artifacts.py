"""Bounded embedding artifacts and content-based model identity."""

import hashlib
import json
import math
import os
import tempfile
from pathlib import Path

from services.analysis.hybrid import text_key

MAX_BYTES = 20_000_000


def _unique_object(pairs: list[tuple[str, object]]) -> dict:
    result: dict = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON object keys are not supported")
        result[key] = value
    return result


def _reject_constant(value: str):
    raise ValueError("Non-finite JSON constants are not supported")


def _finite_float(value: str) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("JSON number exceeds finite float range")
    return number


def read_json(path: Path):
    with path.open("rb") as source:
        content = source.read(MAX_BYTES + 1)
    return decode_json(content)


def decode_json(content: bytes):
    if len(content) > MAX_BYTES:
        raise ValueError("Embedding artifact exceeds 20 MB")
    try:
        return json.loads(
            content,
            object_pairs_hook=_unique_object,
            parse_constant=_reject_constant,
            parse_float=_finite_float,
        )
    except RecursionError as error:
        raise ValueError("JSON artifact nesting is too deep") from error


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
    content = (json.dumps(payload, sort_keys=True, allow_nan=False) + "\n").encode("utf-8")
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
