"""Persist owner-scoped embedding bundles."""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "embedding_bundles",
        sa.Column("owner", sa.String(128), primary_key=True),
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("repository", sa.String(300), nullable=False),
        sa.Column("binding", sa.String(64), nullable=False),
        sa.Column("created_at", sa.String(40), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("payload", sa.Text(), nullable=False),
    )


def downgrade():
    op.drop_table("embedding_bundles")
