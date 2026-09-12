import argparse
import json
from pathlib import Path

from services.analysis.analysis_retrieval import export_texts, load_hybrid, review_criteria
from services.analysis.decompose import Decomposition, RuleDecomposer
from services.analysis.domain import Criterion
from services.analysis.embedding_artifacts import read_json, write_json
from services.analysis.engine import analyze
from services.analysis.model_decompose import ModelDecomposer
from services.analysis.repository import index_change
from services.analysis.verifier import ModelVerifier


def read_criteria(path: Path) -> list[Criterion]:
    payload = read_json(path)
    if isinstance(payload, dict):
        return Decomposition.model_validate(payload).criteria
    if not isinstance(payload, list):
        raise TypeError("Criteria file must contain a criteria list or detailed decomposition")
    return [Criterion.model_validate(c) for c in payload]


def main():
    parser = argparse.ArgumentParser(description="Review requirements against committed source")
    commands = parser.add_subparsers(dest="command", required=True)
    split = commands.add_parser("decompose", help="Save editable acceptance criteria as JSON")
    split.add_argument("requirement", type=Path)
    split.add_argument("--output", required=True, type=Path)
    split.add_argument(
        "--details", action="store_true", help="Include context, review guidance and usage in JSON"
    )
    split.add_argument(
        "--model", action="store_true", help="Send requirement to configured provider"
    )
    review = commands.add_parser("analyze")
    export = commands.add_parser(
        "export-inputs", help="Export exact local analysis embedding texts"
    )
    export.add_argument("--output", type=Path, required=True)
    for command in (review, export):
        command.add_argument("repository", type=Path)
        command.add_argument("--base", required=True)
        command.add_argument("--head", default="HEAD")
        command.add_argument("--requirement", required=True, type=Path)
        command.add_argument("--criteria", type=Path)
    review.add_argument("--embeddings", type=Path, help="Opt in to a local hybrid vector bundle")
    review.add_argument("--window", type=int, default=50)
    review.add_argument("--rrf-k", type=int, default=60)
    review.add_argument(
        "--model", action="store_true", help="Send selected source to configured model provider"
    )
    review.add_argument("--json", action="store_true")
    args = parser.parse_args()
    try:
        requirement = args.requirement.read_text(encoding="utf-8")
        if args.command == "decompose":
            decomposer = ModelDecomposer() if args.model else RuleDecomposer()
            proposal = decomposer.decompose(requirement)
            args.output.write_text(
                proposal.model_dump_json(indent=2)
                if args.details
                else json.dumps([c.model_dump() for c in proposal.criteria], indent=2),
                encoding="utf-8",
            )
            print(f"Review and edit criteria in {args.output} before analysis.")
            print(f"Decomposer: {proposal.version}")
            if proposal.context:
                print(f"Context: {proposal.context}")
            for assumption in proposal.assumptions:
                print(f"Proposed assumption: {assumption}")
            for question in proposal.questions:
                print(f"Review: {question}")
            return
        criteria = read_criteria(args.criteria) if args.criteria else None
        if args.command == "export-inputs":
            if args.output.exists() or args.output.is_symlink():
                raise ValueError("Embedding input export requires a new output path")
            selected = review_criteria(requirement, criteria)
            index = index_change(args.repository, args.base, args.head)
            texts = export_texts(index, selected)
            write_json(args.output, texts)
            print(
                json.dumps(
                    {"inputs": len(texts), "base": index["base_sha"], "head": index["head_sha"]}
                )
            )
            return
        if not args.embeddings and (args.window != 50 or args.rrf_k != 60):
            raise ValueError("Fusion options require --embeddings")
        hybrid = (
            load_hybrid(args.embeddings, window=args.window, rrf_k=args.rrf_k)
            if args.embeddings
            else None
        )
        result = analyze(
            args.repository,
            args.base,
            args.head,
            requirement,
            criteria,
            ModelVerifier() if args.model else None,
            hybrid=hybrid,
        )
        if args.json:
            print(result.model_dump_json(indent=2))
            return
        print(f"SpecGuard | {result.repository} | {result.base_sha[:8]}..{result.head_sha[:8]}")
        print(f"Retriever: {result.versions['retriever']}")
        for item in result.results:
            print(f"\n[{item.verdict}] {item.criterion.text}\n{item.rationale}")
            print(
                f"Model confidence: {item.confidence if item.confidence is not None else 'not available'} | Tests: {item.tests.status}"
            )
            for evidence in item.evidence:
                print(
                    f"  {evidence.path}:{evidence.start_line}-{evidence.end_line} ({evidence.revision[:8]})"
                )
            if item.uncertainty:
                print(f"Uncertainty: {item.uncertainty}")
    except (ValueError, TypeError, OSError) as error:
        parser.exit(2, f"specguard: {error}\n")


if __name__ == "__main__":
    main()
