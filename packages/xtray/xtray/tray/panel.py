"""The XTray tray panel: media/network tabs plus display, adapter, and drive popups."""
from __future__ import annotations

import textwrap
from typing import TYPE_CHECKING, Any

from xtray.core import icons
from xtray.core.theme import AppTheme

from .. import config, ha_rest
from ..audio_utils import active_audio_sources as _active_audio_sources
from ..audio_utils import same_audio_source as _same_audio_source
from ..core import app_logging
from ..core.gui import repolish
from ..services import DisplayService
from ..services.display import audio, display_inventory
from ..services.network import devices as network
from . import panel_network as _panel_network
from .chrome import (
    _clear_layout,
    _current_theme,
    _qicon_for_first,
)
from .constants import (
    _DISPLAY_POWER_BUTTON_WIDTH,
    _DISPLAY_TOGGLE_BUTTON_WIDTH,
    _MEDIA_ICON_PIXELS,
    _PROFILE_ICON_PIXELS,
)
from .formatting import _display_short_name
from .widgets import _volume_fill_bar_class

if TYPE_CHECKING:
    from PySide6.QtWidgets import QLabel, QPushButton


class TrayPanel:  # pragma: no cover - imported only when GUI dependencies exist
    def __init__(
        self,
        controller: Any,
        *,
        service: DisplayService | None = None,
        theme: AppTheme | None = None,
        tray_options: dict[str, Any] | None = None,
    ) -> None:
        from . import _layout_builder

        self.controller = controller
        self.service = service or DisplayService()
        self._theme = theme or _current_theme()
        self._tray_options = tray_options or config.get_tray_options()
        self._mqtt_enabled = True
        self._home_assistant_enabled = True
        self._media_icon_labels: list[tuple[Any, str, str]] = []
        self._refreshing_main_tabs: set[str] = set()
        self._active_profile_name: str | None = None
        _layout_builder.build(self)

        self._tab_widgets = {
            "media": (self.media_scroll, "tab.media"),
            "network": (self.network_tab, "tab.network"),
            "adapters": (self.adapters_tab, "tab.adapters"),
            "drives": (self.drives_tab, "tab.drives"),
        }

        self.profile_buttons: dict[str, Any] = {}
        self.profile_icons: dict[str, str | None] = {}
        self.empty_label: QLabel | None = None
        self.display_toggle_buttons: dict[str, QPushButton] = {}
        self.display_power_buttons: dict[str, QPushButton] = {}
        self.display_make_primary_buttons: dict[str, QPushButton] = {}
        self.display_empty_label: QLabel | None = None
        self.display_row_volume_controls: dict[str, dict[str, Any]] = {}
        self.network_ping_buttons: dict[str, QPushButton] = {}
        self.adapter_action_buttons: dict[int, dict[str, QPushButton]] = {}
        self.drive_open_buttons: dict[str, QPushButton] = {}
        self._busy = False
        self._refreshing_audio = False
        self._refreshing_pc_volume = False
        self._refreshing_display_volumes = False
        self._pc_volume_available = False
        self._pc_muted: bool | None = None
        self._pc_muted_available = False
        self.display_volume_controls: dict[str, dict[str, Any]] = {}
        self.display_volume_empty_label: QLabel | None = None
        self._active_display_context_menu: Any | None = None
        self._active_adapter_context_menu: Any | None = None
        self._wire_popup_trigger_state()
        self._wire_main_context_menu()
        self.apply_tray_options(self._tray_options)
        self.show_audio_loading()
        self.show_displays_loading()
        self.show_adapters_loading()
        self.show_drives_loading()
        self.show_network_loading()

    def _wire_popup_trigger_state(self) -> None:
        """Mirror each side popup's visibility on its header trigger button."""
        bindings = (
            (self.displays_popup, self.displays_popup_button),
            (self.adapters_popup, self.adapters_popup_button),
            (self.drives_popup, self.drives_popup_button),
        )
        self._popup_trigger_buttons = {popup: button for popup, button in bindings}
        for popup, button in bindings:
            popup.aboutToShow.connect(
                lambda b=button: self._set_popup_button_active(b, True)
            )
            popup.aboutToHide.connect(
                lambda b=button: self._set_popup_button_active(b, False)
            )
            self._set_popup_button_active(button, popup.isVisible())

    def _wire_main_context_menu(self) -> None:
        show_menu = getattr(self.controller, "show_tray_context_menu", None)
        if not callable(show_menu):
            return
        self._wire_context_menu(self.header, show_menu)

    @staticmethod
    def _wire_context_menu(widget: Any, handler: Any) -> None:
        from PySide6.QtCore import Qt  # type: ignore[import-not-found]

        widget.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        widget.customContextMenuRequested.connect(
            lambda pos, source=widget: handler(source.mapToGlobal(pos))
        )

    @staticmethod
    def _set_popup_button_active(button: Any, active: bool) -> None:
        if button is None:
            return
        button.setProperty("popupOpen", bool(active))
        repolish(button)

    def __getattr__(self, name: str) -> Any:
        return getattr(self.window, name)

    def _make_header_popup_button(
        self,
        object_name: str,
        action_id: str,
        handler: Any,
    ) -> Any:
        from PySide6.QtCore import Qt  # type: ignore[import-not-found]
        from PySide6.QtWidgets import QPushButton  # type: ignore[import-not-found]

        button = QPushButton()
        button.setObjectName(object_name)
        button.setProperty("iconOnlyButton", True)
        button.setProperty("trayPopupButton", True)
        button.setProperty("surfaceAction", "popup")
        button.setFixedSize(32, 30)
        button.setToolTip(self._action_label(action_id))
        button.setAccessibleName(self._action_label(action_id))
        button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        button.clicked.connect(handler)
        self._set_popup_button_icon(button, action_id)
        return button

    def apply_tray_options(self, options: dict[str, Any]) -> None:
        self._tray_options = config.normalize_tray_options(options)
        self._rebuild_visible_tabs()
        self._apply_media_row_order()
        self._reflow_profile_buttons()
        self.displays_popup_button.setVisible(self._tray_bool("show_displays_popup"))
        self.adapters_popup_button.setVisible(self._tray_bool("show_adapters_popup"))
        self.drives_popup_button.setVisible(self._tray_bool("show_drives_tab"))
        show_display_profiles = self._tray_bool("show_display_profiles")
        show_media_displays = self._tray_bool("show_media_displays")
        self._set_media_device_section_visible(
            "media_displays",
            show_display_profiles or show_media_displays,
        )
        self.display_profiles_block.setVisible(show_display_profiles)
        self.media_displays_faceplates_body.setVisible(show_media_displays)
        self._set_media_device_section_visible(
            "media_adapters",
            self._tray_bool("show_adapters_tab"),
        )
        self._set_media_device_section_visible(
            "media_drives",
            self._tray_bool("show_media_drives"),
        )
        self.pc_volume_row.setVisible(self._tray_bool("show_pc_volume"))
        self._set_media_device_section_visible(
            "media_audio_output",
            self._tray_bool("show_audio_output"),
        )
        self.display_volume_container.setVisible(
            self._tray_bool("show_display_volume")
            and bool(self.display_volume_controls)
        )
        self.ha_indicator.widget.setVisible(
            self._tray_bool("show_home_assistant_indicator")
            and self._home_assistant_enabled
        )
        self.mqtt_indicator.widget.setVisible(
            self._tray_bool("show_mqtt_indicator") and self._mqtt_enabled
        )
        self.options_button.setVisible(self._tray_bool("show_options_button"))
        self.network_manage_button.setVisible(
            self._tray_bool("show_network_manager_button")
        )
        self.computer_manager_button.setVisible(
            self._tray_bool("show_computer_manager_button")
        )
        self._sync_bottom_bar_visibility()
        self._refresh_action_icons()

    def apply_integration_options(self, settings: dict[str, Any]) -> None:
        self._mqtt_enabled = bool(settings.get("enabled"))
        self._home_assistant_enabled = bool(settings.get("home_assistant_enabled"))
        self.ha_indicator.widget.setVisible(
            self._tray_bool("show_home_assistant_indicator")
            and self._home_assistant_enabled
        )
        self.mqtt_indicator.widget.setVisible(
            self._tray_bool("show_mqtt_indicator") and self._mqtt_enabled
        )
        self._sync_bottom_bar_visibility()

    def _rebuild_visible_tabs(self) -> None:
        current_widget = self.tabs.currentWidget()
        current_key = self._tab_key_for_widget(current_widget)
        fallback_was_active = current_widget is self.fallback_tab
        target_index: int | None = None
        while self.tabs.count():
            self.tabs.removeTab(0)
        any_visible = False
        option_keys = {
            "media": "show_media_tab",
            "network": "show_network_tab",
            "adapters": "show_adapters_tab",
            "drives": "show_drives_tab",
        }
        for key in ("media", "network", "adapters", "drives"):
            if not self._tray_bool(option_keys[key]):
                continue
            widget, action_id = self._tab_widgets[key]
            index = self.tabs.addTab(widget, "")
            self._apply_main_tab_icon(index, action_id, key=key)
            if current_key == key:
                target_index = index
            any_visible = True
        if not any_visible:
            self.tabs.addTab(self.fallback_tab, "Options")
            if fallback_was_active:
                target_index = 0
        if target_index is not None:
            self.tabs.setCurrentIndex(target_index)

    def _tab_key_for_widget(self, widget: Any) -> str | None:
        if not hasattr(self, "_tab_widgets"):
            return None
        for key, (tab_widget, _action_id) in self._tab_widgets.items():
            if widget is tab_widget:
                return key
        return None

    def _tab_key_for_index(self, index: int) -> str | None:
        if not hasattr(self, "tabs") or not 0 <= index < self.tabs.count():
            return None
        return self._tab_key_for_widget(self.tabs.widget(index))

    def on_main_tab_changed(self, index: int) -> None:
        tab_key = self._tab_key_for_index(index)
        if tab_key is None:
            return
        handler = getattr(self.controller, "on_tray_tab_changed", None)
        if callable(handler):
            handler(tab_key)

    def _tray_bool(self, key: str) -> bool:
        return bool(self._tray_options.get(key, config.default_tray_options()[key]))

    def _media_profile_columns(self) -> int:
        return int(self._tray_options.get("media_profile_columns", 3))

    def _display_grid_columns(self) -> int:
        return int(self._tray_options.get("display_grid_columns", 2))

    def _media_row_order(self) -> list[str]:
        widgets = getattr(self, "_media_row_widgets", {})
        order = self._tray_options.get("media_row_order")
        if not isinstance(order, list):
            order = config.default_tray_options()["media_row_order"]
        normalized: list[str] = []
        for item in order:
            row_id = str(item)
            if row_id in widgets and row_id not in normalized:
                normalized.append(row_id)
        for row_id in config.default_tray_options()["media_row_order"]:
            if row_id in widgets and row_id not in normalized:
                normalized.append(row_id)
        return normalized

    def _apply_media_row_order(self) -> None:
        widgets = getattr(self, "_media_row_widgets", {})
        for row_id in self._media_row_order():
            widget = widgets.get(row_id)
            if widget is None:
                continue
            self.media_layout.removeWidget(widget)
            self.media_layout.addWidget(widget)

    def _sync_profile_button_columns(self) -> int:
        columns = self._media_profile_columns()
        for column in range(8):
            self.button_layout.setColumnStretch(column, 1 if column < columns else 0)
        return columns

    def _detach_profile_button_layout_items(self) -> None:
        while self.button_layout.count():
            self.button_layout.takeAt(0)

    def _reflow_profile_buttons(self) -> None:
        buttons = list(getattr(self, "profile_buttons", {}).values())
        empty_label = getattr(self, "empty_label", None)
        if not buttons and empty_label is None:
            return
        self._detach_profile_button_layout_items()
        columns = self._sync_profile_button_columns()
        if empty_label is not None and not buttons:
            self.button_layout.addWidget(empty_label, 0, 0, 1, columns)
            return
        for index, button in enumerate(buttons):
            row, column = divmod(index, columns)
            self.button_layout.addWidget(button, row, column)

    def _set_media_device_section_visible(self, row_id: str, visible: bool) -> None:
        section = getattr(self, "_media_device_sections", {}).get(row_id)
        if section is None:
            return
        section["section"].setVisible(bool(visible))
        self._sync_media_device_section_expanded(row_id)

    def _set_media_device_section_expanded(self, row_id: str, expanded: bool) -> None:
        collapsed = getattr(self, "_collapsed_media_device_sections", set())
        if expanded:
            collapsed.discard(row_id)
        else:
            collapsed.add(row_id)
        self._collapsed_media_device_sections = collapsed
        self._sync_media_device_section_expanded(row_id)

    def _sync_media_device_section_expanded(self, row_id: str) -> None:
        section = getattr(self, "_media_device_sections", {}).get(row_id)
        if section is None:
            return
        expanded = row_id not in getattr(self, "_collapsed_media_device_sections", set())
        header = section["header"]
        body = section["body"]
        if header.isChecked() != expanded:
            was_blocked = header.blockSignals(True)
            try:
                header.setChecked(expanded)
            finally:
                header.blockSignals(was_blocked)
        header.setProperty("expanded", expanded)
        body.setVisible(expanded and not section["section"].isHidden())
        repolish(header)
        self._refresh_media_device_section_icon(section)

    def _sync_bottom_bar_visibility(self) -> None:
        widgets = (
            self.mqtt_indicator.widget,
            self.ha_indicator.widget,
            self.options_button,
            self.network_manage_button,
            self.computer_manager_button,
        )
        self.bottom_bar.setVisible(any(not widget.isHidden() for widget in widgets))

    def _action_icon(self, action_id: str) -> dict[str, str]:
        return config.tray_action_icon(self._tray_options, action_id)

    def _action_label(self, action_id: str) -> str:
        return self._action_icon(action_id)["label"]

    def _action_icon_name(self, action_id: str) -> str:
        return self._action_icon(action_id)["icon"]

    def _fallback_label(self, action_id: str) -> str:
        return self._action_icon(action_id)["fallback_label"]

    def _icon_color_for_button(self, button: Any) -> str:
        role = ""
        try:
            role = str(button.property("role") or "")
        except Exception:
            role = ""
        try:
            surface_action = str(button.property("surfaceAction") or "")
        except Exception:
            surface_action = ""
        try:
            profile_state = str(button.property("profileState") or "")
        except Exception:
            profile_state = ""
        if profile_state == "active":
            return self._theme.tray.faceplate_primary_text
        if profile_state == "missing":
            return self._theme.tray.faceplate_disabled_text
        if surface_action == "popup":
            return self._theme.tray.accent_text
        if surface_action == "window":
            return self._theme.tray.accent_text
        try:
            display_state = str(button.property("displayState") or "")
        except Exception:
            display_state = ""
        if display_state == "on":
            return self._theme.tray.success_text
        if display_state == "off":
            return self._theme.tray.warning_text
        if role == "primary":
            return self._theme.tray.accent_text
        return self._theme.tray.text

    def _apply_action_button_icon(
        self,
        button: Any,
        action_id: str,
        *,
        color: str | None = None,
        icon_size: int = 18,
    ) -> None:
        from PySide6.QtCore import QSize  # type: ignore[import-not-found]
        from PySide6.QtGui import QIcon  # type: ignore[import-not-found]

        action = self._action_icon(action_id)
        button.setToolTip(action["label"])
        button.setAccessibleName(action["label"])
        icon = _qicon_for_first(
            (action["icon"],),
            color=color if color is not None else self._icon_color_for_button(button),
            size=48,
        )
        button.setIconSize(QSize(icon_size, icon_size))
        if icon.isNull():
            button.setIcon(QIcon())
            button.setText(action["fallback_label"])
            return
        button.setText("")
        button.setIcon(icon)

    def _refresh_action_icons(self) -> None:
        if not hasattr(self, "header"):
            return
        text_color = self._theme.tray.text
        self._apply_action_button_icon(
            self.computer_manager_button,
            "header.computer_manager",
        )
        hide_action = self._action_icon("header.hide")
        self.hide_button.setToolTip(hide_action["label"])
        self.hide_button.setAccessibleName(hide_action["label"])
        self.header.set_close_icon_color(self._theme.tray.accent)
        self._set_displays_popup_button_icon()
        self._set_popup_button_icon(self.adapters_popup_button, "adapter.popup")
        self._set_popup_button_icon(self.drives_popup_button, "drive.popup")
        self._apply_action_button_icon(
            self.displays_refresh_button,
            "display.refresh",
            color=text_color,
        )
        self._apply_action_button_icon(
            self.network_manage_button,
            "network.manage",
        )
        self._apply_action_button_icon(
            self.adapters_refresh_button,
            "adapter.refresh",
            color=text_color,
        )
        self._apply_action_button_icon(
            self.adapters_network_connections_button,
            "adapter.network_connections",
        )
        self._apply_action_button_icon(
            self.drives_refresh_button,
            "drive.refresh",
            color=text_color,
        )
        self._apply_action_button_icon(
            self.drives_add_button,
            "drive.add_network",
        )
        self._apply_action_button_icon(
            self.options_button,
            "fallback.options",
        )
        self._apply_action_button_icon(
            self.fallback_options_button,
            "fallback.options",
        )
        self._apply_main_tab_icons()
        self._refresh_media_device_section_icons()
        self.audio_combo.setToolTip(self._action_label("media.audio_output"))
        self.pc_volume_slider.setToolTip(self._action_label("media.pc_volume"))

    def hide(self) -> None:
        self._hide_popups()
        self.window.hide()

    def close(self) -> bool:
        self._hide_popups()
        self.displays_popup.close()
        self.adapters_popup.close()
        self.drives_popup.close()
        return bool(self.window.close())

    _SIDE_POPUP_CASCADE_STEP = 24

    def _side_popups(self) -> tuple[Any, ...]:
        return (self.displays_popup, self.adapters_popup, self.drives_popup)

    def _hide_popups(self, *, except_popup: Any | None = None) -> None:
        for popup in self._side_popups():
            if popup is except_popup:
                continue
            popup.hide()

    def toggle_displays_popup(self) -> None:
        if self.displays_popup.isVisible():
            self.displays_popup.hide()
            return
        self.show_displays_popup()

    def show_displays_popup(self) -> None:
        self.on_displays_refresh_clicked()
        self._position_side_popup(self.displays_popup)
        self.displays_popup.show()
        self.displays_popup.raise_()
        self.displays_popup.activateWindow()

    def toggle_adapters_popup(self) -> None:
        if self.adapters_popup.isVisible():
            self.adapters_popup.hide()
            return
        self.show_adapters_popup()

    def show_adapters_popup(self) -> None:
        self.on_adapters_refresh_clicked()
        self._position_side_popup(self.adapters_popup)
        self.adapters_popup.show()
        self.adapters_popup.raise_()
        self.adapters_popup.activateWindow()

    def toggle_drives_popup(self) -> None:
        if self.drives_popup.isVisible():
            self.drives_popup.hide()
            return
        self.show_drives_popup()

    def show_drives_popup(self) -> None:
        self.on_drives_refresh_clicked()
        self._position_side_popup(self.drives_popup)
        self.drives_popup.show()
        self.drives_popup.raise_()
        self.drives_popup.activateWindow()

    def _position_side_popup(self, popup: Any) -> None:
        from PySide6.QtGui import QGuiApplication  # type: ignore[import-not-found]

        if popup.has_user_geometry():
            return
        panel_rect = self.window.frameGeometry()
        screen = QGuiApplication.screenAt(panel_rect.center()) or QGuiApplication.primaryScreen()
        if screen is None:
            return
        rect = screen.availableGeometry()
        popup.adjustSize()
        size_hint = popup.sizeHint()
        width = self._side_popup_open_width(rect)
        height = min(
            max(popup.minimumHeight(), size_hint.height()),
            max(popup.minimumHeight(), int(rect.height() * 0.85)),
        )
        popup.resize(width, height)
        margin = 8
        base_x = panel_rect.left() - width - margin
        base_y = panel_rect.top()
        offset_index = self._cascade_offset_index(popup)
        step = self._SIDE_POPUP_CASCADE_STEP * offset_index
        x = base_x + step
        y = base_y + step
        if x + width > rect.right():
            x = rect.right() - width
        if x < rect.left():
            x = min(panel_rect.left(), rect.right() - width)
        if y + height > rect.bottom():
            y = rect.bottom() - height
        popup.move(max(rect.left(), x), max(rect.top(), y))

    def _side_popup_open_width(self, available_rect: Any) -> int:
        panel_width = self.window.frameGeometry().width()
        if not self.window.isVisible():
            panel_width = self.window.width() or self.window.sizeHint().width()
        if panel_width <= 0:
            panel_width = self.window.sizeHint().width()
        target_width = max(self.window.minimumWidth(), panel_width)
        return min(target_width, max(1, available_rect.width()))

    def _cascade_offset_index(self, popup: Any) -> int:
        """Return how many already-visible side popups should offset ``popup``."""
        index = 0
        for other in self._side_popups():
            if other is popup:
                continue
            if other.isVisible():
                index += 1
        return index

    def set_theme(self, theme: AppTheme) -> None:
        self._theme = theme
        self._apply_theme()
        self._refresh_action_icons()
        self._refresh_media_icons()
        self._refresh_profile_button_icons()
        self._apply_network_kind_tab_icons()
        self._refresh_volume_bar_colors()

    def _refresh_volume_bar_colors(self) -> None:
        bar = getattr(self, "pc_volume_slider", None)
        if bar is not None and hasattr(bar, "setColors"):
            bar.setColors(
                self._theme.tray.subtle_border,
                self._theme.tray.accent,
                self._theme.tray.muted,
            )
        button = getattr(self, "pc_volume_mute_button", None)
        if button is not None:
            self._apply_volume_mute_button_icon(
                button,
                self._pc_muted,
                self._pc_volume_state_text(
                    self.pc_volume_slider.value()
                    if getattr(self, "_pc_volume_available", False)
                    else None,
                    self._pc_muted,
                ),
            )
        for control in getattr(self, "display_volume_controls", {}).values():
            button = control.get("mute_button")
            if button is not None:
                self._apply_volume_mute_button_icon(
                    button,
                    control.get("muted"),
                    self._display_row_volume_state_text(
                        str(control.get("control_label") or "Display volume"),
                        control.get("percent"),
                        control.get("muted"),
                    ),
                )
        for control in getattr(self, "display_row_volume_controls", {}).values():
            button = control.get("mute_button")
            if button is not None:
                self._apply_display_row_mute_button_icon(
                    button,
                    control.get("muted"),
                    self._display_row_volume_state_text(
                        str(control.get("control_label") or "Display volume"),
                        control.get("percent"),
                        control.get("muted"),
                        unavailable_reason=control.get("unavailable_reason"),
                    ),
                )

    def _apply_theme(self) -> None:
        # Use TrayPopupWindow.set_theme — it applies the stylesheet AND
        # propagates the surface color to the drag-background frame
        # (paintEvent paints it directly; the popup itself is
        # WA_TranslucentBackground and would otherwise be invisible).
        self.window.set_theme(self._theme)
        if hasattr(self, "displays_popup"):
            self.displays_popup.set_theme(self._theme)
        if hasattr(self, "adapters_popup"):
            self.adapters_popup.set_theme(self._theme)
        if hasattr(self, "drives_popup"):
            self.drives_popup.set_theme(self._theme)
        if hasattr(self, "mqtt_indicator"):
            self.mqtt_indicator.set_theme(self._theme)
        if hasattr(self, "ha_indicator"):
            self.ha_indicator.set_theme(self._theme)

    def _set_displays_popup_button_icon(self) -> None:
        self._set_popup_button_icon(
            getattr(self, "displays_popup_button", None),
            "display.popup",
        )

    def _set_popup_button_icon(self, button: Any | None, action_id: str) -> None:
        from PySide6.QtCore import QSize  # type: ignore[import-not-found]
        from PySide6.QtGui import QIcon  # type: ignore[import-not-found]

        if button is None:
            return
        action = self._action_icon(action_id)
        button.setToolTip(action["label"])
        button.setAccessibleName(action["label"])
        icon = _qicon_for_first(
            (action["icon"],),
            color=self._icon_color_for_button(button),
            size=48,
        )
        button.setIconSize(QSize(18, 18))
        if icon.isNull():
            button.setIcon(QIcon())
            button.setText(action["fallback_label"])
            return
        button.setText("")
        button.setIcon(icon)

    def _make_media_icon_label(
        self,
        action_id: str,
        tooltip: str | None = None,
        *,
        track_theme: bool = True,
    ) -> Any:
        from PySide6.QtCore import Qt  # type: ignore[import-not-found]
        from PySide6.QtWidgets import QLabel  # type: ignore[import-not-found]

        label = QLabel()
        label.setObjectName("trayMediaControlIcon")
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setFixedSize(_MEDIA_ICON_PIXELS + 6, 32)
        tooltip = tooltip or self._action_label(action_id)
        label.setToolTip(tooltip)
        label.setAccessibleName(tooltip)
        if track_theme:
            self._media_icon_labels.append((label, action_id, tooltip))
        self._apply_media_icon(label, action_id, tooltip)
        return label

    def _apply_media_icon(
        self,
        label: Any,
        action_id: str,
        tooltip: str,
    ) -> None:
        from PySide6.QtCore import QSize  # type: ignore[import-not-found]

        label.setToolTip(tooltip)
        label.setAccessibleName(tooltip)
        icon = _qicon_for_first(
            (self._action_icon_name(action_id),),
            color=self._theme.tray.text,
            size=48,
        )
        if icon.isNull():
            label.clear()
            return
        label.setPixmap(icon.pixmap(QSize(_MEDIA_ICON_PIXELS, _MEDIA_ICON_PIXELS)))

    def _refresh_media_icons(self) -> None:
        active_labels = []
        for label, action_id, tooltip in getattr(self, "_media_icon_labels", []):
            try:
                self._apply_media_icon(label, action_id, tooltip)
            except RuntimeError:
                continue
            active_labels.append((label, action_id, tooltip))
        self._media_icon_labels = active_labels

    def _refresh_profile_button_icons(self) -> None:
        for name, button in self.profile_buttons.items():
            icon_name = self.profile_icons.get(name) or self._action_icon_name(
                "profile.fallback"
            )
            icon = _qicon_for_first(
                (icon_name,),
                color=self._icon_color_for_button(button),
                size=48,
            )
            if not icon.isNull():
                button.setIcon(icon)

    def _apply_network_kind_tab_icons(self) -> None:
        if not hasattr(self, "network_kind_tabs"):
            return
        text_color = self._theme.tray.text
        for index, kind in enumerate(network.DEVICE_KINDS):
            icon_name = self._action_icon_name(f"network.kind.{kind}")
            icon = icons.qicon_for(icon_name, color=text_color, size=48)
            if not icon.isNull():
                self.network_kind_tabs.setTabIcon(index, icon)

    def _apply_main_tab_icons(self) -> None:
        if not hasattr(self, "tabs"):
            return
        for index in range(self.tabs.count()):
            widget = self.tabs.widget(index)
            for key, (tab_widget, action_id) in self._tab_widgets.items():
                if widget is tab_widget:
                    self._apply_main_tab_icon(index, action_id, key=key)
                    break

    def _apply_main_tab_icon(
        self,
        index: int,
        action_id: str,
        *,
        key: str | None = None,
    ) -> None:
        tab_key = key or self._tab_key_for_index(index)
        color = (
            self._theme.tray.accent
            if tab_key in getattr(self, "_refreshing_main_tabs", set())
            else self._theme.tray.text
        )
        icon = icons.qicon_for(
            self._action_icon_name(action_id),
            color=color,
            size=48,
        )
        if not icon.isNull():
            self.tabs.setTabIcon(index, icon)
        self.tabs.setTabText(index, "")
        self.tabs.setTabToolTip(index, self._action_label(action_id))

    def set_main_tab_refreshing(self, tab_key: str, refreshing: bool) -> None:
        key = str(tab_key)
        if refreshing:
            self._refreshing_main_tabs.add(key)
        else:
            self._refreshing_main_tabs.discard(key)
        for index in range(self.tabs.count()):
            if self._tab_key_for_index(index) != key:
                continue
            _widget, action_id = self._tab_widgets[key]
            self._apply_main_tab_icon(index, action_id, key=key)
            break

    def _refresh_media_device_section_icon(self, section: dict[str, Any]) -> None:
        from PySide6.QtCore import QSize  # type: ignore[import-not-found]
        from PySide6.QtGui import QIcon  # type: ignore[import-not-found]

        header = section.get("header")
        action_id = str(section.get("action_id") or "")
        if header is None or not action_id:
            return
        action = self._action_icon(action_id)
        header.setToolTip(action["label"])
        header.setAccessibleName(action["label"])
        try:
            expanded = bool(header.property("expanded"))
        except Exception:
            expanded = bool(header.isChecked())
        color = self._theme.tray.accent_text if expanded else self._theme.tray.text
        icon = _qicon_for_first(
            (action["icon"],),
            color=color,
            size=48,
        )
        header.setIconSize(QSize(18, 18))
        header.setIcon(QIcon() if icon.isNull() else icon)

    def _refresh_media_device_section_icons(self) -> None:
        for section in getattr(self, "_media_device_sections", {}).values():
            self._refresh_media_device_section_icon(section)

    def refresh_active_profile(self) -> None:
        detector = getattr(self.service, "detect_current_favorite_profile", None)
        if not callable(detector):
            self.set_active_profile(None)
            return
        try:
            active_name = detector(self.profile_buttons.keys())
        except Exception:
            app_logging.get_logger("tray").exception(
                "failed to detect active display profile"
            )
            active_name = None
        self.set_active_profile(active_name)

    def set_active_profile(self, name: str | None) -> None:
        active_name = str(name) if name else None
        self._active_profile_name = active_name
        missing = self._fetch_profile_missing_map()
        for profile_name, button in list(self.profile_buttons.items()):
            try:
                is_active = profile_name == active_name
                has_missing = bool(missing.get(profile_name, False))
                button.setProperty("activeProfile", is_active)
                if has_missing:
                    state = "missing"
                elif is_active:
                    state = "active"
                else:
                    state = ""
                button.setProperty("profileState", state)
                repolish(button)
            except RuntimeError:
                continue
        self._refresh_profile_button_icons()

    def _fetch_profile_missing_map(self) -> dict[str, bool]:
        fetcher = getattr(self.service, "profiles_missing_displays", None)
        if not callable(fetcher):
            return {}
        try:
            return dict(fetcher(self.profile_buttons.keys()))
        except Exception:
            app_logging.get_logger("tray").exception(
                "failed to check profile display availability"
            )
            return {}

    def _set_media_control_state(
        self,
        icon_label: Any,
        control: Any,
        state_text: str,
    ) -> None:
        icon_label.setToolTip(state_text)
        icon_label.setAccessibleName(state_text)
        control.setToolTip(state_text)

    def _audio_source_labels(
        self,
        sources: list[audio.AudioSource],
    ) -> dict[audio.AudioSource, str]:
        labeler = getattr(self.service, "audio_source_labels", None)
        if not callable(labeler):
            return {}
        try:
            return dict(labeler(sources))
        except Exception:
            app_logging.get_logger("tray").exception("failed to label audio sources")
            return {}

    def _audio_source_combo_label(
        self,
        source: audio.AudioSource,
        source_labels: dict[audio.AudioSource, str],
    ) -> str:
        return source_labels.get(source) or source.label()

    def show_profiles_loading(self) -> None:
        from PySide6.QtCore import Qt  # type: ignore[import-not-found]
        from PySide6.QtWidgets import QLabel  # type: ignore[import-not-found]

        _clear_layout(self.button_layout)
        self.profile_buttons = {}
        self.profile_icons = {}
        self.empty_label = QLabel("Loading display profiles...")
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.button_layout.addWidget(
            self.empty_label,
            0,
            0,
            1,
            self._sync_profile_button_columns(),
        )
        self.set_status("")

    def refresh_profiles(self) -> None:
        self.apply_profile_icon_map(self.service.list_favorite_profile_icons())

    def apply_profile_icon_map(
        self,
        icon_map: dict[str, str | None],
        *,
        error: str | None = None,
    ) -> None:
        from PySide6.QtCore import QSize, Qt  # type: ignore[import-not-found]
        from PySide6.QtWidgets import (  # type: ignore[import-not-found]
            QLabel,
            QSizePolicy,
            QToolButton,
        )

        _clear_layout(self.button_layout)
        self.profile_buttons = {}
        self.profile_icons = {}
        self.empty_label = None
        columns = self._sync_profile_button_columns()
        names = list(icon_map.keys())
        if not names:
            self.empty_label = QLabel(
                "Display profiles unavailable" if error else "No favorite profiles"
            )
            self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.button_layout.addWidget(
                self.empty_label,
                0,
                0,
                1,
                columns,
            )
            self.set_status(error or "Mark profiles as favorites in the full GUI.")
            return
        for index, name in enumerate(names):
            button = QToolButton()
            button.setObjectName("trayProfileButton")
            button.setText(name)
            button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
            button.setIconSize(QSize(_PROFILE_ICON_PIXELS, _PROFILE_ICON_PIXELS))
            button.setMinimumSize(84, 62)
            button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            button.setProperty("role", "primary")
            button.setProperty("activeProfile", name == self._active_profile_name)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setToolTip(name)
            icon_name = icon_map.get(name)
            self.profile_icons[name] = icon_name
            icon = _qicon_for_first(
                (icon_name or self._action_icon_name("profile.fallback"),),
                color=self._icon_color_for_button(button),
                size=48,
            )
            if not icon.isNull():
                button.setIcon(icon)
            button.clicked.connect(
                lambda _checked=False, profile_name=name: self._apply(profile_name)
            )
            self.profile_buttons[name] = button
            row, column = divmod(index, columns)
            self.button_layout.addWidget(button, row, column)
        self.set_busy(self._busy)
        self.set_status("")
        # set_active_profile may have arrived before the buttons existed
        # (PROFILES and ACTIVE_PROFILE load concurrently). Re-apply so the
        # profileState property — which drives the QSS highlight and icon
        # color — is set on the freshly built buttons.
        if self._active_profile_name is not None:
            self.set_active_profile(self._active_profile_name)

    _MEDIA_DEVICE_FACEPLATE_COLUMNS = 2
    _MEDIA_DEVICE_COLUMN_BUDGET = 16
    _MEDIA_DISPLAY_BUTTON_MIN_WIDTH = 84
    _MEDIA_DISPLAY_BUTTON_MIN_HEIGHT = 62

    def _media_device_faceplate_columns(self, row_id: str) -> int:
        if row_id == "media_displays":
            return 8
        return self._MEDIA_DEVICE_FACEPLATE_COLUMNS

    def _set_media_device_layout_columns(
        self,
        layout: Any,
        row_id: str,
        *,
        columns: int | None = None,
    ) -> int:
        columns = int(columns or self._media_device_faceplate_columns(row_id))
        budget = max(self._MEDIA_DEVICE_COLUMN_BUDGET, columns + 1)
        for column in range(budget):
            stretch = 1 if column < columns else 0
            layout.setColumnStretch(column, stretch)
            layout.setColumnMinimumWidth(column, 0)
        return columns

    def _set_media_device_section_message(self, row_id: str, message: str) -> None:
        from PySide6.QtCore import Qt  # type: ignore[import-not-found]
        from PySide6.QtWidgets import QLabel  # type: ignore[import-not-found]

        section = getattr(self, "_media_device_sections", {}).get(row_id)
        if section is None:
            return
        layout = section["layout"]
        _clear_layout(layout)
        columns = self._set_media_device_layout_columns(layout, row_id)
        label = QLabel(message)
        label.setObjectName("trayPanelStatus")
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setWordWrap(True)
        layout.addWidget(label, 0, 0, 1, columns)

    def _render_media_device_faceplates(
        self,
        row_id: str,
        faceplates: list[dict[str, Any]],
        *,
        empty_message: str,
        popup_handler: Any,
    ) -> None:
        from PySide6.QtCore import QSize, Qt  # type: ignore[import-not-found]
        from PySide6.QtWidgets import QPushButton, QSizePolicy  # type: ignore[import-not-found]

        section = getattr(self, "_media_device_sections", {}).get(row_id)
        if section is None:
            return
        layout = section["layout"]
        _clear_layout(layout)
        if not faceplates:
            self._set_media_device_section_message(row_id, empty_message)
            return
        display_faceplates = row_id == "media_displays"
        columns = self._set_media_device_layout_columns(
            layout,
            row_id,
            columns=len(faceplates) if display_faceplates else None,
        )
        for index, spec in enumerate(faceplates):
            title = str(spec.get("title") or "")
            detail = str(spec.get("detail") or "")
            state = str(spec.get("state") or "unavailable")
            device_kind = str(spec.get("device_kind") or "")
            button = QPushButton("\n".join(part for part in (title, detail) if part))
            button.setObjectName("trayMediaDeviceFaceplate")
            button.setProperty("deviceStatus", state)
            if display_faceplates:
                button.setProperty("deviceKind", "display")
            elif device_kind:
                button.setProperty("deviceKind", device_kind)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            if display_faceplates:
                button.setMinimumSize(
                    self._MEDIA_DISPLAY_BUTTON_MIN_WIDTH,
                    self._MEDIA_DISPLAY_BUTTON_MIN_HEIGHT,
                )
                button.setSizePolicy(
                    QSizePolicy.Policy.Expanding,
                    QSizePolicy.Policy.Fixed,
                )
            else:
                button.setMinimumHeight(54)
                button.setSizePolicy(
                    QSizePolicy.Policy.Expanding,
                    QSizePolicy.Policy.Fixed,
                )
            tooltip = f"{title}: {detail}" if detail else title
            button.setToolTip(tooltip)
            button.setAccessibleName(tooltip)
            icon_name = icons.normalize_icon_name(spec.get("icon"))
            if icon_name:
                icon = icons.qicon_for(
                    icon_name,
                    color=self._media_faceplate_icon_color(state),
                    size=48,
                )
                if not icon.isNull():
                    button.setIconSize(QSize(22, 22))
                    button.setIcon(icon)
            spec_handler = spec.get("handler")
            target_handler = spec_handler if callable(spec_handler) else popup_handler
            button.clicked.connect(
                lambda _checked=False, handler=target_handler: handler()
            )
            context_handler = spec.get("context_handler")
            if callable(context_handler):
                self._wire_context_menu(button, context_handler)
            if display_faceplates:
                row, column = 0, index
            else:
                row, column = divmod(index, columns)
            layout.addWidget(button, row, column)
        remainder = len(faceplates) % columns
        if remainder and not display_faceplates:
            spacer_column = columns - 1
            layout.setColumnStretch(spacer_column, 1)

    def _media_faceplate_icon_color(self, state: str) -> str:
        if state == "primary":
            return self._theme.tray.faceplate_primary_text
        if state in {"enabled", "active", "ok"}:
            return self._theme.tray.faceplate_enabled_text
        if state in {"limited", "warning", "disabled"}:
            return self._theme.tray.faceplate_disabled_text
        if state in {"full", "disconnected"}:
            return self._theme.palette.danger_text
        if state == "unavailable":
            return self._theme.tray.faceplate_unavailable_text
        return self._theme.tray.text

    def _update_media_display_faceplates(
        self,
        items: list[Any],
        *,
        error: str | None = None,
    ) -> None:
        if not items:
            self._set_media_device_section_message(
                "media_displays",
                "Displays unavailable" if error else "No displays",
            )
            return
        specs = []
        enabled_count = sum(1 for entry in items if getattr(entry, "enabled", False))
        for item in items:
            state, state_text = _display_status(item)
            detail = state_text
            specs.append(
                {
                    "title": _compact_display_title(_display_item_title(item)),
                    "detail": detail,
                    "state": state,
                    "context_handler": lambda global_pos, current=item, count=enabled_count: (
                        self._show_display_context_menu(current, count, global_pos)
                    ),
                }
            )
        self._render_media_device_faceplates(
            "media_displays",
            specs,
            empty_message="No displays",
            popup_handler=self.show_displays_popup,
        )

    def _wire_display_context_menu(
        self,
        widget: Any,
        item: Any,
        enabled_count: int,
    ) -> None:
        self._wire_context_menu(
            widget,
            lambda global_pos, current=item, count=enabled_count: (
                self._show_display_context_menu(current, count, global_pos)
            ),
        )

    def _show_display_context_menu(
        self,
        item: Any,
        enabled_count: int,
        global_pos: Any,
    ) -> None:
        menu = self._build_display_context_menu(item, enabled_count)
        self._active_display_context_menu = menu
        menu.popup(global_pos)

    def _build_display_context_menu(self, item: Any, enabled_count: int) -> Any:
        from PySide6.QtWidgets import QMenu  # type: ignore[import-not-found]

        menu = QMenu(self.window)
        enabled = bool(getattr(item, "enabled", False))
        toggle_action_id = "display.disable" if enabled else "display.enable"
        toggle_available = _display_toggle_available(item)
        if enabled and enabled_count <= 1:
            toggle_available = False

        toggle_action = self._add_display_context_action(
            menu,
            toggle_action_id,
            lambda _checked=False, current=item: self.on_display_toggle(current),
        )
        toggle_action.setEnabled(not self._busy and toggle_available)
        if enabled and enabled_count <= 1:
            toggle_action.setToolTip("Cannot disable the only active display")

        display_state = getattr(item, "display", None)
        is_primary = bool(getattr(display_state, "primary", False)) and enabled
        if enabled and not is_primary:
            self._add_display_context_action(
                menu,
                "display.make_primary",
                lambda _checked=False, current=item: self.on_display_make_primary(current),
                enabled=not self._busy,
            )
        return menu

    def _add_display_context_action(
        self,
        menu: Any,
        action_id: str,
        handler: Any,
        *,
        enabled: bool = True,
    ) -> Any:
        icon = _qicon_for_first(
            (self._action_icon_name(action_id),),
            color=self._theme.tray.text,
            size=48,
        )
        action = menu.addAction(self._action_label(action_id))
        if not icon.isNull():
            action.setIcon(icon)
        action.setEnabled(enabled)
        action.triggered.connect(handler)
        return action

    def _show_adapter_context_menu(self, adapter: Any, global_pos: Any) -> None:
        menu = self._build_adapter_context_menu(adapter)
        self._active_adapter_context_menu = menu
        menu.popup(global_pos)

    def _build_adapter_context_menu(self, adapter: Any) -> Any:
        from PySide6.QtWidgets import QMenu  # type: ignore[import-not-found]

        menu = QMenu(self.window)
        enabled = bool(getattr(adapter, "enabled", False))
        toggle_action_id = "adapter.disable" if enabled else "adapter.enable"
        self._add_display_context_action(
            menu,
            toggle_action_id,
            lambda _checked=False, current=adapter: self.on_adapter_toggle(current),
            enabled=not self._busy,
        )
        self._add_display_context_action(
            menu,
            "adapter.properties",
            lambda _checked=False, current=adapter: self.on_adapter_properties(current),
            enabled=not self._busy,
        )
        return menu

    def _configured_adapter_icons(self) -> dict[str, str]:
        raw = self._tray_options.get("adapter_icons")
        if not isinstance(raw, dict):
            return {}
        return {
            str(name): icon
            for name, value in raw.items()
            if (icon := icons.normalize_icon_name(value))
        }

    def _adapter_icon_name(self, adapter: Any) -> str | None:
        return self._configured_adapter_icons().get(str(getattr(adapter, "name", "")))

    def _update_media_adapter_faceplates(
        self,
        adapters: list[Any],
        *,
        error: str | None = None,
    ) -> None:
        if not adapters:
            self._set_media_device_section_message(
                "media_adapters",
                "Network adapters unavailable" if error else "No network adapters",
            )
            return
        specs = []
        for adapter in adapters:
            enabled = bool(getattr(adapter, "enabled", False))
            status = str(getattr(adapter, "status", "") or "Unknown")
            status_key = status.casefold()
            primary_ip = getattr(adapter, "primary_ipv4", None)
            if not enabled:
                state = "unavailable"
            elif "unavailable" in status_key or "not present" in status_key:
                state = "unavailable"
            elif primary_ip and status_key in {"up", "connected"}:
                state = "active"
            else:
                state = "limited"
            detail = "\n".join(
                part
                for part in (
                    status,
                    str(primary_ip or "No IPv4"),
                )
                if part
            )
            specs.append(
                {
                    "title": _compact_adapter_title(
                        str(getattr(adapter, "name", "") or "Adapter")
                    ),
                    "detail": detail,
                    "device_kind": "adapter",
                    "state": state,
                    "icon": self._adapter_icon_name(adapter),
                    "context_handler": lambda global_pos, current=adapter: (
                        self._show_adapter_context_menu(current, global_pos)
                    ),
                }
            )
        self._render_media_device_faceplates(
            "media_adapters",
            specs,
            empty_message="No network adapters",
            popup_handler=self.show_adapters_popup,
        )

    def _update_media_drive_faceplates(
        self,
        drives: list[Any],
        *,
        error: str | None = None,
    ) -> None:
        if not drives:
            self._set_media_device_section_message(
                "media_drives",
                "Drives unavailable" if error else "No drives",
            )
            return
        specs = []
        for drive in drives:
            percent = getattr(drive, "used_percent", None)
            status = str(getattr(drive, "status", "") or "")
            status_key = status.casefold()
            if status_key == "disconnected":
                state = "disconnected"
            elif percent is None:
                state = "unavailable"
            elif percent >= 95:
                state = "full"
            elif percent >= 85:
                state = "warning"
            else:
                state = "ok"
            label = getattr(drive, "label", None) or getattr(drive, "drive_type", None)
            title = f"{getattr(drive, 'letter', '')}: {label or 'Drive'}"
            capacity = (
                f"{percent}% used"
                if percent is not None
                else str(getattr(drive, "drive_type", "") or "Drive")
            )
            free = _format_bytes(getattr(drive, "free_space", None))
            detail = " · ".join(
                part
                for part in (
                    status or capacity,
                    f"{free} free" if free != "-" else capacity,
                )
                if part
            )
            specs.append({"title": title, "detail": detail, "state": state})
        self._render_media_device_faceplates(
            "media_drives",
            specs,
            empty_message="No drives",
            popup_handler=self.show_drives_popup,
        )

    def show_audio_loading(self) -> None:
        was_blocked = self.audio_combo.blockSignals(True)
        try:
            self.audio_combo.clear()
            self.audio_combo.addItem("Loading audio outputs...", None)
            self.audio_combo.setEnabled(False)
            self._set_pc_volume_available(False)
            self._set_pc_muted_available(False)
            self._clear_display_volume_controls("Loading display volume...")
        finally:
            self.audio_combo.blockSignals(was_blocked)

    def show_audio_unavailable(self, message: str) -> None:
        was_blocked = self.audio_combo.blockSignals(True)
        try:
            self.audio_combo.clear()
            self.audio_combo.addItem("Audio outputs unavailable", None)
            self.audio_combo.setEnabled(False)
            self._set_pc_volume_available(False)
            self._set_pc_muted_available(False)
            self._clear_display_volume_controls("Display volume unavailable")
            self.set_status(message)
        finally:
            self.audio_combo.blockSignals(was_blocked)

    def apply_audio_panel_state(self, state: Any) -> None:
        self._refreshing_audio = True
        was_blocked = self.audio_combo.blockSignals(True)
        try:
            self.audio_combo.clear()
            sources = _active_audio_sources(list(getattr(state, "sources", [])))
            default = getattr(state, "default_source", None)
            source_labels = dict(getattr(state, "source_labels", {}) or {})
            if not sources:
                self.audio_combo.addItem("No audio outputs found", None)
                self.audio_combo.setEnabled(False)
            else:
                target_index = 0
                for index, source in enumerate(sources):
                    self.audio_combo.addItem(
                        self._audio_source_combo_label(source, source_labels),
                        source,
                    )
                    if _same_audio_source(source, default):
                        target_index = index
                self.audio_combo.setCurrentIndex(target_index)
                self.audio_combo.setEnabled(not self._busy)

            pc_volume = getattr(state, "pc_volume_percent", None)
            pc_muted = getattr(state, "pc_muted", None)
            if pc_volume is None:
                self._set_pc_volume_available(False)
                pc_error = getattr(state, "pc_volume_error", None)
                if pc_error:
                    self.set_status(str(pc_error))
            else:
                pc_was_blocked = self.pc_volume_slider.blockSignals(True)
                try:
                    self.pc_volume_slider.setValue(int(pc_volume))
                    self._set_media_control_state(
                        self.pc_volume_label,
                        self.pc_volume_slider,
                        self._pc_volume_state_text(int(pc_volume), pc_muted),
                    )
                    self._set_pc_volume_available(True)
                finally:
                    self.pc_volume_slider.blockSignals(pc_was_blocked)
            if pc_muted is None:
                self._set_pc_muted_available(False)
            else:
                self._set_pc_muted_state(bool(pc_muted))

            display_error = getattr(state, "display_volume_error", None)
            display_volume = getattr(state, "display_volume", None)
            if display_error:
                self._clear_display_volume_controls(str(display_error))
            elif display_volume is not None:
                self._render_display_volume_state(display_volume)
            else:
                self._clear_display_volume_controls("No volume control for current audio output")
        finally:
            self.audio_combo.blockSignals(was_blocked)
            self._refreshing_audio = False

    def refresh_audio_sources(self) -> None:
        load_state = getattr(self.service, "load_audio_panel_state", None)
        if callable(load_state):
            self.apply_audio_panel_state(load_state())
            return
        self._refreshing_audio = True
        was_blocked = self.audio_combo.blockSignals(True)
        try:
            self.audio_combo.clear()
            sources = _active_audio_sources(self.service.list_audio_sources())
            default = self.service.get_default_audio_source()
            source_labels = self._audio_source_labels(sources)
            if not sources:
                self.audio_combo.addItem("No audio outputs found", None)
                self.audio_combo.setEnabled(False)
                return
            target_index = 0
            for index, source in enumerate(sources):
                self.audio_combo.addItem(
                    self._audio_source_combo_label(source, source_labels),
                    source,
                )
                if _same_audio_source(source, default):
                    target_index = index
            self.audio_combo.setCurrentIndex(target_index)
            self.audio_combo.setEnabled(not self._busy)
            self.refresh_pc_volume()
            self.refresh_display_volumes()
        except Exception as exc:
            app_logging.get_logger("tray").exception("failed to refresh audio sources")
            self.audio_combo.clear()
            self.audio_combo.addItem("Audio outputs unavailable", None)
            self.audio_combo.setEnabled(False)
            self._set_pc_volume_available(False)
            self._set_pc_muted_available(False)
            self._clear_display_volume_controls("HDMI display volumes unavailable")
            self.set_status(str(exc))
        finally:
            self.audio_combo.blockSignals(was_blocked)
            self._refreshing_audio = False

    def refresh_pc_volume(self) -> None:
        self._refreshing_pc_volume = True
        was_blocked = self.pc_volume_slider.blockSignals(True)
        try:
            percent = self.service.get_volume(None)
            muted = self.service.get_muted(None)
            if percent is None:
                self._set_pc_volume_available(False)
                return
            self.pc_volume_slider.setValue(percent)
            self._set_media_control_state(
                self.pc_volume_label,
                self.pc_volume_slider,
                self._pc_volume_state_text(percent, muted),
            )
            self._set_pc_volume_available(True)
            if muted is None:
                self._set_pc_muted_available(False)
            else:
                self._set_pc_muted_state(bool(muted))
        except Exception as exc:
            app_logging.get_logger("tray").exception("failed to refresh PC volume")
            self._set_pc_volume_available(False)
            self._set_pc_muted_available(False)
            self.set_status(str(exc))
        finally:
            self.pc_volume_slider.blockSignals(was_blocked)
            self._refreshing_pc_volume = False

    def refresh_tv_volume(self) -> None:
        self.refresh_display_volumes()

    def refresh_display_volumes(self) -> None:
        from PySide6.QtCore import Qt  # type: ignore[import-not-found]
        from PySide6.QtWidgets import (  # type: ignore[import-not-found]
            QHBoxLayout,
            QPushButton,
            QSizePolicy,
            QWidget,
        )

        self._refreshing_display_volumes = True
        try:
            _clear_layout(self.display_volume_layout)
            if not self._tray_bool("show_display_volume"):
                self.display_volume_container.setVisible(False)
                self.display_volume_controls = {}
                self.display_volume_empty_label = None
                return
            self.display_volume_container.setVisible(True)
            self.display_volume_controls = {}
            self.display_volume_empty_label = None
            item = self.service.get_active_volume_display()
            if item is None:
                self._clear_display_volume_controls("No volume control for current audio output")
                return
            display_state = item.display
            key = display_inventory.display_volume_entity_key(display_state)
            title = display_inventory.display_title(display_state)
            mode = item.volume_control
            muted: bool | None = None
            if mode == config.VOLUME_CONTROL_HA_ENTITY:
                entity_id = item.volume_ha_entity
                if not entity_id:
                    self._clear_display_volume_controls(
                        f"{title}: Home Assistant entity not configured"
                    )
                    return
                control_label = f"{title} (HA {entity_id})"
                percent: int | None
                try:
                    percent = self.service.get_ha_entity_volume_percent(entity_id)
                except ha_rest.HaRestError as exc:
                    app_logging.get_logger("tray").warning("HA volume read failed: %s", exc)
                    self._clear_display_volume_controls(f"{title}: {exc}")
                    return
                muted = self._read_ha_media_player_muted(entity_id)
            else:
                entity_id = None
                control_label = f"{title} HDMI volume"
                percent = self.service.get_display_monitor_volume(display_state)
            row = QWidget()
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.setSpacing(8)
            label = self._make_media_icon_label(
                "media.display_volume",
                control_label,
                track_theme=False,
            )
            mute_button = QPushButton()
            mute_button.setObjectName("trayDisplayVolumeMuteButton")
            mute_button.setProperty("iconOnlyButton", True)
            mute_button.setFixedSize(24, 24)
            mute_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            mute_button.setCursor(Qt.CursorShape.PointingHandCursor)
            slider = _volume_fill_bar_class()(orientation=Qt.Orientation.Horizontal)
            slider.setObjectName("trayDisplayVolumeFillBar")
            slider.setColors(
                self._theme.tray.subtle_border,
                self._theme.tray.accent,
                self._theme.tray.muted,
            )
            slider.setFixedHeight(22)
            slider.setMinimumWidth(72)
            slider.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            available = percent is not None
            value = int(percent) if percent is not None else None
            if percent is not None:
                slider.setValue(value)
                state_text = self._display_row_volume_state_text(
                    control_label,
                    value,
                    muted,
                )
            else:
                state_text = self._display_row_volume_state_text(
                    control_label,
                    None,
                    muted,
                )
            self._set_media_control_state(label, slider, state_text)
            slider.setEnabled(available and not self._busy)
            mute_available = self._ha_media_player_mute_available(entity_id) and muted is not None
            mute_button.setEnabled(mute_available and not self._busy)
            self._apply_volume_mute_button_icon(mute_button, muted, state_text)
            mute_button.clicked.connect(
                lambda _checked=False, current_key=key: self.on_display_volume_mute_clicked(
                    current_key
                )
            )
            slider.valueChanged.connect(
                lambda value, current_key=key: self.on_display_volume_changed(
                    current_key,
                    value,
                )
            )
            slider.released.connect(
                lambda current_key=key: self.on_display_volume_released(current_key)
            )
            row_layout.addWidget(label)
            row_layout.addWidget(mute_button)
            row_layout.addWidget(slider, 1)
            self.display_volume_layout.addWidget(row)
            self.display_volume_controls[key] = {
                "display": display_state,
                "label": label,
                "row": row,
                "slider": slider,
                "mute_button": mute_button,
                "available": available,
                "mute_available": mute_available,
                "muted": muted,
                "percent": value,
                "mode": mode,
                "ha_entity": entity_id,
                "mute_entity": entity_id if mute_available else None,
                "mute_kind": "ha" if mute_available else None,
                "control_label": control_label,
            }
        except Exception:
            app_logging.get_logger("tray").exception("failed to refresh display volumes")
            self._clear_display_volume_controls("Display volume unavailable")
        finally:
            self._refreshing_display_volumes = False

    def _render_display_volume_state(self, state: Any) -> None:
        from PySide6.QtCore import Qt  # type: ignore[import-not-found]
        from PySide6.QtWidgets import (  # type: ignore[import-not-found]
            QHBoxLayout,
            QPushButton,
            QSizePolicy,
            QWidget,
        )

        if not self._tray_bool("show_display_volume"):
            _clear_layout(self.display_volume_layout)
            self.display_volume_controls = {}
            self.display_volume_empty_label = None
            self.display_volume_container.setVisible(False)
            return
        _clear_layout(self.display_volume_layout)
        self.display_volume_container.setVisible(True)
        self.display_volume_controls = {}
        self.display_volume_empty_label = None
        display_state = state.display_state
        key = str(state.key)
        title = str(state.title)
        mode = str(state.mode)
        if mode == config.VOLUME_CONTROL_HA_ENTITY:
            entity_id = getattr(state, "ha_entity", None)
            control_label = f"{title} (HA {entity_id})"
        else:
            entity_id = None
            control_label = f"{title} HDMI volume"
        percent = getattr(state, "percent", None)
        muted = getattr(state, "muted", None)
        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(8)
        label = self._make_media_icon_label(
            "media.display_volume",
            control_label,
            track_theme=False,
        )
        mute_button = QPushButton()
        mute_button.setObjectName("trayDisplayVolumeMuteButton")
        mute_button.setProperty("iconOnlyButton", True)
        mute_button.setFixedSize(24, 24)
        mute_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        mute_button.setCursor(Qt.CursorShape.PointingHandCursor)
        slider = _volume_fill_bar_class()(orientation=Qt.Orientation.Horizontal)
        slider.setObjectName("trayDisplayVolumeFillBar")
        slider.setColors(
            self._theme.tray.subtle_border,
            self._theme.tray.accent,
            self._theme.tray.muted,
        )
        slider.setFixedHeight(22)
        slider.setMinimumWidth(72)
        slider.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        available = percent is not None
        value = int(percent) if percent is not None else None
        if percent is not None:
            slider.setValue(value)
            state_text = self._display_row_volume_state_text(
                control_label,
                value,
                muted,
            )
        else:
            state_text = self._display_row_volume_state_text(
                control_label,
                None,
                muted,
            )
        self._set_media_control_state(label, slider, state_text)
        slider.setEnabled(available and not self._busy)
        mute_available = self._ha_media_player_mute_available(entity_id) and muted is not None
        mute_button.setEnabled(mute_available and not self._busy)
        self._apply_volume_mute_button_icon(mute_button, muted, state_text)
        mute_button.clicked.connect(
            lambda _checked=False, current_key=key: self.on_display_volume_mute_clicked(
                current_key
            )
        )
        slider.valueChanged.connect(
            lambda value, current_key=key: self.on_display_volume_changed(
                current_key,
                value,
            )
        )
        slider.released.connect(
            lambda current_key=key: self.on_display_volume_released(current_key)
        )
        row_layout.addWidget(label)
        row_layout.addWidget(mute_button)
        row_layout.addWidget(slider, 1)
        self.display_volume_layout.addWidget(row)
        self.display_volume_controls[key] = {
            "display": display_state,
            "label": label,
            "row": row,
            "slider": slider,
            "mute_button": mute_button,
            "available": available,
            "mute_available": mute_available,
            "muted": muted,
            "percent": value,
            "mode": mode,
            "ha_entity": entity_id,
            "mute_entity": entity_id if mute_available else None,
            "mute_kind": "ha" if mute_available else None,
            "control_label": control_label,
        }

    def _clear_display_volume_controls(self, message: str) -> None:
        from PySide6.QtCore import Qt  # type: ignore[import-not-found]
        from PySide6.QtWidgets import QLabel  # type: ignore[import-not-found]

        _clear_layout(self.display_volume_layout)
        self.display_volume_controls = {}
        self.display_volume_empty_label = QLabel(message)
        self.display_volume_empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.display_volume_layout.addWidget(self.display_volume_empty_label)
        self.display_volume_container.setVisible(False)

    def _set_pc_volume_available(self, available: bool) -> None:
        self._pc_volume_available = available
        self.pc_volume_slider.setEnabled(available and not self._busy)
        if not available:
            self._set_media_control_state(
                self.pc_volume_label,
                self.pc_volume_slider,
                "PC volume unavailable",
            )

    def _set_pc_muted_available(self, available: bool) -> None:
        self._pc_muted_available = bool(available)
        button = getattr(self, "pc_volume_mute_button", None)
        if button is None:
            return
        button.setEnabled(bool(available) and not self._busy)
        if not available:
            self._pc_muted = None
            self._apply_volume_mute_button_icon(
                button,
                None,
                "PC mute unavailable",
            )

    def _pc_volume_state_text(self, percent: int | None, muted: bool | None) -> str:
        state_text = (
            "PC volume unavailable" if percent is None else f"PC volume {int(percent)}%"
        )
        if muted is True:
            return f"{state_text} - muted"
        if muted is False:
            return f"{state_text} - unmuted"
        return state_text

    def _set_pc_muted_state(self, muted: bool) -> None:
        self._pc_muted = bool(muted)
        self._pc_muted_available = True
        button = getattr(self, "pc_volume_mute_button", None)
        percent = self.pc_volume_slider.value() if self._pc_volume_available else None
        state_text = self._pc_volume_state_text(percent, bool(muted))
        if button is not None:
            self._apply_volume_mute_button_icon(
                button,
                bool(muted),
                state_text,
            )
            button.setEnabled(not self._busy)
        self._set_media_control_state(
            self.pc_volume_label,
            self.pc_volume_slider,
            state_text,
        )

    def set_busy(self, busy: bool, *, active_name: str | None = None) -> None:
        self._busy = busy
        for name, button in self.profile_buttons.items():
            button.setEnabled(not busy)
            if busy and active_name == name:
                button.setText(f"Applying {name}...")
            else:
                button.setText(name)
        self.audio_combo.setEnabled(not busy and self.audio_combo.currentData() is not None)
        self.pc_volume_slider.setEnabled(not busy and self._pc_volume_available)
        self.pc_volume_mute_button.setEnabled(not busy and self._pc_muted_available)
        for control in self.display_volume_controls.values():
            slider = control["slider"]
            slider.setEnabled(not busy and bool(control.get("available")))
            mute_button = control.get("mute_button")
            if mute_button is not None:
                mute_button.setEnabled(
                    not busy and bool(control.get("mute_available"))
                )
        for control in self.display_row_volume_controls.values():
            slider = control["slider"]
            slider.setEnabled(not busy and bool(control.get("available")))
            mute_button = control.get("mute_button")
            if mute_button is not None:
                mute_button.setEnabled(
                    not busy and bool(control.get("mute_available"))
                )
        for button in self.display_toggle_buttons.values():
            button.setEnabled(
                not busy and bool(getattr(button, "_xtray_available", True))
            )
        for button in self.display_power_buttons.values():
            button.setEnabled(
                not busy and bool(getattr(button, "_xtray_available", True))
            )
        for button in self.display_make_primary_buttons.values():
            button.setEnabled(
                not busy and bool(getattr(button, "_xtray_available", True))
            )
        for buttons in self.adapter_action_buttons.values():
            for button in buttons.values():
                button.setEnabled(not busy)
        for button in self.drive_open_buttons.values():
            button.setEnabled(not busy)
        self.drives_add_button.setEnabled(not busy)
        if busy and active_name:
            self.set_status(f"Applying {active_name}...")

    def set_status(self, message: str) -> None:
        # The status label was removed from the media tab; keep the method as
        # a no-op so existing callers (apply_*, on_*_released, ...) still work
        # but their messages just disappear silently. Forward to the logger so
        # the trail is still available for debugging.
        if message:
            app_logging.get_logger("tray").debug("status: %s", message)

    def on_audio_changed(self, _index: int) -> None:
        if self._refreshing_audio or self._busy:
            return
        source = self.audio_combo.currentData()
        if source is None:
            return
        self.controller.apply_audio_source(source)

    def on_pc_volume_changed(self, value: int) -> None:
        if self._refreshing_pc_volume:
            return
        self._set_media_control_state(
            self.pc_volume_label,
            self.pc_volume_slider,
            self._pc_volume_state_text(value, self._pc_muted),
        )

    def on_pc_volume_released(self) -> None:
        if self._refreshing_pc_volume or self._busy:
            return
        self.controller.apply_volume_percent(None, self.pc_volume_slider.value())

    def on_pc_mute_clicked(self) -> None:
        if self._refreshing_pc_volume or self._busy or self._pc_muted is None:
            return
        previous = bool(self._pc_muted)
        target_muted = not previous
        self._set_pc_muted_state(target_muted)
        apply_muted = getattr(self.controller, "apply_muted", None)
        if callable(apply_muted):
            started = apply_muted(target_muted)
            if started is False:
                self._set_pc_muted_state(previous)

    def on_display_volume_changed(self, key: str, value: int) -> None:
        if self._refreshing_display_volumes:
            return
        control = self.display_volume_controls.get(key)
        if control is None:
            return
        label = control["label"]
        control["percent"] = int(value)
        state_text = self._display_row_volume_state_text(
            str(control["control_label"]),
            int(value),
            control.get("muted"),
        )
        self._set_media_control_state(
            label,
            control["slider"],
            state_text,
        )
        mute_button = control.get("mute_button")
        if mute_button is not None:
            self._apply_volume_mute_button_icon(
                mute_button,
                control.get("muted"),
                state_text,
            )

    def on_display_volume_released(self, key: str) -> None:
        if self._refreshing_display_volumes or self._busy:
            return
        control = self.display_volume_controls.get(key)
        if control is None:
            return
        value = control["slider"].value()
        if control.get("mode") == config.VOLUME_CONTROL_HA_ENTITY:
            entity_id = control.get("ha_entity")
            if not entity_id:
                return
            self.controller.apply_ha_volume_percent(entity_id, value)
            return
        self.controller.apply_display_volume_percent(control["display"], value)

    def _set_display_volume_muted_state(
        self,
        control: dict[str, Any],
        muted: bool,
    ) -> None:
        control["muted"] = bool(muted)
        control["mute_available"] = True
        state_text = self._display_row_volume_state_text(
            str(control["control_label"]),
            control.get("percent"),
            bool(muted),
        )
        self._set_media_control_state(control["label"], control["slider"], state_text)
        mute_button = control.get("mute_button")
        if mute_button is not None:
            self._apply_volume_mute_button_icon(mute_button, bool(muted), state_text)
            mute_button.setEnabled(not self._busy)

    def on_display_volume_mute_clicked(self, key: str) -> None:
        if self._refreshing_display_volumes or self._busy:
            return
        control = self.display_volume_controls.get(key)
        if control is None:
            return
        muted = control.get("muted")
        entity_id = control.get("mute_entity") or control.get("ha_entity")
        if muted is None or not entity_id:
            return
        target_muted = not bool(muted)
        self._set_display_volume_muted_state(control, target_muted)
        apply_ha_muted = getattr(self.controller, "apply_ha_muted", None)
        if not callable(apply_ha_muted):
            self._set_display_volume_muted_state(control, bool(muted))
            return
        started = apply_ha_muted(str(entity_id), target_muted)
        if started is False:
            self._set_display_volume_muted_state(control, bool(muted))

    def on_tv_volume_changed(self, value: int) -> None:
        first_key = next(iter(self.display_volume_controls), None)
        if first_key is not None:
            self.on_display_volume_changed(first_key, value)

    def on_tv_volume_released(self) -> None:
        first_key = next(iter(self.display_volume_controls), None)
        if first_key is not None:
            self.on_display_volume_released(first_key)

    def _apply(self, name: str) -> None:
        missing_names = self._profile_missing_display_names(name)
        if missing_names:
            self._show_missing_displays_dialog(name, missing_names)
            return
        self.controller.apply_profile(name)

    def _profile_missing_display_names(self, profile_name: str) -> list[str]:
        fetcher = getattr(self.service, "profile_missing_display_names", None)
        if not callable(fetcher):
            return []
        try:
            return list(fetcher(profile_name))
        except Exception:
            app_logging.get_logger("tray").exception(
                "failed to fetch missing display names for profile %s", profile_name
            )
            return []

    def _show_missing_displays_dialog(
        self,
        profile_name: str,
        missing_display_names: list[str],
    ) -> None:
        from .dialogs import show_missing_displays_dialog

        show_missing_displays_dialog(self.window, profile_name, missing_display_names)

    def on_adapters_refresh_clicked(self) -> None:
        refresh = getattr(self.controller, "refresh_adapters", None)
        if callable(refresh):
            refresh()

    def on_network_connections_clicked(self) -> None:
        open_connections = getattr(self.controller, "open_network_connections", None)
        if callable(open_connections):
            open_connections()

    def on_adapter_toggle(self, adapter: Any) -> None:
        if self._busy:
            return
        apply_enabled = getattr(self.controller, "apply_adapter_enabled", None)
        if callable(apply_enabled):
            apply_enabled(adapter, not bool(adapter.enabled))

    def on_adapter_info(self, adapter: Any) -> None:
        open_info = getattr(self.controller, "open_adapter_info", None)
        if callable(open_info):
            open_info(adapter)

    def on_adapter_properties(self, adapter: Any) -> None:
        open_properties = getattr(self.controller, "open_adapter_properties", None)
        if callable(open_properties):
            open_properties(adapter)
            return
        open_connections = getattr(self.controller, "open_network_connections", None)
        if callable(open_connections):
            open_connections()

    def on_drives_refresh_clicked(self) -> None:
        refresh = getattr(self.controller, "refresh_drives", None)
        if callable(refresh):
            refresh()

    def on_drive_open(self, drive: Any) -> None:
        open_drive = getattr(self.controller, "open_drive", None)
        if callable(open_drive):
            open_drive(drive)

    def on_add_network_drive(self) -> None:
        add_drive = getattr(self.controller, "open_add_network_drive", None)
        if callable(add_drive):
            add_drive()

    def on_displays_refresh_clicked(self) -> None:
        refresh = getattr(self.controller, "refresh_display_inventory", None)
        if callable(refresh):
            refresh()
            return
        self.refresh_displays()

    def show_displays_loading(self) -> None:
        from PySide6.QtCore import Qt  # type: ignore[import-not-found]
        from PySide6.QtWidgets import QLabel  # type: ignore[import-not-found]

        self.display_toggle_buttons = {}
        self.display_power_buttons = {}
        self.display_make_primary_buttons = {}
        self.display_row_volume_controls = {}
        _clear_layout(self.displays_list_layout)
        self.display_empty_label = QLabel("Loading displays...")
        self.display_empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.displays_list_layout.addWidget(self.display_empty_label, 1)
        self._set_media_device_section_message("media_displays", "Loading displays...")
        self.set_display_status("")

    def refresh_displays(self) -> None:
        try:
            items = self.service.list_display_inventory()
        except Exception as exc:
            app_logging.get_logger("tray").exception("failed to refresh displays")
            self.apply_display_inventory([], error=str(exc))
            return
        self.apply_display_inventory(items)

    def apply_display_inventory(
        self,
        items: list[Any],
        *,
        error: str | None = None,
    ) -> None:
        from PySide6.QtCore import Qt  # type: ignore[import-not-found]
        from PySide6.QtWidgets import (  # type: ignore[import-not-found]
            QFrame,
            QHBoxLayout,
            QLabel,
            QPushButton,
            QSizePolicy,
            QVBoxLayout,
        )

        self.display_toggle_buttons = {}
        self.display_power_buttons = {}
        self.display_make_primary_buttons = {}
        self.display_row_volume_controls = {}
        self.display_empty_label = None
        _clear_layout(self.displays_list_layout)
        self._update_media_display_faceplates(items, error=error)
        if not items:
            self.display_empty_label = QLabel(
                "Displays unavailable" if error else "No displays"
            )
            self.display_empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.displays_list_layout.addWidget(self.display_empty_label, 1)
            self.set_display_status(error or "")
            return

        enabled_count = sum(1 for entry in items if getattr(entry, "enabled", False))

        for item in items:
            display_state = item.display
            key = str(
                getattr(item, "key", "")
                or display_inventory.display_volume_entity_key(display_state)
            )
            has_volume_control = (
                getattr(item, "volume_control", config.VOLUME_CONTROL_NONE)
                != config.VOLUME_CONTROL_NONE
            )
            has_power_control = bool(getattr(item, "power_on_ha_service", None)) or bool(
                getattr(item, "power_off_ha_service", None)
            )
            is_primary = bool(getattr(display_state, "primary", False)) and bool(
                item.enabled
            )
            state, _state_text = _display_status(item)
            row = QFrame()
            row.setObjectName("trayDisplayRow")
            row.setProperty("displayRole", "primary" if is_primary else "normal")
            row.setProperty("displayState", state)
            row.setMinimumHeight(104 if has_volume_control or has_power_control else 66)
            row.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            self._wire_display_context_menu(row, item, enabled_count)
            row_layout = QVBoxLayout(row)
            row_layout.setContentsMargins(8, 8, 8, 10)
            row_layout.setSpacing(8)

            title_row = QHBoxLayout()
            title_row.setContentsMargins(0, 0, 0, 0)
            title_row.setSpacing(6)
            title_block = QVBoxLayout()
            title_block.setContentsMargins(0, 0, 0, 0)
            title_block.setSpacing(3)
            title = QLabel(_display_item_title(item))
            title.setObjectName("trayDisplayTitle")
            title.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            title.setWordWrap(False)
            self._wire_display_context_menu(title, item, enabled_count)
            title_block.addWidget(title)
            metrics_row = QHBoxLayout()
            metrics_row.setContentsMargins(0, 0, 0, 0)
            metrics_row.setSpacing(5)
            resolution_label = QLabel(_display_resolution_value(display_state))
            resolution_label.setObjectName("trayDisplayInlineInfo")
            resolution_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._wire_display_context_menu(resolution_label, item, enabled_count)
            metrics_row.addWidget(resolution_label, 0)
            refresh_label = QLabel(_display_refresh_value(display_state))
            refresh_label.setObjectName("trayDisplayInlineInfo")
            refresh_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._wire_display_context_menu(refresh_label, item, enabled_count)
            metrics_row.addWidget(refresh_label, 0)
            metrics_row.addStretch(1)
            title_block.addLayout(metrics_row)
            title_row.addLayout(title_block, 1)

            toggle_action_id = "display.disable" if item.enabled else "display.enable"
            toggle_button = QPushButton(self._fallback_label(toggle_action_id))
            toggle_button.setObjectName("trayDisplayToggleButton")
            toggle_button.setProperty("displayState", "on" if item.enabled else "off")
            toggle_button.setFixedWidth(_DISPLAY_TOGGLE_BUTTON_WIDTH)
            self._apply_action_button_icon(toggle_button, toggle_action_id)
            toggle_available = _display_toggle_available(item)
            if item.enabled and enabled_count <= 1:
                # Disabling the only active display is rejected downstream;
                # block it here so the button reflects that.
                toggle_available = False
                toggle_button.setToolTip("Cannot disable the only active display")
            toggle_button._xtray_available = toggle_available
            toggle_button.setEnabled(not self._busy and toggle_available)
            toggle_button.clicked.connect(
                lambda _checked=False, current=item: self.on_display_toggle(current)
            )
            self.display_toggle_buttons[key] = toggle_button

            if is_primary:
                primary_label = QLabel(self._fallback_label("display.primary"))
                primary_label.setToolTip(self._action_label("display.primary"))
                primary_label.setAccessibleName(self._action_label("display.primary"))
                primary_label.setObjectName("trayDisplayPrimaryLabel")
                primary_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
                primary_label.setFixedWidth(_DISPLAY_TOGGLE_BUTTON_WIDTH)
                title_row.addWidget(primary_label, 0)
            elif item.enabled:
                make_primary_button = QPushButton(self._fallback_label("display.make_primary"))
                make_primary_button.setObjectName("trayDisplayMakePrimaryButton")
                make_primary_button.setFixedWidth(_DISPLAY_TOGGLE_BUTTON_WIDTH)
                self._apply_action_button_icon(
                    make_primary_button,
                    "display.make_primary",
                    color=self._theme.tray.text,
                )
                make_primary_button._xtray_available = True
                make_primary_button.setEnabled(not self._busy)
                make_primary_button.clicked.connect(
                    lambda _checked=False, current=item: self.on_display_make_primary(
                        current
                    )
                )
                title_row.addWidget(make_primary_button, 0)
                self.display_make_primary_buttons[key] = make_primary_button
            title_row.addWidget(toggle_button, 0)
            row_layout.addLayout(title_row)

            secondary_layout = QHBoxLayout()
            secondary_layout.setContentsMargins(0, 0, 0, 0)
            secondary_layout.setSpacing(6)
            has_secondary_controls = self._add_display_row_volume_control(
                secondary_layout,
                item,
                key,
            )
            if has_power_control and not has_volume_control:
                secondary_layout.addStretch(1)
            power_icon_color = self._theme.tray.text
            if getattr(item, "power_on_ha_service", None):
                power_on_button = QPushButton()
                power_on_button.setObjectName("trayDisplayPowerButton")
                power_on_button.setFixedWidth(_DISPLAY_POWER_BUTTON_WIDTH)
                self._apply_action_button_icon(
                    power_on_button,
                    "display.power_on",
                    color=power_icon_color,
                )
                power_on_button._xtray_available = True
                power_on_button.setEnabled(not self._busy)
                power_on_button.clicked.connect(
                    lambda _checked=False, current=item: self.on_display_power(
                        current,
                        True,
                    )
                )
                secondary_layout.addWidget(power_on_button)
                self.display_power_buttons[f"{key}:on"] = power_on_button
                has_secondary_controls = True

            if getattr(item, "power_off_ha_service", None):
                power_off_button = QPushButton()
                power_off_button.setObjectName("trayDisplayPowerButton")
                power_off_button.setFixedWidth(_DISPLAY_POWER_BUTTON_WIDTH)
                self._apply_action_button_icon(
                    power_off_button,
                    "display.power_off",
                    color=power_icon_color,
                )
                power_off_button._xtray_available = True
                power_off_button.setEnabled(not self._busy)
                power_off_button.clicked.connect(
                    lambda _checked=False, current=item: self.on_display_power(
                        current,
                        False,
                    )
                )
                secondary_layout.addWidget(power_off_button)
                self.display_power_buttons[f"{key}:off"] = power_off_button
                has_secondary_controls = True
            if has_secondary_controls:
                row_layout.addLayout(secondary_layout)

            self.displays_list_layout.addWidget(row)

        self.displays_list_layout.addStretch(1)

        self.set_display_status("")
        self.set_busy(self._busy)

    def on_display_toggle(self, item: Any) -> None:
        if self._busy:
            return
        self.controller.apply_display_enabled(item.display, not bool(item.enabled))

    def on_display_power(self, item: Any, turn_on: bool) -> None:
        if self._busy:
            return
        self.controller.apply_display_power(item.display, turn_on)

    def on_display_make_primary(self, item: Any) -> None:
        if self._busy:
            return
        self.controller.apply_display_primary(item.display)

    def _add_display_row_volume_control(
        self,
        parent_layout: Any,
        item: Any,
        key: str,
    ) -> bool:
        from PySide6.QtCore import Qt  # type: ignore[import-not-found]
        from PySide6.QtWidgets import QPushButton, QSizePolicy  # type: ignore[import-not-found]

        mode = getattr(item, "volume_control", config.VOLUME_CONTROL_NONE)
        if mode == config.VOLUME_CONTROL_NONE:
            return False

        display_state = item.display
        entity_id = None
        percent: int | None = None
        unavailable_reason: str | None = None
        if mode == config.VOLUME_CONTROL_HA_ENTITY:
            entity_id = getattr(item, "volume_ha_entity", None)
            control_label = "HA volume"
            if not entity_id:
                unavailable_reason = "HA volume entity not configured"
            else:
                try:
                    percent = self.service.get_ha_entity_volume_percent(entity_id)
                except Exception as exc:
                    app_logging.get_logger("tray").warning(
                        "HA display volume read failed for %s: %s",
                        entity_id,
                        exc,
                    )
                    unavailable_reason = "HA volume unavailable"
        else:
            control_label = "HDMI volume"
            try:
                percent = self.service.get_display_monitor_volume(display_state)
            except Exception:
                app_logging.get_logger("tray").exception(
                    "failed to read display volume for display row"
                )
                unavailable_reason = "HDMI volume unavailable"
        muted = self._read_ha_media_player_muted(entity_id)
        mute_available = self._ha_media_player_mute_available(entity_id) and muted is not None

        mute_button = QPushButton()
        mute_button.setObjectName("trayDisplayVolumeMuteButton")
        mute_button.setProperty("iconOnlyButton", True)
        mute_button.setFixedSize(24, 24)
        mute_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        mute_button.setCursor(Qt.CursorShape.PointingHandCursor)

        fillbar = _volume_fill_bar_class()(orientation=Qt.Orientation.Horizontal)
        fillbar.setObjectName("trayDisplayVolumeFillBar")
        fillbar.setColors(
            self._theme.tray.subtle_border,
            self._theme.tray.accent,
            self._theme.tray.muted,
        )
        fillbar.setMinimumWidth(72)
        fillbar.setFixedHeight(22)
        fillbar.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        available = percent is not None
        value = int(percent) if percent is not None else None
        if value is not None:
            fillbar.setValue(value)
        state_text = self._display_row_volume_state_text(
            control_label,
            value,
            muted,
            unavailable_reason=unavailable_reason,
        )
        fillbar.setEnabled(available and not self._busy)
        fillbar.valueChanged.connect(
            lambda value, current_key=key: self.on_display_row_volume_changed(
                current_key,
                value,
            )
        )
        fillbar.released.connect(
            lambda current_key=key: self.on_display_row_volume_released(current_key)
        )
        mute_button.clicked.connect(
            lambda _checked=False, current_key=key: self.on_display_row_mute_clicked(
                current_key
            )
        )
        mute_button.setEnabled(mute_available and not self._busy)
        parent_layout.addWidget(mute_button, 0)
        parent_layout.addWidget(fillbar, 1)
        control = {
            "display": display_state,
            "label": None,
            "slider": fillbar,
            "mute_button": mute_button,
            "available": available,
            "mute_available": mute_available,
            "muted": muted,
            "percent": value,
            "unavailable_reason": unavailable_reason,
            "mode": mode,
            "ha_entity": entity_id,
            "mute_entity": entity_id if mute_available else None,
            "mute_kind": "ha" if mute_available else None,
            "control_label": control_label,
        }
        self._set_display_row_volume_state(control, state_text)
        self._apply_display_row_mute_button_icon(mute_button, muted, state_text)
        self.display_row_volume_controls[key] = control
        return True

    def _add_display_row_note(self, parent_layout: Any, message: str) -> None:
        from PySide6.QtWidgets import QLabel  # type: ignore[import-not-found]

        label = QLabel(message)
        label.setObjectName("trayDisplayInfo")
        label.setWordWrap(True)
        parent_layout.addWidget(label)

    def on_display_row_volume_changed(self, key: str, value: int) -> None:
        control = self.display_row_volume_controls.get(key)
        if control is None:
            return
        control["percent"] = int(value)
        self._set_display_row_volume_state(
            control,
            self._display_row_volume_state_text(
                str(control["control_label"]),
                int(value),
                control.get("muted"),
                unavailable_reason=control.get("unavailable_reason"),
            ),
        )

    def _set_display_row_volume_state(self, control: dict[str, Any], state_text: str) -> None:
        label = control.get("label")
        if label is not None:
            label.setText(state_text)
        slider = control.get("slider")
        if slider is not None:
            slider.setToolTip(state_text)
            slider.setAccessibleName(state_text)
        mute_button = control.get("mute_button")
        if mute_button is not None:
            tooltip = self._display_row_mute_tooltip(state_text, control.get("muted"))
            mute_button.setToolTip(tooltip)
            mute_button.setAccessibleName(tooltip)

    def _display_row_volume_state_text(
        self,
        control_label: str,
        percent: int | None,
        muted: bool | None,
        *,
        unavailable_reason: str | None = None,
    ) -> str:
        if percent is None:
            state_text = unavailable_reason or f"{control_label} unavailable"
        else:
            state_text = f"{control_label} {int(percent)}%"
        if muted is True:
            return f"{state_text} - muted"
        if muted is False:
            return f"{state_text} - unmuted"
        return state_text

    def _display_row_mute_tooltip(
        self,
        state_text: str,
        muted: bool | None,
    ) -> str:
        if muted is True:
            return f"{state_text}. Click to unmute"
        if muted is False:
            return f"{state_text}. Click to mute"
        return f"{state_text}. Mute unavailable"

    @staticmethod
    def _ha_media_player_mute_available(entity_id: Any) -> bool:
        return str(entity_id or "").strip().casefold().startswith("media_player.")

    def _read_ha_media_player_muted(self, entity_id: Any) -> bool | None:
        if not self._ha_media_player_mute_available(entity_id):
            return None
        try:
            return self.service.get_ha_entity_muted(str(entity_id))
        except Exception as exc:
            app_logging.get_logger("tray").debug(
                "HA media player mute read failed for %s: %s",
                entity_id,
                exc,
            )
            return None

    def _apply_volume_mute_button_icon(
        self,
        button: Any,
        muted: bool | None,
        state_text: str,
    ) -> None:
        from PySide6.QtCore import QSize  # type: ignore[import-not-found]
        from PySide6.QtGui import QIcon  # type: ignore[import-not-found]

        button.setProperty("muted", bool(muted) if muted is not None else False)
        button.setProperty("muteAvailable", muted is not None)
        tooltip = self._display_row_mute_tooltip(state_text, muted)
        button.setToolTip(tooltip)
        button.setAccessibleName(tooltip)
        icon_names = (
            ("mdi:volume-off", "mdi:volume-mute")
            if muted
            else ("mdi:volume-high", "mdi:volume-medium", "mdi:volume-low")
        )
        color = self._theme.tray.muted if muted else self._theme.tray.text
        icon = _qicon_for_first(icon_names, color=color, size=32)
        button.setIconSize(QSize(18, 18))
        if icon.isNull():
            button.setIcon(QIcon())
            button.setText("M")
        else:
            button.setText("")
            button.setIcon(icon)
        repolish(button)

    def _apply_display_row_mute_button_icon(
        self,
        button: Any,
        muted: bool | None,
        state_text: str,
    ) -> None:
        self._apply_volume_mute_button_icon(button, muted, state_text)

    def _set_display_row_muted_state(
        self,
        control: dict[str, Any],
        muted: bool,
    ) -> None:
        control["muted"] = bool(muted)
        control["mute_available"] = True
        state_text = self._display_row_volume_state_text(
            str(control["control_label"]),
            control.get("percent"),
            bool(muted),
            unavailable_reason=control.get("unavailable_reason"),
        )
        self._set_display_row_volume_state(control, state_text)
        mute_button = control.get("mute_button")
        if mute_button is not None:
            self._apply_display_row_mute_button_icon(mute_button, bool(muted), state_text)

    def on_display_row_mute_clicked(self, key: str) -> None:
        if self._busy:
            return
        control = self.display_row_volume_controls.get(key)
        if control is None:
            return
        muted = control.get("muted")
        if muted is None:
            return
        target_muted = not bool(muted)
        self._set_display_row_muted_state(control, target_muted)
        mute_kind = control.get("mute_kind")
        if mute_kind == "ha":
            entity_id = control.get("mute_entity") or control.get("ha_entity")
            apply_ha_muted = getattr(self.controller, "apply_ha_muted", None)
            if not entity_id or not callable(apply_ha_muted):
                self._set_display_row_muted_state(control, bool(muted))
                return
            started = apply_ha_muted(str(entity_id), target_muted)
            if started is False:
                self._set_display_row_muted_state(control, bool(muted))
            return

    def on_display_row_volume_released(self, key: str) -> None:
        if self._busy:
            return
        control = self.display_row_volume_controls.get(key)
        if control is None:
            return
        value = control["slider"].value()
        if control.get("mode") == config.VOLUME_CONTROL_HA_ENTITY:
            entity_id = control.get("ha_entity")
            if not entity_id:
                return
            self.controller.apply_ha_volume_percent(entity_id, value)
            return
        self.controller.apply_display_volume_percent(control["display"], value)

    def set_display_status(self, message: str) -> None:
        self.displays_status.setText(message)

    def show_adapters_loading(self) -> None:
        from PySide6.QtCore import Qt  # type: ignore[import-not-found]
        from PySide6.QtWidgets import QLabel  # type: ignore[import-not-found]

        self.adapter_action_buttons = {}
        _clear_layout(self.adapters_list_layout)
        empty = QLabel("Loading network adapters...")
        empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.adapters_list_layout.addWidget(empty)
        self._set_media_device_section_message(
            "media_adapters",
            "Loading network adapters...",
        )
        self.set_adapters_status("")

    def apply_adapters(self, adapters: list[Any], *, error: str | None = None) -> None:
        from PySide6.QtCore import Qt  # type: ignore[import-not-found]
        from PySide6.QtWidgets import (  # type: ignore[import-not-found]
            QFrame,
            QHBoxLayout,
            QLabel,
            QPushButton,
            QVBoxLayout,
        )

        self.adapter_action_buttons = {}
        _clear_layout(self.adapters_list_layout)
        visible_ids = self._tray_options.get("visible_adapter_ids")
        if isinstance(visible_ids, list):
            allowed = {str(value).casefold() for value in visible_ids}
            adapters = [
                adapter
                for adapter in adapters
                if str(getattr(adapter, "name", "")).casefold() in allowed
            ]
        self._update_media_adapter_faceplates(adapters, error=error)
        if not adapters:
            label = QLabel("Network adapters unavailable" if error else "No network adapters")
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.adapters_list_layout.addWidget(label)
            self.set_adapters_status(error or "")
            return

        for adapter in adapters:
            row = QFrame()
            row.setObjectName("trayListRow")
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(8, 8, 8, 8)
            row_layout.setSpacing(8)
            text_layout = QVBoxLayout()
            text_layout.setContentsMargins(0, 0, 0, 0)
            title = QLabel(adapter.name)
            title.setObjectName("trayPanelSection")
            detail = QLabel(
                "\n".join(
                    part
                    for part in (
                        adapter.description,
                        (
                            f"Status: {adapter.status} | "
                            f"DHCP: {'On' if adapter.dhcp_enabled else 'Off'}"
                        ),
                        f"IPv4: {', '.join(adapter.ipv4_addresses) or '-'}",
                        f"MAC: {adapter.mac_address or '-'} | Speed: {adapter.link_speed or '-'}",
                    )
                    if part
                )
            )
            detail.setWordWrap(True)
            detail.setObjectName("trayPanelStatus")
            text_layout.addWidget(title)
            text_layout.addWidget(detail)
            row_layout.addLayout(text_layout, 1)

            toggle_action_id = "adapter.disable" if adapter.enabled else "adapter.enable"
            toggle_button = QPushButton(self._fallback_label(toggle_action_id))
            toggle_button.setObjectName("trayAdapterToggleButton")
            toggle_button.setProperty("role", "primary" if not adapter.enabled else "")
            self._apply_action_button_icon(toggle_button, toggle_action_id)
            toggle_button.clicked.connect(
                lambda _checked=False, current=adapter: self.on_adapter_toggle(current)
            )
            row_layout.addWidget(toggle_button)
            info_button = QPushButton(self._fallback_label("adapter.info"))
            info_button.setObjectName("trayAdapterInfoButton")
            info_button.setProperty("surfaceAction", "window")
            self._apply_action_button_icon(info_button, "adapter.info")
            info_button.clicked.connect(
                lambda _checked=False, current=adapter: self.on_adapter_info(current)
            )
            row_layout.addWidget(info_button)
            self.adapter_action_buttons[adapter.if_index] = {
                "toggle": toggle_button,
                "info": info_button,
            }
            self.adapters_list_layout.addWidget(row)
        self.adapters_list_layout.addStretch(1)
        self.set_adapters_status("")
        self.set_busy(self._busy)

    def show_drives_loading(self) -> None:
        from PySide6.QtCore import Qt  # type: ignore[import-not-found]
        from PySide6.QtWidgets import QLabel  # type: ignore[import-not-found]

        self.drive_open_buttons = {}
        _clear_layout(self.drives_list_layout)
        empty = QLabel("Loading drives...")
        empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.drives_list_layout.addWidget(empty)
        self._set_media_device_section_message("media_drives", "Loading drives...")
        self.set_drives_status("")

    def apply_drives(self, drives: list[Any], *, error: str | None = None) -> None:
        from PySide6.QtCore import Qt  # type: ignore[import-not-found]
        from PySide6.QtWidgets import (  # type: ignore[import-not-found]
            QFrame,
            QHBoxLayout,
            QLabel,
            QProgressBar,
            QPushButton,
            QVBoxLayout,
        )

        self.drive_open_buttons = {}
        _clear_layout(self.drives_list_layout)
        visible_ids = self._tray_options.get("visible_drive_ids")
        if isinstance(visible_ids, list):
            allowed = {str(value).strip().rstrip(":").upper() for value in visible_ids}
            drives = [
                drive
                for drive in drives
                if _drive_option_key(drive) in allowed
            ]
        self._update_media_drive_faceplates(drives, error=error)
        if not drives:
            label = QLabel("Drives unavailable" if error else "No drives")
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.drives_list_layout.addWidget(label)
            self.set_drives_status(error or "")
            return

        for drive in drives:
            row = QFrame()
            row.setObjectName("trayListRow")
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(8, 8, 8, 8)
            row_layout.setSpacing(8)
            text_layout = QVBoxLayout()
            text_layout.setContentsMargins(0, 0, 0, 0)
            title = QLabel(f"{drive.letter}: {drive.label or drive.drive_type}")
            title.setObjectName("trayPanelSection")
            remote = f" | {drive.remote_path}" if drive.remote_path else ""
            detail = QLabel(
                f"{drive.drive_type}{remote}\n"
                f"{drive.filesystem or '-'} | Free {_format_bytes(drive.free_space)} "
                f"of {_format_bytes(drive.size)}"
            )
            detail.setWordWrap(True)
            detail.setObjectName("trayPanelStatus")
            text_layout.addWidget(title)
            text_layout.addWidget(detail)
            row_layout.addLayout(text_layout, 1)

            bar = QProgressBar()
            bar.setRange(0, 100)
            percent = drive.used_percent
            if percent is None:
                bar.setTextVisible(False)
                bar.setEnabled(False)
            else:
                bar.setValue(percent)
                bar.setFormat(f"{percent}% used")
            row_layout.addWidget(bar)

            open_button = QPushButton(self._fallback_label("drive.open"))
            open_button.setObjectName("trayDriveOpenButton")
            open_button.setProperty("surfaceAction", "window")
            self._apply_action_button_icon(open_button, "drive.open")
            open_button.clicked.connect(
                lambda _checked=False, current=drive: self.on_drive_open(current)
            )
            row_layout.addWidget(open_button)
            self.drive_open_buttons[drive.letter] = open_button
            self.drives_list_layout.addWidget(row)
        self.drives_list_layout.addStretch(1)
        self.set_drives_status("")
        self.set_busy(self._busy)

    def set_adapters_status(self, message: str) -> None:
        self.adapters_status.setText(message)

    def set_drives_status(self, message: str) -> None:
        self.drives_status.setText(message)

    def show_network_loading(self) -> None:
        _panel_network.show_network_loading(self)

    def refresh_network_devices(self) -> None:
        _panel_network.refresh_network_devices(self)

    def apply_network_devices(
        self,
        devices: list[network.NetworkDevice],
        *,
        error: str | None = None,
    ) -> None:
        _panel_network.apply_network_devices(self, devices, error=error)

    def update_network_status(self, status: network.NetworkStatus) -> None:
        _panel_network.update_network_status(self, status)

    def _set_ping_button_state(self, button: Any, state: str) -> None:
        _panel_network.set_ping_button_state(self, button, state)

    def set_network_status(self, message: str) -> None:
        _panel_network.set_network_status(self, message)

    def on_network_manage(self) -> None:
        self.controller.open_network_manager()


def _format_bytes(value: int | None) -> str:
    if value is None:
        return "-"
    amount = float(value)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if amount < 1024 or unit == "TB":
            if unit == "B":
                return f"{int(amount)} {unit}"
            return f"{amount:.1f} {unit}"
        amount /= 1024


def _display_status(item: Any) -> tuple[str, str]:
    display_state = getattr(item, "display", None)
    available = bool(getattr(item, "available", True))
    if not available:
        return "unavailable", "Unavailable"
    enabled = bool(getattr(item, "enabled", False))
    if enabled and bool(getattr(display_state, "primary", False)):
        return "primary", "Primary"
    if enabled:
        return "enabled", "Enabled"
    return "disabled", "Disabled"


def _display_item_title(item: Any) -> str:
    friendly_name = str(getattr(item, "friendly_name", "") or "").strip()
    if friendly_name:
        return friendly_name
    return _display_short_name(item.display)


def _compact_display_title(title: str, *, limit: int = 12) -> str:
    text = " ".join(str(title or "Display").split())
    if len(text) <= limit:
        return text
    return f"{text[: max(1, limit - 1)].rstrip()}..."


def _compact_adapter_title(
    title: str,
    *,
    line_width: int = 16,
    max_lines: int = 2,
) -> str:
    text = " ".join(str(title or "Adapter").split()) or "Adapter"
    lines = textwrap.wrap(
        text,
        width=line_width,
        break_long_words=True,
        break_on_hyphens=True,
    )
    if not lines:
        return "Adapter"
    if len(lines) > max_lines:
        overflow = " ".join(lines[max_lines - 1 :])
        lines = [
            *lines[: max_lines - 1],
            _compact_display_title(overflow, limit=line_width),
        ]
    return "\n".join(lines)


def _display_resolution_value(display_state: Any) -> str:
    width = getattr(display_state, "width", None)
    height = getattr(display_state, "height", None)
    if width and height:
        return f"{int(width)}x{int(height)}"
    return "Unknown"


def _display_refresh_value(display_state: Any) -> str:
    refresh_hz = getattr(display_state, "refresh_hz", None)
    if not isinstance(refresh_hz, (int, float)) or not refresh_hz:
        return "Unknown"
    value = float(refresh_hz)
    label = f"{int(value)}" if value.is_integer() else f"{value:g}"
    return f"{label} Hz"


def _display_toggle_available(item: Any) -> bool:
    if bool(getattr(item, "available", False)) or bool(getattr(item, "enabled", False)):
        return True
    if getattr(item, "assigned_profiles", None):
        return True
    display_state = getattr(item, "display", None)
    return bool(getattr(display_state, "adapter_name", None))


def _drive_option_key(drive: Any) -> str:
    return str(getattr(drive, "letter", "")).strip().rstrip(":").upper()


ProfilePanel = TrayPanel
