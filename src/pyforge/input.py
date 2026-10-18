"""Per-session input state.

The browser sends input *events* (key down/up, mouse moves, button presses).
HTTP threads put sanitised events into a locked queue; the session's game
thread drains that queue once per frame in :meth:`InputState.begin_frame`.
All the "held / pressed" sets are therefore only ever touched by the game
thread, so game code can read them without locking.

Nothing the browser sends is trusted: events are validated, sizes are capped
and unknown shapes are dropped.
"""
from __future__ import annotations

import math
import threading
from typing import Any, Iterable, List, Optional, Set, Tuple

KEY_ALIASES = {
    "arrowright": "right",
    "arrowleft": "left",
    "arrowup": "up",
    "arrowdown": "down",
    "spacebar": "space",
    "esc": "escape",
    "return": "enter",
    "control": "ctrl",
    "del": "delete",
}
BUTTONS = ("left", "middle", "right")
MAX_KEY_LENGTH = 24
COORD_LIMIT = 1_000_000.0


def normalize_key(name: Any) -> str:
    """Return the canonical lowercase name for a key, e.g. ``"Left"`` -> ``"left"``."""
    if not isinstance(name, str):
        raise TypeError("key names are strings, for example game.key('left')")
    if name == " ":
        return "space"
    key = name.strip().lower()
    return KEY_ALIASES.get(key, key)


def _coord(value: Any) -> Optional[float]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    value = float(value)
    if not math.isfinite(value):
        return None
    return max(-COORD_LIMIT, min(COORD_LIMIT, value))


Event = Tuple[Any, ...]


def clean_event(raw: Any) -> Optional[Event]:
    """Validate one event from the browser. Returns a tuple or None if invalid."""
    if not isinstance(raw, dict):
        return None
    kind = raw.get("type")
    if kind == "key":
        name = raw.get("key")
        down = raw.get("down")
        if not isinstance(name, str) or not isinstance(down, bool):
            return None
        if not name or len(name) > MAX_KEY_LENGTH or not name.isprintable():
            return None
        return ("key", normalize_key(name), down)
    if kind == "mouse":
        x, y = _coord(raw.get("x")), _coord(raw.get("y"))
        if x is None or y is None:
            return None
        return ("mouse", x, y)
    if kind == "button":
        button, down = raw.get("button"), raw.get("down")
        if button not in BUTTONS or not isinstance(down, bool):
            return None
        return ("button", button, down, _coord(raw.get("x")), _coord(raw.get("y")))
    if kind == "reset":
        return ("reset",)
    return None


class InputState:
    """Keyboard and mouse state for one player."""

    def __init__(self, max_pending: int = 1024, max_held: int = 64) -> None:
        self.max_pending = max_pending
        self.max_held = max_held
        self._lock = threading.Lock()
        self._pending: List[Event] = []
        self.held: Set[str] = set()
        self.pressed: Set[str] = set()
        self.released: Set[str] = set()
        self.mouse_x = 0.0
        self.mouse_y = 0.0
        self.buttons_held: Set[str] = set()
        self.buttons_pressed: Set[str] = set()

    # ------------------------------------------------------------------
    # Called from HTTP threads
    # ------------------------------------------------------------------
    def push(self, events: Iterable[Any]) -> int:
        """Queue raw browser events. Returns how many were valid."""
        cleaned = [e for e in (clean_event(raw) for raw in events) if e is not None]
        if not cleaned:
            return 0
        with self._lock:
            for event in cleaned:
                if len(self._pending) >= 2 * self.max_pending:
                    break
                if event[0] == "mouse" and len(self._pending) >= self.max_pending:
                    continue  # mouse moves are the first thing to drop under load
                self._pending.append(event)
        return len(cleaned)

    def request_reset(self) -> None:
        """Ask the game thread to release every key and button on its next frame."""
        with self._lock:
            self._pending.append(("reset",))

    # ------------------------------------------------------------------
    # Called from the game thread
    # ------------------------------------------------------------------
    def begin_frame(self) -> None:
        """Apply queued events. Call once at the start of every frame."""
        with self._lock:
            pending, self._pending = self._pending, []
        self.pressed.clear()
        self.released.clear()
        self.buttons_pressed.clear()
        for event in pending:
            self._apply(event)

    def _apply(self, event: Event) -> None:
        kind = event[0]
        if kind == "key":
            _, name, down = event
            if down:
                if name not in self.held and len(self.held) < self.max_held:
                    self.held.add(name)
                    self.pressed.add(name)
            elif name in self.held:
                self.held.discard(name)
                self.released.add(name)
        elif kind == "mouse":
            self.mouse_x, self.mouse_y = event[1], event[2]
        elif kind == "button":
            _, button, down, x, y = event
            if x is not None and y is not None:
                self.mouse_x, self.mouse_y = x, y
            if down:
                if button not in self.buttons_held:
                    self.buttons_held.add(button)
                    self.buttons_pressed.add(button)
            else:
                self.buttons_held.discard(button)
        elif kind == "reset":
            self.released |= self.held
            self.held.clear()
            self.buttons_held.clear()

    # ------------------------------------------------------------------
    # Queries used by game code
    # ------------------------------------------------------------------
    def is_down(self, name: str) -> bool:
        return normalize_key(name) in self.held

    def was_pressed(self, name: str) -> bool:
        return normalize_key(name) in self.pressed

    def was_released(self, name: str) -> bool:
        return normalize_key(name) in self.released

    def mouse_position(self) -> Tuple[float, float]:
        return (self.mouse_x, self.mouse_y)

    def button_down(self, button: str = "left") -> bool:
        return self._check_button(button) in self.buttons_held

    def button_pressed(self, button: str = "left") -> bool:
        return self._check_button(button) in self.buttons_pressed

    @staticmethod
    def _check_button(button: str) -> str:
        if button not in BUTTONS:
            raise ValueError(f"mouse button must be one of {', '.join(BUTTONS)}, got {button!r}")
        return button
