"""Прямая проверка ключей в процессе Vault (без HTTP :17777)."""
from __future__ import annotations

import sys
import threading

_lock = threading.Lock()
_pkcs = None
_load_error: str | None = None
_loading = False


def _import_check():
    try:
        from winkeycheck.check import check_key, load_all_pkeyconfigs
        return check_key, load_all_pkeyconfigs
    except ImportError:
        from . import paths
        root = paths.app_dir()
        if root not in sys.path:
            sys.path.insert(0, root)
        from winkeycheck.check import check_key, load_all_pkeyconfigs
        return check_key, load_all_pkeyconfigs


def pkcs_count() -> int:
    return len(_pkcs) if _pkcs else 0


def load_error() -> str | None:
    return _load_error


def ensure_loaded() -> bool:
    global _pkcs, _load_error, _loading
    if _pkcs:
        return True
    if _load_error:
        return False
    with _lock:
        if _pkcs:
            return True
        if _load_error:
            return False
        _loading = True
        try:
            _, load_all = _import_check()
            _pkcs = load_all()
            if not _pkcs:
                _load_error = "не загружен ни один pkeyconfig"
        except Exception as e:
            _load_error = str(e)
            _pkcs = None
        finally:
            _loading = False
    return bool(_pkcs)


def warmup_async() -> None:
    if _pkcs or _loading:
        return
    threading.Thread(target=ensure_loaded, daemon=True, name="pkcs-preload").start()


def check_key_direct(
    key: str,
    *,
    online: bool = True,
    mak_count: bool = True,
    consume: bool = False,
    allow_consume_retail: bool = False,
) -> dict:
    if not ensure_loaded():
        return {
            "key": key,
            "ok": False,
            "error": _load_error or "база pkeyconfig ещё загружается, подождите",
            "pkeyconfigs_loaded": 0,
        }
    check_key_fn, _ = _import_check()
    with _lock:
        return check_key_fn(
            key,
            pkcs=_pkcs,
            do_online=online,
            do_mak_count=mak_count,
            do_consume=consume,
            allow_consume_retail=allow_consume_retail,
        )
