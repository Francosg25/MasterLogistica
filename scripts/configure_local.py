"""Create local Docker configuration without overwriting an existing .env."""

import secrets
from pathlib import Path

root = Path(__file__).resolve().parents[1]
destination = root / ".env"
if destination.exists():
    raise SystemExit(
        ".env already exists. Its values and database passwords were preserved."
    )
contents = (root / ".env.example").read_text(encoding="utf-8")
contents = contents.replace(
    "POSTGRES_PASSWORD=\n", f"POSTGRES_PASSWORD={secrets.token_urlsafe(32)}\n"
)
contents = contents.replace(
    "APP_DB_PASSWORD=\n", f"APP_DB_PASSWORD={secrets.token_urlsafe(32)}\n"
)
destination.write_text(contents, encoding="utf-8")
destination.chmod(0o600)
print(
    "Created .env with independent database passwords. Add the Entra IDs before sign-in."
)
