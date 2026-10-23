"""Catch platform-specific omissions before distributing the shared pip locks."""

import re
from pathlib import Path

import pytest
from packaging.markers import default_environment
from packaging.requirements import Requirement

BACKEND = Path(__file__).resolve().parents[1]


def locked_requirements(path):
    for block in path.read_text().replace("\\\n", " ").splitlines():
        if not block.strip() or block.lstrip().startswith("#"):
            continue
        requirement, *hashes = block.split("--hash=sha256:")
        row = Requirement(requirement.strip())
        assert len(row.specifier) == 1
        assert next(iter(row.specifier)).operator == "=="
        assert hashes and all(re.fullmatch(r"[0-9a-f]{64}", value.strip()) for value in hashes)
        yield row


@pytest.mark.parametrize("filename", ["requirements.lock", "requirements-test.lock"])
@pytest.mark.parametrize("version", ["3.11", "3.12", "3.13", "3.14"])
def test_shared_locks_cover_windows_and_linux(filename, version):
    rows = list(locked_requirements(BACKEND / filename))
    for system, platform, os_name in [("Windows", "win32", "nt"), ("Linux", "linux", "posix")]:
        environment = {
            **default_environment(),
            "platform_system": system,
            "sys_platform": platform,
            "os_name": os_name,
            "python_version": version,
            "python_full_version": version + ".0",
            "implementation_name": "cpython",
            "platform_python_implementation": "CPython",
        }
        active = {
            row.name.lower(): row
            for row in rows
            if not row.marker or row.marker.evaluate(environment)
        }
        assert ("uvloop" in active) is (platform == "linux")
        assert ("tzdata" in active) is (platform == "win32")
        if filename == "requirements-test.lock":
            assert ("colorama" in active) is (platform == "win32")
        assert str(active["sqlalchemy"].specifier) == "==2.1.4"
