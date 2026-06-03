"""Persistence layer for the RedPipeline BI tool.

Stores user-created dashboards, notes/recommendations, training sessions and
recruitment shortlists.

Backend selection (via the DATABASE_URL environment variable):
  * Postgres   — set DATABASE_URL=postgres://...  (Vercel Postgres / Neon /
                 Supabase).  Recommended for the deployed app so data syncs
                 across devices.
  * SQLite     — default when DATABASE_URL is unset (sqlite:///./redpipeline.db).
                 Great for local use / self-hosting.

The module degrades gracefully: if the database cannot be reached, the API
reports `db_available = False` and the UI shows a "connect a database" banner
instead of crashing.
"""

from __future__ import annotations

import datetime as _dt
import os
from typing import Any

from sqlalchemy import (
    JSON,
    Column,
    DateTime,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    create_engine,
    delete,
    insert,
    select,
    update,
)
from sqlalchemy.engine import Engine

# ---------------------------------------------------------------------------
# Engine / connection
# ---------------------------------------------------------------------------

def _normalise_url(url: str) -> str:
    # Many providers hand out postgres://; SQLAlchemy wants postgresql://
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)
    return url


DATABASE_URL = _normalise_url(os.environ.get("DATABASE_URL", "sqlite:///./redpipeline.db"))

metadata = MetaData()
_engine: Engine | None = None


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        kwargs: dict[str, Any] = {"pool_pre_ping": True, "future": True}
        if DATABASE_URL.startswith("sqlite"):
            kwargs["connect_args"] = {"check_same_thread": False}
        _engine = create_engine(DATABASE_URL, **kwargs)
        metadata.create_all(_engine)
    return _engine


def db_available() -> bool:
    try:
        eng = get_engine()
        with eng.connect() as conn:
            conn.exec_driver_sql("SELECT 1")
        return True
    except Exception:  # noqa: BLE001
        return False


def db_backend() -> str:
    return "postgres" if DATABASE_URL.startswith("postgresql") else "sqlite"


def _now() -> _dt.datetime:
    return _dt.datetime.utcnow()


# ---------------------------------------------------------------------------
# Tables
# ---------------------------------------------------------------------------

dashboards = Table(
    "dashboards", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("name", String(200), nullable=False),
    Column("context", String(60), nullable=False, default="custom"),   # match / recruitment / training / squad / custom
    Column("layout", JSON, nullable=False, default=list),               # list[widget dict]
    Column("created_at", DateTime, default=_now),
    Column("updated_at", DateTime, default=_now, onupdate=_now),
)

notes = Table(
    "notes", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("scope", String(40), nullable=False, default="general"),     # match / player / training / signing / general
    Column("ref_id", String(120), nullable=True),                       # e.g. match_id or player_id
    Column("ref_label", String(200), nullable=True),                    # human label
    Column("title", String(200), nullable=True),
    Column("body", Text, nullable=False, default=""),
    Column("tags", JSON, nullable=False, default=list),
    Column("created_at", DateTime, default=_now),
    Column("updated_at", DateTime, default=_now, onupdate=_now),
)

training = Table(
    "training", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("session_date", String(20), nullable=False),                 # ISO date string
    Column("focus", String(120), nullable=True),                        # e.g. "High press drills"
    Column("rpe", Integer, nullable=True),                              # session RPE 1-10
    Column("duration_min", Integer, nullable=True),
    Column("metrics", JSON, nullable=False, default=dict),               # arbitrary numeric KPIs
    Column("notes", Text, nullable=True),
    Column("created_at", DateTime, default=_now),
)

shortlist = Table(
    "shortlist", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("player_id", String(60), nullable=True),
    Column("player_name", String(200), nullable=False),
    Column("position", String(60), nullable=True),
    Column("status", String(30), nullable=False, default="watch"),      # watch / target / signed / rejected
    Column("rating", Integer, nullable=True),                          # 1-5
    Column("tags", JSON, nullable=False, default=list),
    Column("notes", Text, nullable=True),
    Column("created_at", DateTime, default=_now),
    Column("updated_at", DateTime, default=_now, onupdate=_now),
)

_TABLES = {
    "dashboards": dashboards,
    "notes": notes,
    "training": training,
    "shortlist": shortlist,
}


# ---------------------------------------------------------------------------
# Generic CRUD helpers
# ---------------------------------------------------------------------------

def _row_to_dict(row) -> dict[str, Any]:
    d = dict(row._mapping)
    for k, v in d.items():
        if isinstance(v, _dt.datetime):
            d[k] = v.isoformat()
    return d


def list_rows(table_name: str, where: dict[str, Any] | None = None,
              order_desc: str | None = "created_at") -> list[dict[str, Any]]:
    table = _TABLES[table_name]
    stmt = select(table)
    if where:
        for col, val in where.items():
            if val is not None:
                stmt = stmt.where(table.c[col] == val)
    if order_desc and order_desc in table.c:
        stmt = stmt.order_by(table.c[order_desc].desc())
    with get_engine().connect() as conn:
        return [_row_to_dict(r) for r in conn.execute(stmt)]


def get_row(table_name: str, row_id: int) -> dict[str, Any] | None:
    table = _TABLES[table_name]
    with get_engine().connect() as conn:
        r = conn.execute(select(table).where(table.c.id == row_id)).first()
        return _row_to_dict(r) if r else None


def create_row(table_name: str, values: dict[str, Any]) -> dict[str, Any]:
    table = _TABLES[table_name]
    allowed = {c.name for c in table.columns}
    clean = {k: v for k, v in values.items() if k in allowed and k != "id"}
    with get_engine().begin() as conn:
        result = conn.execute(insert(table).values(**clean))
        new_id = result.inserted_primary_key[0]
    return get_row(table_name, new_id)  # type: ignore[return-value]


def update_row(table_name: str, row_id: int, values: dict[str, Any]) -> dict[str, Any] | None:
    table = _TABLES[table_name]
    allowed = {c.name for c in table.columns}
    clean = {k: v for k, v in values.items() if k in allowed and k not in ("id", "created_at")}
    with get_engine().begin() as conn:
        conn.execute(update(table).where(table.c.id == row_id).values(**clean))
    return get_row(table_name, row_id)


def delete_row(table_name: str, row_id: int) -> bool:
    table = _TABLES[table_name]
    with get_engine().begin() as conn:
        result = conn.execute(delete(table).where(table.c.id == row_id))
    return result.rowcount > 0
