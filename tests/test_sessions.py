import tempfile
import time
import unittest
from pathlib import Path

from pyforge.sessions import ServerFull, SessionConfig, SessionManager, diff_snapshots

ROOT = Path(__file__).resolve().parent.parent
BASIC = ROOT / "examples" / "basic_game.py"


def wait_until(predicate, timeout=5.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if predicate():
            return True
        time.sleep(0.01)
    return False


def keys(*names, down=True):
    return [{"type": "key", "key": n, "down": down} for n in names]


class SessionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.managers = []

    def manager(self, script=BASIC, **config):
        m = SessionManager(script, SessionConfig(cleanup_interval=0.05, **config))
        self.managers.append(m)
        self.addCleanup(m.close_all)
        return m

    def script(self, text):
        path = Path(self.tmp.name) / "game.py"
        path.write_text(text)
        return path

    def attached(self, manager):
        s = manager.create()
        s.attach()
        self.assertTrue(wait_until(lambda: s.game is not None and s.game.frame_count > 0))
        return s

    def test_two_sessions_have_independent_state(self):
        m = self.manager()
        a, b = self.attached(m), self.attached(m)
        self.assertNotEqual(a.id, b.id)
        a.push_input(keys("right"))
        self.assertTrue(wait_until(lambda: a.game._entities[1].x > 100))
        time.sleep(0.1)
        self.assertEqual(b.game._entities[1].x, 100)
        self.assertEqual(b.game._entities[1].y, 100)
        self.assertIsNot(a.game, b.game)

    def test_game_pauses_without_a_viewer(self):
        m = self.manager()
        s = m.create()
        self.assertTrue(wait_until(lambda: s.game is not None and s.game.status == "running"))
        time.sleep(0.2)
        self.assertEqual(s.game.frame_count, 0)
        s.attach()
        self.assertTrue(wait_until(lambda: s.game.frame_count > 3))
        s.detach()
        time.sleep(0.1)
        frozen = s.game.frame_count
        time.sleep(0.2)
        self.assertLessEqual(s.game.frame_count - frozen, 1)

    def test_idle_sessions_are_swept(self):
        m = self.manager(session_timeout=0.2)
        s = m.create()
        self.assertEqual(m.count(), 1)
        self.assertTrue(wait_until(lambda: m.count() == 0, 3))
        self.assertTrue(s.closed)
        self.assertIsNone(m.get(s.id))

    def test_activity_keeps_a_session_alive(self):
        m = self.manager(session_timeout=0.3)
        s = m.create()
        for _ in range(8):
            time.sleep(0.1)
            s.push_input([])  # heartbeat
        self.assertEqual(m.count(), 1)

    def test_sweep_uses_given_clock(self):
        m = self.manager(session_timeout=10)
        m._stop.set()
        s = m.create()
        self.assertEqual(m.sweep(now=s.last_seen + 5), 0)
        self.assertEqual(m.sweep(now=s.last_seen + 11), 1)

    def test_max_sessions(self):
        m = self.manager(max_sessions=2)
        m.create()
        m.create()
        with self.assertRaises(ServerFull):
            m.create()

    def test_remove_closes_session_and_wakes_waiters(self):
        m = self.manager()
        s = m.create()
        self.assertTrue(m.remove(s.id))
        _, _, closed, reason = s.wait_for_update(-1, 1.0)
        self.assertTrue(closed)
        self.assertFalse(m.remove(s.id))

    def test_error_in_update_is_reported_and_isolated(self):
        path = self.script(
            "import pyforge as game\n"
            "n = 0\n"
            "def update():\n"
            "    global n\n"
            "    n += 1\n"
            "    if n == 3:\n"
            "        raise ValueError('boom')\n"
            "game.run(update)\n"
        )
        m = self.manager(path)
        s = self.attached(m)
        self.assertTrue(wait_until(lambda: s.game.status == "error"))
        snap, _, _, _ = s.wait_for_update(-1, 1.0)
        self.assertEqual(snap.status, "error")
        self.assertIn("ValueError: boom", snap.error)
        self.assertIn("line 7", snap.error)
        # the session survives and can be restarted; other sessions are unaffected
        other = m.create()
        self.assertFalse(other.closed)
        s.request_restart()
        self.assertTrue(wait_until(lambda: s.game.status in ("running", "error") and s.game.epoch == 2))

    def test_syntax_error_in_script_is_reported(self):
        m = self.manager(self.script("def update(:\n    pass\n"))
        s = m.create()
        self.assertTrue(wait_until(lambda: s._snapshot is not None))
        self.assertEqual(s._snapshot.status, "error")
        self.assertIn("SyntaxError", s._snapshot.error)

    def test_script_without_run_is_an_error(self):
        m = self.manager(self.script("import pyforge as game\ngame.init(100, 100)\n"))
        s = m.create()
        self.assertTrue(wait_until(lambda: s._snapshot is not None))
        self.assertIn("game.run", s._snapshot.error)

    def test_bad_sprite_value_is_reported_with_context(self):
        path = self.script(
            "import pyforge as game\n"
            "p = game.Sprite(0, 0, 10, 10)\n"
            "def update():\n"
            "    p.x = 'oops'\n"
            "game.run(update)\n"
        )
        m = self.manager(path)
        s = self.attached(m)
        self.assertTrue(wait_until(lambda: s.game.status == "error"))
        self.assertIn("Sprite #1.x must be a number", s._snapshot.error)

    def test_stop_and_restart(self):
        path = self.script(
            "import pyforge as game\n"
            "p = game.Sprite(0, 0, 10, 10)\n"
            "def update():\n"
            "    p.x += 1\n"
            "    if p.x >= 3:\n"
            "        game.stop()\n"
            "game.run(update)\n"
        )
        m = self.manager(path)
        s = self.attached(m)
        self.assertTrue(wait_until(lambda: s.game.status == "stopped"))
        self.assertEqual(s.game._entities[1].x, 3)
        s.request_restart()
        self.assertTrue(wait_until(lambda: s.game.epoch == 2))
        self.assertTrue(wait_until(lambda: s.game.status == "stopped" and s.game._entities[1].x == 3))

    def test_game_restart_from_script(self):
        path = self.script(
            "import pyforge as game\n"
            "def update():\n"
            "    if game.frame() == 2:\n"
            "        game.restart()\n"
            "game.run(update)\n"
        )
        m = self.manager(path)
        s = self.attached(m)
        self.assertTrue(wait_until(lambda: s.game.epoch >= 2))

    def test_script_is_reread_on_restart(self):
        path = self.script("import pyforge as game\ngame.set_background('#111111')\ngame.run()\n")
        m = self.manager(path)
        s = self.attached(m)
        self.assertEqual(s.game.background, "#111111")
        path.write_text("import pyforge as game\ngame.set_background('#222222')\ngame.run()\n")
        s.request_restart()
        self.assertTrue(wait_until(lambda: s.game.epoch == 2 and s.game.background == "#222222"))


class DiffTests(unittest.TestCase):
    def snap(self, **kw):
        from pyforge.engine import Snapshot

        base = dict(epoch=1, frame=0, status="running", error=None,
                    config={"width": 10, "height": 10}, background="#000", entities={})
        base.update(kw)
        return Snapshot(**base)

    def test_first_message_is_full_init(self):
        cur = self.snap(entities={1: {"x": 1}})
        msg = diff_snapshots(None, cur)
        self.assertEqual(msg["t"], "init")
        self.assertEqual(msg["ents"], {1: {"x": 1}})
        self.assertEqual(msg["order"], [1])

    def test_no_change_means_no_message(self):
        a = self.snap(entities={1: {"x": 1}})
        b = self.snap(frame=5, entities={1: {"x": 1}})
        self.assertIsNone(diff_snapshots(a, b))

    def test_only_changed_fields_are_sent(self):
        a = self.snap(entities={1: {"x": 1, "y": 2}, 2: {"x": 5, "y": 5}})
        b = self.snap(entities={1: {"x": 9, "y": 2}, 2: {"x": 5, "y": 5}})
        self.assertEqual(diff_snapshots(a, b), {"t": "state", "set": {1: {"x": 9}}})

    def test_added_removed_and_order(self):
        a = self.snap(entities={1: {"x": 1}, 2: {"x": 2}})
        b = self.snap(entities={2: {"x": 2}, 3: {"x": 3}})
        msg = diff_snapshots(a, b)
        self.assertEqual(msg["set"], {3: {"x": 3}})
        self.assertEqual(msg["del"], [1])
        self.assertEqual(msg["order"], [2, 3])

    def test_background_and_status(self):
        a = self.snap()
        b = self.snap(background="#fff", status="error", error="bad")
        msg = diff_snapshots(a, b)
        self.assertEqual((msg["bg"], msg["status"], msg["error"]), ("#fff", "error", "bad"))

    def test_new_epoch_or_config_sends_init_again(self):
        a = self.snap()
        self.assertEqual(diff_snapshots(a, self.snap(epoch=2))["t"], "init")
        self.assertEqual(diff_snapshots(a, self.snap(config={"width": 20, "height": 10}))["t"], "init")


if __name__ == "__main__":
    unittest.main()
