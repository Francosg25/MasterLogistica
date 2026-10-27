"""Optional departments in new references; historical matching keys remain stable."""

import re
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass

from sqlalchemy import case, func, or_, select, union_all
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.master_sequences import positive_sequence
from app.models import ReferenceCounter, Shipment, ShipmentIdentifier, User

LEGACY_VERSION = "JE_REF_2026_10_V1"
VERSION = "JE_REF_2026_10_V3"
PROCESSES = {"RM", "AF", "FG", "CR", "FA"}
LEGACY_PROCESSES = {"DR"}
DEPARTMENTS = {"PRJ", "MAT", "QUA", "MAI", "HUM", "FIX", "RAW", "CTM", "SCR"}
# (transport mode, service category, direction). N means no inbound/outbound classification.
OPERATIONS = {
    "AE": ("AIR", "FREIGHT", "O"),
    "AI": ("AIR", "FREIGHT", "I"),
    "SE": ("SEA", "FREIGHT", "O"),
    "SI": ("SEA", "FREIGHT", "I"),
    "LI": ("LAND", "FREIGHT", "I"),
    "LE": ("LAND", "FREIGHT", "O"),
    "PI": (None, "COURIER", "I"),
    "PE": (None, "COURIER", "O"),
    "VI": (None, "COMPLIANCE", "I"),
    "VE": (None, "COMPLIANCE", "O"),
    "A3": (None, "COMPLIANCE", "N"),
    "F4": (None, "COMPLIANCE", "N"),
    "F5": (None, "COMPLIANCE", "N"),
    "R1": (None, "COMPLIANCE", "N"),
}
# Labels used in the source masters. Unknown labels remain valid manual text.
EXCEL_OPERATIONS = {
    "LANDIMPO": "LI",
    "LANDEXPO": "LE",
    "AIRIMPO": "AI",
    "AIREXPO": "AE",
    "SEAIMPO": "SI",
    "SEAEXPO": "SE",
}


def reference_operation(value: str) -> str:
    cleaned = re.sub(r"\s+", "", unicodedata.normalize("NFKC", value)).upper()
    return EXCEL_OPERATIONS.get(cleaned, cleaned)


def operation_classification(value):
    return OPERATIONS.get(reference_operation(value or ""), (None, "FREIGHT", "N"))


PATTERN = re.compile(
    r"(?P<process>RM|AF|FG|CR|DR|FA)(?P<analyst>[1-9])-"
    r"(?P<sequence>\d{1,10})(?P<operation>AE|AI|SE|SI|LI|LE|PI|PE|VI|VE|A3|F4|F5|R1)"
    r"(?P<year>\d{2})-(?P<bu>[A-Z0-9]{1,32})"
    r"(?:-(?P<department>PRJ|MAT|QUA|MAI|HUM|FIX|RAW|CTM|SCR))?"
    r"(?:\.(?P<suffix>DMR|PFA|CS\d{1,32}))?",
    re.ASCII,
)
NUMBER_PATTERN = re.compile(
    r"^(?:RM|AF|FG|CR|DR|FA)(?P<analyst>[1-9])-(?P<sequence>\d{1,10})"
    r"(?:AE|AI|SE|SI|LI|LE|PI|PE|VI|VE|A3|F4|F5|R1)\d{2}-[A-Z0-9]",
    re.ASCII,
)


def reference_number(raw: str):
    # Reading a number must not make unrelated suffixes equivalent for matching.
    text = re.sub(r"\s+", "", unicodedata.normalize("NFKC", raw)).upper()
    match = NUMBER_PATTERN.match(text)
    return (int(match["analyst"]), int(match["sequence"])) if match else None


@dataclass(frozen=True)
class ParsedReference:
    raw_value: str
    base: str
    normalized: str
    process_code: str
    analyst_code: int
    sequence: int
    operation_code: str
    year: int
    business_unit: str
    department_code: str | None
    suffix: str | None
    warnings: tuple[str, ...]
    is_current_format: bool


def parse_reference(raw: str) -> ParsedReference:
    if not raw or len(raw) > 200:
        raise ValueError("Invalid reference length")
    cleaned = re.sub(r"\s+", "", unicodedata.normalize("NFKC", raw)).upper()
    match = PATTERN.fullmatch(cleaned)
    if not match or int(match["sequence"]) <= 0:
        raise ValueError("Reference does not follow the supported nomenclature")
    # Canonical padding is a technical convention; preserve the source raw value separately.
    sequence = int(match["sequence"])
    warnings = []
    if match["process"] in LEGACY_PROCESSES:
        warnings.append("LEGACY_PROCESS_CODE")
    if len(match["sequence"]) != 4:
        warnings.append("SEQUENCE_WIDTH_NOT_FOUR")
    if len(match["bu"]) != 3:
        warnings.append("BUSINESS_UNIT_WIDTH_NOT_THREE")
    # Earlier releases treated department-free references as literal keys. Preserve
    # their sequence spelling, including leading zeroes, when recognizing metadata.
    digits = f"{sequence:04d}" if match["department"] else match["sequence"]
    base = f"{match['process']}{match['analyst']}-{digits}{match['operation']}{match['year']}-{match['bu']}"
    if match["department"]:
        base += "-" + match["department"]
    suffix = match["suffix"]
    return ParsedReference(
        raw_value=raw,
        base=base,
        normalized=base + (f".{suffix}" if suffix else ""),
        process_code=match["process"],
        analyst_code=int(match["analyst"]),
        sequence=sequence,
        operation_code=match["operation"],
        year=2000 + int(match["year"]),
        business_unit=match["bu"],
        department_code=match["department"],
        suffix=suffix,
        warnings=tuple(warnings),
        is_current_format=not warnings,
    )


def generate_reference(
    session: Session,
    user: User,
    *,
    process: str,
    operation: str,
    year: int,
    business_unit: str,
    department: str | None = None,
    business_units: Mapping[str, str],
) -> tuple[str, int]:
    if user.analyst_code is None:
        raise ValueError("Assign an analyst code before creating operations")
    department = department or None
    if process not in PROCESSES or (department is not None and department not in DEPARTMENTS):
        raise ValueError("Unsupported reference catalog code")
    if not operation.strip() or len(operation) > 100:
        raise ValueError("Capture an operation up to 100 characters")
    operation = reference_operation(operation)
    if not 2000 <= year <= 2099 or not re.fullmatch(r"[A-Z0-9]{3}", business_unit, re.ASCII):
        raise ValueError("Invalid reference year or business unit")
    if not business_units or business_unit not in business_units:
        raise ValueError("Business unit must belong to the configured approved catalog")
    # A corrected analyst code may have been used by a different owner in older
    # releases. Reserve its existing numbers across all owners and reference aliases.
    reserve_existing_sequences(session, user)
    while True:
        sequence = next_reference_sequence(session, user, reserve=False)
        reference = (
            f"{process}{user.analyst_code}-{sequence:04d}{operation}{year % 100:02d}-{business_unit}"
            + (f"-{department}" if department else "")
        )
        normalized = normalize_reference(reference)
        aliases = select(ShipmentIdentifier.shipment_id).where(
            ShipmentIdentifier.kind == "REFERENCE",
            ShipmentIdentifier.normalized_value == normalized,
        )
        if (
            session.scalar(
                select(Shipment.id)
                .where(
                    or_(
                        Shipment.reference_normalized == normalized,
                        Shipment.id.in_(aliases),
                    )
                )
                .limit(1)
            )
            is None
        ):
            return reference, sequence


def next_reference_sequence(session: Session, owner: User, *, reserve: bool = True) -> int:
    """Allocate SEC for manual and automatic references in the same transaction."""
    if reserve:
        reserve_existing_sequences(session, owner)
    # UPSERT locks the owner's counter until commit; rollback consumes no number.
    insert_row = sqlite_insert if session.get_bind().dialect.name == "sqlite" else insert
    statement = insert_row(ReferenceCounter).values(owner_id=owner.id, last_value=1)
    statement = statement.on_conflict_do_update(
        index_elements=[ReferenceCounter.owner_id],
        set_={"last_value": ReferenceCounter.last_value + 1},
        where=ReferenceCounter.last_value < 2147483646,
    ).returning(ReferenceCounter.last_value)
    sequence = session.scalar(statement)
    if sequence is None:
        raise ValueError("Se agotó el rango numérico del consecutivo de este master")
    return sequence


def reserve_existing_sequences(session: Session, owner: User) -> None:
    prefix = f"{owner.analyst_code}-"
    values = union_all(
        select(Shipment.reference_normalized).where(
            func.substr(Shipment.reference_normalized, 3, 2) == prefix
        ),
        select(ShipmentIdentifier.normalized_value).where(
            ShipmentIdentifier.kind == "REFERENCE",
            func.substr(ShipmentIdentifier.normalized_value, 3, 2) == prefix,
        ),
    )
    highest = 0
    for existing in session.execute(
        select(
            Shipment.master_data["sec"].as_string().label("sec"),
            Shipment.reference_sequence,
            Shipment.legacy_sec,
        ).where(Shipment.owner_id == owner.id)
    ):
        for value in (
            existing.sec,
            existing.reference_sequence,
            existing.legacy_sec,
        ):
            highest = max(highest, positive_sequence(value))
    for value in session.scalars(values):
        number = reference_number(value)
        if number and number[0] == owner.analyst_code and 0 < number[1] <= 2147483646:
            highest = max(highest, number[1])
    if highest:
        reserve_sequence(session, owner, highest)


def normalize_reference(raw: str) -> str:
    """Use the official key when recognized, otherwise accept the manual reference."""
    try:
        return parse_reference(raw).normalized
    except ValueError:
        return re.sub(r"\s+", "", unicodedata.normalize("NFKC", raw)).upper()


def reserve_manual_sequence(session: Session, owner: User, raw: str) -> None:
    """Keep automatic numbering ahead of a manually entered number for this owner."""
    number = reference_number(raw)
    if not number or number[0] != owner.analyst_code or not 0 < number[1] <= 2147483646:
        return
    reserve_sequence(session, owner, number[1])


def reserve_sequence(session: Session, owner: User, sequence: int) -> None:
    insert_row = sqlite_insert if session.get_bind().dialect.name == "sqlite" else insert
    statement = insert_row(ReferenceCounter).values(owner_id=owner.id, last_value=sequence)
    session.execute(
        statement.on_conflict_do_update(
            index_elements=[ReferenceCounter.owner_id],
            set_={
                "last_value": case(
                    (ReferenceCounter.last_value < sequence, sequence),
                    else_=ReferenceCounter.last_value,
                )
            },
        )
    )


def normalize_identifier(raw: str) -> str:
    """Conservative matching key: keep letters/digits and leading zeros, remove separators."""
    normalized = unicodedata.normalize("NFKC", raw).upper()
    normalized = re.sub(r"[\s\-./]+", "", normalized)
    if (
        not normalized
        or len(normalized) > 200
        or not re.fullmatch(r"[A-Z0-9]+", normalized, re.ASCII)
    ):
        raise ValueError("Identifier must contain letters or digits and supported separators")
    return normalized
