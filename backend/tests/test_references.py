import pytest

from app.references import DEPARTMENTS, OPERATIONS, PROCESSES, normalize_identifier, parse_reference


@pytest.mark.parametrize("suffix", ["", ".DMR", ".PFA", ".CS1280"])
def test_official_examples_and_stable_base(suffix):
    row = parse_reference("RM1-1616LI26-M23-MAT" + suffix)
    assert row.base == "RM1-1616LI26-M23-MAT"
    assert row.sequence == 1616 and row.analyst_code == 1
    assert row.year == 2026 and row.operation_code == "LI"
    assert row.normalized == row.base + suffix


@pytest.mark.parametrize("process", sorted(PROCESSES))
@pytest.mark.parametrize("operation", sorted(OPERATIONS))
def test_process_operation_catalogs(process, operation):
    assert parse_reference(f"{process}6-0001{operation}26-M23-MAT").operation_code == operation


@pytest.mark.parametrize("department", sorted(DEPARTMENTS))
def test_department_catalog(department):
    assert parse_reference(f"RM1-1616LI26-M23-{department}").department_code == department


def test_case_spaces_and_unicode_width():
    assert (
        parse_reference(" ｒｍ1 - 1616li26 - M23 - mat.dmr ").normalized
        == "RM1-1616LI26-M23-MAT.DMR"
    )


@pytest.mark.parametrize(
    "raw",
    [
        "RM0-1616LI26-M23-MAT",
        "RM10-1616LI26-M23-MAT",
        "ZZ1-1616LI26-M23-MAT",
        "RM1-0000LI26-M23-MAT",
        "RM1-1616XX26-M23-MAT",
        "RM1-1616LI26-M23-XYZ",
        "RM1-1616LI26-M23-MAT.PFA.DMR",
        "RM1-1616LI26-M23-MAT.1",
        "",
    ],
)
def test_unconfirmed_or_invalid_formats_rejected(raw):
    with pytest.raises(ValueError):
        parse_reference(raw)


def test_sequence_width_is_not_a_business_restriction():
    assert parse_reference("RM1-1LI26-M23-MAT").normalized == "RM1-0001LI26-M23-MAT"


def test_identifier_normalization_preserves_leading_zeroes():
    assert normalize_identifier(" 001-234/567 ") == "001234567"
    assert normalize_identifier(" msku 123456-7 ") == "MSKU1234567"
    with pytest.raises(ValueError):
        normalize_identifier("??")
