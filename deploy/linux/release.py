"""Verify a native release directory before privileged installation."""

import hashlib
import json
import re
import sys
from pathlib import Path


def verify(root):
    root = Path(root).resolve()
    manifest = json.loads((root / "release.json").read_text())
    if not re.fullmatch(r"[a-f0-9]{16}", manifest.get("id", "")):
        raise ValueError("Identificador de entrega invalido.")
    files = manifest.get("files", {})
    for required in (
        "backend/app/runtime.py",
        "backend/requirements.lock",
        "web/index.html",
        "deploy/linux/install.sh",
        "deploy/linux/activate.sh",
    ):
        if required not in files:
            raise ValueError("La entrega esta incompleta.")
    actual = set()
    for path in root.rglob("*"):
        if any(
            part in {".venv", "__pycache__"} for part in path.relative_to(root).parts
        ):
            continue
        if path.is_symlink():
            raise ValueError("La entrega no debe contener enlaces simbolicos.")
        if path.is_file() and path != root / "release.json":
            actual.add(path.relative_to(root).as_posix())
    if actual != files.keys():
        raise ValueError("Hay archivos faltantes o no declarados en la entrega.")
    digest = hashlib.sha256()
    for name, expected in sorted(files.items()):
        path = root / name
        if path.resolve().is_relative_to(root) is False:
            raise ValueError("Ruta fuera del directorio de entrega.")
        value = hashlib.sha256(path.read_bytes()).hexdigest()
        if value != expected:
            raise ValueError("Un archivo no coincide con la huella de la entrega.")
        digest.update(name.encode() + b"\0" + value.encode() + b"\n")
    if digest.hexdigest()[:16] != manifest["id"]:
        raise ValueError("La huella de la entrega no corresponde a su identificador.")
    return manifest["id"]


if __name__ == "__main__":
    try:
        print(verify(sys.argv[1]))
    except (OSError, ValueError, KeyError, IndexError):
        raise SystemExit(
            "Entrega no valida. Usa el paquete y la huella del canal aprobado."
        ) from None
