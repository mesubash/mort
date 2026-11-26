import json
import tempfile
import threading
import unittest
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from mort import notify, state
from mort.notify import in_quiet


class Quiet(unittest.TestCase):
    def test_ranges(self):
        at = lambda h, m=0: datetime(2026, 11, 26, h, m)
        self.assertTrue(in_quiet("23:00-07:00", at(23)))
        self.assertTrue(in_quiet("23:00-07:00", at(3)))
        self.assertFalse(in_quiet("23:00-07:00", at(7)))      # end is not included
        self.assertTrue(in_quiet("12:00-13:30", at(13, 29)))
        self.assertFalse(in_quiet("12:00-13:30", at(14)))
        self.assertFalse(in_quiet(None, at(3)))


class Phone(unittest.TestCase):
    def setUp(self):
        self.got = []
        got = self.got

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                got.append((self.path, self.headers.get("Authorization"),
                            json.loads(self.rfile.read(int(self.headers["Content-Length"])))))
                self.send_response(200)
                self.end_headers()

            def log_message(self, *a):
                pass

        self.server = HTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.server.server_port}"
        self.tmp = tempfile.TemporaryDirectory()
        self.old_home, state.HOME = state.HOME, Path(self.tmp.name)
        self.old_desktop, notify.desktop = notify.desktop, lambda m, s="": None

    def tearDown(self):
        self.server.shutdown()
        state.HOME, notify.desktop = self.old_home, self.old_desktop
        self.tmp.cleanup()

    def test_push_json_with_token(self):
        notify.phone({"server": self.url, "topic": "t", "token": "tk_x"}, "train died", "02:14 (exit 1) ✗")
        self.assertEqual(self.got, [("/", "Bearer tk_x", {"topic": "t", "title": "mort: train died",
                                                          "message": "02:14 (exit 1) ✗", "icon": notify.ICON_URL})])

    def test_quiet_hours_hold_then_one_digest(self):
        clock = [datetime(2026, 11, 26, 2, 0)]
        n = notify.make({"ntfy": {"server": self.url, "topic": "t"}, "notify": {"quiet": "23:00-07:00"}},
                        now=lambda: clock[0])
        n("a died", "x")
        n("b finished", "y")
        n.flush()
        self.assertEqual(self.got, [])
        clock[0] = datetime(2026, 11, 26, 7, 5)
        n.flush()
        self.assertEqual(len(self.got), 1)
        self.assertEqual(self.got[0][2]["title"], "mort: 2 events during quiet hours")
        self.assertEqual(self.got[0][2]["message"], "a died; b finished")
        n.flush()
        self.assertEqual(len(self.got), 1)

    def test_unreachable_server_does_not_raise(self):
        notify.phone({"server": "http://127.0.0.1:9", "topic": "t"}, "x")


if __name__ == "__main__":
    unittest.main()
