from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "keystore"))

from keystore.app import main as app_main
from keystore.quick_check import main as quick_check_main


def main() -> None:
    if "--quick-check" in sys.argv:
        sys.argv = [arg for arg in sys.argv if arg != "--quick-check"]
        quick_check_main()
        return
    app_main()


if __name__ == "__main__":
    main()
