"""Optional brand logo per job."""
from alembic import op
import sqlalchemy as sa

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("generation_jobs") as batch:
        batch.add_column(sa.Column("logo_path", sa.Text()))


def downgrade() -> None:
    with op.batch_alter_table("generation_jobs") as batch:
        batch.drop_column("logo_path")
