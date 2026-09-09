"""Local persistence with ownership checks at every object lookup."""

import sqlite3
from contextlib import contextmanager
from pathlib import Path

from services.analysis.domain import AnalysisRun


class Store:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS runs (
                    owner TEXT NOT NULL, id TEXT NOT NULL, created_at TEXT NOT NULL,
                    payload TEXT NOT NULL, PRIMARY KEY(owner, id));
                CREATE TABLE IF NOT EXISTS feedback (
                    owner TEXT NOT NULL, run_id TEXT NOT NULL, criterion_id TEXT NOT NULL,
                    note TEXT NOT NULL, PRIMARY KEY(owner, run_id, criterion_id),
                    FOREIGN KEY(owner, run_id) REFERENCES runs(owner, id) ON DELETE CASCADE);
                PRAGMA user_version = 1;
            """)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path)
        db.execute("PRAGMA foreign_keys = ON")
        try:
            with db:
                yield db
        finally:
            db.close()

    def save(self, owner: str, run: AnalysisRun) -> AnalysisRun:
        with self.connect() as db:
            db.execute(
                "INSERT OR IGNORE INTO runs VALUES (?, ?, ?, ?)",
                (owner, run.id, run.created_at.isoformat(), run.model_dump_json()),
            )
        return self.get(owner, run.id)

    def get(self, owner: str, identifier: str) -> AnalysisRun:
        with self.connect() as db:
            row = db.execute(
                "SELECT payload FROM runs WHERE owner = ? AND id = ?", (owner, identifier)
            ).fetchone()
        if not row:
            raise KeyError(identifier)
        return AnalysisRun.model_validate_json(row[0])

    def list(self, owner: str) -> list[AnalysisRun]:
        with self.connect() as db:
            rows = db.execute(
                "SELECT payload FROM runs WHERE owner = ? ORDER BY created_at DESC LIMIT 100",
                (owner,),
            ).fetchall()
        return [AnalysisRun.model_validate_json(row[0]) for row in rows]

    def delete(self, owner: str, identifier: str):
        self.get(owner, identifier)
        with self.connect() as db:
            db.execute("DELETE FROM runs WHERE owner = ? AND id = ?", (owner, identifier))

    def feedback(self, owner: str, identifier: str, criterion: str, note: str):
        run = self.get(owner, identifier)
        if criterion not in {r.criterion.id for r in run.results}:
            raise KeyError(criterion)
        with self.connect() as db:
            db.execute(
                "INSERT OR REPLACE INTO feedback VALUES (?, ?, ?, ?)",
                (owner, identifier, criterion, note),
            )
