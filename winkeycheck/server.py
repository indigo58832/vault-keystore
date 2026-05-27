#!/usr/bin/env python3
"""
Локальный HTTP-сервер для Chrome-расширения.
Слушает только localhost. Один endpoint POST /check.

Запуск:
    python3 server.py [--port 8765]

Запрос (JSON):
    POST /check
    {"key": "XXXXX-XXXXX-XXXXX-XXXXX-XXXXX", "consume": false, "mak_count": true, "online": true}

Ответ:
    JSON с полями: ok, edition, description, type_label, is_mak, mak_count,
                   online_ok, online_code, online_human, ...
"""
import sys, os, json, argparse, threading, traceback
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    from .check import check_key, load_all_pkeyconfigs
except ImportError:
    from check import check_key, load_all_pkeyconfigs

# Загружаем pkeyconfig'и один раз при старте — медленная операция
print("Loading pkeyconfigs...", file=sys.stderr)
PKCS = load_all_pkeyconfigs()
print(f"Loaded {len(PKCS)} pkeyconfigs.", file=sys.stderr)

# Wine + pidgenx должен быть глобально сериализован — нельзя параллельно вызывать
WINE_LOCK = threading.Lock()
ERROR_LOG = os.path.join(os.path.expanduser("~"), "vault_server_error.log")


def log_error_text(text: str):
    try:
        with open(ERROR_LOG, "a", encoding="utf-8") as f:
            f.write(text + "\n\n")
    except Exception:
        pass


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        # Чище в stderr
        sys.stderr.write(f"[{self.log_date_time_string()}] {fmt % args}\n")

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def _json(self, code, payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self._cors()
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_GET(self):
        try:
            if self.path.startswith("/health"):
                return self._json(200, {"ok": True, "pkeyconfigs_loaded": len(PKCS)})
            return self._json(404, {"error": "use POST /check"})
        except BaseException:
            tb = traceback.format_exc()
            log_error_text(tb)
            return self._json(500, {"error": tb[-1500:]})

    def do_POST(self):
        try:
            if not self.path.startswith("/check"):
                return self._json(404, {"error": "use POST /check"})

            length = int(self.headers.get("Content-Length") or 0)
            try:
                raw = self.rfile.read(length).decode("utf-8") if length else "{}"
                req = json.loads(raw) if raw.strip() else {}
            except Exception as e:
                return self._json(400, {"error": f"bad JSON: {e}"})

            key = (req.get("key") or "").strip()
            if not key:
                return self._json(400, {"error": "field 'key' required"})

            opts = dict(
                do_online=req.get("online", True),
                do_consume=req.get("consume", False),
                do_mak_count=req.get("mak_count", True),
                allow_consume_retail=req.get("allow_consume_retail", False),
            )

            with WINE_LOCK:
                try:
                    result = check_key(key, pkcs=PKCS, **opts)
                except Exception as e:
                    tb = traceback.format_exc()
                    log_error_text(tb)
                    return self._json(500, {"error": f"check failed: {e}", "traceback": tb[-1500:]})

            return self._json(200, result)
        except BaseException:
            tb = traceback.format_exc()
            log_error_text(tb)
            return self._json(500, {"error": tb[-1500:]})


def create_server(bind: str = "127.0.0.1", port: int = 8765) -> ThreadingHTTPServer:
    return ThreadingHTTPServer((bind, port), Handler)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--bind", default="127.0.0.1", help="default localhost only")
    args = ap.parse_args()

    srv = create_server(args.bind, args.port)
    print(f"Listening on http://{args.bind}:{args.port}", file=sys.stderr)
    print("Endpoints:  GET /health   POST /check   {key, consume?, mak_count?, online?}", file=sys.stderr)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        srv.shutdown()


if __name__ == "__main__":
    main()
