import argparse
import json
import time
from pathlib import Path

from services.analysis.embedding_artifacts import read_json, validate_inputs, write_json
from services.analysis.embeddings import generate_bundle
from services.analysis.local_encoder import LocalSentenceEncoder


def main():
    parser = argparse.ArgumentParser(
        description="Encode exported benchmark inputs with a local model"
    )
    parser.add_argument("inputs", type=Path)
    parser.add_argument("--model-dir", type=Path, required=True)
    parser.add_argument(
        "--model", required=True, help="Logical model identifier, not a secret or path"
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cache", type=Path)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--batch-size", type=int, default=16)
    args = parser.parse_args()
    try:
        targets = [p.resolve() for p in (args.inputs, args.output, args.cache, args.report) if p]
        if len(targets) != len(set(targets)):
            raise ValueError("Input, output, cache and report must have distinct paths")
        if args.output.exists() or (args.report and args.report.exists()):
            raise ValueError("Output and report paths must be new")
        if any(path.is_relative_to(args.model_dir.resolve()) for path in targets[1:]):
            raise ValueError("Write embedding artifacts outside the model directory")
        started = time.perf_counter()
        inputs = validate_inputs(read_json(args.inputs))
        encoder = LocalSentenceEncoder(args.model_dir, args.model)
        bundle, stats = generate_bundle(
            inputs, encoder, batch_size=args.batch_size, cache_path=args.cache
        )
        encoder.verify_unchanged()
        write_json(args.output, bundle.model_dump())
        report = {
            "generator": "local-encoder/1",
            "runtime_versions": getattr(encoder, "runtime_versions", {}),
            "model": bundle.model,
            "revision": bundle.revision,
            "dimensions": bundle.dimensions,
            **stats,
            "duration_ms": round((time.perf_counter() - started) * 1000),
            "limitation": "Embedding generation does not establish retrieval quality.",
        }
        if args.report:
            write_json(args.report, report)
    except (ValueError, OSError, RuntimeError, TypeError):
        parser.exit(
            2,
            "Embedding generation failed; check inputs, local model, token limits and artifact paths. Valid cache batches can be reused.\n",
        )
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
