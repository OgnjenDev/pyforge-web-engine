"""Things that appear on screen: rectangle sprites and text labels."""
from __future__ import annotations

import math
from typing import Any, Dict, Tuple

from .collision import collides as _collides
from .collision import contains_point
from .engine import GameError, check_color, current_game

MAX_TEXT_LENGTH = 500


def _num(value: Any, what: str) -> Any:
    """Validate a number for sending to the browser (rounded to 2 decimals)."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise GameError(f"{what} must be a number, got {value!r}")
    if not math.isfinite(value):
        raise GameError(f"{what} is {value}; positions and sizes must be finite numbers")
    rounded = round(float(value), 2)
    return int(rounded) if rounded == int(rounded) else rounded


class Sprite:
    """A coloured rectangle.

    ``x`` and ``y`` are the top-left corner in pixels; ``y`` grows downwards.
    Change any attribute (``x``, ``y``, ``width``, ``height``, ``color``,
    ``visible``) at any time and the browser follows.
    """

    kind = "r"

    def __init__(
        self,
        x: float,
        y: float,
        width: float,
        height: float,
        color: str = "#ffffff",
        visible: bool = True,
    ) -> None:
        self._game = current_game()
        self.x = x
        self.y = y
        self.width = width
        self.height = height
        self.color = color
        self.visible = visible
        self.removed = False
        self.id = self._game._register(self)

    # -- geometry --------------------------------------------------------
    @property
    def left(self) -> float:
        return self.x

    @property
    def right(self) -> float:
        return self.x + self.width

    @property
    def top(self) -> float:
        return self.y

    @property
    def bottom(self) -> float:
        return self.y + self.height

    @property
    def center(self) -> Tuple[float, float]:
        return (self.x + self.width / 2, self.y + self.height / 2)

    def move(self, dx: float, dy: float) -> None:
        """Move by (dx, dy) pixels."""
        self.x += dx
        self.y += dy

    def collides(self, other: Any) -> bool:
        """True if this sprite overlaps ``other``."""
        return _collides(self, other)

    def contains(self, px: float, py: float) -> bool:
        """True if the point (px, py) is inside the sprite, e.g. a mouse click."""
        return contains_point(self, px, py)

    def remove(self) -> None:
        """Take the sprite off the screen for good. Safe to call twice."""
        self.removed = True
        self._game._unregister(self)

    # -- internals -------------------------------------------------------
    def _snapshot(self) -> Dict[str, Any]:
        what = f"Sprite #{self.id}"
        return {
            "k": "r",
            "x": _num(self.x, f"{what}.x"),
            "y": _num(self.y, f"{what}.y"),
            "w": _num(self.width, f"{what}.width"),
            "h": _num(self.height, f"{what}.height"),
            "c": check_color(self.color, f"{what}.color"),
            "v": bool(self.visible),
        }

    def __repr__(self) -> str:
        return f"Sprite(x={self.x}, y={self.y}, width={self.width}, height={self.height}, color={self.color!r})"


class Label:
    """A line of text. Change ``text``, ``x``, ``y``, ``color``, ``size`` or ``visible`` any time."""

    kind = "t"

    def __init__(
        self,
        x: float,
        y: float,
        text: str = "",
        color: str = "#ffffff",
        size: float = 20,
        visible: bool = True,
    ) -> None:
        self._game = current_game()
        self.x = x
        self.y = y
        self.text = text
        self.color = color
        self.size = size
        self.visible = visible
        self.removed = False
        self.id = self._game._register(self)

    def remove(self) -> None:
        """Take the label off the screen for good. Safe to call twice."""
        self.removed = True
        self._game._unregister(self)

    def _snapshot(self) -> Dict[str, Any]:
        what = f"Label #{self.id}"
        size = _num(self.size, f"{what}.size")
        if size <= 0:
            raise GameError(f"{what}.size must be greater than 0")
        return {
            "k": "t",
            "x": _num(self.x, f"{what}.x"),
            "y": _num(self.y, f"{what}.y"),
            "s": str(self.text)[:MAX_TEXT_LENGTH],
            "n": size,
            "c": check_color(self.color, f"{what}.color"),
            "v": bool(self.visible),
        }

    def __repr__(self) -> str:
        return f"Label(x={self.x}, y={self.y}, text={self.text!r})"
