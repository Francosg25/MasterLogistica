from alembic import context
from sqlalchemy import create_engine, pool, text

from app.config import MigrationSettings
from app.models import Base

config = context.config
target_metadata = Base.metadata


def migration_url():
    settings = config.attributes.get("migration_settings") or MigrationSettings()
    value = settings.migration_database_url or settings.database_url
    return value.get_secret_value()


def run_offline():
    context.configure(
        url=migration_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_online():
    connectable = create_engine(
        migration_url(),
        poolclass=pool.NullPool,
        hide_parameters=True,
        connect_args={"connect_timeout": 10},
    )
    with connectable.connect() as connection:
        connection.execute(text("SELECT pg_advisory_lock(638917241)"))
        connection.commit()
        try:
            context.configure(
                connection=connection, target_metadata=target_metadata, compare_type=True
            )
            with context.begin_transaction():
                context.run_migrations()
        finally:
            connection.rollback()
            connection.execute(text("SELECT pg_advisory_unlock(638917241)"))
            connection.commit()
    connectable.dispose()


if context.is_offline_mode():
    run_offline()
else:
    run_online()
