from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect


def test_empty_database_migrates_and_downgrades(tmp_path, monkeypatch):
    url = f"sqlite:///{(tmp_path / 'migration.sqlite').as_posix()}"
    monkeypatch.setenv("SPECGUARD_DATABASE_URL", url)
    config = Config("alembic.ini")
    command.upgrade(config, "head")
    engine = create_engine(url)
    assert "embedding_bundles" in inspect(engine).get_table_names()
    assert {"runs", "feedback", "installations", "publications", "webhook_deliveries"}.issubset(
        inspect(engine).get_table_names()
    )
    engine.dispose()
    command.downgrade(config, "base")
    engine = create_engine(url)
    assert inspect(engine).get_table_names() == ["alembic_version"]
    engine.dispose()


def test_bundle_migration_preserves_existing_runs(tmp_path, monkeypatch):
    from sqlalchemy import text

    url = f"sqlite:///{(tmp_path / 'upgrade.sqlite').as_posix()}"
    monkeypatch.setenv("SPECGUARD_DATABASE_URL", url)
    config = Config("alembic.ini")
    command.upgrade(config, "0001")
    engine = create_engine(url)
    with engine.begin() as db:
        db.execute(text("INSERT INTO runs VALUES ('owner', 'run', '2026-01-01', '{}')"))
    command.upgrade(config, "head")
    with engine.connect() as db:
        assert db.execute(text("SELECT id FROM runs")).scalar_one() == "run"
    command.downgrade(config, "0001")
    assert "embedding_bundles" not in inspect(engine).get_table_names()
    with engine.connect() as db:
        assert db.execute(text("SELECT id FROM runs")).scalar_one() == "run"
    engine.dispose()
