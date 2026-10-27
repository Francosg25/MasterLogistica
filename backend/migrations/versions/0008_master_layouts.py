"""Store each master's operational columns without replacing shipment identities."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0008_master_layouts"
down_revision = "0007_flexible_master"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "shipments",
        sa.Column(
            "master_data", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
    )


def downgrade():
    if op.get_bind().scalar(
        sa.text("SELECT count(*) FROM shipments WHERE master_data <> '{}'::jsonb")
    ):
        raise RuntimeError(
            "Hay datos capturados en los masters; consérvalos antes de retroceder de versión."
        )
    op.drop_column("shipments", "master_data")
