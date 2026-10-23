"""Versioned, file-backed SQLite schema for development on this computer only.

Production retains its PostgreSQL/Alembic migration chain. SQLite uses the same
ORM entities, validation, API and financial code, with exact monetary storage.
"""

import re
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DefaultClause, MetaData, inspect, select, text

from app.models import Base, ReferenceCounter, Supplier, User
from app.storage_types import ExactNumeric

SCHEMA_VERSION = 3
LOCAL_TENANT = UUID("f0000000-0000-0000-0000-000000000001")
LOCAL_USER = UUID("f0000000-0000-0000-0000-000000000002")
LOCAL_SUPPLIER = UUID("f0000000-0000-0000-0000-000000000003")
LOCAL_MASTERS = (
    (LOCAL_USER, "DENI", 1),
    (UUID("f0000000-0000-0000-0000-000000000012"), "MAG", 2),
    (UUID("f0000000-0000-0000-0000-000000000013"), "NAT", 3),
    (UUID("f0000000-0000-0000-0000-000000000014"), "ANDREA", 4),
    (UUID("f0000000-0000-0000-0000-000000000015"), "ALEXA", 5),
)
MAX_MONEY = 10**18 - 1


def money_integer(value):
    if value is None:
        return None
    result = int(value)
    if result != value or abs(result) > MAX_MONEY:
        raise ValueError("Money exceeds NUMERIC(18,4)")
    return result


def money_add(a, b):
    return None if a is None or b is None else money_integer(a + b)


def money_subtract(a, b):
    return None if a is None or b is None else money_integer(a - b)


def money_fx(amount, rate):
    if amount is None or rate is None:
        return None
    return money_integer(
        int((Decimal(amount) * Decimal(rate)).quantize(Decimal(1), rounding=ROUND_HALF_UP))
    )


def money_balance(opening, new, adjustment, released):
    if any(value is None for value in (opening, new, adjustment, released)):
        return None
    return money_integer(opening + new + adjustment - released)


def valid_rate(value):
    try:
        number = Decimal(str(value))
        return int(
            number.is_finite()
            and abs(number) < 10**10
            and number == number.quantize(Decimal("0.0000000001"))
        )
    except (InvalidOperation, ValueError):
        return 0


class MoneySum:
    def __init__(self):
        self.total = 0

    def step(self, value):
        if value is not None:
            self.total += int(value)

    def finalize(self):
        # A decimal string lets aggregate totals exceed 64 bits without loss.
        return str(self.total)


def configure_connection(connection):
    connection.isolation_level = None
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 15000")
    connection.create_function("local_uuid", 0, lambda: uuid4().hex)
    for name, count, function in (
        ("local_money_add", 2, money_add),
        ("local_money_subtract", 2, money_subtract),
        ("local_money_fx", 2, money_fx),
        ("local_money_balance", 4, money_balance),
        ("local_valid_rate", 1, valid_rate),
        (
            "local_positive_rate",
            1,
            lambda value: int(bool(valid_rate(value)) and Decimal(value) > 0),
        ),
    ):
        connection.create_function(name, count, function, deterministic=True)
    connection.create_aggregate("local_sum_money", 1, MoneySum)


def local_metadata():
    metadata = MetaData(naming_convention=Base.metadata.naming_convention)
    for source in Base.metadata.sorted_tables:
        source.to_metadata(metadata)
    expressions = {
        "amount + extra_charges": "local_money_add(amount, extra_charges)",
        "(amount + extra_charges) * fx_rate_to_usd": "local_money_fx(local_money_add(amount, extra_charges), fx_rate_to_usd)",
        "net_amount + tax_amount": "local_money_add(net_amount, tax_amount)",
        "provision_release_amount * provision_fx_rate_to_usd": "local_money_fx(provision_release_amount, provision_fx_rate_to_usd)",
        "invoice_allocated_amount * invoice_fx_rate_to_usd": "local_money_fx(invoice_allocated_amount, invoice_fx_rate_to_usd)",
        "invoice_allocated_amount * invoice_fx_rate_to_usd - provision_release_amount * provision_fx_rate_to_usd": "local_money_subtract(local_money_fx(invoice_allocated_amount, invoice_fx_rate_to_usd), local_money_fx(provision_release_amount, provision_fx_rate_to_usd))",
        "opening_amount + new_amount + adjustment_amount - released_amount": "local_money_balance(opening_amount, new_amount, adjustment_amount, released_amount)",
    }
    for table in metadata.tables.values():
        for constraint in table.constraints:
            if isinstance(constraint, CheckConstraint):
                sql = (
                    str(constraint.sqltext)
                    .replace("'NaN'::numeric", "'NaN'")
                    .replace("btrim(", "trim(")
                )
                sql = re.sub(r"EXTRACT\(DAY FROM (\w+)\) = 1", r"strftime('%d', \1) = '01'", sql)
                sql = re.sub(r"(\w*fx_rate_to_usd) > 0", r"local_positive_rate(\1) = 1", sql)
                if constraint.name == "ck_provision_usd_rate":
                    sql = sql.replace("fx_rate_to_usd = 1", "fx_rate_to_usd = '1.0000000000'")
                constraint.sqltext = text(sql)
        for column in table.columns:
            if column.computed is not None:
                column.computed.sqltext = text(expressions[str(column.computed.sqltext)])
            elif column.server_default is not None:
                default = str(column.server_default.arg)
                if "::jsonb" in default:
                    column.server_default = DefaultClause(text("'{}'"))
                elif default == "gen_random_uuid()":
                    column.server_default = DefaultClause(text("(local_uuid())"))
            if isinstance(column.type, ExactNumeric):
                if column.type.scale == 4:
                    guard = f"{column.name} IS NULL OR (typeof({column.name}) = 'integer' AND abs({column.name}) <= {MAX_MONEY})"
                else:
                    guard = f"{column.name} IS NULL OR local_valid_rate({column.name}) = 1"
                table.append_constraint(
                    CheckConstraint(guard, name=f"ck_local_{table.name}_{column.name}")
                )
    return metadata


def upgrade_flexible_master(connection):
    # Rename only the old constrained columns, then copy their values to free-text
    # columns. This preserves the table, IDs, foreign keys, row versions and audit
    # links; SQLite cannot drop a CHECK constraint without replacing its table.
    inspector = inspect(connection)
    columns = {c["name"] for c in inspector.get_columns("shipments")}
    checks = {c["name"] for c in inspector.get_check_constraints("shipments")}
    for name, constraint, definition in (
        ("operation_code", "ck_shipment_operation", "VARCHAR(100)"),
        ("status", "ck_shipment_status", "VARCHAR(100) NOT NULL DEFAULT 'DRAFT'"),
    ):
        legacy = "legacy_" + name
        if constraint in checks and legacy not in columns:
            connection.exec_driver_sql(f"ALTER TABLE shipments RENAME COLUMN {name} TO {legacy}")
            connection.exec_driver_sql(f"ALTER TABLE shipments ADD COLUMN {name} {definition}")
            connection.exec_driver_sql(f"UPDATE shipments SET {name} = {legacy}")
    for name in ("carrier_broker_name", "shipping_line_name"):
        if name not in columns:
            connection.exec_driver_sql(f"ALTER TABLE shipments ADD COLUMN {name} VARCHAR(250)")


def initialize_local(engine, session_factory):
    if engine.dialect.name != "sqlite":
        raise ValueError("Local initialization requires SQLite")
    with engine.begin() as connection:
        tables = set(inspect(connection).get_table_names())
        if "local_schema_version" not in tables:
            if tables:
                raise ValueError(
                    "La base local existente no pertenece a MasterLogistica; no se modificó."
                )
            local_metadata().create_all(connection)
            connection.exec_driver_sql(
                "CREATE TABLE local_schema_version (version INTEGER NOT NULL)"
            )
            connection.exec_driver_sql(
                f"INSERT INTO local_schema_version VALUES ({SCHEMA_VERSION})"
            )
            for table in ("reconciliation_logs", "reconciliation_allocations"):
                for action in ("UPDATE", "DELETE"):
                    connection.exec_driver_sql(f"""CREATE TRIGGER local_{table}_{action.lower()}
                        BEFORE {action} ON {table} BEGIN SELECT RAISE(ABORT, 'Audit records are append-only'); END""")
        else:
            version = (
                connection.exec_driver_sql("SELECT version FROM local_schema_version")
                .scalars()
                .all()
            )
            if version == [1]:
                # Additive upgrade preserves every existing row and its accounting month.
                if "provision_date" not in {
                    c["name"] for c in inspect(connection).get_columns("provisions")
                }:
                    connection.exec_driver_sql(
                        "ALTER TABLE provisions ADD COLUMN provision_date DATE"
                    )
                connection.exec_driver_sql("UPDATE local_schema_version SET version = 2")
                version = [2]
            if version == [2]:
                upgrade_flexible_master(connection)
                connection.exec_driver_sql("UPDATE local_schema_version SET version = 3")
                version = [3]
            if version != [SCHEMA_VERSION]:
                raise ValueError(
                    "La versión de la base local requiere una actualización explícita; conserva el archivo."
                )
            if not set(Base.metadata.tables).issubset(tables):
                raise ValueError(
                    "La base local está incompleta; conserva el archivo y recupera un respaldo."
                )
    with session_factory() as session:
        user = session.get(User, LOCAL_USER)
        if user is None:
            session.add(
                User(
                    id=LOCAL_USER,
                    entra_tenant_id=LOCAL_TENANT,
                    entra_object_id=LOCAL_USER,
                    email="local@example.com",
                    display_name="DENI",
                    role="SUPER_ADMIN",
                    analyst_code=1,
                )
            )
            session.flush()
            session.add(ReferenceCounter(owner_id=LOCAL_USER, last_value=0))
        elif user.display_name == "Desarrollo local":
            user.display_name = "DENI"
        # These identities belong only to the isolated local development database.
        for owner_id, name, code in LOCAL_MASTERS[1:]:
            if session.scalar(select(User.id).where(User.analyst_code == code)) is None:
                session.add(
                    User(
                        id=owner_id,
                        entra_tenant_id=LOCAL_TENANT,
                        entra_object_id=owner_id,
                        email=f"{name.lower()}@example.com",
                        display_name=name,
                        role="OPERATOR",
                        analyst_code=code,
                    )
                )
                session.flush()
                session.add(ReferenceCounter(owner_id=owner_id, last_value=0))
        # Catalog example only; never seed operational shipments, provisions or invoices.
        if session.scalar(select(Supplier.id).where(Supplier.id == LOCAL_SUPPLIER)) is None:
            session.add(
                Supplier(
                    id=LOCAL_SUPPLIER, code="LOCAL-001", legal_name="Proveedor local de ejemplo"
                )
            )
        session.commit()


def check_local_schema(connection):
    return connection.exec_driver_sql(
        "SELECT version FROM local_schema_version"
    ).scalars().all() == [SCHEMA_VERSION]
