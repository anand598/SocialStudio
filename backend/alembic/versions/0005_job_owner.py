"""Per-browser job ownership: store a hash of the creator's owner cookie."""
from alembic import op
import sqlalchemy as sa

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Existing jobs keep NULL and are no longer served; they were created before access control.
    with op.batch_alter_table("generation_jobs") as batch:
        batch.add_column(sa.Column("owner_hash", sa.String(64)))


def downgrade() -> None:
    with op.batch_alter_table("generation_jobs") as batch:
        batch.drop_column("owner_hash")
