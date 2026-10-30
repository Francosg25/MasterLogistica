"""Analyst codes used by new references; shipment ownership remains an immutable ID."""

from sqlalchemy import column, func, select, table, update

ANALYST_LAYOUTS = {
    1: "MAG",
    2: "ALEXA",
    3: "DENI",
    4: "ANDREA",
    5: "NAT",
    6: "COMPLIANCE",
    7: "COMPLIANCE",
    8: "COMPLIANCE",
}
MASTER_ANALYST_CODES = {name: code for code, name in ANALYST_LAYOUTS.items() if code <= 5}


def align_named_master_codes_v1(connection):
    """Correct the five named presets atomically, without guessing account identities.

    Frozen data correction shared by SQLite upgrades and its regression tests.
    PostgreSQL's 0009 migration carries the equivalent SQL independently.
    """
    users = table(
        "users",
        column("id"),
        column("display_name"),
        column("analyst_code"),
        column("row_version"),
        column("updated_at"),
    )
    rows = connection.execute(select(users)).mappings().all()
    targets = {}
    for row in rows:
        target = MASTER_ANALYST_CODES.get(row["display_name"].strip().upper())
        if target is None:
            continue
        if target in targets:
            raise ValueError(
                "Hay dos cuentas para el mismo master; conserva la base y revisa sus códigos de analista."
            )
        targets[target] = row
    ids = {row["id"] for row in targets.values()}
    if any(row["analyst_code"] in targets and row["id"] not in ids for row in rows):
        raise ValueError(
            "Un código de analista está asignado a otra cuenta; conserva la base y revisa esa asignación."
        )
    changed = [(code, row) for code, row in targets.items() if row["analyst_code"] != code]
    for _, row in changed:
        connection.execute(update(users).where(users.c.id == row["id"]).values(analyst_code=None))
    for code, row in changed:
        connection.execute(
            update(users)
            .where(users.c.id == row["id"])
            .values(
                analyst_code=code,
                row_version=users.c.row_version + 1,
                updated_at=func.now(),
            )
        )
