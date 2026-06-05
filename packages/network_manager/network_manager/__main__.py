"""Entry point so `python -m network_manager` works."""
import sys

from .gui_entry import main

if __name__ == "__main__":
    sys.exit(main())
