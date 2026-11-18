"""Versions of a finished result: parent, family root and version number."""
from alembic import op
import sqlalchemy as sa

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("generation_jobs") as batch:
        batch.add_column(sa.Column("parent_id", sa.Uuid()))
        batch.add_column(sa.Column("root_id", sa.Uuid()))
        batch.add_column(sa.Column("variant", sa.Integer(), nullable=False, server_default="1"))
        batch.create_index("ux_generation_jobs_root_variant", ["root_id", "variant"], unique=True)


def downgrade() -> None:
    with op.batch_alter_table("generation_jobs") as batch:
        batch.drop_index("ux_generation_jobs_root_variant")
        batch.drop_column("variant")
        batch.drop_column("root_id")
        batch.drop_column("parent_id")
