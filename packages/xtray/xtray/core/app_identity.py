"""Application identity helpers for desktop shells."""
from __future__ import annotations

import ctypes
import sys
from typing import Any

APP_NAME = "XTray"
APP_DISPLAY_NAME = "XTray"
ORGANIZATION_NAME = "XTray"
WINDOWS_APP_USER_MODEL_ID = "ArrigoCroce.XTray"


def install_windows_app_user_model_id(
    app_user_model_id: str = WINDOWS_APP_USER_MODEL_ID,
) -> bool:
    """Set the Windows AppUserModelID used for taskbar grouping and notifications."""
    if sys.platform != "win32":
        return False
    try:
        result = ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            app_user_model_id
        )
    except Exception:
        return False
    return result == 0


def apply_qt_application_metadata(app: Any) -> None:
    app.setApplicationName(APP_NAME)
    app.setOrganizationName(ORGANIZATION_NAME)
    try:
        app.setApplicationDisplayName(APP_DISPLAY_NAME)
    except AttributeError:
        pass
