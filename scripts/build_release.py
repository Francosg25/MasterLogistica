"""Build an explicit production frontend and a native Linux release, without Docker."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import tarfile
import tempfile
from pathlib import Path

from local_dev import LocalError, checkout_lock, frontend_dependencies_current

ROOT = Path(__file__).resolve().parents[1]


def build(output: Path, wheelhouse: Path | None = None):
    node = shutil.which("node")
    cli = ROOT / "frontend/node_modules/@angular/cli/bin/ng.js"
    if not node or not cli.is_file():
        raise ValueError(
            "Faltan Node o dependencias Angular. Prepara frontend con npm ci en el entorno autorizado."
        )
    if not frontend_dependencies_current(ROOT):
        raise ValueError(
            "Las dependencias no corresponden al lock. Ejecuta npm ci en frontend o inicia el lanzador local para prepararlas."
        )
    subprocess.run(
        [node, str(ROOT / "frontend/scripts/check-toolchain.cjs")], check=True
    )
    # Always rebuild production: a prior e2e build must never become a deployment.
    subprocess.run(
        [node, str(cli), "build", "--configuration", "production"],
        cwd=ROOT / "frontend",
        check=True,
    )
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="masterlogistica-release-") as folder:
        stage = Path(folder)
        for name in ("app", "migrations"):
            shutil.copytree(
                ROOT / "backend" / name,
                stage / "backend" / name,
                ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".env*"),
            )
        for name in ("alembic.ini", "requirements.lock", "pyproject.toml"):
            shutil.copy2(ROOT / "backend" / name, stage / "backend" / name)
        shutil.copytree(ROOT / "frontend/dist/web/browser", stage / "web")
        shutil.copytree(
            ROOT / "deploy/linux",
            stage / "deploy/linux",
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.env"),
        )
        shutil.copytree(ROOT / "docs", stage / "docs")
        # Also handle source trees copied from Windows without Git attributes.
        for script in stage.rglob("*.sh"):
            script.write_bytes(script.read_bytes().replace(b"\r\n", b"\n"))
        if wheelhouse:
            wheels = list(wheelhouse.glob("*.whl"))
            if not wheels:
                raise ValueError(
                    "El wheelhouse indicado no contiene ruedas Python para Linux."
                )
            (stage / "wheels").mkdir()
            for wheel in wheels:
                shutil.copyfile(wheel, stage / "wheels" / wheel.name)
        files = {
            path.relative_to(stage).as_posix(): hashlib.sha256(
                path.read_bytes()
            ).hexdigest()
            for path in sorted(stage.rglob("*"))
            if path.is_file()
        }
        digest = hashlib.sha256()
        for name, value in sorted(files.items()):
            digest.update(name.encode() + b"\0" + value.encode() + b"\n")
        release_id = digest.hexdigest()[:16]
        manifest = {"id": release_id, "configuration": "production", "files": files}
        (stage / "release.json").write_text(
            json.dumps(manifest, indent=2) + "\n", encoding="utf-8", newline="\n"
        )
        archive = output / f"masterlogistica-{release_id}.tar.gz"
        if archive.exists():
            with tarfile.open(archive) as tar:
                saved_file = tar.extractfile("release.json")
                if saved_file is None or json.load(saved_file) != manifest:
                    raise ValueError(
                        "La entrega existente no corresponde al manifiesto."
                    )
                actual = {member.name for member in tar.getmembers() if member.isfile()}
                if actual != files.keys() | {"release.json"}:
                    raise ValueError(
                        "La entrega existente contiene archivos inesperados."
                    )
                for name, expected in files.items():
                    content = tar.extractfile(name)
                    if (
                        content is None
                        or hashlib.file_digest(content, "sha256").hexdigest()
                        != expected
                    ):
                        raise ValueError(
                            "La entrega existente contiene un archivo alterado."
                        )
            print("Se reutiliza el paquete existente de esta misma entrega.")
        else:
            temporary = archive.with_suffix(".tmp")
            try:
                with tarfile.open(temporary, "w:gz") as tar:
                    for path in sorted(stage.rglob("*")):
                        tar.add(path, arcname=path.relative_to(stage), recursive=False)
                temporary.replace(archive)
            finally:
                temporary.unlink(missing_ok=True)
        with archive.open("rb") as source:
            checksum = hashlib.file_digest(source, "sha256").hexdigest()
        archive.with_suffix(archive.suffix + ".sha256").write_text(
            f"{checksum}  {archive.name}\n", encoding="utf-8", newline="\n"
        )
    print(f"Entrega preparada: {archive}")
    print(
        "El servidor no necesita Node ni Docker. Verifica la huella antes de instalar."
    )
    return archive


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / ".artifacts")
    parser.add_argument(
        "--wheelhouse",
        type=Path,
        help="Ruedas preparadas en Linux para la version Python/arquitectura destino.",
    )
    args = parser.parse_args(argv)
    try:
        data = ROOT / ".local-dev"
        data.mkdir(exist_ok=True)
        with checkout_lock(data / "build-release.lock"):
            build(args.output, args.wheelhouse)
    except (
        OSError,
        ValueError,
        subprocess.CalledProcessError,
        tarfile.TarError,
        LocalError,
    ) as error:
        parser.exit(1, f"No se preparo la entrega: {error}\n")


if __name__ == "__main__":
    main()
