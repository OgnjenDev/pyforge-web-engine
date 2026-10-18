"""The ``pyforge`` command line."""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import List, Optional

from . import __version__
from .server import explain_os_error, serve, stop_server

EPILOG = """\
examples:
  pyforge run game.py                       play at http://127.0.0.1:8000/
  pyforge run game.py --port 9000
  pyforge run game.py --host 0.0.0.0        let phones/tablets on your network join
  pyforge stop --port 9000                  stop a server started in another terminal
"""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pyforge",
        description="PyForge: write browser games in plain Python.",
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--version", action="version", version=f"pyforge {__version__}")
    sub = parser.add_subparsers(dest="command", metavar="<command>")

    run = sub.add_parser(
        "run",
        help="run a game file and serve it to browsers",
        description="Run a game file and serve it to browsers. Each browser tab gets its own game.",
    )
    run.add_argument("script", help="your game file, e.g. game.py")
    run.add_argument("--host", default="127.0.0.1", help="address to listen on (default: 127.0.0.1; use 0.0.0.0 for your whole network)")
    run.add_argument("--port", type=int, default=8000, help="port to listen on (default: 8000)")
    run.add_argument("--session-timeout", type=float, default=60.0, metavar="SECONDS", help="close a player's game after this many seconds without contact (default: 60)")
    run.add_argument("--cleanup-interval", type=float, default=5.0, metavar="SECONDS", help="how often to look for timed-out sessions (default: 5)")
    run.add_argument("--max-sessions", type=int, default=50, help="most players at once (default: 50)")
    run.add_argument("--verbose", action="store_true", help="log every HTTP request")

    stop = sub.add_parser("stop", help="stop a server started with 'pyforge run' on this machine")
    stop.add_argument("--host", default="127.0.0.1", help="address the server listens on (default: 127.0.0.1)")
    stop.add_argument("--port", type=int, default=8000, help="port of the server (default: 8000)")
    return parser


def _cmd_run(args: argparse.Namespace) -> int:
    script = Path(args.script)
    if not script.is_file():
        print(f"pyforge: error: game file not found: {args.script}", file=sys.stderr)
        return 2
    if not 0 <= args.port <= 65535:
        print("pyforge: error: --port must be between 0 and 65535", file=sys.stderr)
        return 2
    if args.session_timeout <= 0 or args.cleanup_interval <= 0 or args.max_sessions < 1:
        print("pyforge: error: timeouts must be positive and --max-sessions at least 1", file=sys.stderr)
        return 2
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="[%(asctime)s] %(message)s",
        datefmt="%H:%M:%S",
    )
    try:
        compile(script.read_bytes(), str(script), "exec")
    except SyntaxError as exc:
        # Keep serving: the browser will show the error and Restart re-reads the file.
        print(f"pyforge: warning: {script} has a syntax error: {exc}", file=sys.stderr)
    try:
        serve(
            script,
            args.host,
            args.port,
            session_timeout=args.session_timeout,
            cleanup_interval=args.cleanup_interval,
            max_sessions=args.max_sessions,
            verbose=args.verbose,
        )
    except OSError as exc:
        print(f"pyforge: error: {explain_os_error(exc, args.host, args.port)}", file=sys.stderr)
        return 1
    return 0


def _cmd_stop(args: argparse.Namespace) -> int:
    ok, message = stop_server(args.host, args.port)
    print(message, file=None if ok else sys.stderr)
    return 0 if ok else 1


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "run":
        return _cmd_run(args)
    if args.command == "stop":
        return _cmd_stop(args)
    parser.print_help()
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
