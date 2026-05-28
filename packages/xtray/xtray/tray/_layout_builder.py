"""Build the tray panel widget tree.

`TrayPanel.__init__` previously held ~300 LOC of Qt widget construction
(window chrome + media tab + displays popup + network/adapters/drives/
fallback tabs). That layout building has no logic, just sequential
QWidget composition and signal wiring; keeping it in the panel mixed
visual scaffolding with event handlers and state mutations.

This module exposes a single ``build(panel)`` entry point that the
panel calls after initialising its mutable state. The functions populate
attributes on ``panel`` (panel.tabs, panel.media_layout, etc.) so the
rest of TrayPanel keeps referring to ``self.X`` unchanged.

All four tray surfaces (main panel + displays/adapters/drives side popups)
are now :class:`TrayPopupWindow` instances, which provide a shared shell
with a fancy title bar, a bottom-bar slot, and built-in drag/resize from
the window background and perimeter.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover
    from .panel import TrayPanel


def build(panel: TrayPanel) -> None:
    """Build the entire panel widget tree on the given TrayPanel instance."""
    from PySide6.QtCore import QSize, Qt  # type: ignore[import-not-found]
    from PySide6.QtWidgets import (  # type: ignore[import-not-found]
        QComboBox,
        QFrame,
        QGridLayout,
        QHBoxLayout,
        QLabel,
        QPushButton,
        QScrollArea,
        QSlider,
        QTabWidget,
        QToolButton,
        QVBoxLayout,
        QWidget,
    )

    from .widgets import _centered_icon_tab_bar_class

    CenteredIconTabBar = _centered_icon_tab_bar_class()
    _build_windows(panel)
    _build_media_tab(
        panel, Qt, QWidget, QHBoxLayout, QVBoxLayout, QLabel, QPushButton,
        QComboBox, QSlider, QFrame, QGridLayout, QTabWidget, QToolButton,
        CenteredIconTabBar,
    )
    _build_displays_popup(
        panel, Qt, QWidget, QHBoxLayout, QVBoxLayout, QLabel, QPushButton,
        QScrollArea, QFrame,
    )
    _build_network_tab(
        panel, Qt, QSize, QWidget, QHBoxLayout, QVBoxLayout, QLabel,
        QTabWidget, QScrollArea, QFrame, CenteredIconTabBar,
    )
    _build_adapters_popup(
        panel, Qt, QWidget, QVBoxLayout, QLabel, QPushButton,
        QScrollArea, QFrame,
    )
    _build_drives_popup(
        panel, Qt, QWidget, QVBoxLayout, QLabel, QPushButton,
        QScrollArea, QFrame,
    )
    _build_bottom_bar(panel, Qt, QPushButton)
    _build_fallback_tab(panel, Qt, QWidget, QVBoxLayout, QLabel, QPushButton)


def _build_windows(panel: TrayPanel) -> None:
    from .popup_window import tray_popup_window_class

    TrayPopupWindow = tray_popup_window_class()

    panel.window = TrayPopupWindow(
        "XTray",
        on_close=lambda: panel.hide(),
        minimum_width=320,
        minimum_height=300,
    )
    panel.window.set_content_margins(2, 12, 2, 2)
    panel.window.set_content_spacing(10)
    panel.layout = panel.window.content_layout

    panel.displays_popup = TrayPopupWindow(
        "Displays",
        parent=panel.window,
        on_close=lambda: panel.displays_popup.hide(),
        minimum_width=320,
        minimum_height=260,
        wordmark="displays",
    )
    panel.displays_popup.set_content_margins(8, 8, 8, 8)
    panel.displays_popup.set_content_spacing(6)

    panel.adapters_popup = TrayPopupWindow(
        "Adapters",
        parent=panel.window,
        on_close=lambda: panel.adapters_popup.hide(),
        minimum_width=320,
        minimum_height=320,
        wordmark="adapters",
    )
    panel.adapters_popup.set_content_margins(8, 8, 8, 8)
    panel.adapters_popup.set_content_spacing(6)

    panel.drives_popup = TrayPopupWindow(
        "Drives",
        parent=panel.window,
        on_close=lambda: panel.drives_popup.hide(),
        minimum_width=320,
        minimum_height=260,
        wordmark="drives",
    )
    panel.drives_popup.set_content_margins(8, 8, 8, 8)
    panel.drives_popup.set_content_spacing(6)

    panel._apply_theme()


def _build_media_tab(
    panel: TrayPanel,
    Qt: Any,
    QWidget: Any,
    QHBoxLayout: Any,
    QVBoxLayout: Any,
    QLabel: Any,
    QPushButton: Any,
    QComboBox: Any,
    QSlider: Any,
    QFrame: Any,
    QGridLayout: Any,
    QTabWidget: Any,
    QToolButton: Any,
    CenteredIconTabBar: Any,
) -> None:
    from PySide6.QtCore import QSize  # type: ignore[import-not-found]

    panel.header = panel.window.title_bar
    panel.hide_button = panel.header.close_button
    panel.header.set_theme(panel._theme)
    panel.displays_popup_button = panel._make_header_popup_button(
        "trayDisplaysPopupButton",
        "display.popup",
        panel.toggle_displays_popup,
    )
    panel.adapters_popup_button = panel._make_header_popup_button(
        "trayAdaptersPopupButton",
        "adapter.popup",
        panel.toggle_adapters_popup,
    )
    panel.drives_popup_button = panel._make_header_popup_button(
        "trayDrivesPopupButton",
        "drive.popup",
        panel.toggle_drives_popup,
    )
    panel.header.insert_action(panel.displays_popup_button)
    panel.header.insert_action(panel.adapters_popup_button)
    panel.header.insert_action(panel.drives_popup_button)
    panel.tabs = QTabWidget()
    panel.tabs.setObjectName("trayMainTabs")
    panel.tabs.setTabBar(CenteredIconTabBar(panel.tabs))
    panel.tabs.setIconSize(QSize(20, 20))
    panel.tabs.currentChanged.connect(panel.on_main_tab_changed)
    panel.layout.addWidget(panel.tabs)

    from PySide6.QtWidgets import QScrollArea  # type: ignore[import-not-found]

    panel.media_tab = QWidget()
    panel.media_layout = QVBoxLayout(panel.media_tab)
    panel.media_layout.setContentsMargins(0, 0, 0, 0)
    panel.media_layout.setSpacing(8)
    # Wrap the media tab in a scroll area so shrinking the panel reveals a
    # vertical scrollbar instead of clipping rows on top of each other.
    panel.media_scroll = QScrollArea()
    panel.media_scroll.setWidget(panel.media_tab)
    panel.media_scroll.setWidgetResizable(True)
    panel.media_scroll.setFrameShape(QFrame.Shape.NoFrame)
    panel.media_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    panel.media_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
    panel.tabs.addTab(panel.media_scroll, "Media")

    panel._media_device_sections = {}
    panel._collapsed_media_device_sections = set()

    def _displays_body_layout(body: Any) -> Any:
        layout = QVBoxLayout(body)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        return layout

    _add_media_device_section(
        panel,
        Qt,
        QWidget,
        QVBoxLayout,
        QToolButton,
        QGridLayout,
        "media_displays",
        "Displays",
        "display.popup",
        body_layout_factory=_displays_body_layout,
    )
    panel.media_displays_body_layout = panel.media_displays_layout

    panel.display_profiles_block = QWidget()
    panel.display_profiles_block.setObjectName("trayDisplayProfilesBlock")
    panel.button_container = panel.display_profiles_block
    panel.button_layout = QGridLayout(panel.display_profiles_block)
    panel.button_layout.setContentsMargins(0, 0, 0, 0)
    panel.button_layout.setHorizontalSpacing(6)
    panel.button_layout.setVerticalSpacing(6)
    for column in range(panel._media_profile_columns()):
        panel.button_layout.setColumnStretch(column, 1)
    panel.media_displays_body_layout.addWidget(panel.display_profiles_block)

    panel.media_displays_faceplates_body = QWidget()
    panel.media_displays_faceplates_body.setObjectName(
        "trayMediaDisplaysFaceplatesBody"
    )
    panel.media_displays_layout = QGridLayout(panel.media_displays_faceplates_body)
    panel.media_displays_layout.setContentsMargins(0, 0, 0, 0)
    panel.media_displays_layout.setHorizontalSpacing(6)
    panel.media_displays_layout.setVerticalSpacing(6)
    panel.media_displays_layout.setColumnStretch(0, 1)
    panel.media_displays_layout.setColumnStretch(1, 1)
    panel.media_displays_body_layout.addWidget(panel.media_displays_faceplates_body)
    panel._media_device_sections["media_displays"]["layout"] = (
        panel.media_displays_layout
    )

    panel.audio_row = QWidget()
    panel.audio_row_layout = QHBoxLayout(panel.audio_row)
    panel.audio_row_layout.setContentsMargins(0, 0, 0, 0)
    panel.audio_row_layout.setSpacing(8)
    panel.audio_label = panel._make_media_icon_label("media.audio_output")
    panel.audio_row_layout.addWidget(panel.audio_label)
    panel.audio_combo = QComboBox()
    # Theme repolish can otherwise promote the current item text to the
    # combo's minimum width, which widens the whole media scroll content.
    panel.audio_combo.setSizeAdjustPolicy(
        QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
    )
    panel.audio_combo.setMinimumContentsLength(12)
    panel.audio_combo.setMinimumHeight(32)
    panel.audio_combo.setToolTip(panel._action_label("media.audio_output"))
    panel.audio_combo.currentIndexChanged.connect(panel.on_audio_changed)
    panel.audio_row_layout.addWidget(panel.audio_combo, 1)

    panel.pc_volume_row = QWidget()
    panel.pc_volume_row_layout = QHBoxLayout(panel.pc_volume_row)
    panel.pc_volume_row_layout.setContentsMargins(0, 0, 0, 0)
    panel.pc_volume_row_layout.setSpacing(8)
    panel.pc_volume_label = panel._make_media_icon_label("media.pc_volume")
    panel.pc_volume_row_layout.addWidget(panel.pc_volume_label)
    panel.pc_volume_mute_button = QPushButton()
    panel.pc_volume_mute_button.setObjectName("trayPcVolumeMuteButton")
    panel.pc_volume_mute_button.setProperty("iconOnlyButton", True)
    panel.pc_volume_mute_button.setFixedSize(24, 24)
    panel.pc_volume_mute_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    panel.pc_volume_mute_button.setCursor(Qt.CursorShape.PointingHandCursor)
    panel.pc_volume_mute_button.clicked.connect(panel.on_pc_mute_clicked)
    panel.pc_volume_row_layout.addWidget(panel.pc_volume_mute_button)
    from .widgets import _volume_fill_bar_class

    panel.pc_volume_slider = _volume_fill_bar_class()(
        orientation=Qt.Orientation.Horizontal
    )
    panel.pc_volume_slider.setObjectName("trayPcVolumeFillBar")
    panel.pc_volume_slider.setColors(
        panel._theme.tray.subtle_border,
        panel._theme.tray.accent,
        panel._theme.tray.muted,
    )
    panel.pc_volume_slider.setFixedHeight(22)
    panel.pc_volume_slider.setMinimumWidth(72)
    panel.pc_volume_slider.setToolTip(panel._action_label("media.pc_volume"))
    panel.pc_volume_slider.valueChanged.connect(panel.on_pc_volume_changed)
    panel.pc_volume_slider.released.connect(panel.on_pc_volume_released)
    panel.pc_volume_row_layout.addWidget(panel.pc_volume_slider, 1)

    panel.display_volume_container = QFrame()
    panel.display_volume_layout = QVBoxLayout(panel.display_volume_container)
    panel.display_volume_layout.setContentsMargins(0, 0, 0, 0)
    panel.display_volume_layout.setSpacing(6)

    def _audio_body_layout(body: Any) -> Any:
        layout = QVBoxLayout(body)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        return layout

    _add_media_device_section(
        panel,
        Qt,
        QWidget,
        QVBoxLayout,
        QToolButton,
        QGridLayout,
        "media_audio_output",
        "Audio",
        "media.audio_output",
        body_layout_factory=_audio_body_layout,
    )
    panel.media_audio_output_layout.addWidget(panel.audio_row)
    panel.media_audio_output_layout.addWidget(panel.pc_volume_row)
    panel.media_audio_output_layout.addWidget(panel.display_volume_container)
    panel._media_row_widgets = {
        "audio_output": panel.media_audio_output_section,
        "media_displays": panel.media_displays_section,
    }

    _build_adapters_tab(
        panel,
        Qt,
        QWidget,
        QVBoxLayout,
        QToolButton,
        QGridLayout,
    )
    _build_drives_tab(
        panel,
        Qt,
        QWidget,
        QVBoxLayout,
        QToolButton,
        QGridLayout,
    )


def _build_adapters_tab(
    panel: TrayPanel,
    Qt: Any,
    QWidget: Any,
    QVBoxLayout: Any,
    QToolButton: Any,
    QGridLayout: Any,
) -> None:
    panel.adapters_tab = QWidget()
    panel.adapters_tab_layout = QVBoxLayout(panel.adapters_tab)
    panel.adapters_tab_layout.setContentsMargins(0, 0, 0, 0)
    panel.adapters_tab_layout.setSpacing(8)
    _add_media_device_section(
        panel,
        Qt,
        QWidget,
        QVBoxLayout,
        QToolButton,
        QGridLayout,
        "media_adapters",
        "Network adapters",
        "adapter.popup",
        parent_layout=panel.adapters_tab_layout,
    )
    panel.adapters_tab_layout.addStretch(1)


def _build_drives_tab(
    panel: TrayPanel,
    Qt: Any,
    QWidget: Any,
    QVBoxLayout: Any,
    QToolButton: Any,
    QGridLayout: Any,
) -> None:
    panel.drives_tab = QWidget()
    panel.drives_tab_layout = QVBoxLayout(panel.drives_tab)
    panel.drives_tab_layout.setContentsMargins(0, 0, 0, 0)
    panel.drives_tab_layout.setSpacing(8)
    _add_media_device_section(
        panel,
        Qt,
        QWidget,
        QVBoxLayout,
        QToolButton,
        QGridLayout,
        "media_drives",
        "Drives",
        "drive.popup",
        parent_layout=panel.drives_tab_layout,
    )
    panel.drives_tab_layout.addStretch(1)


def _add_media_device_section(
    panel: TrayPanel,
    Qt: Any,
    QWidget: Any,
    QVBoxLayout: Any,
    QToolButton: Any,
    QGridLayout: Any,
    row_id: str,
    title: str,
    action_id: str,
    *,
    parent_layout: Any = None,
    body_layout_factory: Any = None,
) -> None:
    section = QWidget()
    section.setObjectName("trayMediaDeviceSection")
    section_layout = QVBoxLayout(section)
    section_layout.setContentsMargins(0, 0, 0, 0)
    section_layout.setSpacing(6)

    header = QToolButton()
    header.setObjectName("trayMediaDeviceSectionHeader")
    header.setCheckable(True)
    header.setChecked(True)
    header.setText(title)
    header.setToolTip(title)
    header.setAccessibleName(title)
    header.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
    header.setCursor(Qt.CursorShape.PointingHandCursor)
    header.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    header.toggled.connect(
        lambda expanded, current=row_id: panel._set_media_device_section_expanded(
            current,
            bool(expanded),
        )
    )
    section_layout.addWidget(header)

    body = QWidget()
    body.setObjectName("trayMediaDeviceSectionBody")
    if body_layout_factory is not None:
        body_layout = body_layout_factory(body)
    else:
        body_layout = QGridLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setHorizontalSpacing(6)
        body_layout.setVerticalSpacing(6)
        body_layout.setColumnStretch(0, 1)
        body_layout.setColumnStretch(1, 1)
    section_layout.addWidget(body)
    target_layout = parent_layout if parent_layout is not None else panel.media_layout
    target_layout.addWidget(section)

    attr = row_id.removeprefix("media_")
    setattr(panel, f"media_{attr}_section", section)
    setattr(panel, f"media_{attr}_header", header)
    setattr(panel, f"media_{attr}_body", body)
    setattr(panel, f"media_{attr}_layout", body_layout)
    panel._media_device_sections[row_id] = {
        "section": section,
        "header": header,
        "body": body,
        "layout": body_layout,
        "action_id": action_id,
        "title": title,
    }


def _build_displays_popup(
    panel: TrayPanel,
    Qt: Any,
    QWidget: Any,
    QHBoxLayout: Any,
    QVBoxLayout: Any,
    QLabel: Any,
    QPushButton: Any,
    QScrollArea: Any,
    QFrame: Any,
) -> None:
    panel.displays_layout = panel.displays_popup.content_layout
    panel.displays_header = panel.displays_popup.title_bar
    panel.displays_header.set_theme(panel._theme)
    panel.displays_title = panel.displays_header.title_label
    panel.displays_popup_close_button = panel.displays_header.close_button
    panel.displays_refresh_button = QPushButton(panel._fallback_label("display.refresh"))
    panel.displays_refresh_button.setObjectName("trayDisplaysRefreshButton")
    panel.displays_refresh_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    panel.displays_refresh_button.clicked.connect(panel.on_displays_refresh_clicked)
    panel.displays_header.insert_action(panel.displays_refresh_button)
    panel.displays_scroll = QScrollArea()
    panel.displays_scroll.setWidgetResizable(True)
    panel.displays_scroll.setFrameShape(QFrame.Shape.NoFrame)
    panel.displays_scroll.setContentsMargins(0, 0, 0, 0)
    panel.displays_scroll.setViewportMargins(0, 0, 0, 0)
    panel.displays_scroll.setHorizontalScrollBarPolicy(
        Qt.ScrollBarPolicy.ScrollBarAlwaysOff
    )
    panel.displays_scroll.setMinimumWidth(288)
    panel.displays_container = QWidget()
    panel.displays_list_layout = QVBoxLayout(panel.displays_container)
    panel.displays_list_layout.setContentsMargins(0, 0, 0, 0)
    panel.displays_list_layout.setSpacing(6)
    panel.displays_list_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
    panel.displays_scroll.setWidget(panel.displays_container)
    panel.displays_layout.addWidget(panel.displays_scroll)
    panel.displays_status = QLabel("")
    panel.displays_status.setObjectName("trayPanelStatus")
    panel.displays_status.setWordWrap(True)
    panel.displays_layout.addWidget(panel.displays_status)


def _build_network_tab(
    panel: TrayPanel,
    Qt: Any,
    QSize: Any,
    QWidget: Any,
    QHBoxLayout: Any,
    QVBoxLayout: Any,
    QLabel: Any,
    QTabWidget: Any,
    QScrollArea: Any,
    QFrame: Any,
    CenteredIconTabBar: Any,
) -> None:
    from ..services.network import devices as network

    panel.network_tab = QWidget()
    panel.network_layout = QVBoxLayout(panel.network_tab)
    panel.network_layout.setContentsMargins(0, 0, 0, 0)
    panel.network_layout.setSpacing(10)
    panel.tabs.addTab(panel.network_tab, "Network")
    panel.network_header = QWidget()
    panel.network_header_layout = QHBoxLayout(panel.network_header)
    panel.network_header_layout.setContentsMargins(0, 0, 0, 0)
    panel.network_header_layout.setSpacing(8)
    panel.network_title = QLabel("Network devices")
    panel.network_title.setObjectName("trayPanelTitle")
    panel.network_header_layout.addWidget(panel.network_title, 1)
    panel.network_layout.addWidget(panel.network_header)
    panel.network_kind_tabs = QTabWidget()
    panel.network_kind_tabs.setObjectName("trayNetworkKindTabs")
    panel.network_kind_tabs.setTabBar(CenteredIconTabBar(panel.network_kind_tabs))
    panel.network_kind_tabs.setIconSize(QSize(20, 20))
    panel._network_kind_layouts = {}
    panel._network_kind_empty_labels = {}
    panel._network_kind_scrolls: dict[str, Any] = {}
    for kind in network.DEVICE_KINDS:
        kind_tab = QWidget()
        kind_layout = QVBoxLayout(kind_tab)
        kind_layout.setContentsMargins(2, 2, 2, 2)
        kind_layout.setSpacing(8)
        # Wrap each kind tab in a scroll area so a long device list scrolls
        # vertically instead of getting clipped.
        kind_scroll = QScrollArea()
        kind_scroll.setWidget(kind_tab)
        kind_scroll.setWidgetResizable(True)
        kind_scroll.setFrameShape(QFrame.Shape.NoFrame)
        kind_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        kind_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        index = panel.network_kind_tabs.addTab(kind_scroll, "")
        panel.network_kind_tabs.setTabToolTip(
            index,
            panel._action_label(f"network.kind.{kind}"),
        )
        panel._network_kind_layouts[kind] = kind_layout
        panel._network_kind_empty_labels[kind] = None
        panel._network_kind_scrolls[kind] = kind_scroll
    panel._apply_network_kind_tab_icons()
    panel.network_layout.addWidget(panel.network_kind_tabs)
    panel.network_status = QLabel("")
    panel.network_status.setObjectName("trayPanelStatus")
    panel.network_status.setWordWrap(True)
    panel.network_layout.addWidget(panel.network_status)


def _build_adapters_popup(
    panel: TrayPanel,
    Qt: Any,
    QWidget: Any,
    QVBoxLayout: Any,
    QLabel: Any,
    QPushButton: Any,
    QScrollArea: Any,
    QFrame: Any,
) -> None:
    panel.adapters_layout = panel.adapters_popup.content_layout
    panel.adapters_header = panel.adapters_popup.title_bar
    panel.adapters_header.set_theme(panel._theme)
    panel.adapters_title = panel.adapters_header.title_label
    panel.adapters_popup_close_button = panel.adapters_header.close_button
    panel.adapters_refresh_button = QPushButton(panel._fallback_label("adapter.refresh"))
    panel.adapters_refresh_button.setObjectName("trayAdaptersRefreshButton")
    panel.adapters_refresh_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    panel.adapters_refresh_button.clicked.connect(panel.on_adapters_refresh_clicked)
    panel.adapters_header.insert_action(panel.adapters_refresh_button)
    panel.adapters_network_connections_button = QPushButton(
        panel._fallback_label("adapter.network_connections")
    )
    panel.adapters_network_connections_button.setObjectName(
        "trayAdaptersNetworkConnectionsButton"
    )
    panel.adapters_network_connections_button.setProperty("surfaceAction", "window")
    panel.adapters_network_connections_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    panel.adapters_network_connections_button.clicked.connect(
        panel.on_network_connections_clicked
    )
    panel.adapters_header.insert_action(panel.adapters_network_connections_button)
    panel.adapters_scroll = QScrollArea()
    panel.adapters_scroll.setWidgetResizable(True)
    panel.adapters_scroll.setFrameShape(QFrame.Shape.NoFrame)
    panel.adapters_scroll.setContentsMargins(0, 0, 0, 0)
    panel.adapters_scroll.setViewportMargins(0, 0, 0, 0)
    panel.adapters_container = QWidget()
    panel.adapters_list_layout = QVBoxLayout(panel.adapters_container)
    panel.adapters_list_layout.setContentsMargins(0, 0, 0, 0)
    panel.adapters_list_layout.setSpacing(8)
    panel.adapters_scroll.setWidget(panel.adapters_container)
    panel.adapters_layout.addWidget(panel.adapters_scroll, 1)
    panel.adapters_status = QLabel("")
    panel.adapters_status.setObjectName("trayPanelStatus")
    panel.adapters_status.setWordWrap(True)
    panel.adapters_layout.addWidget(panel.adapters_status)


def _build_drives_popup(
    panel: TrayPanel,
    Qt: Any,
    QWidget: Any,
    QVBoxLayout: Any,
    QLabel: Any,
    QPushButton: Any,
    QScrollArea: Any,
    QFrame: Any,
) -> None:
    panel.drives_layout = panel.drives_popup.content_layout
    panel.drives_header = panel.drives_popup.title_bar
    panel.drives_header.set_theme(panel._theme)
    panel.drives_title = panel.drives_header.title_label
    panel.drives_popup_close_button = panel.drives_header.close_button
    panel.drives_refresh_button = QPushButton(panel._fallback_label("drive.refresh"))
    panel.drives_refresh_button.setObjectName("trayDrivesRefreshButton")
    panel.drives_refresh_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    panel.drives_refresh_button.clicked.connect(panel.on_drives_refresh_clicked)
    panel.drives_header.insert_action(panel.drives_refresh_button)
    panel.drives_add_button = QPushButton(panel._fallback_label("drive.add_network"))
    panel.drives_add_button.setObjectName("trayDrivesAddNetworkButton")
    panel.drives_add_button.setProperty("surfaceAction", "window")
    panel.drives_add_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    panel.drives_add_button.clicked.connect(panel.on_add_network_drive)
    panel.drives_header.insert_action(panel.drives_add_button)
    panel.drives_scroll = QScrollArea()
    panel.drives_scroll.setWidgetResizable(True)
    panel.drives_scroll.setFrameShape(QFrame.Shape.NoFrame)
    panel.drives_scroll.setContentsMargins(0, 0, 0, 0)
    panel.drives_scroll.setViewportMargins(0, 0, 0, 0)
    panel.drives_container = QWidget()
    panel.drives_list_layout = QVBoxLayout(panel.drives_container)
    panel.drives_list_layout.setContentsMargins(0, 0, 0, 0)
    panel.drives_list_layout.setSpacing(8)
    panel.drives_scroll.setWidget(panel.drives_container)
    panel.drives_layout.addWidget(panel.drives_scroll, 1)
    panel.drives_status = QLabel("")
    panel.drives_status.setObjectName("trayPanelStatus")
    panel.drives_status.setWordWrap(True)
    panel.drives_layout.addWidget(panel.drives_status)


def _build_bottom_bar(
    panel: TrayPanel,
    Qt: Any,
    QPushButton: Any,
) -> None:
    from xtray.core import qt_assets

    from .widgets import _StatusIndicator

    panel.bottom_bar = panel.window.bottom_bar
    panel.bottom_bar_layout = panel.bottom_bar._layout
    panel.mqtt_indicator = _StatusIndicator(
        "MQTT",
        qt_assets.MQTT_LOGO_ASSET,
    )
    panel.bottom_bar.add_widget(panel.mqtt_indicator.widget)
    panel.ha_indicator = _StatusIndicator(
        "Home Assistant",
        qt_assets.HOME_ASSISTANT_LOGO_ASSET,
    )
    panel.mqtt_indicator.set_theme(panel._theme)
    panel.ha_indicator.set_theme(panel._theme)
    panel.bottom_bar.add_widget(panel.ha_indicator.widget)
    panel.bottom_bar.add_stretch(1)
    panel.options_button = QPushButton(panel._fallback_label("fallback.options"))
    panel.options_button.setObjectName("trayPanelOptionsButton")
    panel.options_button.setProperty("iconOnlyButton", True)
    panel.options_button.setProperty("surfaceAction", "window")
    panel.options_button.setFixedSize(32, 28)
    panel.options_button.setCursor(Qt.CursorShape.PointingHandCursor)
    panel.options_button.setToolTip(panel._action_label("fallback.options"))
    panel.options_button.setAccessibleName(panel._action_label("fallback.options"))
    panel.options_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    open_options = getattr(panel.controller, "open_options", None)
    if callable(open_options):
        panel.options_button.clicked.connect(lambda _checked=False: open_options())
    else:
        panel.options_button.setEnabled(False)
    panel.bottom_bar.add_widget(panel.options_button)
    panel.network_manage_button = QPushButton(panel._fallback_label("network.manage"))
    panel.network_manage_button.setObjectName("trayPanelNetworkManagerButton")
    panel.network_manage_button.setProperty("iconOnlyButton", True)
    panel.network_manage_button.setProperty("surfaceAction", "window")
    panel.network_manage_button.setFixedSize(32, 28)
    panel.network_manage_button.setCursor(Qt.CursorShape.PointingHandCursor)
    panel.network_manage_button.setToolTip(panel._action_label("network.manage"))
    panel.network_manage_button.setAccessibleName(panel._action_label("network.manage"))
    panel.network_manage_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    panel.network_manage_button.clicked.connect(panel.on_network_manage)
    panel.bottom_bar.add_widget(panel.network_manage_button)
    computer_action = panel._action_icon("header.computer_manager")
    panel.computer_manager_button = QPushButton(computer_action["fallback_label"])
    panel.computer_manager_button.setObjectName("trayPanelComputerManagerButton")
    panel.computer_manager_button.setProperty("iconOnlyButton", True)
    panel.computer_manager_button.setProperty("surfaceAction", "window")
    panel.computer_manager_button.setFixedSize(32, 28)
    panel.computer_manager_button.setCursor(Qt.CursorShape.PointingHandCursor)
    panel.computer_manager_button.setToolTip(computer_action["label"])
    panel.computer_manager_button.setAccessibleName(computer_action["label"])
    panel.computer_manager_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    open_gui = getattr(panel.controller, "open_gui", None)
    if callable(open_gui):
        panel.computer_manager_button.clicked.connect(open_gui)
    else:
        panel.computer_manager_button.setEnabled(False)
    panel.bottom_bar.add_widget(panel.computer_manager_button)


def _build_fallback_tab(
    panel: TrayPanel,
    Qt: Any,
    QWidget: Any,
    QVBoxLayout: Any,
    QLabel: Any,
    QPushButton: Any,
) -> None:
    panel.fallback_tab = QWidget()
    panel.fallback_layout = QVBoxLayout(panel.fallback_tab)
    panel.fallback_layout.setContentsMargins(0, 0, 0, 0)
    panel.fallback_label = QLabel("All tray tabs are hidden.")
    panel.fallback_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    panel.fallback_layout.addWidget(panel.fallback_label)
    panel.fallback_options_button = QPushButton("Options")
    panel.fallback_options_button.setObjectName("trayFallbackOptionsButton")
    panel.fallback_options_button.setProperty("surfaceAction", "window")
    panel.fallback_options_button.clicked.connect(
        lambda _checked=False: panel.controller.open_options()
    )
    panel.fallback_layout.addWidget(
        panel.fallback_options_button, 0, Qt.AlignmentFlag.AlignCenter
    )
    panel.fallback_layout.addStretch(1)
