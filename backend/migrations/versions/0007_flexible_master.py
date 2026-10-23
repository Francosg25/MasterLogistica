"""Allow the manual operation labels, statuses and supplier names used in masters."""

import sqlalchemy as sa
from alembic import op

revision = "0007_flexible_master"
down_revision = "0006_provision_date"
branch_labels = None
depends_on = None


OPERATIONS = ("AE", "AI", "SE", "SI", "LI", "LE", "PI", "PE", "VI", "VE", "A3", "F4", "F5", "R1")
STATUSES = ("DRAFT", "PLANNED", "IN_TRANSIT", "AT_PORT", "CUSTOMS", "DELIVERED", "CANCELLED")


def upgrade():
    op.drop_constraint("ck_shipment_operation", "shipments", type_="check")
    op.drop_constraint("ck_shipment_status", "shipments", type_="check")
    op.alter_column("shipments", "operation_code", existing_type=sa.String(2), type_=sa.String(100))
    op.alter_column("shipments", "status", existing_type=sa.String(24), type_=sa.String(100))
    op.add_column("shipments", sa.Column("carrier_broker_name", sa.String(250), nullable=True))
    op.add_column("shipments", sa.Column("shipping_line_name", sa.String(250), nullable=True))


def downgrade():
    shipments = sa.table(
        "shipments",
        sa.column("operation_code"),
        sa.column("status"),
        sa.column("carrier_broker_name"),
        sa.column("shipping_line_name"),
    )
    incompatible = op.get_bind().scalar(
        sa.select(sa.func.count())
        .select_from(shipments)
        .where(
            sa.or_(
                shipments.c.operation_code.not_in(OPERATIONS),
                shipments.c.status.not_in(STATUSES),
                shipments.c.carrier_broker_name.is_not(None),
                shipments.c.shipping_line_name.is_not(None),
            )
        )
    )
    if incompatible:
        raise RuntimeError(
            "El master contiene captura manual; conserva estos datos antes de retroceder de versión."
        )
    op.drop_column("shipments", "shipping_line_name")
    op.drop_column("shipments", "carrier_broker_name")
    op.alter_column("shipments", "operation_code", existing_type=sa.String(100), type_=sa.String(2))
    op.alter_column("shipments", "status", existing_type=sa.String(100), type_=sa.String(24))
    op.create_check_constraint(
        "ck_shipment_operation",
        "shipments",
        "operation_code IS NULL OR operation_code IN " + str(OPERATIONS),
    )
    op.create_check_constraint("ck_shipment_status", "shipments", "status IN " + str(STATUSES))
