import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from mort import kaggle


class KaggleCli(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        fake = Path(self.tmp.name) / "kaggle"
        fake.write_text("#!/bin/sh\nif [ \"$1\" = hang ]; then sleep 30; fi\necho \"status $1\"\n")
        fake.chmod(0o755)
        self.env = mock.patch.dict(os.environ, {"PATH": f"{self.tmp.name}:{os.environ['PATH']}"})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def test_output_returned(self):
        self.assertEqual(kaggle.kaggle("ok"), ("status ok\n", None))

    def test_wall_clock_deadline_kills_a_hung_call(self):
        real, reads = time.time, []

        def clock():  # the first read sets the deadline; later reads look an hour later, as after a sleep
            reads.append(1)
            return real() + (3600 if len(reads) > 1 else 0)

        t0 = real()
        with mock.patch("mort.run.time.time", side_effect=clock):
            self.assertEqual(kaggle.kaggle("hang", timeout=1800), (None, "kaggle timed out"))
        self.assertLess(real() - t0, 15)

if __name__ == "__main__":
    unittest.main()
