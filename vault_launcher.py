from __future__ import annotations

import argparse
import threading
import time

import requests

from keystore.app import main as vault_main
from keystore.quick_check import main as quick_check_main
from winkeycheck.server import create_server


def run_server_only(port: int) -> None:
    server = create_server("127.0.0.1", port)
    print(f"Listening on http://127.0.0.1:{port}")
    server.serve_forever()


def run_full_app() -> None:
    port = 17777
    server = create_server("127.0.0.1", port)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    deadline = time.time() + 10
    while time.time() < deadline:
        try:
            if requests.get(f"http://127.0.0.1:{port}/health", timeout=1).ok:
                break
        except Exception:
            time.sleep(0.2)

    vault_main()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--quick-check", action="store_true")
    parser.add_argument("--server", action="store_true")
    parser.add_argument("--port", type=int, default=17777)
    args = parser.parse_args()

    if args.quick_check:
        quick_check_main()
        return
    if args.server:
        run_server_only(args.port)
        return
    run_full_app()


if __name__ == "__main__":
    main()
