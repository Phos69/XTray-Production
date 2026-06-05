"""Import-safe GUI entry point for optional PySide6 installs."""
from __future__ import annotations


def main() -> int:
    from xtray.core import app_logging

    app_logging.configure_logging(component="network_manager")
    try:
        from .app import main as app_main
    except ImportError as exc:
        raise SystemExit(
            "PySide6 is not installed. Install with: pip install -e .[gui]"
        ) from exc
    return app_main()
