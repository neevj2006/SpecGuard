from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from services.analysis.engine import analyze
from services.api.schema import feedback
from services.api.store import Store


def test_notes_retention_and_cascade(repository, tmp_path):
    repo, base, head = repository
    run = analyze(repo, base, head, "discount")
    run.created_at = datetime.now(UTC) - timedelta(days=40)
    store = Store(tmp_path / "retention.sqlite")
    store.save("alice", run)
    store.save("bob", run)
    store.feedback("alice", run.id, run.results[0].criterion.id, "Review this")
    assert store.notes("alice", run.id) == {run.results[0].criterion.id: "Review this"}
    assert store.expire("alice", 30) == 1
    with pytest.raises(KeyError):
        store.notes("alice", run.id)
    assert store.get("bob", run.id).id == run.id
    with store.engine.connect() as db:
        assert db.execute(select(feedback)).all() == []


def test_duplicate_analysis_uses_saved_verdict(repository, tmp_path):
    repo, base, head = repository
    store = Store(tmp_path / "cache.sqlite")
    first = analyze(repo, base, head, "discount")
    store.save("alice", first)
    again = analyze(
        repo, base, head, "discount", lookup=lambda identifier: store.get("alice", identifier)
    )
    assert again.created_at == first.created_at
