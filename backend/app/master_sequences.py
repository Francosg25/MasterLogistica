"""Versioned SEC backfill shared by local upgrades and migration tests."""

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from app.models import ReferenceCounter, Shipment


def positive_sequence(value):
    text = str(value or "").strip()
    if text.isascii() and text.isdecimal() and 0 < int(text) <= 2147483646:
        return int(text)
    return 0


def backfill_master_sec_v1(connection):
    """Fill missing SEC without renaming references or altering captured SEC values."""
    rows = (
        connection.execute(
            select(
                Shipment.id,
                Shipment.owner_id,
                Shipment.master_data,
                Shipment.reference_sequence,
                Shipment.legacy_sec,
            ).order_by(Shipment.owner_id, Shipment.created_at, Shipment.id)
        )
        .mappings()
        .all()
    )
    highest = dict(
        connection.execute(select(ReferenceCounter.owner_id, ReferenceCounter.last_value)).all()
    )
    for row in rows:
        owner = row["owner_id"]
        values = (
            (row["master_data"] or {}).get("sec"),
            row["reference_sequence"],
            row["legacy_sec"],
        )
        highest[owner] = max(highest.get(owner, 0), *(positive_sequence(value) for value in values))
    for row in rows:
        data = dict(row["master_data"] or {})
        if str(data.get("sec") or "").strip():
            continue
        owner = row["owner_id"]
        number = positive_sequence(row["reference_sequence"]) or positive_sequence(
            row["legacy_sec"]
        )
        if number:
            data["sec"] = str(number)
        else:
            highest[owner] += 1
            if highest[owner] > 2147483646:
                raise ValueError("Se agotó el rango numérico del consecutivo de este master")
            data["sec"] = str(highest[owner])
        connection.execute(
            update(Shipment)
            .where(Shipment.id == row["id"])
            .values(master_data=data, row_version=Shipment.row_version + 1, updated_at=func.now())
        )
    insert_row = sqlite_insert if connection.dialect.name == "sqlite" else insert
    for owner, number in highest.items():
        statement = insert_row(ReferenceCounter).values(owner_id=owner, last_value=number)
        connection.execute(
            statement.on_conflict_do_update(
                index_elements=[ReferenceCounter.owner_id],
                set_={"last_value": number},
            )
        )
