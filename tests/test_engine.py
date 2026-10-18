import tempfile
import unittest
from pathlib import Path

import pyforge as game
from pyforge.engine import Game, run_script

ROOT = Path(__file__).resolve().parent.parent
EXAMPLES = ROOT / "examples"


def press(g, *names):
    g.input.push([{"type": "key", "key": n, "down": True} for n in names])


class LoopTests(unittest.TestCase):
    def test_frame_counter_and_dt(self):
        g = Game()
        seen = []
        g.run(lambda: seen.append((game.frame(), game.dt())))
        g.tick(0.5)
        g.tick(0.25)
        self.assertEqual(seen, [(0, 0.5), (1, 0.25)])
        self.assertEqual(g.frame_count, 2)

    def test_update_may_take_dt(self):
        g = Game()
        got = []
        g.run(lambda dt: got.append(dt))
        g.tick(0.1)
        self.assertEqual(got, [0.1])

    def test_run_without_update_is_a_static_scene(self):
        g = Game()
        g.run()
        g.tick(0.016)
        self.assertEqual(g.status, "running")

    def test_run_rejects_non_callable(self):
        with self.assertRaises(game.GameError):
            Game().run("update")

    def test_stop_and_status(self):
        g = Game()
        g.run(lambda: g.stop())
        self.assertEqual(g.status, "running")
        g.tick(0.016)
        self.assertEqual(g.status, "stopped")

    def test_restart_flag(self):
        g = Game()
        g.run(lambda: g.restart())
        g.tick(0.016)
        self.assertTrue(g.restart_requested)

    def test_fps_from_run(self):
        g = Game()
        g.run(None, fps=30)
        self.assertEqual(g.fps, 30.0)

    def test_update_exception_propagates_from_tick(self):
        g = Game()

        def boom():
            raise ValueError("boom")

        g.run(boom)
        with self.assertRaises(ValueError):
            g.tick(0.016)

    def test_games_do_not_share_state(self):
        a, b = Game(), Game()
        with a.activate():
            sa = game.Sprite(0, 0, 1, 1)
            game.set_background("red")
        with b.activate():
            game.Sprite(0, 0, 1, 1)
            game.Sprite(0, 0, 1, 1)
        self.assertEqual(len(a.snapshot().entities), 1)
        self.assertEqual(len(b.snapshot().entities), 2)
        self.assertEqual(a.background, "red")
        self.assertEqual(b.background, "#000000")
        self.assertIs(sa._game, a)


class ExampleGameTests(unittest.TestCase):
    def test_basic_example_moves_with_keys(self):
        g = Game(managed=True)
        ns = run_script(g, EXAMPLES / "basic_game.py")
        player = ns["player"]
        self.assertEqual((g.width, g.height, g.background), (800, 600, "#202020"))
        self.assertEqual(g.status, "running")
        press(g, "right", "down")
        g.tick(1 / 60)
        self.assertEqual((player.x, player.y), (105, 105))
        g.input.push([{"type": "key", "key": "right", "down": False}, {"type": "key", "key": "up", "down": True}])
        g.tick(1 / 60)
        self.assertEqual((player.x, player.y), (105, 105))  # down and up cancel out
        self.assertEqual(g.snapshot().entities[player.id]["c"], "#00aaff")

    def test_coin_dash_collect_and_game_over(self):
        g = Game(managed=True)
        ns = run_script(g, EXAMPLES / "coin_dash.py")
        player, coin, enemy = ns["player"], ns["coin"], ns["enemy"]
        enemy.x, enemy.y = 700, 500
        coin.x, coin.y = player.x, player.y
        g.tick(1 / 60)
        self.assertEqual(ns["score"], 1)
        self.assertEqual(ns["score_label"].text, "Score: 1")
        self.assertFalse(ns["game_over"])
        player.x, player.y = enemy.x, enemy.y
        g.tick(1 / 60)
        self.assertTrue(ns["game_over"])
        self.assertTrue(ns["message"].visible)
        press(g, "space")
        g.tick(1 / 60)
        self.assertTrue(g.restart_requested)

    def test_coin_dash_keeps_player_on_screen(self):
        g = Game(managed=True)
        ns = run_script(g, EXAMPLES / "coin_dash.py")
        player = ns["player"]
        ns["enemy"].x, ns["enemy"].y = 700, 500
        press(g, "left", "up")
        for _ in range(200):
            g.tick(0.05)
        self.assertEqual((player.x, player.y), (0, 0))


class ScriptTests(unittest.TestCase):
    def test_run_script_reports_syntax_errors(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.py"
            path.write_text("def update(:\n    pass\n")
            with self.assertRaises(SyntaxError):
                run_script(Game(managed=True), path)


if __name__ == "__main__":
    unittest.main()
