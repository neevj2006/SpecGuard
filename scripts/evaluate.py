import argparse
import json
from pathlib import Path

from services.analysis.evaluation import FixtureBenchmark, evaluate
from services.analysis.hybrid import HybridRetriever, VectorBundle

parser = argparse.ArgumentParser(description="Evaluate the versioned synthetic retrieval fixtures")
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
benchmark = FixtureBenchmark.model_validate_json(args.manifest.read_text(encoding="utf-8"))
hybrid = None
if args.embeddings:
    with args.embeddings.open("rb") as source:
        content = source.read(20_000_001)
    if len(content) > 20_000_000:
        parser.error("Embedding bundle exceeds 20 MB")
    hybrid = HybridRetriever(
        VectorBundle.model_validate_json(content), window=args.window, rrf_k=args.rrf_k
    )
inputs: dict[str, str] | None = {} if args.export_inputs else None
report = evaluate(benchmark, args.k, hybrid=hybrid, embedding_inputs=inputs)
if args.export_inputs:
    args.export_inputs.parent.mkdir(parents=True, exist_ok=True)
    args.export_inputs.write_text(json.dumps(inputs, indent=2), encoding="utf-8")
args.output.parent.mkdir(parents=True, exist_ok=True)
args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
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
