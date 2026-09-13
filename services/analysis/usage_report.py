"""Source-free operational summaries of persisted analyses, not provider billing."""

import math
from collections import Counter
from collections.abc import Sequence
from datetime import UTC
from decimal import Decimal

from services.analysis.domain import AnalysisRun, Verdict

MAX_RUNS = 1000
OUTCOMES = (
    "accepted",
    "no_evidence",
    "secret_withheld",
    "input_budget",
    "request_budget",
    "time_budget",
    "provider_error",
    "invalid_response",
    "response_budget",
)
BUDGET_OUTCOMES = {"input_budget", "request_budget", "time_budget", "response_budget"}
TEST_STATES = ("not_run", "passed", "failed", "timed_out", "infrastructure_error")


def distribution(values: list[int]) -> dict:
    """Nearest-rank percentiles; missing observations never become zero."""
    ordered = sorted(values)
    if not ordered:
        return {"samples": 0, "mean_ms": None, "p50_ms": None, "p95_ms": None, "max_ms": None}
    return {
        "samples": len(ordered),
        "mean_ms": round(sum(ordered) / len(ordered), 2),
        "p50_ms": ordered[math.ceil(len(ordered) * 0.5) - 1],
        "p95_ms": ordered[math.ceil(len(ordered) * 0.95) - 1],
        "max_ms": ordered[-1],
    }


def summarize_usage(runs: Sequence[AnalysisRun]) -> dict:
    if len(runs) > MAX_RUNS:
        raise ValueError("Usage reports accept at most 1000 runs")
    if len({run.id for run in runs}) != len(runs):
        raise ValueError("Usage reports require unique run IDs")
    verdicts = Counter({verdict.value: 0 for verdict in Verdict})
    outcomes = Counter(dict.fromkeys(OUTCOMES, 0))
    tests = Counter(dict.fromkeys(TEST_STATES, 0))
    attempted_ms: list[int] = []
    known_tokens = 0
    unknown_tokens = 0
    known_token_requests = 0
    uninstrumented = 0
    skipped = 0
    criteria = 0
    cited = 0
    costs: list[Decimal] = []
    run_tokens: list[int] = []
    timestamps = []
    for run in runs:
        if run.created_at.utcoffset() is None:
            raise ValueError("Usage reports require timezone-aware creation times")
        timestamps.append(run.created_at.astimezone(UTC))
        if run.cost_usd is not None:
            if not math.isfinite(run.cost_usd):
                raise ValueError("Recorded costs must be finite")
            costs.append(Decimal(str(run.cost_usd)))
        if run.token_usage is not None:
            run_tokens.append(run.token_usage)
        for result in run.results:
            criteria += 1
            verdicts[result.verdict.value] += 1
            tests[result.tests.status] += 1
            cited += bool(result.evidence)
            usage = result.verification_usage
            if usage is None:
                uninstrumented += 1
                continue
            outcomes[usage.status] += 1
            if not usage.request_attempted:
                skipped += 1
                continue
            attempted_ms.append(usage.elapsed_ms)
            if usage.total_tokens is None:
                unknown_tokens += 1
            else:
                known_tokens += usage.total_tokens
                known_token_requests += 1
    unknown_costs = len(runs) - len(costs)
    unknown_run_tokens = len(runs) - len(run_tokens)
    cost_sum = sum(costs, Decimal(0))
    return {
        "version": "usage-report/1",
        "scope": "persisted_analyses",
        "runs": len(runs),
        "period": {
            "oldest_created_at": min(timestamps).isoformat() if timestamps else None,
            "newest_created_at": max(timestamps).isoformat() if timestamps else None,
        },
        "criteria": {
            "total": criteria,
            "verdicts": dict(verdicts),
            "with_citations": cited,
            "without_citations": criteria - cited,
            "test_states": dict(tests),
        },
        "verification": {
            "instrumented_criteria": criteria - uninstrumented,
            "uninstrumented_criteria": uninstrumented,
            "attempted_requests": len(attempted_ms),
            "skipped_requests": skipped,
            "outcomes": dict(outcomes),
            "budget_outcomes": sum(outcomes[key] for key in BUDGET_OUTCOMES),
            "known_tokens": known_tokens,
            "requests_with_known_tokens": known_token_requests,
            "requests_with_unknown_tokens": unknown_tokens,
            "total_tokens": known_tokens if not unknown_tokens and not uninstrumented else None,
            "request_latency": distribution(attempted_ms),
        },
        "recorded_run_usage": {
            "known_tokens": sum(run_tokens),
            "runs_with_unknown_tokens": unknown_run_tokens,
            "total_tokens": sum(run_tokens) if not unknown_run_tokens else None,
            "known_cost_usd": str(cost_sum),
            "runs_with_unknown_cost": unknown_costs,
            "total_cost_usd": str(cost_sum) if not unknown_costs else None,
        },
        "run_latency": distribution([run.duration_ms for run in runs]),
        "limitations": [
            "Persisted runs exclude failed or unrecorded analyses, decomposition and cache hits.",
            "Recorded usage is not a provider invoice or a measurement of current spend.",
            "Accepted responses passed contract validation; they are not verified correct.",
            "Test states count criterion records, not distinct test executions.",
            "Missing criterion telemetry cannot distinguish local analysis from older model runs.",
        ],
    }
