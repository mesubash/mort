import os
import subprocess
import unittest

from mort.machine import parse_swap
from mort.rules import job_event, machine_alerts, pid_alive, stale_lock, time_left

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

    def test_pid_counted_from_end_with_spaces_in_name(self):
        line = "repo mean-teacher seeds 4242 2026-11-25_10:00"
        self.assertTrue(stale_lock(line, -2, DEAD))
        self.assertFalse(stale_lock(line, -2, ALIVE))

    def test_unreadable_pid(self):
        self.assertTrue(stale_lock("repo job", 2, ALIVE))
        self.assertTrue(stale_lock("repo job abc", 2, ALIVE))


class Machine(unittest.TestCase):
    def test_limits_and_margin(self):
        self.assertEqual(machine_alerts(8.0, 4.0, 8, 4, set()), set())  # exactly at the limit is fine
        self.assertEqual(machine_alerts(8.1, 3.9, 8, 4, set()), {"swap", "disk"})
        self.assertEqual(machine_alerts(7.3, 4.3, 8, 4, {"swap", "disk"}), {"swap", "disk"})
        self.assertEqual(machine_alerts(7.1, 4.5, 8, 4, {"swap", "disk"}), set())
        self.assertEqual(machine_alerts(None, 50, 8, 4, set()), set())

    def test_parse_swap(self):
        self.assertAlmostEqual(parse_swap("total = 2048.00M  used = 512.00M  free = 1536.00M  (encrypted)"), 0.5)
        self.assertAlmostEqual(parse_swap("total = 8.00G  used = 6.50G  free = 1.50G"), 6.5)
        self.assertIsNone(parse_swap(""))


class TimeLeft(unittest.TestCase):
    def test_rate_and_edges(self):
        self.assertEqual(time_left(10, 0, 20, 50, 100), 300)  # 10 steps per 100 s, 30 to go
        self.assertIsNone(time_left(10, 0, 10, 50, 100))     # no progress yet
        self.assertIsNone(time_left(10, 0, 50, 50, 100))     # done


class PidAlive(unittest.TestCase):
    def test_self_and_reaped_child(self):
        self.assertTrue(pid_alive(os.getpid()))
        p = subprocess.Popen(["true"])
        p.wait()
        self.assertFalse(pid_alive(p.pid))


if __name__ == "__main__":
    unittest.main()
