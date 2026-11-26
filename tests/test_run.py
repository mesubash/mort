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
        return status({"name": name, "pid": pid, "log": str(log), "started": time.time() - 100, "stall_after": 60, "done_marker": None, "kind": "local", "watch": None, "watch_log": None})[0]

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


class Ssh(unittest.TestCase):
    setUp, tearDown = Run.setUp, Run.tearDown

    def setup_remote(self, replies):
        from mort import remote
        self.calls = []
        self.old_read = remote.read
        def fake(host, path):
            self.calls.append((host, path))
            return replies.pop(0)
        remote.read = fake
        self.addCleanup(setattr, remote, "read", self.old_read)

    def run_check(self, now=None):
        from mort.jobs import check
        sent = []
        check({}, notify=lambda m, s="": sent.append(f"{m}: {s}"), reading=(0.0, 100.0, 16.0))
        return sent

    def test_last_line_decides_and_steps_do_not_finish(self):
        from mort.remote import track
        track("my-server", "/jobs/prep/STATUS", done=r"^s2 DONE", failed=r"FAILED")
        self.setup_remote([("", None), ("s0 DONE\n", None), ("s0 DONE\ns1 DONE\ns2 DONE\n", None)])
        self.assertEqual(self.run_check(), [])            # no STATUS yet
        self.assertEqual(self.run_check(), [])            # one step done is not the job done
        self.assertEqual(self.run_check(), ["prep finished: STATUS: s2 DONE"])
        self.run_check()
        self.assertEqual(len(self.calls), 3)              # finished jobs are not read again

    def test_failed_and_default_markers(self):
        from mort.remote import track
        track("my-server", "/jobs/a/STATUS")
        self.setup_remote([("FAILED-HF\n", None)])
        self.assertEqual(self.run_check(), ["a died: STATUS: FAILED-HF"])

    def test_unreachable_is_unknown_and_backs_off(self):
        from mort.jobs import find, status
        from mort.remote import track
        track("my-server", "/jobs/b/STATUS")
        self.setup_remote([(None, "Connection timed out")])
        self.assertEqual(self.run_check(), [])
        self.run_check()
        self.assertEqual(len(self.calls), 1)              # backed off, no second ssh
        self.assertEqual(status(find("b"))[0], "unknown")

    def test_bad_host_refused(self):
        from mort.remote import track
        for host in ("-oProxyCommand=x", "a b", ""):
            with self.assertRaises(SystemExit):
                track(host, "/x/STATUS")


class GitHub(unittest.TestCase):
    setUp, tearDown = Run.setUp, Run.tearDown

    def test_replies_by_others_once(self):
        from mort import github
        from mort.jobs import check
        db = state.connect()
        github.enable(db, 0)  # since 1970
        db.commit()
        pr = {"repository_url": "https://api.github.com/repos/o/r", "number": 7, "pull_request": {}, "html_url": "u"}
        posts = {
            "repos/o/r/issues/7/comments": [
                {"user": {"login": "me"}, "body": "mine", "created_at": "2026-11-26T01:00:00Z"},
                {"user": {"login": "ci", "type": "Bot"}, "body": "coverage", "created_at": "2026-11-26T01:00:00Z"},
                {"user": {"login": "maint"}, "body": "Looks good,\n one nit", "created_at": "2026-11-26T02:00:00Z"}],
            "repos/o/r/pulls/7/comments": [],
            "repos/o/r/pulls/7/reviews": [{"user": {"login": "maint"}, "state": "APPROVED", "body": "",
                                           "submitted_at": "2026-11-26T03:00:00Z"}],
        }
        def api(path, **params):
            if path == "user":
                return {"login": "me"}
            if path == "search/issues":
                return {"items": [pr]}
            since = params.get("since", "")
            return [p for p in posts[path] if (p.get("created_at") or p.get("submitted_at")) > since]
        sent = []
        run = lambda: check({}, notify=lambda m, s="": sent.append(f"{m}: {s}"), reading=(0.0, 100.0, 16.0), gh_api=api)
        run()
        self.assertEqual(sent, ["reply on o/r#7 from maint: Looks good, one nit", "reply on o/r#7 from maint: approved"])
        db.execute("UPDATE alerts SET value = json_set(value, '$.checked', 0) WHERE key = 'github'")
        db.commit()
        run()
        self.assertEqual(len(sent), 2)  # the same replies are not sent again


class Kaggle(unittest.TestCase):
    setUp, tearDown = Run.setUp, Run.tearDown

    def test_running_then_complete_pulls_once(self):
        from mort import kaggle
        from mort.jobs import check
        replies = ["QUEUED", "RUNNING", "COMPLETE"]
        pulled = []
        old = kaggle.read_status, kaggle.kaggle
        kaggle.read_status = lambda slug: (replies.pop(0), None)
        kaggle.kaggle = lambda *a, timeout=0: (pulled.append(a) or "", None)
        self.addCleanup(lambda: (setattr(kaggle, "read_status", old[0]), setattr(kaggle, "kaggle", old[1])))
        out = Path(self.tmp.name) / "out"
        kaggle.track("user/my-kernel", pull=str(out))
        sent = []
        db = state.connect()
        for _ in range(4):
            check({}, notify=lambda m, s="": sent.append(f"{m}: {s}"), reading=(0.0, 100.0, 16.0))
            db.execute("UPDATE jobs SET tried_at = 0")  # skip the 5-minute wait
            db.commit()
        self.assertEqual(sent, [f"my-kernel finished: output in {out.resolve()}"])
        self.assertEqual(len(pulled), 1)
        self.assertEqual(pulled[0][:3], ("kernels", "output", "user/my-kernel"))

    def test_error_is_died_and_bad_input_refused(self):
        from mort import kaggle
        from mort.jobs import find, status
        old = kaggle.read_status
        kaggle.read_status = lambda slug: ("ERROR", None)
        self.addCleanup(setattr, kaggle, "read_status", old)
        kaggle.track("user/k2")
        db = state.connect()
        kaggle.poll(db, find("k2"), time.time())
        db.commit()
        self.assertEqual(status(find("k2"))[0], "died")
        full = Path(self.tmp.name) / "full"
        full.mkdir()
        (full / "x").write_text("x")
        for slug, pull in (("not-a-slug", None), ("user/k3", str(full))):
            with self.assertRaises(SystemExit):
                kaggle.track(slug, pull=pull)


class Watch(unittest.TestCase):
    setUp, tearDown = Check.setUp, Check.tearDown
    add = Check.add

    def test_frozen_number_stalls_though_log_grows(self):
        from mort.jobs import check, find, status
        log = self.add("w", os.getpid(), stall_after=60)
        db = state.connect()
        db.execute("UPDATE jobs SET watch = ? WHERE name = 'w'", (r"loss=([\d.]+)",))
        db.commit()
        sent = []
        tick = lambda: check({}, notify=lambda m, s="": sent.append(m), reading=(0.0, 100.0, 16.0))
        log.write_text("epoch 1/10 loss=0.90\r")
        tick()
        db.execute("UPDATE jobs SET watch_changed = watch_changed - 120 WHERE name = 'w'")  # 2 min pass
        db.commit()
        log.write_text("epoch 1/10 loss=0.90\nepoch 2/10 loss=0.90\n")  # log grew, number did not
        tick()
        self.assertEqual(sent, ["w stalled"])
        log.write_text("epoch 3/10 loss=0.71\n")
        tick()
        self.assertEqual(status(find("w"))[0], "running")
        self.assertIn("epoch 3/10 loss=0.71", status(find("w"))[1])

    def test_watch_needs_a_group(self):
        from mort.run import check_watch
        with self.assertRaises(SystemExit):
            check_watch("loss=[0-9.]+")


class WatchLog(unittest.TestCase):
    setUp, tearDown = Check.setUp, Check.tearDown
    add = Check.add

    def test_newest_matching_log_is_read(self):
        from mort.jobs import check, find, status
        self.add("multi", os.getpid(), stall_after=60)
        d = Path(self.tmp.name)
        (d / "part_a.log").write_text("1/9 2.0it/s\n")
        t = time.time() - 300
        os.utime(d / "part_a.log", (t, t))
        (d / "part_b.log").write_text("5/9 2.0it/s\n")
        db = state.connect()
        db.execute("UPDATE jobs SET watch = ?, watch_log = ? WHERE name = 'multi'", (r"(\d+/\d+) +[0-9.]+it/s", str(d / "part_*.log")))
        db.commit()
        check({}, notify=lambda m, s="": None, reading=(0.0, 100.0, 16.0))
        self.assertIn("5/9", status(find("multi"))[1])
