"""Add current process/operation codes while preserving historical reference keys."""

from alembic import op

revision = "0003_reference_nomenclature"
down_revision = "0002_runtime_permissions"
branch_labels = None
depends_on = None


def upgrade():
    op.drop_constraint("ck_shipment_process", "shipments", type_="check")
    op.create_check_constraint(
        "ck_shipment_process",
        "shipments",
        "process_code IS NULL OR process_code IN ('RM','AF','FG','DR','CR','FA')",
    )
    op.drop_constraint("ck_shipment_operation", "shipments", type_="check")
    op.create_check_constraint(
        "ck_shipment_operation",
        "shipments",
        "operation_code IS NULL OR operation_code IN ('AE','AI','SE','SI','LI','LE','PI','PE','VI','VE','A3','F4','F5','R1')",
    )


def downgrade():
    # A rollback cannot rename identifiers already used for operational/financial traceability.
    op.execute("""DO $$ BEGIN
        IF EXISTS (SELECT 1 FROM public.shipments WHERE process_code = 'CR' OR operation_code = 'R1') THEN
            RAISE EXCEPTION 'Cannot downgrade while current nomenclature records exist';
        END IF;
    END $$""")
    op.drop_constraint("ck_shipment_operation", "shipments", type_="check")
    op.create_check_constraint(
        "ck_shipment_operation",
        "shipments",
        "operation_code IS NULL OR operation_code IN ('AE','AI','SE','SI','LI','LE','PI','PE','VI','VE','A3','F4','F5')",
    )
    op.drop_constraint("ck_shipment_process", "shipments", type_="check")
    op.create_check_constraint(
        "ck_shipment_process",
        "shipments",
        "process_code IS NULL OR process_code IN ('RM','AF','FG','DR','FA')",
    )
