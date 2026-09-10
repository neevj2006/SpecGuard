"""Compare independent reviews and apply explicit adjudication decisions."""

import hashlib
import json
from typing import Literal

from pydantic import Field

from services.analysis.domain import Contract, Verdict
from services.analysis.verdict_evaluation import VerdictBenchmark, VerdictLabel, ratio


def fingerprint(benchmark: VerdictBenchmark) -> str:
    content = benchmark.model_dump(mode="json", exclude_unset=True)
    return hashlib.sha256(json.dumps(content, sort_keys=True).encode()).hexdigest()


def pair_reviews(
    left: VerdictBenchmark, right: VerdictBenchmark
) -> list[tuple[VerdictLabel, VerdictLabel]]:
    left_runs = {r.id: r.model_dump(mode="json", exclude={"created_at"}) for r in left.runs}
    right_runs = {r.id: r.model_dump(mode="json", exclude={"created_at"}) for r in right.runs}
    if left_runs != right_runs:
        raise ValueError("Reviews must refer to the same saved runs and evidence")
    a = {(label.run_id, label.criterion_id): label for label in left.labels}
    b = {(label.run_id, label.criterion_id): label for label in right.labels}
    if a.keys() != b.keys():
        raise ValueError("Reviews must label exactly the same criteria")
    pairs = []
    for key in sorted(a):
        first, second = a[key], b[key]
        if first.reviewer.strip().casefold() == second.reviewer.strip().casefold():
            raise ValueError("Two distinct reviewer identifiers are required per criterion")
        if not first.reviewer.strip() or not second.reviewer.strip():
            raise ValueError("Reviewer identifiers cannot be blank")
        if (first.group, first.split, first.source, first.license) != (
            second.group,
            second.split,
            second.source,
            second.license,
        ):
            raise ValueError("Case provenance and split assignments must match")
        pairs.append((first, second))
    return pairs


def agreement(pairs: list[tuple[VerdictLabel, VerdictLabel]]) -> dict:
    matrix = {v.value: {w.value: 0 for w in Verdict} for v in Verdict}
    both, citation_matches, unpaired = 0, 0, 0
    for first, second in pairs:
        matrix[first.expected.value][second.expected.value] += 1
        for key in first.citation_correctness.keys() | second.citation_correctness.keys():
            if key not in first.citation_correctness or key not in second.citation_correctness:
                unpaired += 1
            else:
                both += 1
                citation_matches += (
                    first.citation_correctness[key] == second.citation_correctness[key]
                )
    count = len(pairs)
    observed = sum(matrix[v][v] for v in matrix) / count
    chance = (
        sum(sum(matrix[v].values()) * sum(row[v] for row in matrix.values()) for v in matrix)
        / count**2
    )
    return {
        "criteria": count,
        "verdict_agreement": observed,
        "cohens_kappa": (observed - chance) / (1 - chance) if chance < 1 else None,
        "matrix": matrix,
        "jointly_judged_citations": both,
        "citation_agreement": ratio(citation_matches, both),
        "citations_judged_by_one_reviewer": unpaired,
    }


def compare_reviews(left: VerdictBenchmark, right: VerdictBenchmark) -> dict:
    pairs = pair_reviews(left, right)
    differences = []
    for first, second in pairs:
        changed = {
            key: {
                "left": first.citation_correctness.get(key),
                "right": second.citation_correctness.get(key),
            }
            for key in sorted(
                first.citation_correctness.keys() | second.citation_correctness.keys()
            )
            if first.citation_correctness.get(key) != second.citation_correctness.get(key)
        }
        if first.expected != second.expected or changed:
            differences.append(
                {
                    "run_id": first.run_id,
                    "criterion_id": first.criterion_id,
                    "left_verdict": first.expected.value,
                    "right_verdict": second.expected.value,
                    "citation_differences": changed,
                }
            )
    return {
        "version": "review-agreement/1",
        "left_sha256": fingerprint(left),
        "right_sha256": fingerprint(right),
        "splits": {
            split: agreement([(a, b) for a, b in pairs if a.split == split])
            for split in sorted({a.split for a, _ in pairs})
        },
        "disagreements": differences,
        "limitation": "Reviewer identities and independence are declared, not verified. Agreement is not accuracy; missing citation judgments are excluded from citation agreement. Single-class perfect agreement has undefined kappa.",
    }


class Adjudication(Contract):
    left_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    right_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    version: str = Field(min_length=1)
    annotation_status: Literal["synthetic", "human_adjudicated"]
    decisions: list[VerdictLabel] = Field(min_length=1, max_length=10000)


def decision_template(left: VerdictBenchmark, right: VerdictBenchmark) -> dict:
    pairs = pair_reviews(left, right)
    return {
        "left_sha256": fingerprint(left),
        "right_sha256": fingerprint(right),
        "version": "adjudication-draft-1",
        "annotation_status": None,
        "decisions": [
            a.model_dump(mode="json")
            | {
                "expected": None,
                "reviewer": None,
                "citation_correctness": {},
            }
            for a, _ in pairs
        ],
    }


def adjudicate(
    left: VerdictBenchmark, right: VerdictBenchmark, resolution: Adjudication
) -> VerdictBenchmark:
    pairs = pair_reviews(left, right)
    if (resolution.left_sha256, resolution.right_sha256) != (fingerprint(left), fingerprint(right)):
        raise ValueError("Adjudication inputs have changed since the decision template was created")
    if resolution.annotation_status == "human_adjudicated" and "synthetic" in (
        left.annotation_status,
        right.annotation_status,
    ):
        raise ValueError("Synthetic reviews cannot be promoted to human adjudication")
    original = {(a.run_id, a.criterion_id): a for a, _ in pairs}
    for decision in resolution.decisions:
        prior = original.get((decision.run_id, decision.criterion_id))
        if prior is None or (decision.group, decision.split, decision.source, decision.license) != (
            prior.group,
            prior.split,
            prior.source,
            prior.license,
        ):
            raise ValueError("Adjudication must preserve case provenance")
        if not decision.reviewer.strip():
            raise ValueError("Adjudicator identifier cannot be blank")
    return VerdictBenchmark(
        version=resolution.version,
        annotation_status=resolution.annotation_status,
        runs=left.runs,
        labels=resolution.decisions,
    )
