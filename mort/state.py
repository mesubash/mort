import sqlite3
from pathlib import Path

HOME = Path.home() / ".mort"

SCHEMA = """CREATE TABLE IF NOT EXISTS jobs (
    name TEXT PRIMARY KEY,
    pid INTEGER NOT NULL,
    cmd TEXT,
    log TEXT,
    started REAL NOT NULL,
    stall_after REAL,
    lock INTEGER NOT NULL DEFAULT 0,
    last_event TEXT
)"""


def connect(path=None):
    if path is None:
        HOME.mkdir(exist_ok=True)
        path = HOME / "state.db"
    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    db.execute(SCHEMA)
    return db
