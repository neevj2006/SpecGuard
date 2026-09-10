"""Prepare an explicitly unreviewed annotation manifest from a saved run."""

import argparse
import json
from pathlib import Path

from services.analysis.domain import AnalysisRun


def prepare_labels(payload: dict, group: str) -> dict:
    run = AnalysisRun.model_validate(payload.get("run", payload))
    if not group.strip() or not run.results:
        raise ValueError("A repository group and nonempty run are required")
    if len({r.criterion.id for r in run.results}) != len(run.results):
        raise ValueError("Criterion identifiers must be unique")
    return {
        "version": "draft-1",
        "annotation_status": None,
        "runs": [run.model_dump(mode="json")],
        "labels": [
            {
                "run_id": run.id,
                "criterion_id": result.criterion.id,
                "group": group,
                "split": None,
                "expected": None,
                "reviewer": None,
                "source": None,
                "license": None,
                "citation_correctness": {e.id: None for e in result.evidence},
            }
            for result in run.results
        ],
    }


def main():
    parser = argparse.ArgumentParser(description="Prepare blank human-review labels from a run")
    parser.add_argument("run", type=Path)
    parser.add_argument("--group", required=True, help="Stable repository identity across cases")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        with args.run.open("rb") as source:
            content = source.read(20_000_001)
        if len(content) > 20_000_000:
            raise ValueError("Input exceeds 20 MB")
        draft = prepare_labels(json.loads(content), args.group)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8") as output:
            output.write(json.dumps(draft, indent=2) + "\n")
    except (ValueError, OSError, AttributeError):
        parser.exit(2, "Cannot prepare labels: check input, group and a new output path.\n")
    print(f"Unreviewed template written to {args.output}; complete labels before evaluation.")


if __name__ == "__main__":
    main()
