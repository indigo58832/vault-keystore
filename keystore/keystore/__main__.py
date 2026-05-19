import sys

from .app import main as app_main
from .quick_check import main as quick_check_main

if __name__ == "__main__":
    if "--quick-check" in sys.argv:
        sys.argv = [arg for arg in sys.argv if arg != "--quick-check"]
        quick_check_main()
    else:
        app_main()
