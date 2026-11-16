"""Create persistent generation jobs."""
from alembic import op
import sqlalchemy as sa

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "generation_jobs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("stage", sa.String(32), nullable=False),
        sa.Column("progress", sa.Integer(), nullable=False),
        sa.Column("input_type", sa.String(16), nullable=False),
        sa.Column("input_file_path", sa.Text(), nullable=False),
        sa.Column("platform", sa.String(32), nullable=False),
        sa.Column("format", sa.String(32), nullable=False),
        sa.Column("product_analysis", sa.JSON()),
        sa.Column("generated_content", sa.JSON()),
        sa.Column("output_file_path", sa.Text()),
        sa.Column("thumbnail_file_path", sa.Text()),
        sa.Column("error_code", sa.String(64)),
        sa.Column("error_message", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("status IN ('queued', 'processing', 'completed', 'failed')", name="job_status"),
        sa.CheckConstraint("progress BETWEEN 0 AND 100", name="job_progress"),
    )


def downgrade() -> None:
    op.drop_table("generation_jobs")
