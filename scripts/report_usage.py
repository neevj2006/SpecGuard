"""Summarize exported run JSON offline without exposing review content."""

import argparse
import json
from pathlib import Path

from services.analysis.domain import AnalysisRun
from services.analysis.embedding_artifacts import decode_json, write_json
from services.analysis.usage_report import MAX_RUNS, summarize_usage


def load_runs(paths: list[Path]) -> list[AnalysisRun]:
    if not 1 <= len(paths) <= MAX_RUNS:
        raise ValueError("Supply between 1 and 1000 run files")
    runs = []
    total_bytes = 0
    for path in paths:
        with path.open("rb") as source:
            content = source.read(20_000_000 - total_bytes + 1)
        total_bytes += len(content)
        if total_bytes > 20_000_000:
            raise ValueError("Combined run files exceed 20 MB")
        payload = decode_json(content)
        if isinstance(payload, dict) and "run" in payload:
            if set(payload) != {"run", "feedback"}:
                raise ValueError("Invalid run export envelope")
            payload = payload["run"]
        runs.append(AnalysisRun.model_validate(payload))
    return runs


def main():
    parser = argparse.ArgumentParser(description="Report persisted analysis usage offline")
    parser.add_argument("runs", nargs="+", type=Path, help="Run JSON or API run exports")
    parser.add_argument("--output", type=Path, help="New JSON report path; otherwise use stdout")
    args = parser.parse_args()
    try:
        report = summarize_usage(load_runs(args.runs))
        if args.output:
            write_json(args.output, report)
        else:
            print(json.dumps(report, indent=2, allow_nan=False))
    except (ValueError, TypeError, OSError):
        parser.exit(2, "Usage report failed. Check run exports and use a new output path.\n")


if __name__ == "__main__":
    main()
