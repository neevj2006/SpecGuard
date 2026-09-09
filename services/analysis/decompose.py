"""Split explicit acceptance lists without inventing implicit requirements."""

import re

from services.analysis.domain import Criterion, stable_id


def decompose(text: str) -> list[Criterion]:
    if not text.strip() or len(text) > 20000:
        raise ValueError("Supply between 1 and 20000 characters of requirements")
    lines = text.strip().splitlines()
    marked = [
        re.sub(r"^\s*(?:[-*]|\d+[.)])\s+", "", line).strip()
        for line in lines
        if re.match(r"^\s*(?:[-*]|\d+[.)])\s+", line)
    ]
    items = marked or [text.strip()]
    if len(items) > 50:
        raise ValueError("At most 50 criteria are supported per run")
    return [
        Criterion(id=stable_id(f"{i}:{item}"), text=item, source_text=item)
        for i, item in enumerate(items)
    ]
