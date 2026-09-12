"""Portable schema shared by SQLite and PostgreSQL."""

from sqlalchemy import Column, ForeignKeyConstraint, Integer, MetaData, String, Table, Text

metadata = MetaData()
embedding_bundles = Table(
    "embedding_bundles",
    metadata,
    Column("owner", String(128), primary_key=True),
    Column("id", String(64), primary_key=True),
    Column("repository", String(300), nullable=False),
    Column("binding", String(64), nullable=False),
    Column("created_at", String(40), nullable=False),
    Column("summary", Text, nullable=False),
    Column("payload", Text, nullable=False),
)
runs = Table(
    "runs",
    metadata,
    Column("owner", String(128), primary_key=True),
    Column("id", String(64), primary_key=True),
    Column("created_at", String(40), nullable=False),
    Column("payload", Text, nullable=False),
)
feedback = Table(
    "feedback",
    metadata,
    Column("owner", String(128), primary_key=True),
    Column("run_id", String(64), primary_key=True),
    Column("criterion_id", String(80), primary_key=True),
    Column("note", Text, nullable=False),
    ForeignKeyConstraint(["owner", "run_id"], ["runs.owner", "runs.id"], ondelete="CASCADE"),
)
deliveries = Table(
    "webhook_deliveries",
    metadata,
    Column("id", String(128), primary_key=True),
    Column("received_at", String(40), nullable=False),
)
installations = Table(
    "installations",
    metadata,
    Column("owner", String(128), primary_key=True),
    Column("id", Integer, primary_key=True),
)
publications = Table(
    "publications",
    metadata,
    Column("owner", String(128), primary_key=True),
    Column("run_id", String(64), primary_key=True),
    Column("repository", String(250), nullable=False),
    Column("pull_number", Integer, nullable=False),
    Column("comment_url", Text, nullable=False),
    Column("created_at", String(40), nullable=False),
    ForeignKeyConstraint(["owner", "run_id"], ["runs.owner", "runs.id"], ondelete="CASCADE"),
)
