import sqlite3
import tempfile
import unittest
from pathlib import Path

from mort import state


class OldStateDb(unittest.TestCase):
    def test_pid_not_null_is_relaxed_and_rows_kept(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state.db"
            old = sqlite3.connect(path)  # schema of the first releases: pid NOT NULL, no later columns
            old.execute("CREATE TABLE jobs (name TEXT PRIMARY KEY, pid INTEGER NOT NULL, cmd TEXT, log TEXT,"
                        " started REAL NOT NULL, stall_after REAL, lock INTEGER NOT NULL DEFAULT 0, last_event TEXT)")
            old.execute("INSERT INTO jobs (name, pid, cmd, started) VALUES ('train', 42, 'python train.py', 1.0)")
            old.commit()
            old.close()

            db = state.connect(path)
            self.assertEqual(state.columns(db)["pid"], 0)
            row = db.execute("SELECT * FROM jobs WHERE name = 'train'").fetchone()
            self.assertEqual((row["pid"], row["cmd"], row["kind"]), (42, "python train.py", "local"))
            db.execute("INSERT INTO jobs (name, pid, started, kind) VALUES ('nb', NULL, 2.0, 'kaggle')")
            self.assertIsNone(db.execute("SELECT name FROM sqlite_master WHERE name = 'jobs_old'").fetchone())
            db.close()
            self.assertEqual(state.columns(state.connect(path))["pid"], 0)  # second open is a no-op


if __name__ == "__main__":
    unittest.main()
