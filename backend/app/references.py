"""Reference format v1, derived from the nomenclature document dated 2026-10-08."""

import re
import unicodedata
from dataclasses import dataclass

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models import ReferenceCounter, User

VERSION = "JE_REF_2026_10_V1"
PROCESSES = {"RM", "AF", "FG", "DR", "FA"}
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
}
PATTERN = re.compile(
    r"(?P<process>RM|AF|FG|DR|FA)(?P<analyst>[1-9])-"
    r"(?P<sequence>\d{4,10})(?P<operation>AE|AI|SE|SI|LI|LE|PI|PE|VI|VE|A3|F4|F5)"
    r"(?P<year>\d{2})-(?P<bu>[A-Z0-9]{1,32})-"
    r"(?P<department>PRJ|MAT|QUA|MAI|HUM|FIX|RAW|CTM|SCR)"
    r"(?:\.(?P<suffix>DMR|PFA|CS\d{1,32}))?",
    re.ASCII,
)


@dataclass(frozen=True)
class ParsedReference:
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


def parse_reference(raw: str) -> ParsedReference:
    if not raw or len(raw) > 200:
        raise ValueError("Invalid reference length")
    cleaned = re.sub(r"\s+", "", unicodedata.normalize("NFKC", raw)).upper()
    match = PATTERN.fullmatch(cleaned)
    if not match or int(match["sequence"]) <= 0:
        raise ValueError("Reference does not follow the supported nomenclature")
    # Canonical padding is a technical convention; preserve the source raw value separately.
    sequence = int(match["sequence"])
    base = (
        f"{match['process']}{match['analyst']}-{sequence:04d}"
        f"{match['operation']}{match['year']}-{match['bu']}-{match['department']}"
    )
    suffix = match["suffix"]
    return ParsedReference(
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
) -> tuple[str, int]:
    if user.analyst_code is None:
        raise ValueError("Assign an analyst code before creating operations")
    if process not in PROCESSES or operation not in OPERATIONS or department not in DEPARTMENTS:
        raise ValueError("Unsupported reference catalog code")
    if not 2000 <= year <= 2099 or not re.fullmatch(r"[A-Z0-9]{1,32}", business_unit, re.ASCII):
        raise ValueError("Invalid reference year or business unit")
    # UPSERT locks the owner's counter until the transaction commits; rollback consumes no number.
    statement = insert(ReferenceCounter).values(owner_id=user.id, last_value=1)
    statement = statement.on_conflict_do_update(
        index_elements=[ReferenceCounter.owner_id],
        set_={"last_value": ReferenceCounter.last_value + 1},
        where=ReferenceCounter.last_value < 2147483647,
    ).returning(ReferenceCounter.last_value)
    sequence = session.scalar(statement)
    if sequence is None:
        raise ValueError("Reference counter exhausted")
    return (
        f"{process}{user.analyst_code}-{sequence:04d}{operation}{year % 100:02d}"
        f"-{business_unit}-{department}"
    ), sequence


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
