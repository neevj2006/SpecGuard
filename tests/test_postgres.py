import os
from uuid import uuid4

import pytest

from services.analysis.engine import analyze
from services.api.bundles import BundleStore
from services.api.store import Store
from tests.test_bundle_storage import sample_bundle


@pytest.mark.skipif(
    not os.environ.get("TEST_POSTGRES_URL"),
    reason="Set TEST_POSTGRES_URL for PostgreSQL integration",
)
def test_postgres_transactions_ownership_and_feedback(repository):
    url = os.environ["TEST_POSTGRES_URL"]
    if not url.endswith("/specguard_test"):
        pytest.fail("PostgreSQL integration tests require the disposable specguard_test database")
    store = Store(url, initialize=False)
    owner = f"test-{uuid4()}"
    repo, base, head = repository
    run = analyze(repo, base, head, "discount")
    try:
        assert store.save(owner, run).id == run.id
        store.save(owner, run)
        assert len(store.list(owner)) == 1
        bundles = BundleStore(store)
        summary = bundles.save(owner, "fixture", "a" * 64, sample_bundle())
        assert bundles.save(owner, "fixture", "a" * 64, sample_bundle()) == summary
        assert bundles.get(owner, summary["id"])[1] == sample_bundle()
        with pytest.raises(KeyError):
            bundles.get("not-the-owner", summary["id"])
        bundles.delete(owner, summary["id"])
        assert bundles.list(owner) == []
        store.feedback(owner, run.id, run.results[0].criterion.id, "Checked")
        assert store.notes(owner, run.id)[run.results[0].criterion.id] == "Checked"
        with pytest.raises(KeyError):
            store.get("not-the-owner", run.id)
        store.delete(owner, run.id)
        assert store.list(owner) == []
    finally:
        store.delete_repository(owner, "fixture")
        if store.list(owner):
            store.delete(owner, run.id)
        store.engine.dispose()
