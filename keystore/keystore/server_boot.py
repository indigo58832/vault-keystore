"""Запуск winkeycheck-сервера: встроенный поток (один .exe) или dev-режим."""
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


def _server_ready() -> tuple[bool, dict | None]:
    info = CheckerClient().health_info()
    if not info:
        return False, info
    n = int(info.get("pkeyconfigs_loaded") or 0)
    return bool(info.get("ok")) and n > 0, info


def _wait_ready(timeout_sec: float) -> bool:
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        ready, _ = _server_ready()
        if ready:
            return True
        time.sleep(0.25)
    return False


def _free_port(port: int) -> None:
    """Освободить порт от старого KeyCheckerServer / зависшего Vault."""
    if os.name == "nt":
        try:
            r = subprocess.run(
                ["netstat", "-ano"],
                capture_output=True,
                text=True,
                timeout=10,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            pids: set[str] = set()
            for line in (r.stdout or "").splitlines():
                if f":{port}" not in line or "LISTENING" not in line.upper():
                    continue
                parts = line.split()
                if parts and parts[-1].isdigit():
                    pids.add(parts[-1])
            for pid in pids:
                subprocess.run(
                    ["taskkill", "/F", "/PID", pid],
                    capture_output=True,
                    timeout=10,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )
        except Exception:
            pass
        return

    for cmd in (
        ["fuser", "-k", f"{port}/tcp"],
        ["sh", "-c", f"ss -lptn 'sport = :{port}' | sed -n 's/.*pid=\\([0-9]*\\).*/\\1/p' | xargs -r kill"],
    ):
        try:
            subprocess.run(cmd, capture_output=True, timeout=10)
            return
        except Exception:
            continue


def start_embedded_server(port: int = CHECKER_PORT) -> bool:
    """HTTP-сервер проверки в фоновом потоке того же процесса."""
    global _embedded_http_server
    with _embedded_lock:
        if _embedded_http_server is not None:
            return _server_ready()[0]
        try:
            from winkeycheck.server import create_server
        except ImportError:
            return False
        srv = create_server("127.0.0.1", port)
        thread = threading.Thread(target=srv.serve_forever, daemon=True, name="winkeycheck")
        thread.start()
        _embedded_http_server = srv
    timeout = 120.0 if getattr(sys, "frozen", False) else 30.0
    return _wait_ready(timeout)


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
    return _wait_ready(timeout_sec)


def ensure_checker_server_running(
    *,
    server_binary: str,
    server_dev_script: str,
    log_file: str,
    is_frozen: bool,
) -> bool:
    """Сервер на :17777 с загруженными pkeyconfig (не пустой health)."""
    ready, _ = _server_ready()
    if ready:
        return True

    # Старый KeyCheckerServer на порту без pkeyconfig — убрать и поднять заново.
    _free_port(CHECKER_PORT)

    timeout = 45.0 if is_frozen else 12.0

    # Portable Windows: только встроенный сервер (данные внутри Vault.exe).
    if is_frozen:
        return start_embedded_server(CHECKER_PORT)

    if os.path.isfile(server_binary):
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
