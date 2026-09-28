"""Build a libpq connection string from an explicitly selected environment."""

from __future__ import annotations

import os
from collections.abc import Mapping

from psycopg.conninfo import make_conninfo


def dsn_from_postgres_env(env: Mapping[str, str] | None = None) -> str:
    """Return a safely escaped DSN from the five Compose PostgreSQL variables."""

    values = os.environ if env is None else env
    names = (
        "POSTGRES_USER",
        "POSTGRES_PASSWORD",
        "POSTGRES_HOST",
        "POSTGRES_PORT",
        "POSTGRES_DB",
    )
    missing = [name for name in names if not values.get(name)]
    if missing:
        raise ValueError(f"missing PostgreSQL environment: {', '.join(missing)}")
    return make_conninfo(
        user=values["POSTGRES_USER"],
        password=values["POSTGRES_PASSWORD"],
        host=values["POSTGRES_HOST"],
        port=values["POSTGRES_PORT"],
        dbname=values["POSTGRES_DB"],
    )
