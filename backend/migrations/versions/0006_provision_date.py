"""Keep the exact provision date alongside the accounting month.

Existing provisions retain a null date: their original day is unknown.
"""

import sqlalchemy as sa
from alembic import op

revision = "0006_provision_date"
down_revision = "0005_invoice_excel"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("provisions", sa.Column("provision_date", sa.Date(), nullable=True))


def downgrade():
    op.drop_column("provisions", "provision_date")
