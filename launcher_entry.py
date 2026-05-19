from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import requests
from PyQt6.QtWidgets import QApplication, QMessageBox


def app_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def wait_server(port: int, timeout_sec: float = 15.0) -> bool:
    deadline = time.time() + timeout_sec
    url = f"http://127.0.0.1:{port}/health"
    while time.time() < deadline:
        try:
            if requests.get(url, timeout=1).ok:
                return True
        except Exception:
            time.sleep(0.25)
    return False


def show_error(text: str) -> None:
    app = QApplication.instance() or QApplication(sys.argv)
    QMessageBox.critical(None, "Vault", text)


def main() -> int:
    root = app_dir()
    vault_exe = root / "Vault.exe"
    server_exe = root / "KeyCheckerServer.exe"
    port = 17777

    if not vault_exe.exists():
        show_error(f"Не найден файл: {vault_exe.name}")
        return 1
    if not server_exe.exists():
        show_error(f"Не найден файл: {server_exe.name}")
        return 1

    creationflags = 0
    startupinfo = None
    if os.name == "nt":
        creationflags = subprocess.CREATE_NO_WINDOW
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

    server_proc = subprocess.Popen(
        [str(server_exe), "--port", str(port)],
        cwd=root,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL,
        creationflags=creationflags,
        startupinfo=startupinfo,
    )

    if not wait_server(port):
        try:
            server_proc.terminate()
        except Exception:
            pass
        show_error("Сервер Vault не запустился.")
        return 1

    vault_proc = subprocess.Popen([str(vault_exe)], cwd=root)
    exit_code = vault_proc.wait()

    try:
        server_proc.terminate()
        server_proc.wait(timeout=5)
    except Exception:
        try:
            server_proc.kill()
        except Exception:
            pass

    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
