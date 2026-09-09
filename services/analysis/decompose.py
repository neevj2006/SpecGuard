"""Split explicit acceptance lists without inventing implicit requirements."""

import re
from typing import Protocol

from pydantic import Field

from services.analysis.domain import Contract, Criterion, stable_id

MARKER = re.compile(r"^([ \t]*)(?:[-*+]|\d+[.)])(?:[ \t]+|$)(.*)$")


class DecompositionUsage(Contract):
    requested_model: str = Field(min_length=1, max_length=200)
    request_attempted: bool
    total_tokens: int | None = Field(default=None, ge=0, strict=True)
    elapsed_ms: int = Field(ge=0)


class Decomposition(Contract):
    criteria: list[Criterion] = Field(min_length=1, max_length=50)
    context: str = Field(default="", max_length=20000)
    assumptions: list[str] = Field(default_factory=list, max_length=50)
    questions: list[str] = Field(default_factory=list, max_length=50)
    version: str = Field(min_length=1, max_length=200)
    usage: DecompositionUsage | None = None


class Decomposer(Protocol):
    version: str

    def decompose(self, text: str) -> Decomposition: ...


class RuleDecomposer:
    version = "explicit-lists/3"

    def decompose(self, text: str) -> Decomposition:
        criteria = decompose(text)
        lines = text.splitlines()
        first_marker = next((i for i, line in enumerate(lines) if MARKER.match(line)), None)
        context = "\n".join(lines[:first_marker]).strip() if first_marker is not None else ""
        questions = []
        if context:
            questions.append(
                "Does the introductory context add constraints that should be included in the criteria?"
            )
        if first_marker is None:
            questions.append(
                "Should this prose be split into independently testable acceptance criteria?"
            )
        seen = set()
        for position, criterion in enumerate(criteria, 1):
            normalized = " ".join(criterion.text.casefold().split())
            if normalized in seen:
                questions.append(
                    f"Criterion {position} repeats an earlier criterion. Is it needed?"
                )
            seen.add(normalized)
            if any(MARKER.match(line) for line in criterion.text.splitlines()[1:]):
                questions.append(
                    f"Criterion {position} contains nested conditions. Should they be reviewed separately?"
                )
        # Keep all criteria; questions are review guidance, never inferred requirements.
        return Decomposition(
            criteria=criteria, context=context, questions=questions[:50], version=self.version
        )


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
