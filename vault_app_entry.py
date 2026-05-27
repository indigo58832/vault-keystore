from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "keystore"))

from keystore.app import main as app_main
from keystore.quick_check import main as quick_check_main


def self_test_pkeyconfigs() -> None:
    """Проверка загрузки pkeyconfig (для CI и отладки frozen-сборки)."""
    sys.path.insert(0, HERE)
    from winkeycheck.check import load_all_pkeyconfigs, _bundle_roots

    roots = _bundle_roots()
    pkcs = load_all_pkeyconfigs()
    print(f"bundle_roots={roots}", file=sys.stderr)
    print(f"pkeyconfigs_loaded={len(pkcs)}", file=sys.stderr)
    if not pkcs:
        sys.exit(1)


def main() -> None:
    if "--self-test-pkeyconfigs" in sys.argv:
        self_test_pkeyconfigs()
        return
    if "--diagnose" in sys.argv:
        sys.path.insert(0, os.path.join(HERE, "keystore"))
        from keystore.diagnose import run_cli
        sys.exit(run_cli())
    if "--quick-check" in sys.argv:
        sys.argv = [arg for arg in sys.argv if arg != "--quick-check"]
        quick_check_main()
        return
    app_main()


if __name__ == "__main__":
    main()
