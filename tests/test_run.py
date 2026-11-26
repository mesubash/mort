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
        self.lock.write_text(f"repo job of several words {os.getpid()} 2026-11-25_10:00\n")
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


class Status(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old_home, state.HOME = state.HOME, Path(self.tmp.name)
        (state.HOME / "logs").mkdir()

    def tearDown(self):
        state.HOME = self.old_home
        self.tmp.cleanup()

    def job(self, name, pid, code=None, log_age=0):
        from mort.jobs import status
        log, exit_file = state.job_files(name)
        log.write_text("x")
        t = time.time() - log_age
        os.utime(log, (t, t))
        if code is not None:
            exit_file.write_text(f"{code}\n")
        return status({"name": name, "pid": pid, "log": str(log), "started": time.time() - 100, "stall_after": 60, "done_marker": None})[0]

    def test_states(self):
        self.assertEqual(self.job("a", 999999, code=0), "finished")
        self.assertEqual(self.job("b", 999999, code=1), "died")
        self.assertEqual(self.job("c", 999999), "died")
        self.assertEqual(self.job("d", os.getpid(), log_age=120), "stalled")
        self.assertEqual(self.job("e", os.getpid(), log_age=5), "running")


class Kill(unittest.TestCase):
    setUp, tearDown = Run.setUp, Run.tearDown

    def test_kill_records_exit_and_frees_lock(self):
        from mort.jobs import kill
        start(["sleep", "30"], "k", lock={"path": str(self.lock)})
        time.sleep(0.3)
        self.assertTrue(self.lock.exists())
        self.assertTrue(kill("k", confirm=lambda _: "y"))
        self.assertTrue(wait_for(state.HOME / "logs" / "k.exit"))
        self.assertNotEqual((state.HOME / "logs" / "k.exit").read_text().strip(), "0")
        time.sleep(0.2)
        self.assertFalse(self.lock.exists())

    def test_kill_needs_yes(self):
        from mort.jobs import kill
        name, pid, _ = start(["sleep", "30"], "k2")
        self.assertFalse(kill("k2", confirm=lambda _: ""))
        os.killpg(pid, 9)


class Track(unittest.TestCase):
    setUp, tearDown = Run.setUp, Run.tearDown

    def test_adopted_job_finished_by_marker_or_died(self):
        import subprocess
        from mort.jobs import find, status
        from mort.run import track
        for name, text, want in (("ok", "epoch 3/3\nTRAINING DONE\n", "finished"), ("bad", "Traceback\n", "died")):
            log = state.HOME / f"{name}.txt"
            p = subprocess.Popen(["sleep", "30"])
            track(p.pid, name, log=str(log.touch() or log), done="TRAINING DONE")
            self.assertEqual(status(find(name))[0], "running")
            log.write_text(text)
            p.kill(); p.wait()
            self.assertEqual(status(find(name))[0], want)

    def test_dead_pid_refused(self):
        from mort.run import track
        with self.assertRaises(SystemExit):
            track(999999)


class Check(unittest.TestCase):
    setUp, tearDown = Run.setUp, Run.tearDown

    def add(self, name, pid, lock=0, stall_after=None, log_age=0):
        log, _ = state.job_files(name)
        log.parent.mkdir(exist_ok=True)
        log.write_text("x")
        t = time.time() - log_age
        os.utime(log, (t, t))
        db = state.connect()
        db.execute("INSERT INTO jobs (name, pid, log, started, stall_after, lock) VALUES (?, ?, ?, ?, ?, ?)",
                   (name, pid, str(log), time.time() - 100, stall_after, lock))
        db.commit()
        return log

    def run_check(self, lock=None):
        from mort.jobs import check
        sent = []
        check({"lock": lock} if lock else {}, notify=lambda m, s="": sent.append(m), reading=(0.0, 100.0, 16.0))
        return sent

    def test_event_sent_once(self):
        self.add("j", 999999)
        state.job_files("j")[1].write_text("1\n")
        self.assertEqual(self.run_check(), ["j died"])
        self.assertEqual(self.run_check(), [])

    def test_stall_resets_when_output_resumes(self):
        log = self.add("s", os.getpid(), stall_after=60, log_age=120)
        self.assertEqual(self.run_check(), ["s stalled"])
        log.write_text("more")
        self.assertEqual(self.run_check(), [])
        t = time.time() - 120
        os.utime(log, (t, t))
        self.assertEqual(self.run_check(), ["s stalled"])

    def test_mort_lock_freed_foreign_lock_warned_once(self):
        self.add("crashed", 999998, lock=1)
        self.lock.write_text("crashed 999998 2026-11-25T10:00\n")
        sent = self.run_check({"path": str(self.lock)})
        self.assertIn("freed the lock left by crashed", sent)
        self.assertFalse(self.lock.exists())
        self.lock.write_text("other 999997 2026-11-25T10:00\n")
        self.assertEqual(self.run_check({"path": str(self.lock)}), ["stale lock: its process is gone"])
        self.assertEqual(self.run_check({"path": str(self.lock)}), [])
        self.assertTrue(self.lock.exists())

    def test_kill_adopted_job_stops_its_children(self):
        import subprocess
        from mort.jobs import descendants, kill
        from mort.run import track
        parent = subprocess.Popen(["sh", "-c", "sleep 30; true"])  # like caffeinate: TERM to it alone spares the child
        time.sleep(0.3)
        children = descendants(parent.pid)
        self.assertTrue(children)
        track(parent.pid, "adopted")
        self.assertTrue(kill("adopted", confirm=lambda _: "y"))
        parent.wait(timeout=5)
        time.sleep(0.2)
        from mort.rules import pid_alive
        self.assertFalse(any(pid_alive(c) for c in children))


class Machine(unittest.TestCase):
    setUp, tearDown = Run.setUp, Run.tearDown

    def test_alert_once_then_clear_with_margin(self):
        from mort.jobs import check
        sent = []
        run = lambda swap, disk: check({}, notify=lambda m, s="": sent.append(m.split(":")[0]), reading=(swap, disk, 16.0))
        run(9.0, 3.0)
        self.assertEqual(sorted(sent), ["disk low", "swap high"])
        run(9.0, 3.0); run(7.5, 4.2)  # still on: within 10% of the limits
        self.assertEqual(len(sent), 2)
        run(1.0, 20.0); run(9.0, 20.0)  # cleared, then swap again
        self.assertEqual(sent[-1], "swap high")
