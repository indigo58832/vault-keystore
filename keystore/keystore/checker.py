"""Проверка ключей: HTTP-сервер (dev/Linux) или напрямую в процессе (Windows exe)."""
from __future__ import annotations

import sys
import time

import requests

from . import paths

DEFAULT_SERVER = "http://127.0.0.1:17777"


def _health_timeout_sec() -> float:
    return 120.0 if getattr(sys, "frozen", False) else 5.0


class CheckerClient:
    def __init__(self, base_url: str = DEFAULT_SERVER):
        self.base_url = base_url.rstrip("/")
        self._direct = paths.use_direct_check()

    def health_info(self) -> dict | None:
        if self._direct:
            from . import direct_check

            if direct_check.load_error():
                return {
                    "ok": False,
                    "pkeyconfigs_loaded": 0,
                    "mode": "direct",
                    "error": direct_check.load_error(),
                }
            n = direct_check.pkcs_count()
            if n > 0:
                return {"ok": True, "pkeyconfigs_loaded": n, "mode": "direct"}
            if direct_check.ensure_loaded():
                n = direct_check.pkcs_count()
                return {"ok": n > 0, "pkeyconfigs_loaded": n, "mode": "direct"}
            return {
                "ok": False,
                "pkeyconfigs_loaded": 0,
                "mode": "direct",
                "error": direct_check.load_error() or "загрузка pkeyconfig",
            }

        try:
            r = requests.get(
                f"{self.base_url}/health",
                timeout=_health_timeout_sec(),
            )
            if not r.ok:
                return None
            data = r.json()
            if isinstance(data, dict):
                data["mode"] = "http"
            return data
        except Exception:
            return None

    def health(self) -> bool:
        info = self.health_info()
        if not info:
            return False
        n = int(info.get("pkeyconfigs_loaded") or 0)
        return bool(info.get("ok")) and n > 0

    def wait_until_ready(self, timeout_sec: float = 180.0) -> dict | None:
        deadline = time.time() + timeout_sec
        while time.time() < deadline:
            info = self.health_info()
            if info and int(info.get("pkeyconfigs_loaded") or 0) > 0 and info.get("ok"):
                return info
            time.sleep(0.5)
        return None

    def check(
        self,
        key: str,
        *,
        online: bool = True,
        mak_count: bool = True,
        consume: bool = False,
        allow_consume_retail: bool = False,
    ) -> dict:
        if self._direct:
            from . import direct_check

            return direct_check.check_key_direct(
                key,
                online=online,
                mak_count=mak_count,
                consume=consume,
                allow_consume_retail=allow_consume_retail,
            )

        r = requests.post(
            f"{self.base_url}/check",
            json={
                "key": key,
                "online": online,
                "mak_count": mak_count,
                "consume": consume,
                "allow_consume_retail": allow_consume_retail,
            },
            timeout=120,
        )
        if not r.ok:
            return {"key": key, "ok": False, "error": f"HTTP {r.status_code}: {r.text[:200]}"}
        return r.json()
