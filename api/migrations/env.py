import os
import sys
from logging.config import fileConfig
from pathlib import Path

from sqlalchemy import engine_from_config
from sqlalchemy import pool

from alembic import context

# migrations/env.py -> parents[1] is api/ -- put it on sys.path so
# `from app.db import Base` resolves the same way it does for the app
# itself and for tests, without requiring `api` to be pip-installed.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db import Base  # noqa: E402

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Same DATABASE_URL env var app/db.py reads -- overrides alembic.ini's
# static placeholder so `alembic upgrade head` targets whatever database
# the API itself is actually configured against (see docker-compose.yml).
if os.environ.get("DATABASE_URL"):
    config.set_main_option("sqlalchemy.url", os.environ["DATABASE_URL"])

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Every table in app/db/ is registered on Base.metadata as a side effect
# of the import above -- app/db/__init__.py imports each of its submodules
# (reports/rbac/ldap/jobs) eagerly for exactly this reason, so autogenerate
# can diff against the full schema, not just whichever tables some other
# import path happened to touch first.
target_metadata = Base.metadata

# other values from the config, defined by the needs of env.py,
# can be acquired:
# my_important_option = config.get_main_option("my_important_option")
# ... etc.


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    In this scenario we need to create an Engine
    and associate a connection with the context.

    """
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        # SQLite can't ALTER TABLE to add a foreign key (or most other
        # constraint changes) to an existing table -- it has to recreate
        # the table under the hood, which is exactly what Alembic's
        # "batch" mode does automatically. Irrelevant for Postgres (the
        # real target -- see docker-compose.yml), which supports plain
        # ALTER TABLE for this, so only turn it on for the SQLite fallback
        # (app/db.py's zero-setup local-dev default).
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=(connection.dialect.name == "sqlite"),
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
