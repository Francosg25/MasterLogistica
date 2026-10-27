"""Align named master presets without rewriting any shipment or reference."""

from alembic import op

revision = "0009_optional_department"
down_revision = "0008_master_layouts"
branch_labels = None
depends_on = None

# Freeze this mapping with the migration. Corporate accounts using other display
# names retain the analyst code explicitly assigned during account provisioning.
MAPPING = "('MAG',1),('ALEXA',2),('DENI',3),('ANDREA',4),('NAT',5)"


def upgrade():
    op.execute(f"""DO $$ BEGIN
        IF EXISTS (
            WITH wanted(name, code) AS (VALUES {MAPPING})
            SELECT 1 FROM users u JOIN wanted w ON upper(btrim(u.display_name)) = w.name
            GROUP BY w.name HAVING count(*) > 1
        ) THEN
            RAISE EXCEPTION 'Two accounts identify the same master; review analyst assignments';
        END IF;
        IF EXISTS (
            WITH wanted(name, code) AS (VALUES {MAPPING})
            SELECT 1 FROM wanted w
            JOIN users target ON upper(btrim(target.display_name)) = w.name
            JOIN users occupied ON occupied.analyst_code = w.code AND occupied.id <> target.id
            WHERE upper(btrim(occupied.display_name)) NOT IN (SELECT name FROM wanted)
        ) THEN
            RAISE EXCEPTION 'An analyst code belongs to another account; review that assignment';
        END IF;
    END $$""")
    # NULL is permitted by the unique constraint and lets permutations occur
    # within this transaction without temporarily giving two users the same code.
    op.execute(f"""WITH wanted(name, code) AS (VALUES {MAPPING})
        UPDATE users u SET analyst_code = NULL FROM wanted w
        WHERE upper(btrim(u.display_name)) = w.name
          AND u.analyst_code IS DISTINCT FROM w.code""")
    op.execute(f"""WITH wanted(name, code) AS (VALUES {MAPPING})
        UPDATE users u SET analyst_code = w.code,
            row_version = u.row_version + 1, updated_at = now()
        FROM wanted w WHERE upper(btrim(u.display_name)) = w.name
          AND u.analyst_code IS DISTINCT FROM w.code""")


def downgrade():
    # A software rollback cannot restore the mistaken business assignments.
    # Department and reference columns were already nullable; there is no DDL to reverse.
    pass
