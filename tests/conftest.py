import subprocess

import pytest


@pytest.fixture
def repository(tmp_path):
    def run(*args):
        return subprocess.check_output(["git", "-C", str(tmp_path), *args]).decode().strip()

    run("init", "-q")
    run("config", "user.name", "Fixture")
    run("config", "user.email", "fixture@example.test")
    (tmp_path / "discount.ts").write_text(
        "export function discount(total: number) {\n  return total;\n}\n"
    )
    run("add", ".")
    run("commit", "-qm", "Add checkout fixture")
    base = run("rev-parse", "HEAD")
    (tmp_path / "discount.ts").write_text(
        "export function discount(total: number) {\n  return Math.max(0, total * 0.9);\n}\n"
    )
    run("add", ".")
    run("commit", "-qm", "Apply checkout discount")
    return tmp_path, base, run("rev-parse", "HEAD")
