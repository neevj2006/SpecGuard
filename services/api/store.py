"""Transactional persistence; every user-owned lookup includes its owner."""

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import create_engine, delete, event, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from services.analysis.domain import AnalysisRun
from services.api.schema import (
    deliveries,
    embedding_bundles,
    feedback,
    installations,
    metadata,
    publications,
    runs,
)


class Store:
    def __init__(self, path: Path | str, *, initialize: bool = True):
        if isinstance(path, Path) or "://" not in str(path):
            path = Path(path)
            path.parent.mkdir(parents=True, exist_ok=True)
            url = f"sqlite:///{path.resolve().as_posix()}"
        else:
            url = str(path)
        self.engine = create_engine(url, pool_pre_ping=True)
        if self.engine.dialect.name == "sqlite":

            @event.listens_for(self.engine, "connect")
            def configure(connection, _record):
                connection.execute("PRAGMA foreign_keys = ON")
                connection.execute("PRAGMA busy_timeout = 5000")

        if initialize:
            metadata.create_all(self.engine)

    def _insert(self, table):
        return (
            pg_insert(table) if self.engine.dialect.name == "postgresql" else sqlite_insert(table)
        )

    def save(self, owner: str, run: AnalysisRun) -> AnalysisRun:
        with self.engine.begin() as db:
            db.execute(
                self._insert(runs)
                .values(
                    owner=owner,
                    id=run.id,
                    created_at=run.created_at.isoformat(),
                    payload=run.model_dump_json(),
                )
                .on_conflict_do_nothing()
            )
        return self.get(owner, run.id)

    def get(self, owner: str, identifier: str) -> AnalysisRun:
        with self.engine.connect() as db:
            payload = db.execute(
                select(runs.c.payload).where(runs.c.owner == owner, runs.c.id == identifier)
            ).scalar_one_or_none()
        if payload is None:
            raise KeyError(identifier)
        return AnalysisRun.model_validate_json(payload)

    def list(self, owner: str, limit: int = 100, offset: int = 0) -> list[AnalysisRun]:
        with self.engine.connect() as db:
            payloads = (
                db.execute(
                    select(runs.c.payload)
                    .where(runs.c.owner == owner)
                    .order_by(runs.c.created_at.desc(), runs.c.id)
                    .limit(limit)
                    .offset(offset)
                )
                .scalars()
                .all()
            )
        return [AnalysisRun.model_validate_json(payload) for payload in payloads]

    def delete(self, owner: str, identifier: str):
        with self.engine.begin() as db:
            result = db.execute(delete(runs).where(runs.c.owner == owner, runs.c.id == identifier))
            if not result.rowcount:
                raise KeyError(identifier)

    def feedback(self, owner: str, identifier: str, criterion: str, note: str):
        run = self.get(owner, identifier)
        if criterion not in {r.criterion.id for r in run.results}:
            raise KeyError(criterion)
        with self.engine.begin() as db:
            db.execute(
                self._insert(feedback)
                .values(owner=owner, run_id=identifier, criterion_id=criterion, note=note)
                .on_conflict_do_update(
                    index_elements=["owner", "run_id", "criterion_id"], set_={"note": note}
                )
            )

    def notes(self, owner: str, identifier: str) -> dict[str, str]:
        self.get(owner, identifier)
        with self.engine.connect() as db:
            return {
                row[0]: row[1]
                for row in db.execute(
                    select(feedback.c.criterion_id, feedback.c.note).where(
                        feedback.c.owner == owner, feedback.c.run_id == identifier
                    )
                )
            }

    def expire(self, owner: str, days: int) -> int:
        if days < 1:
            raise ValueError("Retention must be at least one day")
        cutoff = (datetime.now(UTC) - timedelta(days=days)).isoformat()
        with self.engine.begin() as db:
            db.execute(
                delete(embedding_bundles).where(
                    embedding_bundles.c.owner == owner, embedding_bundles.c.created_at < cutoff
                )
            )
            return db.execute(
                delete(runs).where(runs.c.owner == owner, runs.c.created_at < cutoff)
            ).rowcount

    def delete_repository(self, owner: str, repository: str) -> int:
        identifiers = [run.id for run in self.list(owner, 100000) if run.repository == repository]
        with self.engine.begin() as db:
            db.execute(
                delete(embedding_bundles).where(
                    embedding_bundles.c.owner == owner, embedding_bundles.c.repository == repository
                )
            )
            return db.execute(
                delete(runs).where(runs.c.owner == owner, runs.c.id.in_(identifiers))
            ).rowcount

    def claim_delivery(self, identifier: str) -> bool:
        with self.engine.begin() as db:
            return bool(
                db.execute(
                    self._insert(deliveries)
                    .values(id=identifier, received_at=datetime.now(UTC).isoformat())
                    .on_conflict_do_nothing()
                ).rowcount
            )

    def allow_installation(self, owner: str, installation_id: int):
        with self.engine.begin() as db:
            db.execute(
                self._insert(installations)
                .values(owner=owner, id=installation_id)
                .on_conflict_do_nothing()
            )

    def installation_ids(self, owner: str) -> Sequence[int]:
        with self.engine.connect() as db:
            return list(
                db.execute(
                    select(installations.c.id).where(installations.c.owner == owner)
                ).scalars()
            )

    def record_publication(self, owner: str, run_id: str, repository: str, number: int, url: str):
        self.get(owner, run_id)
        with self.engine.begin() as db:
            db.execute(
                self._insert(publications)
                .values(
                    owner=owner,
                    run_id=run_id,
                    repository=repository,
                    pull_number=number,
                    comment_url=url,
                    created_at=datetime.now(UTC).isoformat(),
                )
                .on_conflict_do_nothing()
            )

    def publication(self, owner: str, run_id: str) -> str | None:
        self.get(owner, run_id)
        with self.engine.connect() as db:
            return db.execute(
                select(publications.c.comment_url).where(
                    publications.c.owner == owner, publications.c.run_id == run_id
                )
            ).scalar_one_or_none()
