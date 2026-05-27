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
_boot_log_path: str | None = None


def set_boot_log(path: str | None) -> None:
    global _boot_log_path
    _boot_log_path = path


def _boot_log(msg: str) -> None:
    if not _boot_log_path:
        return
    try:
        with open(_boot_log_path, "a", encoding="utf-8") as f:
            f.write(msg + "\n")
    except Exception:
        pass


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


def _windows_image_name(pid: str) -> str:
    try:
        r = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
            capture_output=True,
            text=True,
            timeout=8,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        line = (r.stdout or "").strip()
        if not line or "No tasks" in line:
            return ""
        return line.split(",")[0].strip('"').lower()
    except Exception:
        return ""


def _should_kill_listener_pid(pid: str) -> bool:
    if pid == str(os.getpid()):
        return False
    if os.name == "nt":
        image = _windows_image_name(pid)
        if not image:
            return False
        # Никогда не убивать Vault.exe — иначе второй запуск ломает первый.
        if image == "vault.exe":
            return False
        if "keycheckerserver" in image:
            return True
        return False
    return True


def _free_port(port: int) -> None:
    """Освободить порт только от старого KeyCheckerServer (не от Vault.exe)."""
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
                if not _should_kill_listener_pid(pid):
                    _boot_log(f"free_port: skip pid={pid} image={_windows_image_name(pid)}")
                    continue
                _boot_log(f"free_port: kill pid={pid} image={_windows_image_name(pid)}")
                subprocess.run(
                    ["taskkill", "/F", "/PID", pid],
                    capture_output=True,
                    timeout=10,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )
        except Exception as e:
            _boot_log(f"free_port error: {e}")
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
            from winkeycheck.server import create_server, get_pkcs
        except ImportError as e:
            _boot_log(f"embedded import error: {e}")
            return False
        try:
            n = len(get_pkcs())
            _boot_log(f"embedded pkcs preloaded: {n}")
        except Exception as e:
            _boot_log(f"embedded pkcs preload error: {e}")
            return False
        try:
            srv = create_server("127.0.0.1", port)
        except Exception as e:
            _boot_log(f"embedded bind error: {e}")
            return False
        thread = threading.Thread(target=srv.serve_forever, daemon=True, name="winkeycheck")
        thread.start()
        _embedded_http_server = srv
    timeout = 180.0 if getattr(sys, "frozen", False) else 30.0
    ok = _wait_ready(timeout)
    _boot_log(f"embedded wait_ready {timeout}s -> {ok}")
    return ok


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
    ready, info = _server_ready()
    if ready:
        _boot_log(f"server already ready: {info}")
        return True

    _boot_log("server not ready, trying boot...")
    _free_port(CHECKER_PORT)

    timeout = 45.0 if is_frozen else 12.0

    if is_frozen:
        ok = start_embedded_server(CHECKER_PORT)
        _boot_log(f"ensure frozen embedded -> {ok}")
        return ok

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
