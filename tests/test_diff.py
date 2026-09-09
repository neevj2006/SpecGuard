import subprocess

from services.analysis.repository import index_change


def commit(repo, *args):
    return subprocess.check_output(["git", "-C", str(repo), *args]).decode().strip()


def test_only_enclosing_changed_symbol_gets_boost(repository):
    repo, _, _ = repository
    path = repo / "discount.ts"
    path.write_text(
        "export function discount() { return 10; }\n\nexport function receipt() { return false; }\n"
    )
    commit(repo, "add", ".")
    commit(repo, "commit", "-qm", "Add independent symbols")
    base = commit(repo, "rev-parse", "HEAD")
    path.write_text(
        "export function discount() { return 20; }\n\nexport function receipt() { return false; }\n"
    )
    commit(repo, "add", ".")
    commit(repo, "commit", "-qm", "Adjust discount")
    chunks = index_change(repo, base, "HEAD")["chunks"]
    assert next(c for c in chunks if c.symbol == "discount").changed
    assert not next(c for c in chunks if c.symbol == "receipt").changed


def test_renamed_source_uses_current_path_and_deleted_file_is_absent(repository):
    repo, base, _ = repository
    commit(repo, "mv", "discount.ts", "pricing.ts")
    commit(repo, "commit", "-qm", "Rename pricing module")
    assert {c.path for c in index_change(repo, base, "HEAD")["chunks"]} == {"pricing.ts"}
    commit(repo, "rm", "pricing.ts")
    commit(repo, "commit", "-qm", "Remove pricing module")
    assert index_change(repo, base, "HEAD")["chunks"] == []
