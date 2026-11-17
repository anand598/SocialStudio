"""Optional user-supplied background music for video outputs."""
from alembic import op
import sqlalchemy as sa

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("generation_jobs") as batch:
        batch.add_column(sa.Column("music_path", sa.Text()))


def downgrade() -> None:
    with op.batch_alter_table("generation_jobs") as batch:
        batch.drop_column("music_path")
