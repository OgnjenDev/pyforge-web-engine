"""Keeps the README honest: documented API must exist, and examples must match."""
import re
import unittest
from pathlib import Path

import pyforge

ROOT = Path(__file__).resolve().parent.parent
README = (ROOT / "README.md").read_text(encoding="utf-8")
SPRITE_ATTRS = ["x", "y", "width", "height", "color", "visible", "left", "right", "top", "bottom",
                "center", "move", "collides", "contains", "remove"]


class ReadmeTests(unittest.TestCase):
    def test_every_documented_game_function_exists(self):
        names = set(re.findall(r"game\.([A-Za-z_]+)\(", README))
        self.assertGreater(len(names), 15)
        missing = sorted(n for n in names if not hasattr(pyforge, n))
        self.assertEqual(missing, [])

    def test_documented_names_are_exported(self):
        for name in re.findall(r"\| `game\.([A-Za-z_]+)\(", README):
            self.assertIn(name, pyforge.__all__)

    def test_sprite_and_label_attributes_exist(self):
        g = pyforge.Game()
        with g.activate():
            sprite = pyforge.Sprite(0, 0, 1, 1)
            label = pyforge.Label(0, 0, "x")
        for attr in SPRITE_ATTRS:
            self.assertTrue(hasattr(sprite, attr), attr)
        for attr in ["x", "y", "text", "color", "size", "visible", "remove"]:
            self.assertTrue(hasattr(label, attr), attr)

    def test_readme_tutorial_code_matches_the_example_files(self):
        for name in ("basic_game.py", "coin_dash.py"):
            code = (ROOT / "examples" / name).read_text(encoding="utf-8").strip()
            self.assertIn(code, README, f"README no longer contains examples/{name}")

    def test_cli_options_in_readme_exist(self):
        from pyforge.cli import build_parser

        help_text = build_parser()._subparsers._group_actions[0].choices["run"].format_help()
        for option in re.findall(r"^\| `(--[a-z-]+)`", README, flags=re.M):
            self.assertIn(option, help_text)

    def test_version_is_consistent(self):
        self.assertRegex(pyforge.__version__, r"^\d+\.\d+\.\d+$")


if __name__ == "__main__":
    unittest.main()
