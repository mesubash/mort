import sqlite3
import tomllib
from pathlib import Path

HOME = Path.home() / ".mort"

SCHEMA = """CREATE TABLE IF NOT EXISTS jobs (
    name TEXT PRIMARY KEY,
    pid INTEGER,
    cmd TEXT,
    log TEXT,
    started REAL NOT NULL,
    stall_after REAL,
    lock INTEGER NOT NULL DEFAULT 0,
    last_event TEXT
)"""

ADDED = {
    "done_marker": "TEXT",
    "kind": "TEXT NOT NULL DEFAULT 'local'",  # local, ssh or kaggle
    "failed_marker": "TEXT",
    "target": "TEXT",           # ssh: host:path
    "remote_text": "TEXT",      # ssh: last lines read
    "remote_error": "TEXT",
    "remote_at": "REAL",        # ssh: time of the last good read
    "tried_at": "REAL",
    "pull": "TEXT",             # kaggle: folder for the output
    "watch": "TEXT",            # regex whose first group must keep changing
    "watch_value": "TEXT",
    "watch_changed": "REAL",
    "progress": "TEXT",         # last log line the watch regex matched
    "progress_start": "TEXT",   # "n time" when an N/M count was first seen
    "watch_log": "TEXT",        # glob of the log(s) the job writes itself; the newest is read
    "every": "REAL",            # ssh, kaggle: seconds between reads (default: every check / 5 min)
}


ALERTS = "CREATE TABLE IF NOT EXISTS alerts (key TEXT PRIMARY KEY, value TEXT)"


def connect(path=None):
    if path is None:
        HOME.mkdir(exist_ok=True)
        path = HOME / "state.db"
    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    db.execute(SCHEMA)
    db.execute(ALERTS)
    have = {r[1] for r in db.execute("PRAGMA table_info(jobs)")}
    for column, kind in ADDED.items():  # columns newer than an existing state.db
        if column not in have:
            db.execute(f"ALTER TABLE jobs ADD COLUMN {column} {kind}")
    return db


def load_config():
    path = HOME / "config.toml"
    if not path.exists():
        return {}
    with open(path, "rb") as f:
        return tomllib.load(f)


def job_files(name):
    logs = HOME / "logs"
    return logs / f"{name}.log", logs / f"{name}.exit"
