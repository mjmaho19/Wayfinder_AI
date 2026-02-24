"""Add AgentTask orchestration fields

Revision ID: 34d8d86c863e
Revises:
Create Date: 2026-02-23 17:11:51.484831
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "34d8d86c863e"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    # 1) Add new columns with SERVER DEFAULTS so existing rows get values immediately
    with op.batch_alter_table("agent_task", schema=None) as batch_op:
        batch_op.add_column(sa.Column("input_json", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("attempts", sa.Integer(), nullable=False, server_default=sa.text("0")))
        batch_op.add_column(sa.Column("max_attempts", sa.Integer(), nullable=False, server_default=sa.text("3")))
        batch_op.add_column(sa.Column("worker_id", sa.String(length=200), nullable=True))

    # 2) Optional cleanup: remove server defaults after backfill
    with op.batch_alter_table("agent_task", schema=None) as batch_op:
        batch_op.alter_column("attempts", server_default=None)
        batch_op.alter_column("max_attempts", server_default=None)


def downgrade():
    # Reverse: drop the columns we added
    with op.batch_alter_table("agent_task", schema=None) as batch_op:
        batch_op.drop_column("worker_id")
        batch_op.drop_column("max_attempts")
        batch_op.drop_column("attempts")
        batch_op.drop_column("input_json")