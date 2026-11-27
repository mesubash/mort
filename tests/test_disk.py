import os
import tempfile
import time
import unittest
from pathlib import Path

from mort import disk, state
from mort.jobs import disk_used

GB = disk.KB_PER_GB
DAY = disk.DAY


class Disk(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old_home, state.HOME = state.HOME, Path(self.tmp.name)
        self.db = state.connect()

    def tearDown(self):
        state.HOME = self.old_home
        self.tmp.cleanup()

    def sizes(self, at, **kb):
        disk.record(self.db, {p.replace("_", "/"): v for p, v in kb.items()}, at)

    def test_parse_du(self):
        self.assertEqual(disk.parse_du("120\t/h/.cache/uv\n8\t/h/.cache/pip\n128\t/h/.cache\nnoise\n"),
                         {"/h/.cache/uv": 120, "/h/.cache/pip": 8, "/h/.cache": 128})

    def test_child_named_instead_of_parent_with_hint(self):
        now = 10 * DAY
        self.sizes(now - 7 * DAY, _h_c=5 * GB, _h_c_uv=2 * GB, _h_c_pip=1 * GB, _h_Downloads=1 * GB)
        self.sizes(now, _h_c=36 * GB, _h_c_uv=33 * GB, _h_c_pip=1 * GB, _h_Downloads=3 * GB)
        ranked = disk.growth(self.db, now)
        self.assertEqual([p for p, _ in ranked], ["/h/c/uv", "/h/Downloads"])  # /h/c is explained by uv
        self.assertEqual(disk.why(self.db, now), "/h/c/uv +31 GB this week (uv cache clean); /h/Downloads +2 GB this week")

    def test_needs_half_a_day_of_history_and_drops_old(self):
        now = 40 * DAY
        self.sizes(now - 3600, _h_c_uv=1 * GB)
        self.sizes(now, _h_c_uv=9 * GB)
        self.assertEqual(disk.growth(self.db, now), [])           # one hour apart is too soon to call growth
        self.sizes(now - 35 * DAY, _h_c_uv=1)
        disk.record(self.db, {}, now)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM disk_sizes WHERE at < ?", (now - 30 * DAY,)).fetchone()[0], 0)

    def test_due_once_a_day(self):
        self.assertTrue(disk.due(self.db, 1000))
        disk.record(self.db, {"/x": 1}, 1000)
        self.assertFalse(disk.due(self.db, 1000 + 3600))
        self.assertTrue(disk.due(self.db, 1000 + DAY))

    def test_measure_real_folder(self):
        d = Path(self.tmp.name) / "cache"
        (d / "big").mkdir(parents=True)
        (d / "big" / "f").write_bytes(b"x" * 300_000)
        sizes = disk.measure([str(d)])
        self.assertGreater(sizes[str(d / "big")], 250)
        self.assertGreaterEqual(sizes[str(d)], sizes[str(d / "big")])

    def test_hint_from_any_part_of_the_path(self):
        self.assertEqual(disk.hint("/h/Library/Containers/com.docker.docker/Data"), "docker system prune")
        self.assertEqual(disk.hint("/h/Library/Caches/Homebrew"), "brew cleanup --prune=all")
        self.assertIsNone(disk.hint("/h/Developer/my-project"))

    def test_disk_used_text(self):
        self.assertEqual(disk_used(50.0, 45.8), " · used 4.2 GB disk")
        self.assertEqual(disk_used(50.0, 50.05), "")
        self.assertEqual(disk_used(40.0, 42.0), " · 2.0 GB more free disk")

    def test_job_notice_and_low_disk_warning_carry_the_cause(self):
        from mort.jobs import check
        log, exit_file = state.job_files("train")
        log.parent.mkdir()
        log.write_text("x")
        exit_file.write_text("0\n")
        self.db.execute("INSERT INTO jobs (name, pid, log, started, disk_start) VALUES ('train', 999999, ?, ?, 50.0)",
                        (str(log), time.time() - 100))
        now = time.time()
        self.sizes(now - 6 * DAY, _h_c_uv=2 * GB)
        self.sizes(now, _h_c_uv=33 * GB)
        self.db.commit()
        sent = []
        check({}, notify=lambda m, s="": sent.append(f"{m}: {s}"), reading=(0.0, 3.6, 16.0))
        self.assertIn("train finished", sent[0])
        self.assertTrue(sent[0].endswith(" · used 46.4 GB disk"))
        self.assertEqual(sent[1], "disk low: 3.6 GB free: /h/c/uv +31 GB this week (uv cache clean)")


if __name__ == "__main__":
    unittest.main()
