"""Пути к ресурсам и бинарникам: dev (python -m keystore) и frozen (PyInstaller)."""
from __future__ import annotations

import os
import sys


def is_frozen() -> bool:
    return getattr(sys, "frozen", False)


def app_dir() -> str:
    """Каталог portable-сборки (рядом лежат Vault и KeyCheckerServer)."""
    if is_frozen():
        return os.path.dirname(os.path.abspath(sys.executable))
    # keystore/keystore/paths.py -> корень репозитория (work_tool)
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def bundle_root() -> str:
    if is_frozen():
        return getattr(sys, "_MEIPASS", app_dir())
    return os.path.join(app_dir(), "winkeycheck")


def resource_path(*parts: str) -> str:
    if is_frozen():
        return os.path.join(getattr(sys, "_MEIPASS", app_dir()), *parts)
    keystore_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(keystore_root, *parts)


def icon_path() -> str:
    return resource_path("icons", "logos", "logo1_v_minimal.png")


def _exe_name(stem: str) -> str:
    return f"{stem}.exe" if os.name == "nt" else stem


def vault_binary() -> str:
    return os.path.join(app_dir(), _exe_name("Vault"))


def server_binary() -> str:
    return os.path.join(app_dir(), _exe_name("KeyCheckerServer"))


def server_dev_script() -> str:
    return os.path.join(app_dir(), "winkeycheck", "server.py")


def build_id() -> str:
    for base in (resource_path("vault_build.txt"), os.path.join(app_dir(), "vault_build.txt")):
        try:
            if os.path.isfile(base):
                return open(base, encoding="utf-8").read().strip()
        except Exception:
            pass
    return "dev"
