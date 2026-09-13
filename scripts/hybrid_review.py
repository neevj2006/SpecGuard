"""Prepare, encode and analyze a server-hosted change in explicit stages."""

import argparse
import json
import os
from pathlib import Path

from services.analysis.embedding_artifacts import read_json
from services.analysis.remote_workflow import ApiClient, analyze_remote, encode, prepare
from services.api.hybrid_routes import ChangeInput


def main():
    parser = argparse.ArgumentParser(description="Run the registered hybrid API workflow")
    commands = parser.add_subparsers(dest="command", required=True)
    export = commands.add_parser("prepare", help="Fetch and pin the change's embedding inputs")
    export.add_argument(
        "change", type=Path, help="JSON with the API change fields and reviewed criteria"
    )
    export.add_argument("directory", type=Path, help="New private workspace directory")
    encoding = commands.add_parser(
        "encode", help="Encode prepared inputs locally without API access"
    )
    encoding.add_argument("directory", type=Path)
    encoding.add_argument("--model-dir", required=True, type=Path)
    encoding.add_argument("--model", required=True)
    encoding.add_argument("--batch-size", type=int, default=16)
    review = commands.add_parser("analyze", help="Register vectors and request a hybrid analysis")
    review.add_argument("directory", type=Path)
    review.add_argument(
        "--use-model", action="store_true", help="Authorize configured server model verification"
    )
    review.add_argument("--window", type=int, default=50)
    review.add_argument("--rrf-k", type=int, default=60)
    args = parser.parse_args()
    client = None
    try:
        if args.command == "encode":
            result = encode(args.directory, args.model_dir, args.model, args.batch_size)
        else:
            client = ApiClient(
                os.environ.get("SPECGUARD_API_URL", "http://127.0.0.1:8000"),
                os.environ.get("SPECGUARD_API_TOKEN", ""),
            )
            if args.command == "prepare":
                result = prepare(
                    client, ChangeInput.model_validate(read_json(args.change)), args.directory
                )
            else:
                result = analyze_remote(
                    client,
                    args.directory,
                    use_model=args.use_model,
                    window=args.window,
                    rrf_k=args.rrf_k,
                )
    except (ValueError, TypeError, OSError, RuntimeError):
        parser.exit(
            2,
            "Hybrid workflow failed. Check configuration and local artifacts; inspect API history before retrying a failed request.\n",
        )
    finally:
        if client is not None:
            client.close()
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
