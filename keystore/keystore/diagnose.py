"""Диагностика Vault/winkeycheck для отладки Windows-сборки."""
from __future__ import annotations

import json
import os
import sys

from .checker import CheckerClient
from . import paths


def share_dir() -> str:
    return os.path.expanduser("~/.local/share/keystore")


def report_paths() -> list[str]:
    """Куда пишем отчёт: сначала рядом с Vault.exe (проще найти)."""
    out = [os.path.join(paths.app_dir(), "vault_diagnose.json")]
    out.append(os.path.join(share_dir(), "vault_diagnose.json"))
    return out


def diagnose_path() -> str:
    return report_paths()[0]


def collect(*, load_local_pkcs: bool = True) -> dict:
    roots: list[str] = []
    local_n: int | None = None
    if load_local_pkcs:
        try:
            from winkeycheck.check import load_all_pkeyconfigs, _bundle_roots
        except ImportError:
            sys.path.insert(0, paths.app_dir())
            from winkeycheck.check import load_all_pkeyconfigs, _bundle_roots
        roots = _bundle_roots()
        local_n = len(load_all_pkeyconfigs())
    info = CheckerClient().health_info()

    return {
        "build_id": paths.build_id(),
        "frozen": paths.is_frozen(),
        "platform": sys.platform,
        "executable": sys.executable,
        "app_dir": paths.app_dir(),
        "meipass": getattr(sys, "_MEIPASS", None),
        "bundle_roots": roots,
        "pkeyconfigs_local": local_n,
        "health": info,
        "legacy_server_binary": paths.server_binary(),
        "legacy_server_exists": os.path.isfile(paths.server_binary()),
        "report_paths": report_paths(),
    }


def write_report(*, load_local_pkcs: bool = False) -> str:
    """Быстрый отчёт при старте GUI (без повторной загрузки 80 pkeyconfig)."""
    os.makedirs(share_dir(), exist_ok=True)
    os.makedirs(paths.app_dir(), exist_ok=True)
    data = collect(load_local_pkcs=load_local_pkcs)
    written = []
    for path in report_paths():
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            written.append(path)
        except Exception:
            pass
    return written[0] if written else diagnose_path()


def run_cli() -> int:
    import tempfile

    from .server_boot import ensure_checker_server_running

    ensure_checker_server_running(
        server_binary=paths.server_binary(),
        server_dev_script=paths.server_dev_script(),
        log_file=os.path.join(tempfile.gettempdir(), "winkeycheck.log"),
        is_frozen=paths.is_frozen(),
    )
    path = write_report(load_local_pkcs=True)
    data = collect(load_local_pkcs=False)

    lines = [
        f"build_id={data.get('build_id')}",
        f"pkeyconfigs_local={data.get('pkeyconfigs_local')}",
        f"health={data.get('health')}",
        f"json={path}",
        f"also={report_paths()}",
    ]
    text = "\n".join(lines) + "\n"
    out_txt = os.path.join(paths.app_dir(), "vault_diagnose_output.txt")
    try:
        with open(out_txt, "w", encoding="utf-8") as f:
            f.write(text)
    except Exception:
        pass

    print(text)
    if not data.get("health") or int((data.get("health") or {}).get("pkeyconfigs_loaded") or 0) < 1:
        return 1
    return 0
