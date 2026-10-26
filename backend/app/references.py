"""Reference generation v2; historical keys remain readable without rewriting them."""

import re
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass

from sqlalchemy import case
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.models import ReferenceCounter, User

LEGACY_VERSION = "JE_REF_2026_10_V1"
VERSION = "JE_REF_2026_10_V2"
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
    r"(?P<year>\d{2})-(?P<bu>[A-Z0-9]{1,32})-"
    r"(?P<department>PRJ|MAT|QUA|MAI|HUM|FIX|RAW|CTM|SCR)"
    r"(?:\.(?P<suffix>DMR|PFA|CS\d{1,32}))?",
    re.ASCII,
)


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
    department_code: str
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
    base = (
        f"{match['process']}{match['analyst']}-{sequence:04d}"
        f"{match['operation']}{match['year']}-{match['bu']}-{match['department']}"
    )
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
    department: str,
    business_units: Mapping[str, str],
) -> tuple[str, int]:
    if user.analyst_code is None:
        raise ValueError("Assign an analyst code before creating operations")
    if process not in PROCESSES or department not in DEPARTMENTS:
        raise ValueError("Unsupported reference catalog code")
    if not operation.strip() or len(operation) > 100:
        raise ValueError("Capture an operation up to 100 characters")
    operation = reference_operation(operation)
    if not 2000 <= year <= 2099 or not re.fullmatch(r"[A-Z0-9]{3}", business_unit, re.ASCII):
        raise ValueError("Invalid reference year or business unit")
    if not business_units or business_unit not in business_units:
        raise ValueError("Business unit must belong to the configured approved catalog")
    # UPSERT locks the owner's counter until the transaction commits; rollback consumes no number.
    insert_row = sqlite_insert if session.get_bind().dialect.name == "sqlite" else insert
    statement = insert_row(ReferenceCounter).values(owner_id=user.id, last_value=1)
    statement = statement.on_conflict_do_update(
        index_elements=[ReferenceCounter.owner_id],
        set_={"last_value": ReferenceCounter.last_value + 1},
        where=ReferenceCounter.last_value < 9999,
    ).returning(ReferenceCounter.last_value)
    sequence = session.scalar(statement)
    if sequence is None:
        raise ValueError("Four-digit reference counter exhausted; a reset policy must be approved")
    return (
        f"{process}{user.analyst_code}-{sequence:04d}{operation}{year % 100:02d}"
        f"-{business_unit}-{department}"
    ), sequence


def normalize_reference(raw: str) -> str:
    """Use the official key when recognized, otherwise accept the manual reference."""
    try:
        return parse_reference(raw).normalized
    except ValueError:
        return re.sub(r"\s+", "", unicodedata.normalize("NFKC", raw)).upper()


def reserve_manual_sequence(session: Session, owner: User, raw: str) -> None:
    """Keep automatic numbering ahead of a manually entered number for this owner."""
    try:
        parsed = parse_reference(raw)
    except ValueError:
        return
    if parsed.analyst_code != owner.analyst_code or parsed.sequence > 9999:
        return
    insert_row = sqlite_insert if session.get_bind().dialect.name == "sqlite" else insert
    statement = insert_row(ReferenceCounter).values(owner_id=owner.id, last_value=parsed.sequence)
    session.execute(
        statement.on_conflict_do_update(
            index_elements=[ReferenceCounter.owner_id],
            set_={
                "last_value": case(
                    (ReferenceCounter.last_value < parsed.sequence, parsed.sequence),
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
