"""Restricted API database role and append-only audit records."""

from alembic import op

revision = "0002_runtime_permissions"
down_revision = "0001_core"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
    CREATE FUNCTION public.reject_audit_mutation() RETURNS trigger
    LANGUAGE plpgsql AS $$
    BEGIN
        RAISE EXCEPTION 'Audit records are append-only' USING ERRCODE = '42501';
    END;
    $$
    """)
    op.execute("""
    CREATE TRIGGER audit_records_immutable
    BEFORE UPDATE OR DELETE ON public.reconciliation_logs
    FOR EACH ROW EXECUTE FUNCTION public.reject_audit_mutation()
    """)
    op.execute("REVOKE ALL ON ALL TABLES IN SCHEMA public FROM PUBLIC")
    op.execute("""
    DO $$
    BEGIN
      IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'masterlogistica_app') THEN
        GRANT USAGE ON SCHEMA public TO masterlogistica_app;
        GRANT SELECT ON ALL TABLES IN SCHEMA public TO masterlogistica_app;
        GRANT INSERT, UPDATE ON public.users, public.suppliers, public.shipments,
          public.provisions, public.accounting_periods, public.reference_counters TO masterlogistica_app;
        GRANT INSERT ON public.shipment_identifiers TO masterlogistica_app;
        GRANT INSERT ON public.reconciliation_logs TO masterlogistica_app;
        REVOKE ALL ON public.alembic_version FROM masterlogistica_app;
        GRANT SELECT ON public.alembic_version TO masterlogistica_app;
      END IF;
    END;
    $$
    """)


def downgrade():
    op.execute("DROP TRIGGER audit_records_immutable ON public.reconciliation_logs")
    op.execute("DROP FUNCTION public.reject_audit_mutation()")
    op.execute("""
    DO $$ BEGIN
      IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'masterlogistica_app') THEN
        REVOKE ALL ON ALL TABLES IN SCHEMA public FROM masterlogistica_app;
      END IF;
    END $$
    """)
