"""Player sessions: one game, one thread and one input queue per browser.

Design
------
* Every session runs its game on its own thread. A slow or crashing game
  cannot block other players' games.
* The game thread is the only thread that touches the ``Game`` object. After
  each frame it publishes an immutable :class:`~pyforge.engine.Snapshot`;
  HTTP threads only read snapshots, so there are no data races on game state.
* While no browser is attached the game loop pauses, and sessions that show
  no sign of life for ``session_timeout`` seconds are closed by a reaper
  thread, so abandoned games do not pile up.
"""
from __future__ import annotations

import logging
import secrets
import threading
import time
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional, Tuple, Union

from .engine import MAX_FPS, Game, GameError, Snapshot, run_script
from .input import InputState

log = logging.getLogger("pyforge")

MAX_DT = 0.25
MAX_ERROR_LENGTH = 4000


class ServerFull(Exception):
    """Raised when the maximum number of sessions is already running."""


@dataclass
class SessionConfig:
    session_timeout: float = 60.0  # seconds without any sign of life
    cleanup_interval: float = 5.0  # how often the reaper looks for idle sessions
    max_sessions: int = 50
    max_sprites: int = 5000  # per session


def format_error(exc: BaseException, script_path: Path) -> str:
    """Turn an exception into text for the browser, showing the game's own lines."""
    script = str(script_path)
    frames = [f for f in traceback.extract_tb(exc.__traceback__) if f.filename == script]
    if frames and not isinstance(exc, SyntaxError):
        lines = ["Traceback (most recent call last):\n"]
        lines += traceback.format_list(frames)
        lines += traceback.format_exception_only(type(exc), exc)
    elif isinstance(exc, SyntaxError):
        lines = traceback.format_exception_only(type(exc), exc)
    else:
        lines = traceback.format_exception(type(exc), exc, exc.__traceback__)
    text = "".join(lines).rstrip()
    return text[-MAX_ERROR_LENGTH:]


class Session:
    """One player's running game."""

    def __init__(self, session_id: str, script_path: Path, config: SessionConfig) -> None:
        self.id = session_id
        self.script_path = Path(script_path)
        self.config = config
        self.input = InputState()
        self.game: Optional[Game] = None
        self.last_seen = time.monotonic()
        self._cond = threading.Condition()
        self._snapshot: Optional[Snapshot] = None
        self._version = 0
        self._listeners = 0
        self._closed = False
        self._close_reason = ""
        self._restart = threading.Event()
        self._wake = threading.Event()
        self._epoch = 0
        self._thread = threading.Thread(target=self._main, name=f"pyforge-{session_id[:6]}", daemon=True)

    # ------------------------------------------------------------------
    # Called from HTTP threads
    # ------------------------------------------------------------------
    def start(self) -> None:
        self._thread.start()

    @property
    def closed(self) -> bool:
        return self._closed

    @property
    def listeners(self) -> int:
        return self._listeners

    def touch(self) -> None:
        self.last_seen = time.monotonic()

    def push_input(self, events: Any) -> int:
        self.touch()
        return self.input.push(events)

    def request_restart(self) -> None:
        self.touch()
        self._restart.set()
        self._wake.set()

    def attach(self) -> None:
        """A browser stream connected."""
        with self._cond:
            self._listeners += 1
            if self._listeners == 1:
                self.input.request_reset()  # drop keys that were held before the pause
            self.touch()
            self._cond.notify_all()

    def detach(self) -> None:
        """A browser stream disconnected."""
        with self._cond:
            self._listeners = max(0, self._listeners - 1)
            self.touch()

    def wait_for_update(self, seen_version: int, timeout: float) -> Tuple[Optional[Snapshot], int, bool, str]:
        """Block until a newer snapshot exists, the session closes, or ``timeout`` passes."""
        with self._cond:
            self._cond.wait_for(lambda: self._version != seen_version or self._closed, timeout)
            return self._snapshot, self._version, self._closed, self._close_reason

    def close(self, reason: str = "closed") -> None:
        with self._cond:
            if self._closed:
                return
            self._closed = True
            self._close_reason = reason
            self._cond.notify_all()
        self._restart.set()
        self._wake.set()

    # ------------------------------------------------------------------
    # Game thread
    # ------------------------------------------------------------------
    def _main(self) -> None:
        game: Optional[Game] = None
        try:
            while not self._closed:
                self._restart.clear()
                self._epoch += 1
                game = self._boot()
                restart = self._play(game) if game.status == "running" else False
                if self._closed:
                    break
                if not restart:
                    self._restart.wait()  # stopped or crashed: wait for Restart (or close)
        except Exception:  # pragma: no cover - last-resort guard
            log.exception("[%s] session thread crashed", self.id[:8])
            self.close("internal error")
        finally:
            if game is not None:
                game.clear()
            self._snapshot = None

    def _boot(self) -> Game:
        """Create a fresh game, run the script (re-read from disk) and publish frame 0."""
        game = Game(
            input_state=self.input,
            max_sprites=self.config.max_sprites,
            managed=True,
            epoch=self._epoch,
        )
        self.game = game
        try:
            run_script(game, self.script_path)
            if game.status == "idle":
                raise GameError(
                    "The script finished without calling game.run(update). "
                    "Add game.run(update) at the end of your game file."
                )
        except SystemExit:
            game.stop()
        except Exception as exc:
            self._fail(game, exc)
        self._publish(game)
        return game

    def _fail(self, game: Game, exc: BaseException) -> None:
        game.status = "error"
        game.error = format_error(exc, self.script_path)
        log.error("[%s] game error:\n%s", self.id[:8], game.error)

    def _publish(self, game: Game) -> None:
        try:
            snap = game.snapshot()
        except Exception as exc:
            self._fail(game, exc)
            previous = self._snapshot
            entities = previous.entities if previous is not None and previous.epoch == game.epoch else {}
            snap = Snapshot(
                game.epoch, game.frame_count, "error", game.error, game.config(), game.background, entities
            )
        with self._cond:
            self._snapshot = snap
            self._version += 1
            self._cond.notify_all()

    def _pause_until_watched(self) -> bool:
        """Block while no browser is attached. Returns True if it had to wait."""
        waited = False
        with self._cond:
            while self._listeners == 0 and not self._closed and not self._restart.is_set():
                waited = True
                self._cond.wait(0.5)
        return waited

    def _play(self, game: Game) -> bool:
        """Run frames until the game stops, fails or is closed. True means restart."""
        now = time.perf_counter()
        next_tick = now
        last = now - 1.0 / game.fps
        while True:
            if self._closed:
                return False
            if self._restart.is_set() or game.restart_requested:
                return True
            if game.status != "running":
                return False
            if self._pause_until_watched():
                now = time.perf_counter()
                next_tick, last = now, now - 1.0 / game.fps
                continue
            now = time.perf_counter()
            dt = min(now - last, MAX_DT)
            last = now
            try:
                game.tick(dt)
            except SystemExit:
                game.stop()
            except Exception as exc:
                self._fail(game, exc)
            self._publish(game)
            next_tick += 1.0 / min(game.fps, MAX_FPS)
            delay = next_tick - time.perf_counter()
            if delay > 0:
                self._wake.wait(delay)
                self._wake.clear()
            else:
                next_tick = time.perf_counter()  # running behind: do not try to catch up


class SessionManager:
    """Thread-safe registry of sessions with timeout cleanup."""

    def __init__(self, script_path: Union[str, Path], config: Optional[SessionConfig] = None) -> None:
        self.script_path = Path(script_path)
        self.config = config or SessionConfig()
        self._lock = threading.Lock()
        self._sessions: Dict[str, Session] = {}
        self._stop = threading.Event()
        self._reaper = threading.Thread(target=self._reap_loop, name="pyforge-reaper", daemon=True)
        self._reaper.start()

    def create(self) -> Session:
        with self._lock:
            if len(self._sessions) >= self.config.max_sessions:
                raise ServerFull(f"already running {self.config.max_sessions} sessions")
            session = Session(secrets.token_urlsafe(16), self.script_path, self.config)
            self._sessions[session.id] = session
        try:
            session.start()
        except Exception:
            with self._lock:
                self._sessions.pop(session.id, None)
            raise
        return session

    def get(self, session_id: str) -> Optional[Session]:
        """Look up a live session and mark it as recently used."""
        with self._lock:
            session = self._sessions.get(session_id)
        if session is None or session.closed:
            return None
        session.touch()
        return session

    def remove(self, session_id: str, reason: str = "closed") -> bool:
        with self._lock:
            session = self._sessions.pop(session_id, None)
        if session is None:
            return False
        session.close(reason)
        return True

    def count(self) -> int:
        with self._lock:
            return len(self._sessions)

    def sweep(self, now: Optional[float] = None) -> int:
        """Close sessions that have shown no sign of life. Returns how many."""
        now = time.monotonic() if now is None else now
        with self._lock:
            expired = [
                s for s in self._sessions.values()
                if s.closed or now - s.last_seen > self.config.session_timeout
            ]
            for s in expired:
                del self._sessions[s.id]
        for s in expired:
            s.close("timeout")
            log.info("session %s closed (timeout)", s.id[:8])
        return len(expired)

    def close_all(self, reason: str = "server stopped") -> None:
        self._stop.set()
        with self._lock:
            sessions = list(self._sessions.values())
            self._sessions.clear()
        for s in sessions:
            s.close(reason)

    def _reap_loop(self) -> None:
        while not self._stop.wait(self.config.cleanup_interval):
            try:
                self.sweep()
            except Exception:  # pragma: no cover - keep the reaper alive
                log.exception("session cleanup failed")


def diff_snapshots(prev: Optional[Snapshot], cur: Snapshot) -> Optional[Dict[str, Any]]:
    """Build the message to send a browser that has ``prev`` and now needs ``cur``.

    Returns a full ``init`` message when there is no usable previous state,
    a small ``state`` delta otherwise, or None if nothing changed.
    """
    if prev is None or prev.epoch != cur.epoch or prev.config != cur.config:
        return {
            "t": "init",
            "config": cur.config,
            "bg": cur.background,
            "ents": cur.entities,
            "order": list(cur.entities),
            "status": cur.status,
            "error": cur.error,
            "frame": cur.frame,
        }
    msg: Dict[str, Any] = {}
    if prev.background != cur.background:
        msg["bg"] = cur.background
    changed: Dict[int, Dict[str, Any]] = {}
    for eid, props in cur.entities.items():
        old = prev.entities.get(eid)
        if old is None:
            changed[eid] = props
        elif old != props:
            changed[eid] = {k: v for k, v in props.items() if old.get(k) != v}
    if changed:
        msg["set"] = changed
    removed = [eid for eid in prev.entities if eid not in cur.entities]
    if removed:
        msg["del"] = removed
    if list(prev.entities) != list(cur.entities):
        msg["order"] = list(cur.entities)
    if prev.status != cur.status or prev.error != cur.error:
        msg["status"] = cur.status
        msg["error"] = cur.error
    if not msg:
        return None
    msg["t"] = "state"
    return msg
