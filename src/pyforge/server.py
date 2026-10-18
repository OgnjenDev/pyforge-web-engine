"""The web server: serves the browser client and the small JSON/SSE API.

Built on the standard library only (``http.server`` + threads).

Endpoints
---------
GET  /                  browser client (index.html)
GET  /client.js         browser client script
GET  /api/stream        Server-Sent Events: game state for one session
GET  /api/health        sessions count, version
POST /api/session       create a session -> {"session": "<id>"}
POST /api/input         {"events": [...]} key / mouse input (also the heartbeat)
POST /api/restart       restart the game of a session
POST /api/close         end a session now
POST /api/shutdown      stop the server (loopback + secret token only)

The server only ever runs the game script you started it with. No endpoint
accepts code, and browsers are not trusted: input is validated and all game
logic runs server-side. See the README's security section before exposing a
server beyond your own network.
"""
from __future__ import annotations

import errno
import hmac
import json
import logging
import os
import re
import secrets
import select
import socket
import sys
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple, Union
from urllib.parse import parse_qs, urlsplit

from . import __version__
from .sessions import ServerFull, Session, SessionConfig, SessionManager, diff_snapshots

log = logging.getLogger("pyforge")

SESSION_ID_RE = re.compile(r"^[A-Za-z0-9_-]{8,64}$")
MAX_BODY = 64 * 1024
MAX_EVENTS = 256
KEEPALIVE_SECONDS = 10.0
POLL_SECONDS = 1.0
LOOPBACK = ("127.0.0.1", "::1", "::ffff:127.0.0.1")
DISCONNECTS = (ConnectionError, socket.timeout)

WEB_DIR = Path(__file__).resolve().parent / "web"
STATIC = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/index.html": ("index.html", "text/html; charset=utf-8"),
    "/client.js": ("client.js", "application/javascript; charset=utf-8"),
}
CSP = (
    "default-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
    "connect-src 'self'; frame-ancestors 'none'"
)


class ApiError(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


class PyForgeServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True
    request_queue_size = 64

    def __init__(
        self,
        address: Tuple[str, int],
        manager: SessionManager,
        *,
        verbose: bool = False,
        shutdown_token: str = "",
    ) -> None:
        self.manager = manager
        self.verbose = verbose
        self.shutdown_token = shutdown_token
        self.static: Dict[str, bytes] = {
            name: (WEB_DIR / name).read_bytes() for name in {v[0] for v in STATIC.values()}
        }
        if ":" in address[0]:
            self.address_family = socket.AF_INET6
        super().__init__(address, Handler)

    def handle_error(self, request: Any, client_address: Any) -> None:
        exc = sys.exc_info()[1]
        if isinstance(exc, DISCONNECTS):
            return  # a browser went away; nothing to report
        log.exception("error while handling a request from %s", client_address[0])

    def request_shutdown(self) -> None:
        threading.Thread(target=self.shutdown, name="pyforge-shutdown", daemon=True).start()


class Handler(BaseHTTPRequestHandler):
    server: PyForgeServer  # type: ignore[assignment]
    server_version = "PyForge/" + __version__
    protocol_version = "HTTP/1.1"
    timeout = 30

    def log_message(self, format: str, *args: Any) -> None:
        if self.server.verbose:
            log.info("%s %s", self.address_string(), format % args)

    # ------------------------------------------------------------------
    # Routing
    # ------------------------------------------------------------------
    def do_GET(self) -> None:
        self._dispatch("GET")

    def do_POST(self) -> None:
        self._dispatch("POST")

    def _dispatch(self, method: str) -> None:
        try:
            url = urlsplit(self.path)
            query = parse_qs(url.query)
            path = url.path
            if method == "GET":
                if path in STATIC:
                    return self._send_static(path)
                if path == "/api/stream":
                    return self._stream(query)
                if path == "/api/health":
                    return self._send_json(
                        200, {"ok": True, "version": __version__, "sessions": self.server.manager.count()}
                    )
                if path.startswith("/api/") and path in self._post_routes():
                    raise ApiError(405, "use POST for this endpoint")
            else:
                body = self._read_body()
                route = self._post_routes().get(path)
                if route is not None:
                    return route(query, body)
                if path in STATIC or path in ("/api/stream", "/api/health"):
                    raise ApiError(405, "use GET for this endpoint")
            raise ApiError(404, "not found")
        except ApiError as exc:
            if exc.status in (400, 411, 413):
                self.close_connection = True  # the request body may be unread
            self._send_json(exc.status, {"error": exc.message})
        except DISCONNECTS:
            self.close_connection = True
        except Exception:
            log.exception("unexpected error handling %s %s", method, self.path)
            self.close_connection = True
            try:
                self._send_json(500, {"error": "internal server error"})
            except Exception:
                pass

    def _post_routes(self) -> Dict[str, Callable[[Dict[str, List[str]], bytes], None]]:
        return {
            "/api/session": self._api_create,
            "/api/input": self._api_input,
            "/api/restart": self._api_restart,
            "/api/close": self._api_close,
            "/api/shutdown": self._api_shutdown,
        }

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _read_body(self) -> bytes:
        if "chunked" in self.headers.get("Transfer-Encoding", "").lower():
            raise ApiError(411, "Content-Length is required")
        raw = self.headers.get("Content-Length")
        if raw is None:
            return b""
        try:
            length = int(raw)
        except ValueError:
            raise ApiError(400, "invalid Content-Length")
        if length < 0:
            raise ApiError(400, "invalid Content-Length")
        if length > MAX_BODY:
            raise ApiError(413, f"request body is larger than {MAX_BODY} bytes")
        return self.rfile.read(length) if length else b""

    def _send_json(self, status: int, payload: Dict[str, Any]) -> None:
        data = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        if self.close_connection:
            self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(data)

    def _send_static(self, path: str) -> None:
        name, content_type = STATIC[path]
        data = self.server.static[name]
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", CSP)
        self.end_headers()
        self.wfile.write(data)

    def _session(self, query: Dict[str, List[str]]) -> Session:
        session_id = (query.get("session") or [""])[0]
        if not SESSION_ID_RE.match(session_id):
            raise ApiError(400, "missing or malformed session id")
        session = self.server.manager.get(session_id)
        if session is None:
            raise ApiError(404, "unknown or expired session")
        return session

    # ------------------------------------------------------------------
    # POST endpoints
    # ------------------------------------------------------------------
    def _api_create(self, query: Dict[str, List[str]], body: bytes) -> None:
        try:
            session = self.server.manager.create()
        except ServerFull:
            raise ApiError(503, "the server is full, try again later")
        log.info("session %s started (%d active)", session.id[:8], self.server.manager.count())
        self._send_json(200, {"session": session.id})

    def _api_input(self, query: Dict[str, List[str]], body: bytes) -> None:
        session = self._session(query)
        try:
            data = json.loads(body.decode("utf-8")) if body else {}
        except (ValueError, UnicodeDecodeError):
            raise ApiError(400, "body must be JSON")
        events = data.get("events", []) if isinstance(data, dict) else None
        if not isinstance(events, list):
            raise ApiError(400, 'body must look like {"events": [...]}')
        accepted = session.push_input(events[:MAX_EVENTS])
        self._send_json(200, {"ok": True, "accepted": accepted})

    def _api_restart(self, query: Dict[str, List[str]], body: bytes) -> None:
        self._session(query).request_restart()
        self._send_json(200, {"ok": True})

    def _api_close(self, query: Dict[str, List[str]], body: bytes) -> None:
        session_id = (query.get("session") or [""])[0]
        if SESSION_ID_RE.match(session_id) and self.server.manager.remove(session_id, "closed by browser"):
            log.info("session %s closed by browser", session_id[:8])
        self._send_json(200, {"ok": True})

    def _api_shutdown(self, query: Dict[str, List[str]], body: bytes) -> None:
        token = self.headers.get("X-PyForge-Token", "")
        expected = self.server.shutdown_token
        if self.client_address[0] not in LOOPBACK or not expected or not hmac.compare_digest(token, expected):
            raise ApiError(403, "forbidden")
        self._send_json(200, {"ok": True})
        self.server.request_shutdown()

    # ------------------------------------------------------------------
    # Server-Sent Events
    # ------------------------------------------------------------------
    def _sse_send(self, message: Dict[str, Any]) -> None:
        payload = json.dumps(message, separators=(",", ":")).encode("utf-8")
        self.wfile.write(b"data: " + payload + b"\n\n")
        self.wfile.flush()

    def _peer_closed(self) -> bool:
        try:
            readable, _, _ = select.select([self.connection], [], [], 0)
            return bool(readable) and self.connection.recv(1, socket.MSG_PEEK) == b""
        except (OSError, ValueError):
            return True

    def _stream(self, query: Dict[str, List[str]]) -> None:
        session = self._session(query)
        self.close_connection = True
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()
        self.wfile.write(b"retry: 2000\n\n")
        self.wfile.flush()
        session.attach()
        try:
            previous = None
            seen = -1
            last_write = time.monotonic()
            while True:
                snap, version, closed, reason = session.wait_for_update(seen, POLL_SECONDS)
                if closed:
                    self._sse_send({"t": "closed", "reason": reason})
                    return
                if version != seen and snap is not None:
                    seen = version
                    message = diff_snapshots(previous, snap)
                    previous = snap
                    if message is not None:
                        self._sse_send(message)
                        last_write = time.monotonic()
                    continue
                if self._peer_closed():
                    return
                if time.monotonic() - last_write > KEEPALIVE_SECONDS:
                    self.wfile.write(b": keepalive\n\n")
                    self.wfile.flush()
                    last_write = time.monotonic()
        except DISCONNECTS:
            pass
        finally:
            session.detach()


# ----------------------------------------------------------------------
# Starting and stopping
# ----------------------------------------------------------------------
def _state_dir() -> Optional[Path]:
    """A private per-user folder for the shutdown token (None if unavailable)."""
    try:
        base = os.environ.get("PYFORGE_STATE_DIR") or str(Path.home() / ".pyforge")
        path = Path(base)
        path.mkdir(mode=0o700, parents=True, exist_ok=True)
        return path
    except OSError:
        return None


def _token_path(port: int) -> Optional[Path]:
    state = _state_dir()
    return state / f"server-{port}.token" if state else None


def _write_token(port: int, token: str) -> bool:
    path = _token_path(port)
    if path is None:
        return False
    try:
        fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as handle:
            handle.write(token)
        return True
    except OSError:
        return False


def _remove_token(port: int) -> None:
    path = _token_path(port)
    if path is not None:
        try:
            path.unlink()
        except OSError:
            pass


def make_server(
    script: Union[str, Path],
    host: str = "127.0.0.1",
    port: int = 8000,
    *,
    session_timeout: float = 60.0,
    cleanup_interval: float = 5.0,
    max_sessions: int = 50,
    max_sprites: int = 5000,
    verbose: bool = False,
    shutdown_token: str = "",
) -> PyForgeServer:
    """Create (but do not start) a server for ``script``. Use port 0 for any free port."""
    script_path = Path(script).resolve()
    if not script_path.is_file():
        raise FileNotFoundError(f"game file not found: {script}")
    if str(script_path.parent) not in sys.path:
        sys.path.insert(0, str(script_path.parent))  # let games import their own helper modules
    config = SessionConfig(
        session_timeout=session_timeout,
        cleanup_interval=cleanup_interval,
        max_sessions=max_sessions,
        max_sprites=max_sprites,
    )
    manager = SessionManager(script_path, config)
    try:
        return PyForgeServer((host, port), manager, verbose=verbose, shutdown_token=shutdown_token)
    except Exception:
        manager.close_all()
        raise


def lan_addresses() -> List[str]:
    """Best-effort list of this machine's non-loopback IPv4 addresses."""
    found: List[str] = []
    for target in ("10.255.255.255", "8.8.8.8"):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                sock.connect((target, 1))  # UDP connect sends nothing; it only picks a route
                found.append(sock.getsockname()[0])
        except OSError:
            continue
    try:
        found += socket.gethostbyname_ex(socket.gethostname())[2]
    except OSError:
        pass
    unique: List[str] = []
    for ip in found:
        if not ip.startswith("127.") and ip != "0.0.0.0" and ip not in unique:
            unique.append(ip)
    return unique


def serve(
    script: Union[str, Path],
    host: str = "127.0.0.1",
    port: int = 8000,
    **options: Any,
) -> None:
    """Run the server for ``script`` until Ctrl+C or ``pyforge stop``."""
    token = secrets.token_hex(16)
    server = make_server(script, host, port, shutdown_token=token, **options)
    real_port = server.server_address[1]
    has_token = _write_token(real_port, token)
    shown_host = "127.0.0.1" if host in ("0.0.0.0", "::") else host
    print(f"PyForge {__version__} serving {Path(script).name}")
    print(f"  Local:   http://{shown_host}:{real_port}/")
    if host in ("0.0.0.0", "::"):
        addresses = lan_addresses()
        for ip in addresses:
            print(f"  Network: http://{ip}:{real_port}/")
        if not addresses:
            print("  Network: could not detect this device's IP; look it up in your network settings")
        print("  Anyone who can reach this address can play (and load) your game.")
    stop_hint = f" or run `pyforge stop --port {real_port}`" if has_token else ""
    print(f"Press Ctrl+C to stop{stop_hint}.", flush=True)
    try:
        server.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        print("\nStopping...")
    finally:
        server.manager.close_all()
        server.server_close()
        _remove_token(real_port)


def stop_server(host: str = "127.0.0.1", port: int = 8000) -> Tuple[bool, str]:
    """Ask a server started by this user on ``port`` to shut down."""
    path = _token_path(port)
    if path is None or not path.is_file():
        return False, f"No PyForge server started by you was found on port {port}."
    token = path.read_text().strip()
    request = urllib.request.Request(
        f"http://{host}:{port}/api/shutdown",
        data=b"{}",
        method="POST",
        headers={"X-PyForge-Token": token, "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=5):
            pass
    except urllib.error.HTTPError as exc:
        return False, f"The server refused the request (HTTP {exc.code})."
    except (urllib.error.URLError, OSError):
        _remove_token(port)
        return False, f"Nothing is listening on {host}:{port} (removed a stale token file)."
    return True, f"Stopped the PyForge server on port {port}."


def explain_os_error(exc: OSError, host: str, port: int) -> str:
    if exc.errno == errno.EADDRINUSE:
        return f"port {port} is already in use. Pick another one, e.g. --port {port + 1}."
    if exc.errno == errno.EACCES:
        return f"permission denied for port {port}. Ports below 1024 usually need admin rights; try --port 8000."
    if exc.errno in (errno.EADDRNOTAVAIL, errno.ENODEV) or isinstance(exc, socket.gaierror):
        return f"cannot use host {host!r} on this device. Try --host 127.0.0.1 or --host 0.0.0.0."
    return f"could not start the server: {exc}"
