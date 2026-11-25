import os
import subprocess
import unittest

from mort.rules import job_event, pid_alive, stale_lock

ALIVE = lambda pid: True
DEAD = lambda pid: False


class JobEvent(unittest.TestCase):
    def test_finished(self):
        self.assertEqual(job_event(False, 0, 0, 100, 20), "finished")

    def test_died_nonzero(self):
        self.assertEqual(job_event(False, 1, 0, 100, 20), "died")

    def test_died_without_exit_code(self):
        self.assertEqual(job_event(False, None, 0, 100, 20), "died")

    def test_stall_boundary(self):
        self.assertIsNone(job_event(True, None, 0, 20, 20))
        self.assertEqual(job_event(True, None, 0, 21, 20), "stalled")

    def test_stall_off(self):
        self.assertIsNone(job_event(True, None, 0, 10**9, None))


class StaleLock(unittest.TestCase):
    LINE = "repo job 4242 2026-11-25T10:00"

    def test_live_pid(self):
        self.assertFalse(stale_lock(self.LINE, 2, ALIVE))

    def test_dead_pid(self):
        self.assertTrue(stale_lock(self.LINE, 2, DEAD))

    def test_empty_lock(self):
        self.assertFalse(stale_lock("  \n", 2, DEAD))

    def test_unreadable_pid(self):
        self.assertTrue(stale_lock("repo job", 2, ALIVE))
        self.assertTrue(stale_lock("repo job abc", 2, ALIVE))


class PidAlive(unittest.TestCase):
    def test_self_and_reaped_child(self):
        self.assertTrue(pid_alive(os.getpid()))
        p = subprocess.Popen(["true"])
        p.wait()
        self.assertFalse(pid_alive(p.pid))


if __name__ == "__main__":
    unittest.main()
