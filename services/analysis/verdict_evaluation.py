"""Evaluate saved verdicts against explicit, independently supplied review labels."""

import hashlib
import json
from typing import Annotated, Literal

from pydantic import Field, model_validator

from services.analysis.domain import AnalysisRun, Contract, Verdict


class VerdictLabel(Contract):
    run_id: str = Field(min_length=1)
    criterion_id: str = Field(min_length=1)
    group: str = Field(min_length=1)
    split: Literal["development", "test"]
    expected: Verdict
    reviewer: str = Field(min_length=1)
    source: str = Field(min_length=1)
    license: str = Field(min_length=1)
    citation_correctness: dict[str, Annotated[bool, Field(strict=True)]] = Field(
        default_factory=dict
    )


class VerdictBenchmark(Contract):
    version: str = Field(min_length=1)
    annotation_status: Literal["synthetic", "human_reviewed", "human_adjudicated"]
    runs: list[AnalysisRun] = Field(min_length=1, max_length=1000)
    labels: list[VerdictLabel] = Field(min_length=1, max_length=10000)

    @model_validator(mode="after")
    def consistent_labels(self):
        if len({run.id for run in self.runs}) != len(self.runs):
            raise ValueError("Duplicate run identifiers")
        results = {}
        for run in self.runs:
            if not run.results:
                raise ValueError("Evaluation runs must contain criterion results")
            for result in run.results:
                key = (run.id, result.criterion.id)
                if key in results:
                    raise ValueError("Duplicate criterion identifiers within a run")
                if len({e.id for e in result.evidence}) != len(result.evidence):
                    raise ValueError("Duplicate citations in a criterion result")
                results[key] = result
        seen = set()
        groups: dict[str, str] = {}
        run_groups: dict[str, tuple[str, str]] = {}
        for label in self.labels:
            key = (label.run_id, label.criterion_id)
            if key in seen or key not in results:
                raise ValueError("Duplicate label or label without a matching result")
            seen.add(key)
            if groups.setdefault(label.group, label.split) != label.split:
                raise ValueError("A repository group cannot cross evaluation splits")
            assignment = (label.group, label.split)
            if run_groups.setdefault(label.run_id, assignment) != assignment:
                raise ValueError("A run must belong to one repository group and split")
            citations = {e.id for e in results[key].evidence}
            if not set(label.citation_correctness) <= citations:
                raise ValueError("Citation judgment references evidence outside its result")
        if seen != set(results):
            raise ValueError("Every saved criterion result must have a label")
        return self


def ratio(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def metrics(rows: list[tuple], thresholds: list[float]) -> dict:
    classes = [v.value for v in Verdict]
    matrix = {expected: dict.fromkeys(classes, 0) for expected in classes}
    for label, result in rows:
        matrix[label.expected.value][result.verdict.value] += 1
    per_class = {}
    for name in classes:
        tp = matrix[name][name]
        support = sum(matrix[name].values())
        predicted = sum(matrix[other][name] for other in classes)
        per_class[name] = {
            "support": support,
            "predicted": predicted,
            "precision": ratio(tp, predicted),
            "recall": ratio(tp, support),
            "f1": ratio(2 * tp, support + predicted),
        }
    answered = [(label, result) for label, result in rows if result.verdict != Verdict.UNKNOWN]
    judgments = [value for label, _ in rows for value in label.citation_correctness.values()]
    citations = sum(len(result.evidence) for _, result in rows)
    curve = []
    for threshold in thresholds:
        selected = [
            (label, result)
            for label, result in answered
            if result.confidence is not None and result.confidence >= threshold
        ]
        curve.append(
            {
                "threshold": threshold,
                "selected": len(selected),
                "coverage": ratio(len(selected), len(rows)),
                "risk": ratio(
                    sum(label.expected != result.verdict for label, result in selected),
                    len(selected),
                ),
            }
        )
    return {
        "criteria": len(rows),
        "confusion_matrix": matrix,
        "per_class": per_class,
        "accuracy": ratio(
            sum(label.expected == result.verdict for label, result in rows), len(rows)
        ),
        "macro_f1": sum(item["f1"] or 0 for item in per_class.values()) / len(classes),
        "answer_coverage": ratio(len(answered), len(rows)),
        "answer_risk": ratio(
            sum(label.expected != result.verdict for label, result in answered), len(answered)
        ),
        "abstentions": len(rows) - len(answered),
        "missing_answer_confidence": sum(result.confidence is None for _, result in answered),
        "citation_judgments": len(judgments),
        "citations": citations,
        "citation_judgment_coverage": ratio(len(judgments), citations),
        "citation_correctness": ratio(sum(judgments), len(judgments)),
        "coverage_risk": curve,
    }


def evaluate_verdicts(benchmark: VerdictBenchmark, thresholds: list[float] | None = None) -> dict:
    thresholds = [0, 0.5, 0.75, 0.9, 1] if thresholds is None else thresholds
    if not thresholds or any(not 0 <= value <= 1 for value in thresholds):
        raise ValueError("Confidence thresholds must be between zero and one")
    thresholds = sorted(set(thresholds))
    results = {
        (run.id, result.criterion.id): result for run in benchmark.runs for result in run.results
    }
    splits = {}
    for split in sorted({label.split for label in benchmark.labels}):
        labels = [label for label in benchmark.labels if label.split == split]
        rows = [(label, results[(label.run_id, label.criterion_id)]) for label in labels]
        runs = [run for run in benchmark.runs if run.id in {label.run_id for label in labels}]
        splits[split] = {
            **metrics(rows, thresholds),
            "runs": len(runs),
            "total_duration_ms": sum(run.duration_ms for run in runs),
            "known_total_tokens": sum(
                run.token_usage for run in runs if run.token_usage is not None
            ),
            "runs_missing_token_usage": sum(run.token_usage is None for run in runs),
            "known_cost_usd": sum(run.cost_usd for run in runs if run.cost_usd is not None),
            "runs_missing_cost": sum(run.cost_usd is None for run in runs),
        }
    return {
        "evaluator": "verdict-metrics/1",
        "benchmark_version": benchmark.version,
        "annotation_status": benchmark.annotation_status,
        "input_sha256": hashlib.sha256(
            json.dumps(
                benchmark.model_dump(mode="json", exclude_unset=True), sort_keys=True
            ).encode()
        ).hexdigest(),
        "macro_f1_policy": "All four classes; undefined class F1 contributes zero.",
        "limitation": "Labels and citation judgments are supplied by reviewers, not inferred. Annotation status is declared, not independently certified. Confidence thresholds do not establish calibration or test execution.",
        "splits": splits,
    }
