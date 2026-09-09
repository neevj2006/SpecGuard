import argparse
import json
from pathlib import Path

from services.analysis.evaluation import FixtureBenchmark, evaluate

parser = argparse.ArgumentParser(description="Evaluate the versioned synthetic retrieval fixtures")
parser.add_argument(
    "--manifest", type=Path, default=Path("tests/fixtures/retrieval-benchmark.json")
)
parser.add_argument("--output", type=Path, default=Path(".specguard/retrieval-report.json"))
parser.add_argument("--k", type=int, default=3)
args = parser.parse_args()
benchmark = FixtureBenchmark.model_validate_json(args.manifest.read_text(encoding="utf-8"))
report = evaluate(benchmark, args.k)
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
