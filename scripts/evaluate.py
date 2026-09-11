import argparse
import json
from pathlib import Path

from services.analysis.embedding_artifacts import read_json, write_json
from services.analysis.evaluation import FixtureBenchmark, evaluate
from services.analysis.hybrid import HybridRetriever, VectorBundle


def validate_paths(inputs: list[Path], outputs: list[Path]):
    paths = [path.resolve() for path in inputs + outputs]
    if len(set(paths)) != len(paths):
        raise ValueError("Input and output paths must be distinct")
    for output in outputs:
        if output.exists() or output.is_symlink():
            raise ValueError("Output paths must be new")
    for output in paths[len(inputs) :]:
        if any(path != output and path.is_relative_to(output) for path in paths):
            raise ValueError("An output cannot contain another artifact path")
        if any(parent.exists() and not parent.is_dir() for parent in output.parents):
            raise ValueError("Output parent must be a directory")


def main():
    parser = argparse.ArgumentParser(
        description="Evaluate the versioned synthetic retrieval fixtures"
    )
    parser.add_argument(
        "--manifest", type=Path, default=Path("tests/fixtures/retrieval-benchmark.json")
    )
    parser.add_argument("--output", type=Path, default=Path(".specguard/retrieval-report.json"))
    parser.add_argument("--k", type=int, default=3)
    parser.add_argument("--embeddings", type=Path, help="Offline content-addressed vector bundle")
    parser.add_argument("--window", type=int, default=50)
    parser.add_argument("--rrf-k", type=int, default=60)
    parser.add_argument(
        "--export-inputs", type=Path, help="Export exact texts keyed by SHA-256 for local embedding"
    )
    args = parser.parse_args()
    try:
        sources = [args.manifest] + ([args.embeddings] if args.embeddings else [])
        outputs = [args.output] + ([args.export_inputs] if args.export_inputs else [])
        validate_paths(sources, outputs)
        if not 1 <= args.k <= 100:
            raise ValueError("K must be between 1 and 100")
        if not 1 <= args.window <= 1000 or not 1 <= args.rrf_k <= 1000:
            raise ValueError("Invalid fusion configuration")
        if args.embeddings and args.k > args.window:
            raise ValueError("K must fit the fusion window")
        benchmark = FixtureBenchmark.model_validate(read_json(args.manifest))
        hybrid = None
        if args.embeddings:
            hybrid = HybridRetriever(
                VectorBundle.model_validate(read_json(args.embeddings)),
                window=args.window,
                rrf_k=args.rrf_k,
            )
        inputs: dict[str, str] | None = {} if args.export_inputs else None
        report = evaluate(benchmark, args.k, hybrid=hybrid, embedding_inputs=inputs)
        if args.export_inputs and inputs is not None:
            write_json(args.export_inputs, inputs)
        write_json(args.output, report)
    except (ValueError, TypeError, OSError, RuntimeError):
        parser.exit(
            2,
            "Evaluation failed; check input JSON, fixture labels, embedding coverage, options and new output paths. A completed input export may remain if report publication failed.\n",
        )
    print(
        json.dumps(
            {
                "report": str(args.output),
                "aggregates": report["aggregates"],
                "limitation": report["limitation"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
