"""Financial workflows and append-only reconciliation ledger."""

import sqlalchemy as sa
from alembic import op

revision = "0004_financial_workflows"
down_revision = "0003_reference_nomenclature"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("invoice_lines", sa.Column("shipment_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_invoice_lines_shipment_id_shipments",
        "invoice_lines",
        "shipments",
        ["shipment_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index("ix_invoice_lines_shipment_id", "invoice_lines", ["shipment_id"])
    op.create_index("ix_logs_shipment_time", "reconciliation_logs", ["shipment_id", "occurred_at"])
    op.execute("""CREATE TRIGGER allocations_immutable BEFORE UPDATE OR DELETE ON public.reconciliation_allocations
                  FOR EACH ROW EXECUTE FUNCTION public.reject_audit_mutation()""")
    op.execute("""DO $$ BEGIN
      IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'masterlogistica_app') THEN
        GRANT INSERT, UPDATE ON public.invoices TO masterlogistica_app;
        GRANT INSERT ON public.invoice_lines, public.invoice_line_identifiers, public.reconciliation_allocations TO masterlogistica_app;
      END IF;
    END $$""")


def downgrade():
    op.execute("DROP TRIGGER allocations_immutable ON public.reconciliation_allocations")
    op.execute("""DO $$ BEGIN
      IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'masterlogistica_app') THEN
        REVOKE INSERT, UPDATE ON public.invoices FROM masterlogistica_app;
        REVOKE INSERT ON public.invoice_lines, public.invoice_line_identifiers, public.reconciliation_allocations FROM masterlogistica_app;
      END IF;
    END $$""")
    op.drop_index("ix_logs_shipment_time", table_name="reconciliation_logs")
    op.drop_index("ix_invoice_lines_shipment_id", table_name="invoice_lines")
    op.drop_constraint(
        "fk_invoice_lines_shipment_id_shipments", "invoice_lines", type_="foreignkey"
    )
    op.drop_column("invoice_lines", "shipment_id")
