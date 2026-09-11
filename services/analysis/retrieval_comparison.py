"""Paired, repository-group bootstrap comparisons for retrieval reports."""

import hashlib
import json
import math
import random
from statistics import mean

METRICS = ("recall", "mrr", "ndcg")


def percentile(values: list[float], probability: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def compare_retrieval(
    report: dict,
    baseline: str,
    candidate: str,
    *,
    samples: int = 2000,
    seed: int = 0,
    confidence: float = 0.95,
) -> dict:
    if type(samples) is not int or not 100 <= samples <= 10000:
        raise ValueError("Use between 100 and 10000 bootstrap samples")
    if type(seed) is not int or not 0 <= seed <= 2**32 - 1:
        raise ValueError("Seed must be an unsigned 32-bit integer")
    if not 0.5 <= confidence <= 0.99:
        raise ValueError("Confidence must be between 0.5 and 0.99")
    if not baseline or not candidate or baseline == candidate:
        raise ValueError("Choose two distinct retrieval methods")
    if not isinstance(report, dict) or report.get("origin") != "synthetic":
        raise ValueError("Supply a synthetic retrieval evaluation report")
    if report.get("annotation_status") != "not_human_adjudicated":
        raise ValueError("Unsupported report annotation status")
    rows = report.get("cases")
    if not isinstance(rows, list) or not 1 <= len(rows) <= 100:
        raise ValueError("Report must contain between 1 and 100 cases")
    groups: dict[str, str] = {}
    seen: set[str] = set()
    normalized = []
    for row in rows:
        if not isinstance(row, dict):
            raise TypeError("Invalid report case")
        case_id, group, split = (row.get(key) for key in ("id", "group", "split"))
        if (
            not isinstance(case_id, str)
            or not isinstance(group, str)
            or not case_id.strip()
            or not group.strip()
        ):
            raise ValueError("Every case needs an identifier and repository group")
        if case_id in seen or split not in ("development", "test"):
            raise ValueError("Duplicate case or invalid split")
        if group in groups and groups[group] != split:
            raise ValueError("Repository groups cannot cross splits")
        seen.add(case_id)
        groups[group] = split
        methods = row.get("ablations")
        scores: dict[str, dict[str, float]] = {}
        for name in (baseline, candidate):
            values = methods.get(name) if isinstance(methods, dict) else None
            if not isinstance(values, dict):
                raise TypeError("Both methods must be measured for every case")
            scores[name] = {}
            for metric in METRICS:
                value = values.get(metric)
                if (
                    not isinstance(value, (int, float))
                    or isinstance(value, bool)
                    or not 0 <= value <= 1
                    or not math.isfinite(value)
                ):
                    raise ValueError(
                        "Retrieval metrics must be finite numbers between zero and one"
                    )
                scores[name][metric] = float(value)
        normalized.append({"id": case_id, "group": group, "split": split, "scores": scores})
    normalized.sort(key=lambda row: row["id"])
    fingerprint = hashlib.sha256(
        json.dumps(normalized, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    splits = {}
    for split in sorted({row["split"] for row in normalized}):
        selected = [row for row in normalized if row["split"] == split]
        names = sorted({row["group"] for row in selected})
        grouped = [[row for row in selected if row["group"] == name] for name in names]
        # Share sampled group indices across metrics and paired methods.
        rng = random.Random(f"group-bootstrap/1:{seed}:{split}")
        draws = [rng.choices(range(len(names)), k=len(names)) for _ in range(samples)]
        metrics = {}
        for metric in METRICS:
            left = [mean(row["scores"][baseline][metric] for row in group) for group in grouped]
            right = [mean(row["scores"][candidate][metric] for row in group) for group in grouped]
            deltas = [b - a for a, b in zip(left, right, strict=True)]
            interval = None
            if len(names) >= 2:
                distribution = [mean(deltas[index] for index in draw) for draw in draws]
                tail = (1 - confidence) / 2
                interval = {
                    "lower": percentile(distribution, tail),
                    "upper": percentile(distribution, 1 - tail),
                }
            metrics[metric] = {
                "baseline": mean(left),
                "candidate": mean(right),
                "delta": mean(deltas),
                "interval": interval,
                "groups_improved": sum(delta > 0 for delta in deltas),
                "groups_tied": sum(delta == 0 for delta in deltas),
                "groups_regressed": sum(delta < 0 for delta in deltas),
            }
        splits[split] = {
            "cases": len(selected),
            "groups": len(names),
            "interval_status": "estimated" if len(names) >= 2 else "insufficient_groups",
            "metrics": metrics,
        }
    return {
        "version": "group-bootstrap/1",
        "measurements_sha256": fingerprint,
        "baseline": baseline,
        "candidate": candidate,
        "samples": samples,
        "seed": seed,
        "confidence": confidence,
        "method": "paired_percentile_bootstrap",
        "weighting": "equal_repository_groups",
        "origin": report["origin"],
        "annotation_status": report["annotation_status"],
        "splits": splits,
        "limitation": "Synthetic fixtures only. Intervals describe sampled group variability, not model nondeterminism or real-world quality. Few groups yield unstable intervals; no significance or release decision is implied.",
    }
