"""Клиент к локальному winkeycheck-серверу (тот же что использует Chrome-расширение)."""
import requests

DEFAULT_SERVER = "http://127.0.0.1:17777"


class CheckerClient:
    def __init__(self, base_url: str = DEFAULT_SERVER):
        self.base_url = base_url.rstrip("/")

    def health_info(self) -> dict | None:
        try:
            r = requests.get(f"{self.base_url}/health", timeout=2)
            if not r.ok:
                return None
            return r.json()
        except Exception:
            return None

    def health(self) -> bool:
        info = self.health_info()
        if not info:
            return False
        n = int(info.get("pkeyconfigs_loaded") or 0)
        return bool(info.get("ok")) and n > 0

    def check(self, key: str, *, online: bool = True, mak_count: bool = True,
              consume: bool = False, allow_consume_retail: bool = False) -> dict:
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
