"""Owner-scoped vector artifacts; source text is never stored in this table."""

import hashlib
import json
from datetime import UTC, datetime

from sqlalchemy import delete, select

from services.analysis.hybrid import VectorBundle
from services.api.schema import embedding_bundles as table
from services.api.store import Store


class BundleStore:
    def __init__(self, store: Store):
        self.store = store

    def save(self, owner: str, repository: str, binding: str, bundle: VectorBundle) -> dict:
        payload = json.dumps(bundle.model_dump(), sort_keys=True, allow_nan=False)
        if len(payload.encode()) > 20_000_000:
            raise ValueError("Vector bundle exceeds storage limit")
        digest = hashlib.sha256(payload.encode()).hexdigest()
        identifier = hashlib.sha256(f"{binding}:{digest}".encode()).hexdigest()
        summary = {
            "id": identifier,
            "repository": repository,
            "binding_sha256": binding,
            "created_at": datetime.now(UTC).isoformat(),
            "model": bundle.model,
            "revision": bundle.revision,
            "dimensions": bundle.dimensions,
            "vector_count": len(bundle.vectors),
            "bundle_sha256": digest,
        }
        with self.store.engine.begin() as db:
            db.execute(
                self.store._insert(table)
                .values(
                    owner=owner,
                    id=identifier,
                    repository=repository,
                    binding=binding,
                    created_at=summary["created_at"],
                    summary=json.dumps(summary),
                    payload=payload,
                )
                .on_conflict_do_nothing()
            )
        return self.get(owner, identifier)[0]

    def get(self, owner: str, identifier: str) -> tuple[dict, VectorBundle]:
        with self.store.engine.connect() as db:
            row = db.execute(
                select(table.c.summary, table.c.payload).where(
                    table.c.owner == owner, table.c.id == identifier
                )
            ).first()
        if row is None:
            raise KeyError(identifier)
        return json.loads(row.summary), VectorBundle.model_validate_json(row.payload)

    def list(self, owner: str, limit: int = 100, offset: int = 0) -> list[dict]:
        with self.store.engine.connect() as db:
            summaries = (
                db.execute(
                    select(table.c.summary)
                    .where(table.c.owner == owner)
                    .order_by(table.c.created_at.desc(), table.c.id)
                    .limit(limit)
                    .offset(offset)
                )
                .scalars()
                .all()
            )
        return [json.loads(summary) for summary in summaries]

    def delete(self, owner: str, identifier: str):
        with self.store.engine.begin() as db:
            result = db.execute(
                delete(table).where(table.c.owner == owner, table.c.id == identifier)
            )
            if not result.rowcount:
                raise KeyError(identifier)
