"""Conservative outbound screening; this is not a complete secret detector."""

import re

PATTERNS = [
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}\b"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{30,}\b"),
    re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{24,}\b"),
    re.compile(
        r"""(?i)\b(?:password|api[_-]?key|client[_-]?secret|access[_-]?token)\s*[=:]\s*["'][^"'\s]{8,}["']"""
    ),
]


def contains_secret(text: str, known: tuple[str, ...] = ()) -> bool:
    return any(value and value in text for value in known) or any(
        pattern.search(text) for pattern in PATTERNS
    )
