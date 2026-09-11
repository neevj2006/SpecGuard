import argparse
import json
from pathlib import Path

from services.analysis.embedding_artifacts import read_json, write_json
from services.analysis.retrieval_comparison import compare_retrieval


def main():
    parser = argparse.ArgumentParser(
        description="Compare paired retrieval methods by repository group"
    )
    parser.add_argument("report", type=Path)
    parser.add_argument("--baseline", default="bm25_with_boosts")
    parser.add_argument("--candidate", default="hybrid_rrf")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--samples", type=int, default=2000)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--confidence", type=float, default=0.95)
    args = parser.parse_args()
    try:
        if args.report.resolve() == args.output.resolve() or args.output.exists():
            raise ValueError("Output must be a new path")
        result = compare_retrieval(
            read_json(args.report),
            args.baseline,
            args.candidate,
            samples=args.samples,
            seed=args.seed,
            confidence=args.confidence,
        )
        write_json(args.output, result)
    except (ValueError, TypeError, OSError):
        parser.exit(
            2, "Comparison failed; check report metrics, groups, options and output path.\n"
        )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
