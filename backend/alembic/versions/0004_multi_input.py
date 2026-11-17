"""Support video and URL inputs: source media, source URL and extracted page metadata."""
from alembic import op
import sqlalchemy as sa

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Batch mode lets SQLite (local demo) rebuild the table to relax the NOT NULL constraint.
    with op.batch_alter_table("generation_jobs") as batch:
        batch.alter_column("input_file_path", existing_type=sa.Text(), nullable=True)
        batch.add_column(sa.Column("source_media_path", sa.Text()))
        batch.add_column(sa.Column("source_url", sa.Text()))
        batch.add_column(sa.Column("source_metadata", sa.JSON()))


def downgrade() -> None:
    with op.batch_alter_table("generation_jobs") as batch:
        batch.drop_column("source_metadata")
        batch.drop_column("source_url")
        batch.drop_column("source_media_path")
        batch.alter_column("input_file_path", existing_type=sa.Text(), nullable=False)
