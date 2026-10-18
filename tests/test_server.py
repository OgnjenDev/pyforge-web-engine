"""End-to-end tests: a real server on a free port, driven over HTTP like a browser would."""
import http.client
import json
import socket
import threading
import time
import unittest
from pathlib import Path

from pyforge.server import make_server

ROOT = Path(__file__).resolve().parent.parent
BASIC = ROOT / "examples" / "basic_game.py"


class Stream:
    """A minimal Server-Sent Events reader."""

    def __init__(self, port, session, timeout=5.0):
        self.conn = http.client.HTTPConnection("127.0.0.1", port, timeout=timeout)
        self.conn.request("GET", f"/api/stream?session={session}")
        self.resp = self.conn.getresponse()
        self.status = self.resp.status

    def next(self):
        """Return the next JSON message, or None on a read timeout."""
        while True:
            try:
                line = self.resp.fp.readline()
            except (socket.timeout, TimeoutError):
                return None
            if not line:
                return "EOF"
            line = line.decode().strip()
            if line.startswith("data: "):
                return json.loads(line[6:])

    def wait_for(self, predicate, limit=200):
        for _ in range(limit):
            msg = self.next()
            if msg is None or msg == "EOF":
                return None
            if predicate(msg):
                return msg
        return None

    def close(self):
        self.conn.close()


class ServerTestCase(unittest.TestCase):
    script = BASIC
    options = {}

    def setUp(self):
        self.server = make_server(self.script, "127.0.0.1", 0, cleanup_interval=0.1, **self.options)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
        self.thread.start()
        self.streams = []

    def tearDown(self):
        for s in self.streams:
            s.close()
        self.server.manager.close_all()
        self.server.shutdown()
        self.server.server_close()

    def request(self, method, path, body=None, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        data = body if isinstance(body, (bytes, type(None))) else json.dumps(body).encode()
        conn.request(method, path, body=data, headers=headers or {})
        resp = conn.getresponse()
        raw = resp.read()
        conn.close()
        try:
            return resp.status, json.loads(raw)
        except ValueError:
            return resp.status, raw

    def new_session(self):
        status, data = self.request("POST", "/api/session")
        self.assertEqual(status, 200)
        return data["session"]

    def open_stream(self, session):
        s = Stream(self.port, session)
        self.streams.append(s)
        return s

    def send(self, session, *events):
        return self.request("POST", f"/api/input?session={session}", {"events": list(events)})


def key(name, down):
    return {"type": "key", "key": name, "down": down}


class TwoClientsTests(ServerTestCase):
    def test_two_browsers_play_separate_games_at_the_same_time(self):
        sid_a, sid_b = self.new_session(), self.new_session()
        self.assertNotEqual(sid_a, sid_b)
        stream_a, stream_b = self.open_stream(sid_a), self.open_stream(sid_b)

        init_a = stream_a.wait_for(lambda m: m["t"] == "init")
        init_b = stream_b.wait_for(lambda m: m["t"] == "init")
        for init in (init_a, init_b):
            self.assertEqual(init["config"]["width"], 800)
            self.assertEqual(init["bg"], "#202020")
            self.assertEqual(init["ents"]["1"]["x"], 100)

        # Player A holds RIGHT; player B holds DOWN.
        self.send(sid_a, key("right", True))
        self.send(sid_b, key("down", True))
        msg_a = stream_a.wait_for(lambda m: m["t"] == "state" and m.get("set", {}).get("1", {}).get("x", 0) >= 150)
        msg_b = stream_b.wait_for(lambda m: m["t"] == "state" and m.get("set", {}).get("1", {}).get("y", 0) >= 150)
        self.assertIsNotNone(msg_a, "player A's sprite never moved right")
        self.assertIsNotNone(msg_b, "player B's sprite never moved down")
        self.assertNotIn("y", msg_a["set"]["1"])  # A never moved vertically
        self.assertNotIn("x", msg_b["set"]["1"])  # B never moved horizontally

        # Server-side truth agrees: neither game was touched by the other's input.
        game_a = self.server.manager.get(sid_a).game._entities[1]
        game_b = self.server.manager.get(sid_b).game._entities[1]
        self.assertGreater(game_a.x, 100)
        self.assertEqual(game_a.y, 100)
        self.assertEqual(game_b.x, 100)
        self.assertGreater(game_b.y, 100)

        # Releasing the key stops the sprite (no stuck input).
        self.send(sid_a, key("right", False))
        time.sleep(0.2)
        x = self.server.manager.get(sid_a).game._entities[1].x
        time.sleep(0.2)
        self.assertEqual(self.server.manager.get(sid_a).game._entities[1].x, x)

    def test_static_files_and_health(self):
        status, body = self.request("GET", "/")
        self.assertEqual(status, 200)
        self.assertIn(b"<canvas", body)
        status, body = self.request("GET", "/client.js")
        self.assertEqual(status, 200)
        self.assertIn(b"EventSource", body)
        status, data = self.request("GET", "/api/health")
        self.assertEqual((status, data["ok"]), (200, True))


class RobustnessTests(ServerTestCase):
    def assert_server_alive(self):
        status, data = self.request("GET", "/api/health")
        self.assertEqual(status, 200)

    def test_invalid_requests_do_not_crash_the_server(self):
        sid = self.new_session()
        cases = [
            ("GET", "/nope", None, 404),
            ("GET", "/../../etc/passwd", None, 404),
            ("GET", "/api/stream", None, 400),
            ("GET", "/api/stream?session=does-not-exist-123", None, 404),
            ("POST", "/api/input", b"{}", 400),
            ("POST", "/api/input?session=!!!", b"{}", 400),
            ("POST", "/api/input?session=doesnotexist1234", b"{}", 404),
            ("POST", f"/api/input?session={sid}", b"not json", 400),
            ("POST", f"/api/input?session={sid}", b"[1,2,3]", 400),
            ("POST", f"/api/input?session={sid}", b'{"events": "nope"}', 400),
            ("POST", f"/api/input?session={sid}", b"\xff\xfe", 400),
            ("POST", f"/api/input?session={sid}", b"x" * (70 * 1024), 413),
            ("GET", "/api/input", None, 405),
            ("POST", "/api/health", b"", 405),
            ("POST", "/api/shutdown", b"{}", 403),
        ]
        for method, path, body, expected in cases:
            with self.subTest(method=method, path=path[:40]):
                status, _ = self.request(method, path, body)
                self.assertEqual(status, expected)
        self.assert_server_alive()

    def test_garbage_events_are_ignored(self):
        sid = self.new_session()
        status, data = self.send(sid, None, 5, {"type": "key"}, {"type": "mouse", "x": "a", "y": 1}, key("left", True))
        self.assertEqual((status, data["accepted"]), (200, 1))

    def test_raw_garbage_on_the_socket(self):
        for payload in (b"\x00\x01\x02garbage\r\n\r\n", b"GET / HTTP/9.9\r\n\r\n", b"POST /api/session HTTP/1.1\r\nContent-Length: abc\r\n\r\n"):
            with socket.create_connection(("127.0.0.1", self.port), timeout=3) as s:
                s.sendall(payload)
                try:
                    s.recv(1024)
                except socket.timeout:
                    pass
        self.assert_server_alive()

    def test_unexpected_shutdown_token_is_rejected(self):
        status, _ = self.request("POST", "/api/shutdown", b"{}", {"X-PyForge-Token": "guess"})
        self.assertEqual(status, 403)
        self.assert_server_alive()


class SessionLifecycleTests(ServerTestCase):
    options = {"session_timeout": 0.6}

    def test_idle_session_is_cleaned_up(self):
        sid = self.new_session()
        status, health = self.request("GET", "/api/health")
        self.assertEqual(health["sessions"], 1)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            status, _ = self.send(sid)
            if status == 404:
                break
            time.sleep(1.0)  # longer than the timeout, so the heartbeat below is skipped
        self.assertEqual(status, 404)
        _, health = self.request("GET", "/api/health")
        self.assertEqual(health["sessions"], 0)

    def test_heartbeat_keeps_session_alive(self):
        sid = self.new_session()
        for _ in range(8):
            time.sleep(0.2)
            status, _ = self.send(sid)
            self.assertEqual(status, 200)

    def test_disconnected_stream_releases_the_session_listener(self):
        sid = self.new_session()
        stream = self.open_stream(sid)
        stream.wait_for(lambda m: m["t"] == "init")
        session = self.server.manager.get(sid)
        self.assertEqual(session.listeners, 1)
        stream.close()
        deadline = time.monotonic() + 5
        while session.listeners and time.monotonic() < deadline:
            time.sleep(0.05)
        self.assertEqual(session.listeners, 0)

    def test_close_endpoint_frees_the_session(self):
        sid = self.new_session()
        status, _ = self.request("POST", f"/api/close?session={sid}")
        self.assertEqual(status, 200)
        status, _ = self.send(sid)
        self.assertEqual(status, 404)

    def test_closing_notifies_the_stream(self):
        sid = self.new_session()
        stream = self.open_stream(sid)
        stream.wait_for(lambda m: m["t"] == "init")
        self.request("POST", f"/api/close?session={sid}")
        msg = stream.wait_for(lambda m: m["t"] == "closed")
        self.assertIsNotNone(msg)


class FullServerTests(ServerTestCase):
    options = {"max_sessions": 2}

    def test_server_full_returns_503(self):
        self.new_session()
        self.new_session()
        status, data = self.request("POST", "/api/session")
        self.assertEqual(status, 503)
        self.assertIn("full", data["error"])


class ErrorReportingTests(ServerTestCase):
    @classmethod
    def setUpClass(cls):
        import tempfile

        cls.tmp = tempfile.TemporaryDirectory()
        path = Path(cls.tmp.name) / "broken.py"
        path.write_text(
            "import pyforge as game\n"
            "def update():\n"
            "    1 / 0\n"
            "game.run(update)\n"
        )
        cls.script = path

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_browser_receives_the_game_error_and_server_survives(self):
        sid = self.new_session()
        stream = self.open_stream(sid)
        msg = stream.wait_for(lambda m: m.get("status") == "error")
        self.assertIsNotNone(msg)
        self.assertIn("ZeroDivisionError", msg["error"])
        self.assertIn("line 3", msg["error"])
        self.assertEqual(self.request("GET", "/api/health")[0], 200)
        status, _ = self.request("POST", f"/api/restart?session={sid}")
        self.assertEqual(status, 200)


if __name__ == "__main__":
    unittest.main()
