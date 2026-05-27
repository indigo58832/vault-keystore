"""Запуск winkeycheck-сервера: внешний процесс или встроенный поток (один .exe)."""
from __future__ import annotations

import os
import subprocess
import sys
import threading
import time

from .checker import CheckerClient

CHECKER_PORT = 17777

_embedded_http_server = None
_embedded_lock = threading.Lock()


def _wait_health(timeout_sec: float) -> bool:
    client = CheckerClient()
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        if client.health():
            return True
        time.sleep(0.25)
    return False


def start_embedded_server(port: int = CHECKER_PORT) -> bool:
    """HTTP-сервер проверки в фоновом потоке того же процесса."""
    global _embedded_http_server
    with _embedded_lock:
        if _embedded_http_server is not None:
            return True
        try:
            from winkeycheck.server import create_server
        except ImportError:
            return False
        srv = create_server("127.0.0.1", port)
        thread = threading.Thread(target=srv.serve_forever, daemon=True, name="winkeycheck")
        thread.start()
        _embedded_http_server = srv
    return _wait_health(120.0 if getattr(sys, "frozen", False) else 30.0)


def start_external_server(
    cmd: list[str],
    *,
    cwd: str,
    log_file: str | None,
    timeout_sec: float,
) -> bool:
    creationflags = 0
    popen_kwargs: dict = {"cwd": cwd, "stdin": subprocess.DEVNULL}
    if log_file:
        try:
            fh = open(log_file, "ab")
            popen_kwargs["stdout"] = fh
            popen_kwargs["stderr"] = fh
        except Exception:
            popen_kwargs["stdout"] = subprocess.DEVNULL
            popen_kwargs["stderr"] = subprocess.DEVNULL
    else:
        popen_kwargs["stdout"] = subprocess.DEVNULL
        popen_kwargs["stderr"] = subprocess.DEVNULL

    if os.name == "nt":
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
    else:
        popen_kwargs["start_new_session"] = True

    subprocess.Popen(cmd, creationflags=creationflags, **popen_kwargs)
    return _wait_health(timeout_sec)


def ensure_checker_server_running(
    *,
    server_binary: str,
    server_dev_script: str,
    log_file: str,
    is_frozen: bool,
) -> bool:
    """Сервер на :17777: уже живой → внешний exe → python server.py → встроенный поток."""
    if _wait_health(0.5):
        return True

    timeout = 45.0 if is_frozen else 12.0

    if is_frozen and os.path.isfile(server_binary):
        if start_external_server(
            [server_binary, "--port", str(CHECKER_PORT)],
            cwd=os.path.dirname(server_binary),
            log_file=log_file,
            timeout_sec=timeout,
        ):
            return True

    if os.path.isfile(server_dev_script):
        if start_external_server(
            [sys.executable, server_dev_script, "--port", str(CHECKER_PORT)],
            cwd=os.path.dirname(server_dev_script),
            log_file=log_file,
            timeout_sec=timeout,
        ):
            return True

    return start_embedded_server(CHECKER_PORT)
