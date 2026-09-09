"""Create review storage and integration audit records."""

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "runs",
        sa.Column("owner", sa.String(128), primary_key=True),
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("created_at", sa.String(40), nullable=False),
        sa.Column("payload", sa.Text, nullable=False),
    )
    op.create_table(
        "feedback",
        sa.Column("owner", sa.String(128), primary_key=True),
        sa.Column("run_id", sa.String(64), primary_key=True),
        sa.Column("criterion_id", sa.String(80), primary_key=True),
        sa.Column("note", sa.Text, nullable=False),
        sa.ForeignKeyConstraint(["owner", "run_id"], ["runs.owner", "runs.id"], ondelete="CASCADE"),
    )
    op.create_table(
        "webhook_deliveries",
        sa.Column("id", sa.String(128), primary_key=True),
        sa.Column("received_at", sa.String(40), nullable=False),
    )
    op.create_table(
        "installations",
        sa.Column("owner", sa.String(128), primary_key=True),
        sa.Column("id", sa.Integer, primary_key=True),
    )
    op.create_table(
        "publications",
        sa.Column("owner", sa.String(128), primary_key=True),
        sa.Column("run_id", sa.String(64), primary_key=True),
        sa.Column("repository", sa.String(250), nullable=False),
        sa.Column("pull_number", sa.Integer, nullable=False),
        sa.Column("comment_url", sa.Text, nullable=False),
        sa.Column("created_at", sa.String(40), nullable=False),
        sa.ForeignKeyConstraint(["owner", "run_id"], ["runs.owner", "runs.id"], ondelete="CASCADE"),
    )


def downgrade():
    for name in ("publications", "installations", "webhook_deliveries", "feedback", "runs"):
        op.drop_table(name)
