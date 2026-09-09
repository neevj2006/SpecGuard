"""Read committed blobs only; never install or execute the reviewed repository."""

import json
import re
import subprocess
from pathlib import Path

from services.analysis.domain import Evidence

EXCLUDED = {"node_modules", "dist", "build", "coverage", ".next", "vendor", ".git"}
EXTENSIONS = {".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs"}


def git(repo: Path, *args: str) -> bytes:
    result = subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, timeout=30, check=False
    )
    if result.returncode:
        raise ValueError("Unable to read repository revision")
    if len(result.stdout) > 15_000_000:
        raise ValueError("Repository response exceeds analysis budget")
    return result.stdout


def resolve(repo: Path, revision: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_./~^@{}-]{1,200}", revision) or revision.startswith("-"):
        raise ValueError("Invalid revision")
    return (
        git(repo, "rev-parse", "--verify", "--end-of-options", f"{revision}^{{commit}}")
        .decode()
        .strip()
    )


def index_change(repo: Path, base: str, head: str) -> dict:
    base_sha, head_sha = resolve(repo, base), resolve(repo, head)
    changed = set(
        git(repo, "diff", "--no-ext-diff", "--name-only", "-z", base_sha, head_sha)
        .decode()
        .split("\0")
    )
    files: list[dict[str, str]] = []
    excluded: list[dict[str, str]] = []
    total = 0
    entries = git(repo, "ls-tree", "-r", "-z", head_sha).decode().split("\0")
    entries.sort(key=lambda entry: (entry.split("\t", 1)[-1] not in changed, entry))
    for entry in entries:
        if not entry:
            continue
        metadata, path = entry.split("\t", 1)
        mode, kind, oid = metadata.split()
        if Path(path).suffix not in EXTENSIONS:
            continue
        reason = ""
        if mode not in {"100644", "100755"} or kind != "blob":
            reason = "Not a regular source file"
        elif EXCLUDED.intersection(Path(path).parts) or path.endswith(".d.ts") or ".min." in path:
            reason = "Generated or excluded source"
        if reason:
            excluded.append({"path": path, "reason": reason})
            continue
        size = int(git(repo, "cat-file", "-s", oid))
        if size > 100_000 or total + size > 2_000_000 or len(files) >= 200:
            excluded.append({"path": path, "reason": "Source budget exceeded"})
            continue
        try:
            source = git(repo, "cat-file", "blob", oid).decode("utf-8")
        except UnicodeDecodeError:
            excluded.append({"path": path, "reason": "Not UTF-8 source"})
            continue
        files.append({"path": path, "source": source})
        total += size
    index = parse_sources(files, base_sha, head_sha, changed, excluded)
    spans_by_path = {}
    for path in {chunk.path for chunk in index["chunks"] if chunk.changed}:
        patch = git(
            repo,
            "diff",
            "--no-ext-diff",
            "--no-textconv",
            "--unified=0",
            base_sha,
            head_sha,
            "--",
            path,
        ).decode("utf-8", errors="replace")
        spans = []
        for first, count in re.findall(
            r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@", patch, re.MULTILINE
        ):
            start, length = int(first), int(count) if count else 1
            spans.append((max(1, start), max(1, start + max(length, 1) - 1)))
        spans_by_path[path] = spans
    index["chunks"] = [
        chunk.model_copy(
            update={
                "changed": any(
                    chunk.start_line <= end and chunk.end_line >= start
                    for start, end in spans_by_path.get(chunk.path, [])
                )
            }
        )
        for chunk in index["chunks"]
    ]
    return index


def parse_sources(
    files: list[dict[str, str]],
    base_sha: str,
    head_sha: str,
    changed: set[str],
    excluded: list[dict[str, str]],
) -> dict:
    script = Path(__file__).resolve().parents[2] / "indexing" / "parse.mjs"
    result = subprocess.run(
        ["node", str(script)],
        input=json.dumps({"files": files, "revision": head_sha}),
        text=True,
        capture_output=True,
        timeout=30,
        encoding="utf-8",
        check=False,
    )
    if result.returncode:
        raise ValueError("TypeScript parser unavailable; run npm install at the project root")
    parsed = json.loads(result.stdout)
    chunks: list[Evidence] = []
    for file in parsed["files"]:
        if file["diagnostics"]:
            excluded.append({"path": file["path"], "reason": "Syntax errors; evidence omitted"})
            continue
        chunks.extend(
            Evidence(**chunk, changed=chunk["path"] in changed) for chunk in file["chunks"]
        )
    from services.analysis.graph import resolve_imports

    return {
        "base_sha": base_sha,
        "head_sha": head_sha,
        "chunks": chunks,
        "excluded": excluded,
        "parser_version": parsed["version"],
        "sources": {file["path"]: file["source"] for file in files},
        "imports": resolve_imports(
            [
                edge
                for file in parsed["files"]
                if not file["diagnostics"]
                for edge in file["imports"]
            ],
            {chunk.path for chunk in chunks},
        ),
    }


def validate_citation(evidence: Evidence, sources: dict[str, str], revision: str) -> bool:
    source = sources.get(evidence.path)
    if source is None or evidence.revision != revision:
        return False
    return (
        "\n".join(source.splitlines()[evidence.start_line - 1 : evidence.end_line])
        == evidence.quote
    )
