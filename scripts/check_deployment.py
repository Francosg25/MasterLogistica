"""Read-only HTTPS check from the server or an authorized user workstation."""

import argparse
import json
import ssl
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit


def check(origin, ca_file=None):
    parsed = urlsplit(origin)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.path not in {"", "/"}
    ):
        raise ValueError("Indica el origen HTTPS sin ruta ni credenciales.")
    origin = origin.rstrip("/")
    context = ssl.create_default_context()
    if ca_file:
        context.load_verify_locations(cafile=ca_file)
    opener = urllib.request.build_opener(urllib.request.HTTPSHandler(context=context))
    with opener.open(origin + "/", timeout=10) as response:
        if (
            response.status != 200
            or urlsplit(response.url).netloc != parsed.netloc
            or urlsplit(response.url).scheme != "https"
        ):
            raise ValueError("El frontend no responde en el origen esperado.")
        if b"<html" not in response.read(8192).lower():
            raise ValueError("La respuesta no contiene el frontend HTML.")
    with opener.open(origin + "/api/v1/auth/config", timeout=10) as response:
        data = json.load(response)
        if (
            not isinstance(data, dict)
            or response.url != origin + "/api/v1/auth/config"
            or data.get("enabled") is not True
        ):
            raise ValueError("La configuracion de acceso Entra no esta disponible.")
        if not all(
            data.get(name) for name in ("authority", "frontend_client_id", "scope")
        ):
            raise ValueError("Falta configuracion publica Entra.")
    print(
        "HTTPS, frontend y configuracion Entra responden. Comprueba el inicio de sesion con un usuario autorizado."
    )


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("origin")
    parser.add_argument("--ca-file", type=Path)
    args = parser.parse_args(argv)
    try:
        check(args.origin, args.ca_file)
    except (OSError, ValueError):
        parser.exit(
            1,
            "Fallo la comprobacion. Revisa DNS, TCP 443, certificado, proxy y configuracion Entra.\n",
        )


if __name__ == "__main__":
    main()
