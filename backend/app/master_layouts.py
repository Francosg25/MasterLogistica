"""Column contracts for the five masters, independent of transport operation."""

import json
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

LAYOUTS = json.loads(Path(__file__).with_suffix(".json").read_text(encoding="utf-8"))["layouts"]
ANALYST_LAYOUTS = {1: "DENI", 2: "MAG", 3: "NAT", 4: "ANDREA", 5: "ALEXA"}


def stored_master_data(row):
    """Keep earlier typed operational values visible until explicitly overridden."""
    values = dict(row.master_data or {})
    legacy = {
        key: key
        for key in (
            "scs_security_status",
            "arrival_port",
            "vessel",
            "etd_origin_port",
            "actual_departure_port",
            "eta_arrival_port",
            "actual_arrival_port",
            "customs_appointment",
            "haulage_type",
        )
    }
    legacy.update(
        weight="weight_kg",
        packages="package_count",
        pieces="piece_count",
        export_invoice="export_invoice_reference",
    )
    for key, attribute in legacy.items():
        value = getattr(row, attribute, None)
        if key in values or value is None:
            continue
        if isinstance(value, datetime):
            value = value.isoformat(sep=" ", timespec="minutes")
        elif isinstance(value, date):
            value = value.isoformat()
        elif isinstance(value, Decimal):
            value = format(value, "f")
        values[key] = str(value)
    return values


def layout_code(owner):
    name = str(getattr(owner, "display_name", "")).strip().upper()
    return name if name in LAYOUTS else ANALYST_LAYOUTS.get(getattr(owner, "analyst_code", None))


def merge_master_data(owner, current, changes):
    layout = LAYOUTS.get(layout_code(owner))
    fields = {
        f["key"].removeprefix("master."): f
        for f in (layout or {}).get("fields", [])
        if f["key"].startswith("master.")
    }
    result = dict(current or {})
    for key, value in changes.items():
        field = fields.get(key)
        if field is None:
            raise ValueError(f"El campo {key} no pertenece al master de este responsable")
        value = value.strip() if isinstance(value, str) else value
        if value is not None and len(value) > field["max"]:
            raise ValueError(f"{field['label']}: máximo {field['max']} caracteres")
        if value and field["kind"] == "date":
            try:
                if date.fromisoformat(value).isoformat() != value:
                    raise ValueError()
            except ValueError:
                raise ValueError(f"{field['label']}: captura una fecha válida") from None
        result[key] = value or None
    if len(json.dumps(result, ensure_ascii=False)) > 64000:
        raise ValueError("Los datos de este registro superan 64 KB")
    return result


def master_changes(before, after, code=None):
    """Expose the changed columns individually without rewriting stored audit evidence."""
    layouts = [LAYOUTS[code]] if code in LAYOUTS else LAYOUTS.values()
    labels = {f["key"]: f["label"] for layout in layouts for f in layout["fields"]}
    old, new = before or {}, after or {}
    return [
        dict(
            field="master." + key,
            label=labels.get("master." + key, key),
            before=old.get(key),
            after=new.get(key),
        )
        for key in sorted(old.keys() | new.keys())
        if old.get(key) != new.get(key)
    ]
