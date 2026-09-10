import argparse
import json
from pathlib import Path

from services.analysis.verdict_evaluation import VerdictBenchmark, evaluate_verdicts


def main():
    parser = argparse.ArgumentParser(
        description="Evaluate saved runs against reviewed verdict labels"
    )
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--output", type=Path, default=Path(".specguard/verdict-report.json"))
    args = parser.parse_args()
    try:
        with args.manifest.open("rb") as source:
            content = source.read(20_000_001)
        if len(content) > 20_000_000:
            raise ValueError("Verdict benchmark exceeds 20 MB")
        report = evaluate_verdicts(VerdictBenchmark.model_validate_json(content))
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    except (ValueError, OSError):
        parser.exit(
            2, "Invalid or unreadable benchmark; check the schema, labels and file paths.\n"
        )
    print(f"Verdict evaluation written to {args.output}")


if __name__ == "__main__":
    main()
