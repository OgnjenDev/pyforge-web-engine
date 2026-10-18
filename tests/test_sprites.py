import unittest

import pyforge as game
from pyforge.engine import Game


class SpriteTests(unittest.TestCase):
    def setUp(self):
        self.g = Game()

    def test_sprite_stores_position_size_and_color(self):
        with self.g.activate():
            s = game.Sprite(100, 120, 40, 30, color="#00aaff")
        self.assertEqual((s.x, s.y, s.width, s.height, s.color), (100, 120, 40, 30, "#00aaff"))
        self.assertTrue(s.visible)

    def test_edges_and_center(self):
        with self.g.activate():
            s = game.Sprite(10, 20, 40, 60)
        self.assertEqual((s.left, s.right, s.top, s.bottom), (10, 50, 20, 80))
        self.assertEqual(s.center, (30, 50))

    def test_move_and_direct_assignment(self):
        with self.g.activate():
            s = game.Sprite(0, 0, 10, 10)
        s.move(3, -2)
        s.x += 5
        self.assertEqual((s.x, s.y), (8, -2))

    def test_snapshot_shape_and_rounding(self):
        with self.g.activate():
            s = game.Sprite(1.234567, 2, 3, 4, color="red", visible=False)
        self.assertEqual(
            s._snapshot(), {"k": "r", "x": 1.23, "y": 2, "w": 3, "h": 4, "c": "red", "v": False}
        )

    def test_ids_are_unique_and_draw_order_is_creation_order(self):
        with self.g.activate():
            a = game.Sprite(0, 0, 1, 1)
            b = game.Sprite(0, 0, 1, 1)
        self.assertNotEqual(a.id, b.id)
        self.assertEqual(list(self.g.snapshot().entities), [a.id, b.id])

    def test_remove_is_idempotent_and_hides_from_snapshot(self):
        with self.g.activate():
            s = game.Sprite(0, 0, 1, 1)
        s.remove()
        s.remove()
        self.assertTrue(s.removed)
        self.assertEqual(self.g.snapshot().entities, {})

    def test_bad_values_become_clear_errors(self):
        with self.g.activate():
            s = game.Sprite(0, 0, 10, 10)
        s.x = "left"
        with self.assertRaisesRegex(game.GameError, r"Sprite #1\.x must be a number"):
            self.g.snapshot()
        s.x = float("nan")
        with self.assertRaisesRegex(game.GameError, "finite"):
            self.g.snapshot()
        s.x = 0
        s.color = 123
        with self.assertRaisesRegex(game.GameError, "colour"):
            self.g.snapshot()

    def test_sprite_limit(self):
        small = Game(max_sprites=2)
        with small.activate():
            game.Sprite(0, 0, 1, 1)
            game.Sprite(0, 0, 1, 1)
            with self.assertRaisesRegex(game.GameError, "too many objects"):
                game.Sprite(0, 0, 1, 1)


class LabelTests(unittest.TestCase):
    def test_label_snapshot(self):
        g = Game()
        with g.activate():
            label = game.Label(5, 6, "Score: 3", size=24)
        label.text = "Score: 4"
        self.assertEqual(
            label._snapshot(),
            {"k": "t", "x": 5, "y": 6, "s": "Score: 4", "n": 24, "c": "#ffffff", "v": True},
        )

    def test_label_text_is_converted_and_capped(self):
        g = Game()
        with g.activate():
            label = game.Label(0, 0, 12345)
        self.assertEqual(label._snapshot()["s"], "12345")
        label.text = "x" * 10_000
        self.assertEqual(len(label._snapshot()["s"]), 500)

    def test_label_size_must_be_positive(self):
        g = Game()
        with g.activate():
            label = game.Label(0, 0, "hi", size=0)
        with self.assertRaises(game.GameError):
            g.snapshot()


class ConfigTests(unittest.TestCase):
    def test_init_validates(self):
        g = Game()
        g.init(640, 480, title="T", fps=30)
        self.assertEqual((g.width, g.height, g.fps, g.title), (640, 480, 30.0, "T"))
        for bad in [(0, 10), (10, 99999), ("a", 10), (10.5, 10), (True, 10)]:
            with self.assertRaises(game.GameError):
                g.init(*bad)
        with self.assertRaises(game.GameError):
            g.init(10, 10, fps=0)
        with self.assertRaises(game.GameError):
            g.init(10, 10, touch_controls="maybe")

    def test_set_background_validates(self):
        g = Game()
        g.set_background("#202020")
        self.assertEqual(g.background, "#202020")
        with self.assertRaises(game.GameError):
            g.set_background("")


if __name__ == "__main__":
    unittest.main()
