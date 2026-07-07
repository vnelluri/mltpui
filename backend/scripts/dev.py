#!/usr/bin/env python
"""One-command local dev startup with NO Docker required.

Replaces docker-compose + LocalStack with `python -m moto.server` (pure
Python, no Docker, no JVM) for DynamoDB/S3/KMS/Secrets Manager emulation.
Run from the `backend/` directory:

    python scripts/dev.py

Ctrl+C stops both uvicorn and the moto server together.
"""
from __future__ import annotations

import atexit
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

# Windows' default console codepage (cp1252) can't encode the ✅/⚠️/✔ symbols
# used below and would crash on the very first print. Force UTF-8 output
# regardless of the OS's default console encoding.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

BACKEND_DIR = Path(__file__).resolve().parent.parent
MOTO_PORT = 5000
MOTO_URL = f"http://localhost:{MOTO_PORT}"
BACKEND_URL = "http://localhost:8000"

_moto_process: subprocess.Popen | None = None


def _child_env() -> dict:
    """Environment for every subprocess this script spawns.

    Every child script here (moto_server, the setup scripts, uvicorn)
    prints the same kind of unicode symbols this script does — force UTF-8
    for all of them too, not just this top-level process, or they'd hit
    the identical crash on Windows' default console codepage.
    """
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    # Unbuffered, so output from setup steps appears immediately/in-order
    # instead of sitting in a block buffer until the process exits (the
    # default when stdout isn't a TTY, e.g. when redirected to a log file).
    env["PYTHONUNBUFFERED"] = "1"
    return env


def _fail(message: str) -> None:
    print(f"❌ {message}", file=sys.stderr)
    sys.exit(1)


def check_moto_installed() -> None:
    try:
        import moto  # noqa: F401
    except ImportError:
        _fail(
            "moto[server] is not installed.\n"
            "  Run: pip install -r requirements.txt -r requirements-dev.txt"
        )


def ensure_env_file() -> None:
    env_path = BACKEND_DIR / ".env"
    example_path = BACKEND_DIR / ".env.example"
    if not env_path.exists():
        shutil.copyfile(example_path, env_path)
        print(f"⚠️  No .env found — created one from .env.example.")
    else:
        print("Using existing backend/.env")


def load_env() -> None:
    from dotenv import load_dotenv

    load_dotenv(BACKEND_DIR / ".env", override=True)


def start_moto_server() -> subprocess.Popen:
    global _moto_process
    print(f"Starting moto_server on port {MOTO_PORT} ...")
    process = subprocess.Popen(
        [sys.executable, "-m", "moto.server", "-p", str(MOTO_PORT)],
        cwd=BACKEND_DIR,
        env=_child_env(),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    _moto_process = process
    atexit.register(stop_moto_server)
    return process


def stop_moto_server() -> None:
    global _moto_process
    if _moto_process is not None and _moto_process.poll() is None:
        print("\nStopping moto_server ...")
        _moto_process.terminate()
        try:
            _moto_process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            _moto_process.kill()
        _moto_process = None


def wait_for(url: str, label: str, timeout: int = 20) -> None:
    elapsed = 0.0
    interval = 0.5
    while elapsed < timeout:
        try:
            urllib.request.urlopen(url, timeout=2)
            print(f"✔ {label} is ready")
            return
        except (urllib.error.URLError, ConnectionError, OSError):
            print(".", end="", flush=True)
            time.sleep(interval)
            elapsed += interval
    print()
    _fail(f"{label} did not become ready within {timeout}s (checked {url}).")


def run_step(*args: str, label: str) -> None:
    print(f"\n→ {label}")
    result = subprocess.run([sys.executable, *args], cwd=BACKEND_DIR, env=_child_env())
    if result.returncode != 0:
        stop_moto_server()
        _fail(f"{label} failed (exit code {result.returncode}). Aborting startup.")


def main() -> None:
    check_moto_installed()
    ensure_env_file()
    load_env()

    start_moto_server()
    wait_for(MOTO_URL, "moto_server (DynamoDB/S3/KMS/Secrets Manager emulation)")

    run_step("scripts/setup_local_kms.py", label="Setting up local KMS key")
    run_step("scripts/create_tables.py", label="Creating DynamoDB table")
    run_step("scripts/seed_demo_data.py", label="Seeding demo data")

    print(
        f"""
✅ Backend running locally (no Docker)

API:         {BACKEND_URL}
API docs:    {BACKEND_URL}/docs
moto server: {MOTO_URL}  (AWS emulation — DynamoDB, S3, KMS, Secrets Manager)

Demo credentials (AUTH_MODE=dev):
  Role:     PlatformAdmin  (change DEV_USER_ROLE in backend/.env)
  Tenants:  Risk Analytics · Fraud Detection · Compliance

To change your demo role:
  Edit DEV_USER_ROLE in backend/.env, then stop this script (Ctrl+C) and
  re-run it — environment variables are read once at process startup,
  so a plain file edit has no effect until the process restarts.

To reset demo data:
  python scripts/reset_local_db.py   (moto_server must still be running)

To stop:
  Ctrl+C in this terminal (stops uvicorn and moto_server together)

Starting uvicorn ...
"""
    )

    try:
        subprocess.run(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "app.main:app",
                "--reload",
                "--host",
                "0.0.0.0",
                "--port",
                "8000",
            ],
            cwd=BACKEND_DIR,
            env=_child_env(),
        )
    except KeyboardInterrupt:
        pass
    finally:
        stop_moto_server()


if __name__ == "__main__":
    main()
