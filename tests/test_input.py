import unittest

from pyforge.input import InputState, normalize_key


def key(name, down):
    return {"type": "key", "key": name, "down": down}


class InputTests(unittest.TestCase):
    def setUp(self):
        self.inp = InputState()

    def test_held_and_pressed(self):
        self.inp.push([key("ArrowRight", True)])
        self.inp.begin_frame()
        self.assertTrue(self.inp.is_down("right"))
        self.assertTrue(self.inp.was_pressed("right"))
        self.inp.begin_frame()
        self.assertTrue(self.inp.is_down("right"))
        self.assertFalse(self.inp.was_pressed("right"))

    def test_release(self):
        self.inp.push([key("space", True)])
        self.inp.begin_frame()
        self.inp.push([key("space", False)])
        self.inp.begin_frame()
        self.assertFalse(self.inp.is_down("space"))
        self.assertTrue(self.inp.was_released("space"))

    def test_quick_tap_inside_one_frame_is_not_lost(self):
        self.inp.push([key("space", True), key("space", False)])
        self.inp.begin_frame()
        self.assertFalse(self.inp.is_down("space"))
        self.assertTrue(self.inp.was_pressed("space"))
        self.assertTrue(self.inp.was_released("space"))

    def test_aliases_and_case(self):
        self.assertEqual(normalize_key("Left"), "left")
        self.assertEqual(normalize_key(" "), "space")
        self.assertEqual(normalize_key("ArrowUp"), "up")
        self.inp.push([key("A", True)])
        self.inp.begin_frame()
        self.assertTrue(self.inp.is_down("a"))
        self.assertTrue(self.inp.is_down("A"))

    def test_non_string_key_name_is_an_error(self):
        with self.assertRaises(TypeError):
            self.inp.is_down(5)

    def test_reset_releases_everything(self):
        self.inp.push([key("left", True), {"type": "button", "button": "left", "down": True}])
        self.inp.begin_frame()
        self.inp.push([{"type": "reset"}])
        self.inp.begin_frame()
        self.assertFalse(self.inp.is_down("left"))
        self.assertFalse(self.inp.button_down("left"))

    def test_mouse_position_and_buttons(self):
        self.inp.push([
            {"type": "mouse", "x": 10.5, "y": 20},
            {"type": "button", "button": "right", "down": True, "x": 30, "y": 40},
        ])
        self.inp.begin_frame()
        self.assertEqual(self.inp.mouse_position(), (30.0, 40.0))
        self.assertTrue(self.inp.button_down("right"))
        self.assertTrue(self.inp.button_pressed("right"))
        self.assertFalse(self.inp.button_down("left"))
        with self.assertRaises(ValueError):
            self.inp.button_down("fire")

    def test_invalid_events_are_dropped(self):
        bad = [
            None, 5, "x", [], {}, {"type": "nope"},
            {"type": "key", "key": 5, "down": True},
            {"type": "key", "key": "a", "down": "yes"},
            {"type": "key", "key": "", "down": True},
            {"type": "key", "key": "x" * 100, "down": True},
            {"type": "mouse", "x": float("nan"), "y": 1},
            {"type": "mouse", "x": "1", "y": 1},
            {"type": "mouse", "x": True, "y": 1},
            {"type": "button", "button": "fire", "down": True},
        ]
        self.assertEqual(self.inp.push(bad), 0)
        self.inp.begin_frame()
        self.assertEqual(self.inp.held, set())

    def test_mouse_coordinates_are_clamped(self):
        self.inp.push([{"type": "mouse", "x": 1e30, "y": -1e30}])
        self.inp.begin_frame()
        self.assertEqual(self.inp.mouse_position(), (1_000_000.0, -1_000_000.0))

    def test_held_keys_are_capped(self):
        inp = InputState(max_held=3)
        inp.push([key(f"k{i}", True) for i in range(10)])
        inp.begin_frame()
        self.assertEqual(len(inp.held), 3)

    def test_queue_is_bounded(self):
        inp = InputState(max_pending=10)
        inp.push([{"type": "mouse", "x": i, "y": i} for i in range(1000)])
        inp.push([key("a", True)] * 1000)
        self.assertLessEqual(len(inp._pending), 20)


if __name__ == "__main__":
    unittest.main()
