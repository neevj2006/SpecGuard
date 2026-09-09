"""Validated review contracts. Static claims never imply a test execution."""

from datetime import UTC, datetime
from enum import StrEnum
from hashlib import sha256
from pathlib import PurePosixPath

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Verdict(StrEnum):
    SATISFIED = "satisfied"
    PARTIAL = "partially_satisfied"
    MISSING = "not_satisfied"
    UNKNOWN = "not_verifiable"


class Criterion(Contract):
    id: str = Field(min_length=1, max_length=80)
    text: str = Field(min_length=1, max_length=4000)
    source_text: str = Field(min_length=1, max_length=4000)


class Evidence(Contract):
    id: str
    revision: str = Field(pattern=r"^[0-9a-f]{40,64}$")
    path: str
    start_line: int = Field(ge=1)
    end_line: int = Field(ge=1)
    quote: str = Field(min_length=1)
    symbol: str
    kind: str
    score: float = Field(default=0, ge=0)
    changed: bool = False

    @model_validator(mode="after")
    def valid_span(self):
        path = PurePosixPath(self.path)
        if path.is_absolute() or ".." in path.parts or "\\" in self.path or ":" in self.path:
            raise ValueError("Evidence must use a relative repository path")
        if self.end_line < self.start_line:
            raise ValueError("Invalid source span")
        if len(self.quote.splitlines()) != self.end_line - self.start_line + 1:
            raise ValueError("Quote does not cover the declared lines")
        return self


class TestExecution(Contract):
    status: str = Field(
        default="not_run", pattern="^(not_run|passed|failed|timed_out|infrastructure_error)$"
    )
    command: list[str] = Field(default_factory=list)
    revision: str | None = None
    exit_code: int | None = None
    duration_ms: int | None = Field(default=None, ge=0)
    environment: str | None = None

    @model_validator(mode="after")
    def actual_execution(self):
        if self.status != "not_run":
            if (
                not self.command
                or not self.revision
                or not self.environment
                or self.duration_ms is None
            ):
                raise ValueError("Executed tests require provenance")
            if self.status == "passed" and self.exit_code != 0:
                raise ValueError("Passed tests require exit code zero")
            if self.status == "failed" and self.exit_code in (None, 0):
                raise ValueError("Failed tests require a nonzero exit code")
        elif self.command or self.revision or self.exit_code is not None:
            raise ValueError("Unexecuted tests cannot contain execution results")
        return self


class CriterionResult(Contract):
    criterion: Criterion
    verdict: Verdict
    rationale: str = Field(min_length=1)
    evidence: list[Evidence] = Field(default_factory=list)
    confidence: float | None = Field(default=None, ge=0, le=1)
    uncertainty: str = ""
    suggestion: str = ""
    tests: TestExecution = Field(default_factory=TestExecution)

    @model_validator(mode="after")
    def grounded_claim(self):
        if self.verdict != Verdict.UNKNOWN and not self.evidence:
            raise ValueError("Every non-abstaining verdict requires evidence")
        if self.verdict == Verdict.UNKNOWN and not self.uncertainty:
            raise ValueError("Abstention requires an explanation")
        return self


class AnalysisRun(Contract):
    id: str
    repository: str
    base_sha: str
    head_sha: str
    requirement: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    results: list[CriterionResult]
    duration_ms: int = Field(ge=0)
    versions: dict[str, str]
    excluded: list[dict[str, str]] = Field(default_factory=list)
    token_usage: int | None = Field(default=0, ge=0)
    cost_usd: float | None = Field(default=0, ge=0)


def stable_id(value: str) -> str:
    return sha256(value.encode()).hexdigest()[:24]
