"""Fill missing SEC and reserve counters without changing references or financial links."""

from alembic import op

revision = "0010_automatic_sec"
down_revision = "0009_optional_department"
branch_labels = None
depends_on = None


def reserve_counters():
    op.execute("""WITH sequence_values AS (
        SELECT owner_id, reference_sequence::bigint AS value FROM shipments
        UNION ALL
        SELECT owner_id, CASE WHEN btrim(master_data->>'sec') ~ '^[0-9]+$'
            THEN btrim(master_data->>'sec')::numeric END FROM shipments
        UNION ALL
        SELECT owner_id, CASE WHEN btrim(legacy_sec) ~ '^[0-9]+$'
            THEN btrim(legacy_sec)::numeric END FROM shipments
    ), highest AS (
        SELECT owner_id, coalesce(max(value) FILTER (WHERE value BETWEEN 1 AND 2147483646), 0)::integer AS value
        FROM sequence_values GROUP BY owner_id
    ) INSERT INTO reference_counters(owner_id, last_value)
      SELECT owner_id, value FROM highest
      ON CONFLICT (owner_id) DO UPDATE
      SET last_value = greatest(reference_counters.last_value, excluded.last_value)""")


def upgrade():
    op.execute("LOCK TABLE shipments, reference_counters IN SHARE ROW EXCLUSIVE MODE")
    op.execute("""WITH existing AS (
        SELECT id, coalesce(reference_sequence, CASE
            WHEN btrim(legacy_sec) ~ '^[0-9]+$' THEN CASE
                WHEN btrim(legacy_sec)::numeric BETWEEN 1 AND 2147483646
                THEN btrim(legacy_sec)::numeric::integer END END) AS value
        FROM shipments WHERE coalesce(btrim(master_data->>'sec'), '') = ''
    ) UPDATE shipments s SET master_data = jsonb_set(s.master_data, '{sec}', to_jsonb(e.value::text)),
        row_version = s.row_version + 1, updated_at = now()
      FROM existing e WHERE s.id = e.id AND e.value > 0""")
    reserve_counters()
    op.execute("""DO $$ BEGIN
        IF EXISTS (
            SELECT s.owner_id FROM shipments s JOIN reference_counters c ON c.owner_id = s.owner_id
            WHERE coalesce(btrim(s.master_data->>'sec'), '') = ''
            GROUP BY s.owner_id, c.last_value HAVING c.last_value::bigint + count(*) > 2147483646
        ) THEN
            RAISE EXCEPTION 'Se agotó el rango numérico del consecutivo de este master';
        END IF;
    END $$""")
    op.execute("""WITH missing AS (
        SELECT s.id, c.last_value + row_number() OVER (
            PARTITION BY s.owner_id ORDER BY s.created_at, s.id) AS value
        FROM shipments s JOIN reference_counters c ON c.owner_id = s.owner_id
        WHERE coalesce(btrim(s.master_data->>'sec'), '') = ''
    ) UPDATE shipments s SET master_data = jsonb_set(s.master_data, '{sec}', to_jsonb(m.value::text)),
        row_version = s.row_version + 1, updated_at = now()
      FROM missing m WHERE s.id = m.id""")
    reserve_counters()


def downgrade():
    # Assigned business numbers remain valid when rolling back application code.
    pass
