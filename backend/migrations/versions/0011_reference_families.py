"""Explicit parent and numbered transport movements; existing financial identities stay intact."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0011_reference_families"
down_revision = "0010_automatic_sec"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "shipments", sa.Column("parent_shipment_id", postgresql.UUID(as_uuid=True), nullable=True)
    )
    op.add_column("shipments", sa.Column("movement_number", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_shipment_parent",
        "shipments",
        "shipments",
        ["parent_shipment_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_unique_constraint(
        "uq_shipment_movement", "shipments", ["parent_shipment_id", "movement_number"]
    )
    op.create_check_constraint(
        "ck_shipment_parent",
        "shipments",
        "(parent_shipment_id IS NULL AND movement_number IS NULL) OR (parent_shipment_id IS NOT NULL AND movement_number IS NOT NULL AND movement_number > 0 AND movement_number <= 999999999 AND parent_shipment_id <> id)",
    )


def downgrade():
    if op.get_context().as_sql:
        raise RuntimeError("La reversión requiere comprobar si existen movimientos vinculados")
    if op.get_bind().scalar(
        sa.text("SELECT EXISTS (SELECT 1 FROM shipments WHERE parent_shipment_id IS NOT NULL)")
    ):
        raise RuntimeError(
            "La base contiene familias de referencias; conserva los vínculos y utiliza una versión compatible de la aplicación"
        )
    op.drop_constraint("ck_shipment_parent", "shipments", type_="check")
    op.drop_constraint("uq_shipment_movement", "shipments", type_="unique")
    op.drop_constraint("fk_shipment_parent", "shipments", type_="foreignkey")
    op.drop_column("shipments", "movement_number")
    op.drop_column("shipments", "parent_shipment_id")
