from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, update

from services.analysis.hybrid import VectorBundle, text_key
from services.api.bundles import BundleStore
from services.api.schema import embedding_bundles
from services.api.store import Store


def sample_bundle():
    return VectorBundle(
        model="synthetic", revision="fixture", dimensions=2, vectors={text_key("source"): [1, 0]}
    )


def test_bundle_storage_is_idempotent_owner_scoped_and_source_free(tmp_path):
    store = Store(tmp_path / "vectors.sqlite")
    bundles = BundleStore(store)
    first = bundles.save("alice", "repo", "a" * 64, sample_bundle())
    assert bundles.save("alice", "repo", "a" * 64, sample_bundle()) == first
    second = bundles.save("alice", "repo", "b" * 64, sample_bundle())
    assert first["id"] != second["id"]
    assert len(bundles.list("alice", 1)) == len(bundles.list("alice", 1, 1)) == 1
    assert bundles.list("bob") == []
    with pytest.raises(KeyError):
        bundles.get("bob", first["id"])
    with pytest.raises(KeyError):
        bundles.delete("bob", first["id"])
    with store.engine.connect() as db:
        payloads = db.execute(select(embedding_bundles.c.payload)).scalars().all()
        assert all('"source"' not in payload for payload in payloads)
    store.engine.dispose()


def test_retention_and_repository_deletion_remove_only_owned_bundles(tmp_path):
    store = Store(tmp_path / "vectors.sqlite")
    bundles = BundleStore(store)
    old = bundles.save("alice", "old-repo", "a" * 64, sample_bundle())
    bundles.save("bob", "old-repo", "a" * 64, sample_bundle())
    fresh = bundles.save("alice", "new-repo", "b" * 64, sample_bundle())
    with store.engine.begin() as db:
        db.execute(
            update(embedding_bundles)
            .where(embedding_bundles.c.id == old["id"])
            .values(created_at=(datetime.now(UTC) - timedelta(days=40)).isoformat())
        )
    assert store.expire("alice", 30) == 0
    assert [item["id"] for item in bundles.list("alice")] == [fresh["id"]]
    assert bundles.get("bob", old["id"])
    assert store.delete_repository("alice", "new-repo") == 0
    assert bundles.list("alice") == []
    assert bundles.list("bob")
    store.engine.dispose()
