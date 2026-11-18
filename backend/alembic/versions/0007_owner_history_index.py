"""Index jobs by owner and creation time for the per-browser history list."""
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index("ix_generation_jobs_owner_created", "generation_jobs", ["owner_hash", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_generation_jobs_owner_created", table_name="generation_jobs")
