import argparse
import json
from pathlib import Path

from services.analysis.review_agreement import (
    Adjudication,
    adjudicate,
    compare_reviews,
    decision_template,
)
from services.analysis.verdict_evaluation import VerdictBenchmark


def read_json(path: Path):
    with path.open("rb") as source:
        content = source.read(20_000_001)
    if len(content) > 20_000_000:
        raise ValueError("Review input exceeds 20 MB")
    return json.loads(content)


def main():
    parser = argparse.ArgumentParser(description="Compare reviews or apply explicit adjudication")
    parser.add_argument("left", type=Path)
    parser.add_argument("right", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--template", action="store_true")
    mode.add_argument("--decisions", type=Path)
    args = parser.parse_args()
    try:
        left, right = [
            VerdictBenchmark.model_validate(read_json(path)) for path in (args.left, args.right)
        ]
        if args.decisions:
            result = adjudicate(
                left, right, Adjudication.model_validate(read_json(args.decisions))
            ).model_dump(mode="json")
        else:
            result = (
                decision_template(left, right) if args.template else compare_reviews(left, right)
            )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8") as output:
            output.write(json.dumps(result, indent=2) + "\n")
    except (ValueError, OSError):
        parser.exit(
            2,
            "Cannot process reviews: verify schemas, matching runs, provenance and a new output path.\n",
        )
    print(f"Review artifact written to {args.output}")


if __name__ == "__main__":
    main()
