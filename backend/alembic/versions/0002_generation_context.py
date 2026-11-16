"""Persist brand context and explicit inference mode."""
from alembic import op
import sqlalchemy as sa

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("generation_jobs", sa.Column("brand_context", sa.JSON(), nullable=False, server_default="{}"))
    op.add_column("generation_jobs", sa.Column("generation_mode", sa.String(16), nullable=False, server_default="ollama"))


def downgrade() -> None:
    op.drop_column("generation_jobs", "generation_mode")
    op.drop_column("generation_jobs", "brand_context")
