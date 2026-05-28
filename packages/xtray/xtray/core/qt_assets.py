"""Qt helpers for loading XTray window and tray assets."""
from __future__ import annotations

import re
from importlib import resources
from pathlib import Path
from typing import Any

import xtray

NAV_ICON_ASSET = "assets/xtray_nav_icon.svg"
TRAY_LOGO_ASSET = "assets/xtray_minimal_logo.svg"
TRAY_GLYPH_ASSET = "assets/xtray_tray_glyph.svg"
HOME_ASSISTANT_LOGO_ASSET = "assets/homeassistant_logo.svg"
MQTT_LOGO_ASSET = "assets/mqtt_logo.svg"
RESTART_ICON_ASSET = "assets/restart.svg"

_TINTABLE_FILL_RE = re.compile(
    r"fill=([\"'])(?:currentColor|#(?:000|000000))\1",
    re.IGNORECASE,
)
# Sentinel fill used by xtray_minimal_logo.svg's tray-base path so it can be
# tinted independently from the X mark and "tray" wordmark.
_ACCENT_FILL_RE = re.compile(
    r"fill=([\"'])#(?:f0f|ff00ff)\1",
    re.IGNORECASE,
)
# Matches the wordmark <text>tray</text> in xtray_minimal_logo.svg.
_WORDMARK_TEXT_RE = re.compile(r"(<text\b[^>]*>)tray(</text>)")
# SVG declares width/viewBox at 1200x320; when a longer wordmark is requested
# we grow the horizontal extent so the text fits without clipping.
_LOGO_DEFAULT_VIEWBOX_WIDTH = 1200
_LOGO_VIEWBOX_HEIGHT = 320
_LOGO_TEXT_START_X = 360
_LOGO_TEXT_RIGHT_MARGIN = 40
# Estimated advance width per character for Impact at font-size 180;
# conservative so wide letters (m, w) still fit.
_LOGO_CHAR_ADVANCE = 68


def _repo_root_asset(relative_path: str) -> Path:
    return Path(__file__).resolve().parents[1] / Path(relative_path).name


def _asset_text(relative_path: str) -> str:
    try:
        return resources.files(xtray).joinpath(relative_path).read_text(encoding="utf-8")
    except (FileNotFoundError, ModuleNotFoundError, OSError):
        return _repo_root_asset(relative_path).read_text(encoding="utf-8")


def qicon_from_asset(relative_path: str) -> Any:
    from PySide6.QtGui import QIcon  # type: ignore[import-not-found]

    try:
        asset = resources.files(xtray).joinpath(relative_path)
        with resources.as_file(asset) as icon_path:
            icon = QIcon(str(icon_path))
            if not icon.isNull():
                return icon
    except Exception:
        pass

    fallback = _repo_root_asset(relative_path)
    icon = QIcon(str(fallback)) if fallback.exists() else QIcon()
    return icon if not icon.isNull() else QIcon()


def _system_is_dark() -> bool:
    # Why: tray (taskbar) and DWM title bars follow the OS color scheme, not the
    # in-app theme. A pure-black icon disappears on the dark Windows taskbar.
    try:
        from PySide6.QtCore import Qt  # type: ignore[import-not-found]
        from PySide6.QtGui import QGuiApplication  # type: ignore[import-not-found]
    except ImportError:
        return False
    app = QGuiApplication.instance()
    if app is None:
        return False
    try:
        return app.styleHints().colorScheme() == Qt.ColorScheme.Dark
    except AttributeError:
        return False


def _system_icon_color() -> str:
    return "#ffffff" if _system_is_dark() else "#000000"


def _multi_size_icon(
    relative_path: str,
    sizes: tuple[int, ...],
    *,
    accent_color: str | None = None,
) -> Any:
    from PySide6.QtGui import QIcon  # type: ignore[import-not-found]

    color = _system_icon_color()
    icon = QIcon()
    for size in sizes:
        pixmap = svg_asset_pixmap(
            relative_path,
            size,
            size,
            color=color,
            accent_color=accent_color or color,
        )
        if not pixmap.isNull():
            icon.addPixmap(pixmap)
    return icon if not icon.isNull() else qicon_from_asset(relative_path)


def window_icon() -> Any:
    return _multi_size_icon(NAV_ICON_ASSET, (16, 20, 24, 32, 48, 64, 128, 256))


def tray_icon(*, accent_color: str | None = None) -> Any:
    return _multi_size_icon(
        NAV_ICON_ASSET,
        (16, 20, 24, 32, 48, 64),
        accent_color=accent_color,
    )


def set_application_window_icon(app: Any | None = None) -> Any:
    from PySide6.QtWidgets import QApplication  # type: ignore[import-not-found]

    icon = window_icon()
    if icon.isNull():
        return icon
    target_app = app or QApplication.instance()
    if target_app is not None:
        target_app.setWindowIcon(icon)
    return icon


def set_window_icon(window: Any) -> bool:
    icon = set_application_window_icon()
    if icon.isNull():
        return False
    try:
        window.setWindowIcon(icon)
    except AttributeError:
        return False
    return True


def _xml_escape(value: str) -> str:
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _logo_viewbox_width_for(wordmark: str) -> int:
    needed = _LOGO_TEXT_START_X + _LOGO_CHAR_ADVANCE * len(wordmark) + _LOGO_TEXT_RIGHT_MARGIN
    return max(_LOGO_DEFAULT_VIEWBOX_WIDTH, needed)


def svg_asset_pixmap(
    relative_path: str,
    width: int,
    height: int,
    *,
    color: str | None = None,
    accent_color: str | None = None,
    wordmark_text: str | None = None,
) -> Any:
    from PySide6.QtCore import Qt  # type: ignore[import-not-found]
    from PySide6.QtGui import QPixmap  # type: ignore[import-not-found]

    svg_text = _asset_text(relative_path)
    if color:
        svg_text = _TINTABLE_FILL_RE.sub(rf"fill=\1{color}\1", svg_text)
    if accent_color:
        svg_text = _ACCENT_FILL_RE.sub(rf"fill=\1{accent_color}\1", svg_text)
    if wordmark_text is not None:
        svg_text = _WORDMARK_TEXT_RE.sub(
            lambda m: f"{m.group(1)}{_xml_escape(wordmark_text)}{m.group(2)}",
            svg_text,
        )
        new_vb_width = _logo_viewbox_width_for(wordmark_text)
        if new_vb_width != _LOGO_DEFAULT_VIEWBOX_WIDTH:
            svg_text = svg_text.replace(
                f'viewBox="0 0 {_LOGO_DEFAULT_VIEWBOX_WIDTH} {_LOGO_VIEWBOX_HEIGHT}"',
                f'viewBox="0 0 {new_vb_width} {_LOGO_VIEWBOX_HEIGHT}"',
                1,
            )
            svg_text = svg_text.replace(
                f'width="{_LOGO_DEFAULT_VIEWBOX_WIDTH}"',
                f'width="{new_vb_width}"',
                1,
            )

    pixmap = QPixmap()
    if not pixmap.loadFromData(svg_text.encode("utf-8"), "SVG"):
        return QPixmap()
    return pixmap.scaled(
        width,
        height,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )


def tray_nav_icon_pixmap(
    size: int,
    *,
    color: str | None = None,
    accent_color: str | None = None,
) -> Any:
    base_color = color or "#000000"
    return svg_asset_pixmap(
        NAV_ICON_ASSET,
        size,
        size,
        color=color,
        accent_color=accent_color or base_color,
    )


def tray_glyph_pixmap(size: int, *, color: str | None = None) -> Any:
    return svg_asset_pixmap(TRAY_GLYPH_ASSET, size, size, color=color)


def tray_logo_pixmap(
    width: int,
    height: int,
    *,
    color: str | None = None,
    accent_color: str | None = None,
    wordmark_text: str | None = None,
) -> Any:
    # Grow the requested width so longer wordmarks keep the same visual
    # height instead of being squashed by KeepAspectRatio scaling.
    if wordmark_text is not None:
        vb_width = _logo_viewbox_width_for(wordmark_text)
        scaled_width = int(round(height * vb_width / _LOGO_VIEWBOX_HEIGHT))
        width = max(width, scaled_width)
    return svg_asset_pixmap(
        TRAY_LOGO_ASSET,
        width,
        height,
        color=color,
        accent_color=accent_color,
        wordmark_text=wordmark_text,
    )
