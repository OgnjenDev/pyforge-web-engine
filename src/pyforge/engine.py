"""Game state and the per-frame update.

A :class:`Game` holds everything that belongs to *one player's* game: the
sprites, the input state, the background colour, the frame counter and the
update callback. The server creates one ``Game`` per browser session, so two
players never share state.

The module-level functions in :mod:`pyforge` (``game.key()``, ``game.run()``
...) act on the *current* game, which is tracked with a context variable. The
session thread activates its own game before it runs your script and before
every frame.

Thread safety: a ``Game`` is only ever touched by the single thread that owns
its session. Other threads (HTTP handlers) never read it; they read immutable
:class:`Snapshot` objects published by that thread and push input through the
locked queue in :mod:`pyforge.input`.
"""
from __future__ import annotations

import contextlib
import contextvars
import inspect
import math
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, List, Optional, Union

from .collision import collides
from .input import InputState

DEFAULT_TITLE = "PyForge game"
MAX_CANVAS = 4096
MAX_FPS = 240
MAX_COLOR_LENGTH = 64


class PyForgeError(Exception):
    """Base class for PyForge errors."""


class GameError(PyForgeError):
    """Raised when a game script uses the API incorrectly."""


@dataclass
class Snapshot:
    """An immutable-by-convention picture of a game at the end of a frame."""

    epoch: int
    frame: int
    status: str
    error: Optional[str]
    config: Dict[str, Any]
    background: str
    entities: Dict[int, Dict[str, Any]]


class _Watch:
    """A collision callback registered with :meth:`Game.on_collision`."""

    __slots__ = ("sprite", "others", "callback", "active")

    def __init__(self, sprite: Any, others: Any, callback: Callable[[Any, Any], Any]) -> None:
        self.sprite = sprite
        self.others = others
        self.callback = callback
        self.active: set = set()


def check_color(value: Any, what: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise GameError(f"{what} must be a colour string such as '#ff0000' or 'red', got {value!r}")
    if len(value) > MAX_COLOR_LENGTH:
        raise GameError(f"{what} is too long to be a colour")
    return value


def _check_size(value: Any, name: str) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or int(value) != value
    ):
        raise GameError(f"{name} must be a whole number, got {value!r}")
    value = int(value)
    if not 1 <= value <= MAX_CANVAS:
        raise GameError(f"{name} must be between 1 and {MAX_CANVAS}, got {value}")
    return value


def _check_fps(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise GameError(f"fps must be a number, got {value!r}")
    if not 1 <= value <= MAX_FPS:
        raise GameError(f"fps must be between 1 and {MAX_FPS}, got {value}")
    return float(value)


def _accepts_dt(fn: Callable[..., Any]) -> bool:
    """True if ``fn`` can take a positional argument (so we can pass dt)."""
    try:
        params = inspect.signature(fn).parameters.values()
    except (TypeError, ValueError):
        return False
    return any(
        p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD, p.VAR_POSITIONAL) for p in params
    )


class Game:
    """The complete state of one player's game."""

    def __init__(
        self,
        width: int = 800,
        height: int = 600,
        *,
        input_state: Optional[InputState] = None,
        max_sprites: int = 5000,
        managed: bool = False,
        epoch: int = 0,
    ) -> None:
        self.width = width
        self.height = height
        self.title = DEFAULT_TITLE
        self.fps = 60.0
        self.touch_controls: Union[bool, str] = "auto"
        self.background = "#000000"
        self.status = "idle"  # idle -> running -> stopped | error
        self.error: Optional[str] = None
        self.managed = managed  # True when a server session drives the loop
        self.epoch = epoch
        self.max_sprites = max_sprites
        self.input = input_state if input_state is not None else InputState()
        self.restart_requested = False
        self._entities: Dict[int, Any] = {}
        self._next_id = 1
        self._frame = 0
        self._dt = 0.0
        self._update: Optional[Callable[..., Any]] = None
        self._update_takes_dt = False
        self._watches: List[_Watch] = []

    # ------------------------------------------------------------------
    # Configuration
    # ------------------------------------------------------------------
    def init(
        self,
        width: int = 800,
        height: int = 600,
        title: str = DEFAULT_TITLE,
        fps: Optional[float] = None,
        touch_controls: Union[bool, str] = "auto",
    ) -> None:
        self.width = _check_size(width, "width")
        self.height = _check_size(height, "height")
        if not isinstance(title, str) or len(title) > 100:
            raise GameError("title must be a string of at most 100 characters")
        self.title = title
        if fps is not None:
            self.fps = _check_fps(fps)
        if touch_controls not in (True, False, "auto"):
            raise GameError("touch_controls must be True, False or 'auto'")
        self.touch_controls = touch_controls

    def set_background(self, color: str) -> None:
        self.background = check_color(color, "background colour")

    def set_fps(self, fps: float) -> None:
        self.fps = _check_fps(fps)

    def config(self) -> Dict[str, Any]:
        return {
            "width": self.width,
            "height": self.height,
            "title": self.title,
            "fps": self.fps,
            "touch": self.touch_controls,
        }

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def run(self, update: Optional[Callable[..., Any]] = None, fps: Optional[float] = None) -> None:
        """Register the update function and mark the game as running."""
        if update is not None and not callable(update):
            raise GameError("game.run() expects a function, for example game.run(update)")
        if fps is not None:
            self.set_fps(fps)
        self._update = update
        self._update_takes_dt = update is not None and _accepts_dt(update)
        if self.status in ("idle", "stopped"):
            self.status = "running"

    def stop(self) -> None:
        """Stop the game loop. The browser keeps showing the last frame."""
        if self.status in ("idle", "running"):
            self.status = "stopped"

    def restart(self) -> None:
        """Ask the session to start the game over (re-runs your script)."""
        self.restart_requested = True

    # ------------------------------------------------------------------
    # Per-frame work
    # ------------------------------------------------------------------
    @property
    def frame_count(self) -> int:
        """Number of completed frames. The first update() call sees 0."""
        return self._frame

    @property
    def delta_time(self) -> float:
        """Seconds since the previous frame."""
        return self._dt

    def tick(self, dt: float) -> None:
        """Advance the game by one frame."""
        with self.activate():
            self.input.begin_frame()
            self._dt = dt
            if self._update is not None:
                if self._update_takes_dt:
                    self._update(dt)
                else:
                    self._update()
            self._run_watches()
            self._frame += 1

    # ------------------------------------------------------------------
    # Objects
    # ------------------------------------------------------------------
    def _register(self, entity: Any) -> int:
        if len(self._entities) >= self.max_sprites:
            raise GameError(
                f"too many objects (limit {self.max_sprites}); "
                "call remove() on sprites and labels you no longer need"
            )
        entity_id = self._next_id
        self._next_id += 1
        self._entities[entity_id] = entity
        return entity_id

    def _unregister(self, entity: Any) -> None:
        entity_id = getattr(entity, "id", None)
        if self._entities.get(entity_id) is entity:
            del self._entities[entity_id]

    def clear(self) -> None:
        """Drop every object (used when a session ends)."""
        self._entities.clear()
        self._watches.clear()
        self._update = None

    def on_collision(self, sprite: Any, others: Any, callback: Callable[[Any, Any], Any]) -> None:
        """Call ``callback(sprite, other)`` when ``sprite`` starts touching ``other``.

        ``others`` is one sprite or a list/tuple/set of sprites. A list is read
        every frame, so sprites you add to it later are included.
        """
        if not callable(callback):
            raise GameError("on_collision() needs a function as the third argument")
        if isinstance(others, (list, tuple, set)):
            targets: Any = others
        elif hasattr(others, "width") and hasattr(others, "height"):
            targets = [others]
        else:
            raise GameError("on_collision() needs a sprite or a list of sprites as the second argument")
        self._watches.append(_Watch(sprite, targets, callback))

    def _run_watches(self) -> None:
        for watch in list(self._watches):
            if getattr(watch.sprite, "removed", False):
                self._watches.remove(watch)
                continue
            hits = [
                o for o in list(watch.others)
                if o is not watch.sprite and not o.removed and collides(watch.sprite, o)
            ]
            now = {o.id for o in hits}
            fresh = [o for o in hits if o.id not in watch.active]
            watch.active = now
            for other in fresh:
                watch.callback(watch.sprite, other)

    # ------------------------------------------------------------------
    # Publishing
    # ------------------------------------------------------------------
    def snapshot(self) -> Snapshot:
        """Capture what the browser needs to draw this frame."""
        entities = {eid: ent._snapshot() for eid, ent in self._entities.items()}
        return Snapshot(
            epoch=self.epoch,
            frame=self._frame,
            status=self.status,
            error=self.error,
            config=self.config(),
            background=self.background,
            entities=entities,
        )

    @contextlib.contextmanager
    def activate(self) -> Iterator["Game"]:
        """Make this the current game for the calling thread."""
        token = _current.set(self)
        try:
            yield self
        finally:
            _current.reset(token)


_current: "contextvars.ContextVar[Optional[Game]]" = contextvars.ContextVar("pyforge_game", default=None)
_default_game: Optional[Game] = None


def current_game() -> Game:
    """Return the game the calling code belongs to.

    Inside a server session that is the session's game. Anywhere else (for
    example when you run ``python game.py`` directly) it is a shared default
    game.
    """
    global _default_game
    game = _current.get()
    if game is not None:
        return game
    if _default_game is None:
        _default_game = Game()
    return _default_game


def run_script(game: Game, path: Union[str, Path]) -> Dict[str, Any]:
    """Execute a game script with ``game`` as the current game.

    This runs the *developer's own* script, chosen on the command line. The
    server never runs code that arrives from a browser.
    Returns the script's global namespace.
    """
    path = Path(path)
    code = compile(path.read_bytes(), str(path), "exec")
    namespace: Dict[str, Any] = {"__name__": "__main__", "__file__": str(path)}
    with game.activate():
        exec(code, namespace)
    return namespace


def run(update: Optional[Callable[..., Any]] = None, fps: Optional[float] = None) -> None:
    """Register ``update`` for the current game.

    Under ``pyforge run`` this returns immediately and the server calls
    ``update`` every frame. If you start a game file directly with
    ``python game.py`` this also starts a server with default settings.
    """
    game = current_game()
    game.run(update, fps)
    if not game.managed:
        _launch_standalone()


def _launch_standalone() -> None:
    main = sys.modules.get("__main__")
    path = getattr(main, "__file__", None)
    if not path:
        raise GameError(
            "game.run() was called outside a script. Save your game as game.py "
            "and start it with: pyforge run game.py"
        )
    from .server import serve  # imported late: the engine does not need the server

    serve(path)
