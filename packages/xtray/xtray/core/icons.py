"""MDI icon loading and picker widgets.

The bundled Material Design Icons live in ``assets/mdi/`` as a complete set of
24x24 SVGs with ``fill="currentColor"``. Profiles and network devices store an
icon name as a short string such as ``"mdi:monitor"``; the helpers in this
module turn that string into a tinted ``QIcon`` for the tray and editor
surfaces.
"""
from __future__ import annotations

from collections.abc import Callable, Iterable
from functools import lru_cache
from importlib import resources
from pathlib import Path
from typing import Any

ICON_NAME_PREFIX = "mdi:"
_ASSETS_PACKAGE = "xtray.core.assets.mdi"
_PICKER_ICON_PIXELS = 40
_PICKER_ITEM_PIXELS = 72
_PICKER_GRID_PIXELS = 80


def _set_xtray_window_icon(window: Any) -> None:
    try:
        from xtray.core import qt_assets
    except Exception:
        return
    try:
        qt_assets.set_window_icon(window)
    except Exception:
        return


def normalize_icon_name(value: Any) -> str | None:
    """Coerce stored icon values to ``"mdi:<name>"`` or None.

    Why: Profile / device JSON may carry legacy values (bare names, empty
    strings, ``None``). Centralising normalisation keeps the rest of the app
    from having to special-case those.
    """
    if value is None:
        return None
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text.lower().startswith(ICON_NAME_PREFIX):
        name = text[len(ICON_NAME_PREFIX):].strip()
    else:
        name = text
    if not name or "/" in name or "\\" in name or name.startswith("."):
        return None
    return f"{ICON_NAME_PREFIX}{name}"


def icon_short_name(value: str | None) -> str | None:
    normalized = normalize_icon_name(value)
    if normalized is None:
        return None
    return normalized[len(ICON_NAME_PREFIX):]


def _mdi_dir() -> Path | None:
    try:
        with resources.as_file(resources.files("xtray.core").joinpath("assets/mdi")) as path:
            return Path(path) if path.exists() else None
    except (FileNotFoundError, ModuleNotFoundError):
        return None


@lru_cache(maxsize=1)
def list_available_icons() -> tuple[str, ...]:
    """Return all bundled icon names (without the ``mdi:`` prefix), sorted."""
    folder = _mdi_dir()
    if folder is None:
        return ()
    names = sorted(p.stem for p in folder.glob("*.svg"))
    return tuple(names)


def icon_path(value: str | None) -> Path | None:
    """Resolve an icon identifier to the SVG path, or None if unknown."""
    short = icon_short_name(value)
    if short is None:
        return None
    folder = _mdi_dir()
    if folder is None:
        return None
    candidate = folder / f"{short}.svg"
    return candidate if candidate.exists() else None


def icon_label(value: str | None) -> str:
    short = icon_short_name(value)
    return short.replace("-", " ").title() if short else "(nessuna)"


def qicon_for(value: str | None, *, color: str | None = None, size: int = 64) -> Any:
    """Build a tinted ``QIcon`` for the given identifier.

    Imports PySide6 lazily so non-GUI surfaces (CLI, API) can still import
    this module. Returns an empty ``QIcon`` when PySide6 is unavailable or
    the icon is unknown.
    """
    from PySide6.QtGui import QIcon  # type: ignore[import-not-found]

    path = icon_path(value)
    if path is None:
        return QIcon()
    pixmap = _render_svg_pixmap(
        str(path),
        color=color or _default_icon_color(),
        size=size,
    )
    if pixmap is None:
        return QIcon(str(path))
    return QIcon(pixmap)


def _default_icon_color() -> str:
    try:
        from PySide6.QtGui import QPalette  # type: ignore[import-not-found]
        from PySide6.QtWidgets import QApplication  # type: ignore[import-not-found]
    except ImportError:
        return "#202020"

    app = QApplication.instance()
    if app is None:
        return "#202020"
    color = app.palette().color(QPalette.ColorRole.WindowText)
    if not color.isValid():
        return "#202020"
    return color.name()


@lru_cache(maxsize=512)
def _render_svg_pixmap(path_text: str, *, color: str, size: int) -> Any:
    """Render an MDI SVG to a tinted ``QPixmap``.

    Why: the bundled SVGs use ``fill="currentColor"`` so they have no real
    colour until we substitute one. We read the XML, replace the literal
    ``currentColor`` token, then hand the bytes to ``QSvgRenderer``.
    """
    try:
        from PySide6.QtCore import QByteArray, QSize, Qt  # type: ignore[import-not-found]
        from PySide6.QtGui import QImage, QPainter, QPixmap  # type: ignore[import-not-found]
        from PySide6.QtSvg import QSvgRenderer  # type: ignore[import-not-found]
    except ImportError:
        return None

    path = Path(path_text)
    fill = color
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    if "currentColor" in text:
        text = text.replace("currentColor", fill)
    data = QByteArray(text.encode("utf-8"))
    renderer = QSvgRenderer(data)
    if not renderer.isValid():
        return None
    image = QImage(QSize(size, size), QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    try:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        renderer.render(painter)
    finally:
        painter.end()
    return QPixmap.fromImage(image)


class IconPickerDialog:  # pragma: no cover - imported only when GUI dependencies exist
    """Grid dialog that lets the user pick an MDI icon by name or visual."""

    def __init__(
        self,
        parent: Any = None,
        *,
        current: str | None = None,
        color: str | None = None,
        names: Iterable[str] | None = None,
        title: str = "Scegli un'icona",
    ) -> None:
        from PySide6.QtCore import Qt, QTimer  # type: ignore[import-not-found]
        from PySide6.QtWidgets import (  # type: ignore[import-not-found]
            QDialog,
            QDialogButtonBox,
            QHBoxLayout,
            QLabel,
            QLineEdit,
            QListView,
            QListWidget,
            QListWidgetItem,
            QPushButton,
            QVBoxLayout,
        )

        self._qt = Qt
        self._initial: str | None = normalize_icon_name(current)
        self._selected: str | None = self._initial
        self._cleared = False
        self._color = color
        self._timer = QTimer
        self._icon_loaded: set[str] = set()
        self._pending_icon_refresh = False

        self.dialog = QDialog(parent)
        self.dialog.setWindowTitle(title)
        _set_xtray_window_icon(self.dialog)
        self.dialog.setMinimumSize(420, 460)

        layout = QVBoxLayout(self.dialog)

        search_row = QHBoxLayout()
        search_row.addWidget(QLabel("Filtra:"))
        self.search = QLineEdit()
        self.search.setPlaceholderText("nome icona, es. monitor")
        search_row.addWidget(self.search, 1)
        layout.addLayout(search_row)

        self.list = QListWidget()
        self.list.setViewMode(QListView.ViewMode.IconMode)
        self.list.setIconSize(self._qt_size(_PICKER_ICON_PIXELS))
        self.list.setGridSize(self._qt_size(_PICKER_GRID_PIXELS))
        self.list.setResizeMode(QListView.ResizeMode.Adjust)
        self.list.setMovement(QListView.Movement.Static)
        self.list.setUniformItemSizes(True)
        self.list.setWordWrap(False)
        self.list.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.list.setSpacing(8)
        layout.addWidget(self.list, 1)

        self._items: list[tuple[str, QListWidgetItem]] = []
        all_names = tuple(names) if names is not None else list_available_icons()
        for short_name in all_names:
            full = f"{ICON_NAME_PREFIX}{short_name}"
            item = QListWidgetItem(short_name)
            item.setData(Qt.ItemDataRole.UserRole, full)
            item.setSizeHint(self._qt_size(_PICKER_ITEM_PIXELS))
            item.setToolTip(short_name)
            self.list.addItem(item)
            self._items.append((short_name, item))

        if self._selected:
            for short_name, item in self._items:
                if f"{ICON_NAME_PREFIX}{short_name}" == self._selected:
                    self.list.setCurrentItem(item)
                    self._ensure_item_icon(short_name, item)
                    break

        self.clear_button = QPushButton("Rimuovi icona")
        self.clear_button.clicked.connect(self._on_clear)
        layout.addWidget(self.clear_button)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.dialog.reject)
        layout.addWidget(buttons)

        self.search.textChanged.connect(self._apply_filter)
        self.list.itemDoubleClicked.connect(lambda _i: self._on_accept())
        self.list.currentItemChanged.connect(lambda *_args: self._queue_visible_icon_refresh())
        self.list.verticalScrollBar().valueChanged.connect(
            lambda _value: self._queue_visible_icon_refresh()
        )
        self._queue_visible_icon_refresh()

    def __getattr__(self, name: str) -> Any:
        return getattr(self.dialog, name)

    def _qt_size(self, value: int) -> Any:
        from PySide6.QtCore import QSize  # type: ignore[import-not-found]

        return QSize(value, value)

    def _apply_filter(self, text: str) -> None:
        query = text.strip().lower()
        for short_name, item in self._items:
            item.setHidden(bool(query) and query not in short_name.lower())
        self._queue_visible_icon_refresh()

    def _queue_visible_icon_refresh(self) -> None:
        if self._pending_icon_refresh:
            return
        self._pending_icon_refresh = True
        self._timer.singleShot(0, self._refresh_visible_icons)

    def _refresh_visible_icons(self) -> None:
        self._pending_icon_refresh = False
        viewport = self.list.viewport().rect()
        current = self.list.currentItem()
        for short_name, item in self._items:
            if item.isHidden():
                continue
            if item is current or self.list.visualItemRect(item).intersects(viewport):
                self._ensure_item_icon(short_name, item)

    def _ensure_item_icon(self, short_name: str, item: Any) -> None:
        if short_name in self._icon_loaded:
            return
        item.setIcon(
            qicon_for(
                f"{ICON_NAME_PREFIX}{short_name}",
                color=self._color,
                size=_PICKER_ICON_PIXELS,
            )
        )
        self._icon_loaded.add(short_name)

    def _on_clear(self) -> None:
        self._cleared = True
        self._selected = None
        self.dialog.accept()

    def _on_accept(self) -> None:
        current = self.list.currentItem()
        if current is not None:
            value = current.data(self._qt.ItemDataRole.UserRole)
            if isinstance(value, str):
                self._selected = normalize_icon_name(value)
        self.dialog.accept()

    def selected_icon(self) -> str | None:
        if self.dialog.result() == 0 and not self._cleared:
            return self._initial
        return self._selected


class IconPickerButton:  # pragma: no cover - imported only when GUI dependencies exist
    """Compact widget that shows the current icon and opens the picker dialog."""

    def __init__(
        self,
        *,
        current: str | None = None,
        color: str | None = None,
        on_change: Callable[[str | None], None] | None = None,
        parent: Any = None,
    ) -> None:
        from PySide6.QtCore import QSize, Qt  # type: ignore[import-not-found]
        from PySide6.QtWidgets import QPushButton  # type: ignore[import-not-found]

        self._qt = Qt
        self._size = QSize(28, 28)
        self._color = color
        self.on_change = on_change
        self._value = normalize_icon_name(current)

        self.button = QPushButton(parent)
        self.button.setIconSize(self._size)
        self.button.setMinimumHeight(34)
        self.button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.button.clicked.connect(self._open_picker)
        self._refresh()

    def __getattr__(self, name: str) -> Any:
        return getattr(self.button, name)

    @property
    def widget(self) -> Any:
        return self.button

    def value(self) -> str | None:
        return self._value

    def set_value(self, value: str | None) -> None:
        self._value = normalize_icon_name(value)
        self._refresh()

    def set_color(self, color: str | None) -> None:
        self._color = color
        self._refresh()

    def _refresh(self) -> None:
        label = icon_label(self._value)
        self.button.setText(f"  {label}")
        if self._value is None:
            from PySide6.QtGui import QIcon  # type: ignore[import-not-found]

            self.button.setIcon(QIcon())
            self.button.setToolTip("Nessuna icona — clicca per scegliere")
        else:
            self.button.setIcon(qicon_for(self._value, color=self._color, size=48))
            self.button.setToolTip(f"{self._value} — clicca per cambiare")

    def _open_picker(self) -> None:
        picker = IconPickerDialog(
            parent=self.button.window(),
            current=self._value,
            color=self._color,
        )
        if not picker.exec():
            return
        new_value = picker.selected_icon()
        if new_value == self._value:
            return
        self._value = new_value
        self._refresh()
        if self.on_change is not None:
            self.on_change(self._value)
