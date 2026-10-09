from alembic import context
from sqlalchemy import create_engine, pool

from app.config import Settings
from app.models import Base

config = context.config
target_metadata = Base.metadata


def migration_url():
    settings = Settings()
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
    connectable = create_engine(migration_url(), poolclass=pool.NullPool, hide_parameters=True)
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()
    connectable.dispose()


if context.is_offline_mode():
    run_offline()
else:
    run_online()
