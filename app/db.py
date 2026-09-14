"""Conexión a `catalog.db`. SQLite de solo lectura, sin ORM (CLAUDE.md)."""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

DB_PATH = Path(os.environ.get("CATALOG_DB_PATH", Path(__file__).resolve().parent.parent / "catalog.db"))


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn
