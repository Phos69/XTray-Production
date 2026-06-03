"""Entry point so `python -m computer_manager` works."""
import sys

from .app import main

if __name__ == "__main__":
    sys.exit(main())
