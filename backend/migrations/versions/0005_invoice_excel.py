"""Keep the consolidated USD amount and original invoice evidence."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0005_invoice_excel"
down_revision = "0004_financial_workflows"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "invoices",
        sa.Column(
            "source_data", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
    )


def downgrade():
    op.drop_column("invoices", "source_data")
