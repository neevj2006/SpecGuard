"""Create a small committed repository for a repeatable local demonstration."""

import argparse
import subprocess
from pathlib import Path


def create_demo(destination: Path):
    if destination.exists():
        raise ValueError("Choose a destination that does not exist")
    destination.mkdir(parents=True)

    def git(*args):
        subprocess.run(["git", "-C", str(destination), *args], check=True, capture_output=True)

    git("init", "-q")
    git("config", "user.name", "SpecGuard Fixture")
    git("config", "user.email", "fixture@example.test")
    (destination / "discount.ts").write_text(
        "export function applyDiscount(total: number) {\n  return total;\n}\n", encoding="utf-8"
    )
    git("add", ".")
    git("commit", "-qm", "Add checkout calculation")
    (destination / "discount.ts").write_text(
        "export function applyDiscount(total: number) {\n  return Math.max(0, total * 0.9);\n}\n",
        encoding="utf-8",
    )
    (destination / "requirement.txt").write_text(
        "- Apply a ten percent discount to the total.\n- Send a receipt after checkout.\n",
        encoding="utf-8",
    )
    git("add", ".")
    git("commit", "-qm", "Apply checkout discount")
    print(f"Created {destination}. Compare HEAD~1 with HEAD.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("destination", type=Path)
    create_demo(parser.parse_args().destination)
