from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect


def test_empty_database_migrates_and_downgrades(tmp_path, monkeypatch):
    url = f"sqlite:///{(tmp_path / 'migration.sqlite').as_posix()}"
    monkeypatch.setenv("SPECGUARD_DATABASE_URL", url)
    config = Config("alembic.ini")
    command.upgrade(config, "head")
    engine = create_engine(url)
    assert {"runs", "feedback", "installations", "publications", "webhook_deliveries"}.issubset(
        inspect(engine).get_table_names()
    )
    engine.dispose()
    command.downgrade(config, "base")
    engine = create_engine(url)
    assert inspect(engine).get_table_names() == ["alembic_version"]
    engine.dispose()
