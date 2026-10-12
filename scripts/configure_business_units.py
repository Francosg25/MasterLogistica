"""Load an approved private BU JSON catalog into .env without changing other settings."""

import argparse
import json
import re
from pathlib import Path


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Catalog JSON contains duplicate keys")
        result[key] = value
    return result


def configure_catalog(catalog_file: Path, env_file: Path) -> int:
    data = json.loads(
        catalog_file.read_text(encoding="utf-8-sig"), object_pairs_hook=unique_object
    )
    catalog = (
        data.get("business_units")
        if isinstance(data, dict) and "business_units" in data
        else data
    )
    if not isinstance(catalog, dict) or not catalog:
        raise ValueError(
            "Catalog must be a nonempty object keyed by business unit code"
        )
    if any(
        not isinstance(code, str) or not re.fullmatch(r"[A-Z0-9]{3}", code, re.ASCII)
        for code in catalog
    ):
        raise ValueError(
            "Business unit codes must contain three uppercase letters or digits"
        )
    if any(
        not isinstance(name, str) or not name.strip() or len(name) > 250
        for name in catalog.values()
    ):
        raise ValueError("Descriptions must contain 1 to 250 characters")
    if not env_file.exists():
        raise ValueError(
            "Create local configuration with scripts/configure_local.py first"
        )
    catalog = {code: name.strip() for code, name in catalog.items()}
    text = env_file.read_text(encoding="utf-8")
    line = json.dumps(catalog, ensure_ascii=False, separators=(",", ":"))
    # Dotenv single quotes prevent expansion of dollar signs in operational descriptions.
    line = "BUSINESS_UNITS='" + line.replace("\\", "\\\\").replace("'", "\\'") + "'"
    pattern = r"(?m)^\s*BUSINESS_UNITS\s*=.*$"
    if re.search(pattern, text):
        text = re.sub(pattern, lambda match: line, text)
    else:
        text = text.rstrip("\n") + "\n" + line + "\n"
    temporary = env_file.with_name(env_file.name + ".catalog-tmp")
    try:
        temporary.write_text(text, encoding="utf-8")
        temporary.chmod(0o600)
        temporary.replace(env_file)
    finally:
        temporary.unlink(missing_ok=True)
    return len(catalog)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("catalog_file", type=Path)
    parser.add_argument(
        "--env-file", type=Path, default=Path(__file__).resolve().parents[1] / ".env"
    )
    args = parser.parse_args()
    try:
        count = configure_catalog(args.catalog_file, args.env_file)
    except (OSError, ValueError):
        parser.exit(
            1,
            "Catalog configuration failed. Check the private JSON catalog and existing .env.\n",
        )
    print(f"Configured {count} business units. Restart the API to apply the catalog.")


if __name__ == "__main__":
    main()
