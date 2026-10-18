"""PyForge: write browser games in plain Python.

Typical use::

    import pyforge as game

    game.init(800, 600)
    player = game.Sprite(100, 100, 40, 40, color="#00aaff")

    def update():
        if game.key("right"):
            player.x += 5

    game.run(update)

Start it with ``pyforge run game.py`` and open the printed address.
"""
from __future__ import annotations

from typing import Any, Callable, List, Optional, Tuple, Union

from . import collision as _collision
from .engine import Game, GameError, PyForgeError, current_game, run
from .sprites import Label, Sprite

__version__ = "0.1.0"

__all__ = [
    "Game",
    "GameError",
    "Label",
    "PyForgeError",
    "Sprite",
    "collides",
    "collisions",
    "current_game",
    "dt",
    "frame",
    "init",
    "key",
    "key_pressed",
    "key_released",
    "mouse",
    "mouse_down",
    "mouse_pressed",
    "on_collision",
    "restart",
    "run",
    "set_background",
    "stop",
]


def init(
    width: int = 800,
    height: int = 600,
    title: str = "PyForge game",
    fps: Optional[float] = None,
    touch_controls: Union[bool, str] = "auto",
) -> None:
    """Set the canvas size (pixels), window title, update rate and touch controls."""
    current_game().init(width, height, title=title, fps=fps, touch_controls=touch_controls)


def set_background(color: str) -> None:
    """Set the background colour, e.g. ``"#202020"`` or ``"navy"``."""
    current_game().set_background(color)


def stop() -> None:
    """Stop the game loop. The browser shows a Restart button."""
    current_game().stop()


def restart() -> None:
    """Start the game over from the top of your script."""
    current_game().restart()


def key(name: str) -> bool:
    """True while the key is held down, e.g. ``game.key("left")``."""
    return current_game().input.is_down(name)


def key_pressed(name: str) -> bool:
    """True only on the frame the key went down (also catches quick taps)."""
    return current_game().input.was_pressed(name)


def key_released(name: str) -> bool:
    """True only on the frame the key was let go."""
    return current_game().input.was_released(name)


def mouse() -> Tuple[float, float]:
    """The mouse (or finger) position as ``(x, y)`` in game pixels."""
    return current_game().input.mouse_position()


def mouse_down(button: str = "left") -> bool:
    """True while a mouse button ("left", "middle", "right") is held."""
    return current_game().input.button_down(button)


def mouse_pressed(button: str = "left") -> bool:
    """True only on the frame the button went down."""
    return current_game().input.button_pressed(button)


def collides(a: Any, b: Any) -> bool:
    """True if the two sprites overlap (touching edges do not count)."""
    return _collision.collides(a, b)


def collisions(sprite: Any, others: Any) -> List[Any]:
    """The sprites in ``others`` that overlap ``sprite``."""
    return _collision.collisions(sprite, others)


def on_collision(sprite: Any, others: Any, callback: Callable[[Any, Any], Any]) -> None:
    """Call ``callback(sprite, other)`` once each time ``sprite`` starts touching ``other``."""
    current_game().on_collision(sprite, others, callback)


def frame() -> int:
    """Frames completed so far. The first ``update()`` call sees 0."""
    return current_game().frame_count


def dt() -> float:
    """Seconds since the previous frame."""
    return current_game().delta_time
