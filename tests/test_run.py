import os
import tempfile
import time
import unittest
from pathlib import Path

from mort import state
from mort.run import start


def wait_for(path, timeout=10):
    end = time.time() + timeout
    while not path.exists() and time.time() < end:
        time.sleep(0.05)
    return path.exists()


class Run(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old_home, state.HOME = state.HOME, Path(self.tmp.name)
        self.lock = Path(self.tmp.name) / "BUSY"

    def tearDown(self):
        state.HOME = self.old_home
        self.tmp.cleanup()

    def test_exit_code_log_and_lock_release(self):
        cfg = {"path": str(self.lock), "format": "repo {name} {pid} {start}"}
        name, pid, log = start(["sh", "-c", "echo hi; exit 3"], "t", lock=cfg)
        exit_file = state.HOME / "logs" / "t.exit"
        self.assertTrue(wait_for(exit_file))
        self.assertEqual(exit_file.read_text().strip(), "3")
        self.assertIn("hi", log.read_text())
        time.sleep(0.2)
        self.assertFalse(self.lock.exists())
        row = state.connect().execute("SELECT pid, lock FROM jobs WHERE name='t'").fetchone()
        self.assertEqual((row["pid"], row["lock"]), (pid, 1))

    def test_held_lock_refuses(self):
        self.lock.write_text(f"other job {os.getpid()} 2026-11-25T10:00\n")
        with self.assertRaises(SystemExit):
            start(["true"], "t", lock={"path": str(self.lock), "format": "repo {name} {pid} {start}"})

    def test_stale_lock_is_taken(self):
        self.lock.write_text("other job 999999 2026-11-25T10:00\n")
        start(["true"], "t", lock={"path": str(self.lock)})
        self.assertTrue(wait_for(state.HOME / "logs" / "t.exit"))
        time.sleep(0.2)
        self.assertFalse(self.lock.exists())

    def test_bad_name(self):
        with self.assertRaises(SystemExit):
            start(["true"], "../x")


if __name__ == "__main__":
    unittest.main()
