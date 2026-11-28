import json
import os
import tempfile
import time
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest import mock

from mort import cli, jobs, state  # noqa: F401 (daemon patched by path)


class AgentCommands(unittest.TestCase):
    """mort status --json and mort wait, for scripts and coding agents."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old_home, state.HOME = state.HOME, Path(self.tmp.name)
        (state.HOME / "logs").mkdir()

    def tearDown(self):
        state.HOME = self.old_home
        self.tmp.cleanup()

    def add(self, name, pid, code=None):
        log, exit_file = state.job_files(name)
        log.write_text("step 1\n")
        if code is not None:
            exit_file.write_text(f"{code}\n")
        db = state.connect()
        db.execute("INSERT INTO jobs (name, pid, log, started, stall_after) VALUES (?, ?, ?, ?, ?)",
                   (name, pid, str(log), time.time() - 60, 3600))
        db.commit()

    def test_status_json(self):
        self.add("train", 999999, code=0)
        self.add("eval", os.getpid())
        buf = StringIO()
        with redirect_stdout(buf):
            cli.main(["status", "--json"])
        out = {j["name"]: j for j in json.loads(buf.getvalue())}
        self.assertEqual((out["train"]["state"], out["eval"]["state"]), ("finished", "running"))
        self.assertEqual(out["train"]["log"], str(state.job_files("train")[0]))

    def test_wait_returns_when_the_job_dies(self):
        self.add("train", os.getpid())
        rounds = []

        def sleep(_):  # the job dies after the first look
            rounds.append(1)
            state.job_files("train")[1].write_text("1\n")

        job = jobs.wait("train", sleep=sleep)
        self.assertEqual((job["state"], len(rounds)), ("died", 1))

    def test_wait_times_out(self):
        self.add("train", os.getpid())
        t = [0.0]

        def sleep(s):
            t[0] += s

        self.assertIsNone(jobs.wait("train", timeout=90, every=30, sleep=sleep, clock=lambda: t[0]))
        self.assertEqual(t[0], 90)

    def test_wait_exit_code(self):
        self.add("train", 999999, code=0)
        buf = StringIO()
        with redirect_stdout(buf), self.assertRaises(SystemExit) as end, \
                mock.patch("mort.daemon.running", return_value=True):  # no real check, so no real notification
            cli.main(["wait", "train", "--every", "0"])
        self.assertEqual((end.exception.code, json.loads(buf.getvalue())["state"]), (0, "finished"))


if __name__ == "__main__":
    unittest.main()
