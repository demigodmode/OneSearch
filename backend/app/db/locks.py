# Copyright (C) 2026 demigodmode
# SPDX-License-Identifier: AGPL-3.0-only

"""Write-lock helpers shared by the API modules."""

from sqlalchemy.orm import Session


def begin_immediate(db: Session) -> None:
    # Only wait briefly for the write lock. busy_timeout sticks to the pooled
    # connection, so put the old value back before anything else gets it.
    conn = db.connection()
    previous = int(conn.exec_driver_sql("PRAGMA busy_timeout").scalar())
    conn.exec_driver_sql("PRAGMA busy_timeout=400")
    try:
        conn.exec_driver_sql("BEGIN IMMEDIATE")
    finally:
        conn.exec_driver_sql(f"PRAGMA busy_timeout={previous}")
