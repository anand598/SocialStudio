"""Guard state changes and artifacts against expired worker attempts."""
from alembic import op
import sqlalchemy as sa

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("generation_jobs", sa.Column("run_token", sa.Uuid()))


def downgrade() -> None:
    op.drop_column("generation_jobs", "run_token")
