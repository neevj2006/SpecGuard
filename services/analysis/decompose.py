"""Split explicit acceptance lists without inventing implicit requirements."""

import re

from services.analysis.domain import Criterion, stable_id

MARKER = re.compile(r"^([ \t]*)(?:[-*+]|\d+[.)])(?:[ \t]+|$)(.*)$")


def explicit_items(text: str) -> list[str]:
    lines = text.splitlines()
    matches = [MARKER.match(line) for line in lines]
    indents = [len(m[1].expandtabs(4)) for m in matches if m]
    if not indents:
        return [text.strip()]
    root_indent = min(indents)
    items: list[str] = []
    current: list[str] = []
    for line, match in zip(lines, matches):
        if match and len(match[1].expandtabs(4)) == root_indent:
            if current:
                items.append("\n".join(current).strip())
            content = re.sub(r"^\[[ xX]\](?:[ \t]+|$)", "", match[2]).strip()
            if not content:
                raise ValueError("Acceptance list items must contain requirement text")
            current = [content]
        elif current:
            # Keep continuation constraints and nested lists attached to their parent.
            current.append(line)
    if current:
        items.append("\n".join(current).strip())
    return items


def decompose(text: str) -> list[Criterion]:
    if not text.strip() or len(text) > 20000:
        raise ValueError("Supply between 1 and 20000 characters of requirements")
    items = explicit_items(text)
    if len(items) > 50:
        raise ValueError("At most 50 criteria are supported per run")
    return [
        Criterion(id=stable_id(f"{i}:{item}"), text=item, source_text=item)
        for i, item in enumerate(items)
    ]
