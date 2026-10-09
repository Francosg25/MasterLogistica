"""One-time initial administrator provisioning using migration credentials."""

import argparse
from uuid import UUID, uuid4

from pydantic import EmailStr, TypeAdapter
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session

from app.api import ADMIN_LOCK
from app.config import Settings
from app.models import ReconciliationLog, ReferenceCounter, User
from app.schemas import UserRead


def bootstrap_admin(
    settings: Settings,
    object_id: UUID,
    email: str,
    display_name: str,
    analyst_code: int | None = None,
    last_reference_sequence: int = 0,
):
    if not settings.entra_tenant_id:
        raise ValueError("Configure ENTRA_TENANT_ID before provisioning the administrator")
    email = str(TypeAdapter(EmailStr).validate_python(email))
    display_name = display_name.strip()
    if (
        not display_name
        or len(display_name) > 150
        or (analyst_code is not None and not 1 <= analyst_code <= 9)
    ):
        raise ValueError("Invalid administrator display name or analyst code")
    if not 0 <= last_reference_sequence < 2147483647:
        raise ValueError("Invalid initial reference counter")
    url = settings.migration_database_url or settings.database_url
    engine = create_engine(
        url.get_secret_value(), hide_parameters=True, connect_args={"connect_timeout": 5}
    )
    try:
        with Session(engine) as session, session.begin():
            if session.scalar(text("SELECT current_user")) == "masterlogistica_app":
                raise ValueError("Bootstrap requires the separate migration database role")
            session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": ADMIN_LOCK})
            if session.scalar(
                select(User.id).where(User.role == "SUPER_ADMIN", User.is_active.is_(True)).limit(1)
            ):
                raise ValueError(
                    "An active administrator already exists; use the authenticated user administration API"
                )
            row = User(
                id=uuid4(),
                entra_tenant_id=settings.entra_tenant_id,
                entra_object_id=object_id,
                email=email,
                display_name=display_name,
                role="SUPER_ADMIN",
                is_active=True,
                analyst_code=analyst_code,
            )
            session.add(row)
            session.flush()
            if analyst_code is not None:
                session.add(ReferenceCounter(owner_id=row.id, last_value=last_reference_sequence))
            session.add(
                ReconciliationLog(
                    service_actor="bootstrap-admin",
                    event_type="USER_BOOTSTRAPPED",
                    severity="GREEN",
                    rule_version="PHASE2_V1",
                    before_values={},
                    after_values=UserRead.model_validate(row).model_dump(mode="json"),
                )
            )
            return row.id
    finally:
        engine.dispose()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "object_id", type=UUID, help="Entra object ID, not an email or application ID"
    )
    parser.add_argument("email")
    parser.add_argument("display_name")
    parser.add_argument("--analyst-code", type=int)
    parser.add_argument("--last-reference-sequence", type=int, default=0)
    args = parser.parse_args()
    try:
        bootstrap_admin(
            Settings(),
            args.object_id,
            args.email,
            args.display_name,
            args.analyst_code,
            args.last_reference_sequence,
        )
    except Exception:
        parser.exit(
            1,
            "Administrator provisioning failed. Verify the migration connection, tenant and absence of an existing active administrator.\n",
        )
    print("Initial administrator provisioned; further users require the authenticated admin API.")


if __name__ == "__main__":
    main()
