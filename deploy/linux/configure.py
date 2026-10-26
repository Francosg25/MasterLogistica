"""Render Linux deployment files without root, network calls or secret arguments."""

from __future__ import annotations

import argparse
import re
from pathlib import Path

TEMPLATES = Path(__file__).resolve().parent


def render(domain: str, output: Path):
    domain = domain.lower().rstrip(".")
    if (
        len(domain) > 253
        or "." not in domain
        or any(
            not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label)
            for label in domain.split(".")
        )
    ):
        raise ValueError(
            "Indica el nombre DNS asignado, sin protocolo, puerto ni ruta."
        )
    if output.exists() and any(output.iterdir()):
        raise ValueError(
            "El directorio de salida debe estar vacio; se conservan configuraciones previas."
        )
    output.mkdir(parents=True, exist_ok=True, mode=0o700)
    for source, name in (
        ("api.env.example", "api.env"),
        ("migration.env.example", "migration.env"),
        ("network.env.example", "network.env"),
        ("masterlogistica-api.service.in", "masterlogistica-api.service"),
        ("nginx.conf.in", "masterlogistica.conf"),
    ):
        target = output / name
        target.write_text(
            (TEMPLATES / source)
            .read_text(encoding="utf-8")
            .replace("@DOMAIN@", domain),
            encoding="utf-8",
            newline="\n",
        )
        target.chmod(0o600 if name.endswith(".env") else 0o644)
    print(
        "Configuracion preparada. Completa PostgreSQL, Entra y catalogos en los archivos .env."
    )
    print("No se instalaron servicios, certificados ni reglas de red.")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--domain", required=True)
    parser.add_argument("--output", type=Path, default=TEMPLATES.parent / "generated")
    args = parser.parse_args(argv)
    try:
        render(args.domain, args.output)
    except (OSError, ValueError) as error:
        parser.exit(1, f"ERROR: {error}\n")


if __name__ == "__main__":
    main()
