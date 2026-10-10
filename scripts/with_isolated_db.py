"""Run one command against the isolated NorthStar database without editing the root .env.

The root .env DATABASE_URL may point at the legacy database (127.0.0.1:5432). This wrapper
copies that URL, replaces only the port with the isolated database port (default 5433), and
runs the given command with DATABASE_URL set in that child process only. Credentials are never
printed. It refuses the legacy port and can refuse to start when an HTTP port is already in
use (two uvicorn processes can silently share a port on Windows).

    python -m scripts.with_isolated_db --require-free-port 8001 -- python -m uvicorn ...
    python -m scripts.with_isolated_db -- python -m alembic -c backend/alembic.ini upgrade head
"""
from __future__ import annotations

import argparse
import os
import re
import socket
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
ISOLATED_PORT = 5433
LEGACY_PORT = 5432


def _validated_parts(database_url: str):
    """Validate before exposing URL parts; malformed userinfo can resemble a host."""
    if (not isinstance(database_url, str) or not database_url
            or any(char.isspace() or char in "\"'<>" for char in database_url)
            or "?" in database_url or "#" in database_url):
        raise ValueError("DATABASE_URL is malformed; details withheld")
    try:
        parts = urlsplit(database_url)
        port = parts.port
        if (parts.scheme not in {"postgresql", "postgresql+psycopg"}
                or parts.hostname not in {"127.0.0.1", "localhost", "::1"}
                or port is None or not 1 <= port <= 65535
                or parts.netloc.count("@") > 1
                or not re.fullmatch(r"/[A-Za-z_][A-Za-z0-9_]*", parts.path)):
            raise ValueError
        authority = parts.netloc.rsplit("@", 1)[-1]
        if not re.fullmatch(r"[0-9]+", authority.rsplit(":", 1)[-1]):
            raise ValueError
    except Exception:
        raise ValueError("DATABASE_URL must name a local PostgreSQL database with an explicit port; details withheld") from None
    return parts


def with_port(database_url: str, port: int) -> str:
    """Return database_url with only its port replaced; user, password, host and path are kept."""
    if not isinstance(port, int) or isinstance(port, bool) or not 1 <= port <= 65535 or port == LEGACY_PORT:
        raise ValueError("Refusing an invalid or protected destination port")
    parts = _validated_parts(database_url)
    credentials, _, host_port = parts.netloc.rpartition("@")
    host = host_port.rsplit(":", 1)[0]
    netloc = f"{credentials}@{host}:{port}" if credentials else f"{host}:{port}"
    return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))


def redacted(database_url: str) -> str:
    parts = _validated_parts(database_url)
    return f"{parts.hostname}:{parts.port}{parts.path}"


def port_in_use(port: int, host: str = "127.0.0.1") -> bool:
    # A plain bind (no SO_REUSEADDR) fails while any socket holds the port; the connect probe
    # additionally catches listeners on other local addresses.
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        try:
            probe.bind((host, port))
        except OSError:
            return True
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.settimeout(0.5)
        return probe.connect_ex((host, port)) == 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--db-port", type=int, default=ISOLATED_PORT)
    parser.add_argument("--require-free-port", type=int, default=None,
                        help="Exit without running the command if this local port is already in use.")
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command:
        parser.error("give the command to run after --")
    if args.db_port == LEGACY_PORT:
        parser.error(f"refusing port {LEGACY_PORT}: that is the legacy database")
    if not 1 <= args.db_port <= 65535:
        parser.error("invalid database port")
    if args.require_free_port is not None and (not 1 <= args.require_free_port <= 65535
            or args.require_free_port in {LEGACY_PORT, ISOLATED_PORT}):
        parser.error("the availability check must use an HTTP port, not a database port")

    try:
        source = os.environ.get("DATABASE_URL") or dotenv_values(ROOT / ".env").get("DATABASE_URL")
        target = with_port(source, args.db_port) if source else None
    except Exception:
        print("DATABASE_URL could not be validated; command not started; details withheld", file=sys.stderr)
        return 2
    if not source:
        print("DATABASE_URL is not set in the environment or the root .env", file=sys.stderr)
        return 2

    if args.require_free_port is not None and port_in_use(args.require_free_port):
        print(f"Port {args.require_free_port} is already in use (a backend is probably already running). "
              "Stop it first; starting another would share the port.", file=sys.stderr)
        return 3

    # Windows does not resolve a relative executable (e.g. .venv\Scripts\python.exe) against cwd.
    executable = ROOT / command[0]
    if not Path(command[0]).is_absolute() and executable.is_file():
        command = [str(executable), *command[1:]]

    print(f"[with_isolated_db] DATABASE_URL -> {redacted(target)}", flush=True)
    try:
        return subprocess.call(command, env={**os.environ, "DATABASE_URL": target}, cwd=ROOT)
    except KeyboardInterrupt:
        return 130
    except OSError:
        print("Command could not be started; details withheld", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
