"""Qt stylesheet builders for application and tray surfaces."""
from __future__ import annotations

from .dataclasses import AppTheme, ButtonRole, ButtonTheme
from .palettes import DEFAULT_THEME


def build_stylesheet(theme: AppTheme = DEFAULT_THEME) -> str:
    """Compatibility wrapper for the standard application stylesheet."""
    return build_app_stylesheet(theme)


def build_app_stylesheet(theme: AppTheme = DEFAULT_THEME) -> str:
    """Build Qt stylesheet text from shared application theme tokens."""
    return f"""
QMainWindow, QDialog, QWidget {{
    background-color: {theme.window_background};
    color: {theme.text};
    font-family: "Segoe UI Variable", "Segoe UI";
}}

QMenuBar, QMenu, QStatusBar {{
    background-color: {theme.panel_background};
    color: {theme.text};
}}

QMenuBar::item:selected, QMenu::item:selected {{
    background-color: {theme.selection_background};
    color: {theme.selection_text};
}}

QToolTip {{
    background-color: {theme.panel_background};
    border: 1px solid {theme.panel_border};
    color: {theme.text};
}}

QGraphicsView, QListWidget, QPlainTextEdit, QTableWidget, QTableView, QTreeView {{
    background-color: {theme.panel_background};
    border: 1px solid {theme.panel_border};
    border-radius: {theme.metrics.radius_medium}px;
    color: {theme.text};
}}

QPlainTextEdit {{
    selection-background-color: {theme.selection_background};
    selection-color: {theme.selection_text};
}}

QHeaderView::section {{
    background-color: {theme.tables.header_background};
    border: 1px solid {theme.tables.grid_line};
    color: {theme.tables.header_text};
    font-weight: 600;
    padding: 5px 7px;
}}

QTableWidget {{
    alternate-background-color: {theme.tables.alternate_row};
    gridline-color: {theme.tables.grid_line};
}}

QTableWidget::item:selected, QTableView::item:selected {{
    background-color: {theme.selection_background};
    color: {theme.selection_text};
}}

QListWidget {{
    padding: 6px;
    outline: 0;
}}

QListWidget::item {{
    border-radius: {theme.metrics.radius_small}px;
    padding: 7px 9px;
    color: {theme.text};
}}

QListWidget::item:hover {{
    background-color: {theme.tables.hover_row};
}}

QListWidget::item:selected {{
    background-color: {theme.selection_background};
    color: {theme.selection_text};
}}

QTabWidget::pane {{
    border: 1px solid {theme.panel_border};
    border-radius: {theme.metrics.radius_medium}px;
    top: -1px;
}}

QTabBar::tab {{
    background-color: {theme.control_background};
    border: 1px solid {theme.panel_border};
    border-bottom-color: {theme.control_border};
    border-top-left-radius: {theme.metrics.radius_small}px;
    border-top-right-radius: {theme.metrics.radius_small}px;
    color: {theme.text};
    min-height: {theme.metrics.app_control_height}px;
    padding: 6px 14px;
}}

QTabBar::tab:selected {{
    background-color: {theme.selection_background};
    border-color: {theme.control_focus};
    color: {theme.selection_text};
}}

QTabBar::tab:hover {{
    background-color: {theme.buttons.default.hover};
    color: {theme.text};
}}

QGroupBox {{
    border: 1px solid {theme.panel_border};
    border-radius: {theme.metrics.radius_medium}px;
    color: {theme.text};
    font-weight: 600;
    margin-top: 12px;
    padding: 10px 8px 8px 8px;
}}

QGroupBox::title {{
    subcontrol-origin: margin;
    left: 8px;
    padding: 0 4px;
}}

QGroupBox[selected="true"] {{
    border-color: {theme.control_focus};
}}

QLabel {{
    color: {theme.text};
}}

QLabel#trayPanelStatus, QLabel[muted="true"] {{
    color: {theme.muted_text};
}}

QLabel#dialogTitle {{
    color: {theme.text};
    font-weight: 700;
}}

QLineEdit, QComboBox, QSpinBox {{
    background-color: {theme.control_background};
    border: 1px solid {theme.control_border};
    border-radius: {theme.metrics.radius_small}px;
    color: {theme.text};
    min-height: {theme.metrics.app_control_height}px;
    padding: 3px 8px;
    selection-background-color: {theme.selection_background};
    selection-color: {theme.selection_text};
}}

QLineEdit:focus, QComboBox:focus, QSpinBox:focus {{
    border-color: {theme.control_focus};
}}

QCheckBox {{
    color: {theme.text};
    spacing: 8px;
}}

QCheckBox::indicator {{
    background-color: {theme.control_background};
    border: 1px solid {theme.control_border};
    border-radius: 4px;
    height: 16px;
    width: 16px;
}}

QCheckBox::indicator:checked {{
    background-color: {theme.buttons.primary.background};
    border-color: {theme.buttons.primary.border};
}}

QProgressBar {{
    background-color: {theme.control_background};
    border: 1px solid {theme.control_border};
    border-radius: {theme.metrics.radius_small}px;
    color: {theme.text};
    min-height: 18px;
    text-align: center;
}}

QProgressBar::chunk {{
    background-color: {theme.palette.accent};
    border-radius: {theme.metrics.radius_small}px;
}}

QPushButton, QToolButton {{
    background-color: {theme.buttons.default.background};
    border: 1px solid {theme.buttons.default.border};
    border-radius: 7px;
    color: {theme.buttons.default.text};
    font-weight: 600;
    min-height: 32px;
    padding: 5px 12px;
}}

QPushButton:hover, QToolButton:hover {{
    background-color: {theme.buttons.default.hover};
}}

QPushButton:pressed, QToolButton:pressed {{
    background-color: {theme.buttons.default.pressed};
}}

{_button_role_qss("primary", theme.buttons.primary)}
{_button_role_qss("success", theme.buttons.success)}
{_button_role_qss("danger", theme.buttons.danger)}
{_button_role_qss("info", theme.buttons.info)}
{_button_role_qss("accent", theme.buttons.accent)}
{_disabled_button_qss(theme.buttons)}
""".strip()


def build_tray_stylesheet(theme: AppTheme = DEFAULT_THEME) -> str:
    """Build stylesheet text for frameless tray panels and popups."""
    tray = theme.tray
    palette = theme.palette
    metrics = theme.metrics
    toggle_width = metrics.display_toggle_button_width - 2
    power_width = metrics.display_power_button_width - 2
    return f"""
QWidget#trayPanel {{
    background-color: transparent;
    color: {tray.text};
    font-family: "Segoe UI Variable", "Segoe UI";
}}

QWidget#trayPanel QWidget {{
    background-color: transparent;
    color: {tray.text};
    font-family: "Segoe UI Variable", "Segoe UI";
}}

QWidget#trayPanelHeader {{
    background-color: transparent;
    border: none;
}}

QLabel#trayPanelHeaderTitle {{
    color: {tray.text};
    font-size: 13px;
    font-weight: 600;
    padding-left: 6px;
}}

QLabel#trayPanelTitle {{
    color: {tray.text};
    font-size: 14px;
    font-weight: 600;
}}

QLabel#trayPanelSection {{
    color: {tray.text};
    font-weight: 600;
}}

QLabel#trayPanelStatus {{
    color: {tray.muted};
}}

QWidget#trayPanel QFrame {{
    background-color: transparent;
    border: none;
}}

QWidget#trayPanel QFrame#trayPanelBottomBar {{
    border-top: 1px solid {tray.subtle_border};
}}

QWidget#trayPanel QFrame#trayDisplayRow,
QWidget#trayPanel QFrame#trayListRow {{
    background-color: {tray.row_surface};
    border: 1px solid {tray.subtle_border};
    border-radius: {metrics.radius_medium}px;
}}

QWidget#trayPanel QFrame#trayDisplayRow:hover,
QWidget#trayPanel QFrame#trayListRow:hover {{
    background-color: {tray.row_surface_hover};
    border-color: {tray.border};
}}

QWidget#trayPanel QFrame#trayDisplayRow[displayRole="primary"] {{
    background-color: {tray.primary_display_surface};
    border-color: {tray.primary_display_border};
}}

QWidget#trayPanel QFrame#trayDisplayRow[displayRole="primary"]:hover {{
    background-color: {tray.primary_display_surface_hover};
    border-color: {tray.primary_display_border};
}}

QWidget#trayPanel QFrame#trayDisplayRow[displayState="disabled"] {{
    border-color: {tray.warning};
}}

QLabel#trayDisplayTitle {{
    color: {tray.text};
    font-size: 13px;
    font-weight: 700;
}}

QFrame#trayDisplayRow[displayRole="primary"] QLabel#trayDisplayTitle {{
    color: {tray.primary_display_text};
}}

QLabel#trayDisplayInfo,
QLabel#trayDisplayControlLabel {{
    color: {tray.muted};
}}

QLabel#trayDisplayInlineInfo {{
    background-color: {tray.control_pressed};
    border: 1px solid {tray.subtle_border};
    border-radius: {metrics.radius_small}px;
    color: {tray.muted};
    font-size: 11px;
    font-weight: 600;
    min-height: 22px;
    padding: 1px 8px;
}}

QWidget#trayPanel QPushButton#trayDisplayVolumeMuteButton,
QWidget#trayPanel QPushButton#trayPcVolumeMuteButton {{
    background-color: transparent;
    border: 1px solid transparent;
    border-radius: {metrics.radius_small}px;
    min-height: 22px;
    max-height: 24px;
    min-width: 22px;
    max-width: 24px;
    padding: 0;
}}

QWidget#trayPanel QPushButton#trayDisplayVolumeMuteButton:hover,
QWidget#trayPanel QPushButton#trayPcVolumeMuteButton:hover {{
    background-color: {tray.control_hover};
    border-color: {tray.border};
}}

QWidget#trayPanel QPushButton#trayDisplayVolumeMuteButton:pressed,
QWidget#trayPanel QPushButton#trayPcVolumeMuteButton:pressed {{
    background-color: {tray.control_pressed};
    border-color: {tray.accent};
}}

QWidget#trayPanel QPushButton#trayDisplayVolumeMuteButton[muted="true"],
QWidget#trayPanel QPushButton#trayPcVolumeMuteButton[muted="true"] {{
    background-color: {tray.control_pressed};
    border-color: {tray.subtle_border};
}}

QWidget#trayPanel QPushButton#trayDisplayVolumeMuteButton:disabled,
QWidget#trayPanel QPushButton#trayPcVolumeMuteButton:disabled {{
    background-color: transparent;
    border-color: transparent;
}}

QWidget#trayPanel QToolButton#trayMediaDeviceSectionHeader {{
    background-color: {tray.control};
    border: 1px solid {tray.border};
    border-radius: {metrics.radius_small}px;
    color: {tray.text};
    font-weight: 600;
    min-height: {metrics.control_height}px;
    padding: 4px 8px;
    text-align: left;
}}

QWidget#trayPanel QToolButton#trayMediaDeviceSectionHeader:hover {{
    background-color: {tray.control_hover};
}}

QWidget#trayPanel QToolButton#trayMediaDeviceSectionHeader:pressed {{
    background-color: {tray.control_pressed};
}}

QWidget#trayPanel QToolButton#trayMediaDeviceSectionHeader[expanded="true"] {{
    background-color: {tray.accent};
    border-color: {tray.accent};
    color: {tray.accent_text};
}}

QWidget#trayPanel QToolButton#trayMediaDeviceSectionHeader[expanded="true"]:hover {{
    background-color: {tray.accent_hover};
    border-color: {tray.accent_hover};
}}

QWidget#trayPanel QToolButton#trayMediaDeviceSectionHeader[expanded="true"]:pressed {{
    background-color: {tray.accent_pressed};
    border-color: {tray.accent_pressed};
}}

QWidget#trayPanel QPushButton#trayMediaDeviceFaceplate {{
    background-color: {tray.row_surface};
    border: 1px solid {tray.subtle_border};
    border-radius: {metrics.radius_small}px;
    color: {tray.text};
    font-weight: 600;
    min-height: 54px;
    padding: 6px 8px;
    text-align: left;
}}

QWidget#trayPanel QPushButton#trayMediaDeviceFaceplate[deviceKind="display"] {{
    font-size: 11px;
    font-weight: 700;
    min-height: 56px;
    padding: 4px;
    text-align: center;
}}

QWidget#trayPanel QPushButton#trayMediaDeviceFaceplate[deviceKind="adapter"] {{
    font-size: 11px;
    min-height: 66px;
    padding: 5px 6px;
    text-align: center;
}}

QWidget#trayPanel QPushButton#trayMediaDeviceFaceplate:hover {{
    background-color: {tray.row_surface_hover};
    border-color: {tray.border};
}}

QWidget#trayPanel QPushButton#trayMediaDeviceFaceplate[deviceStatus="primary"] {{
    background-color: {tray.faceplate_primary_bg};
    border-color: {tray.faceplate_primary_border};
    color: {tray.faceplate_primary_text};
}}

QWidget#trayPanel QPushButton#trayMediaDeviceFaceplate[deviceStatus="enabled"],
QWidget#trayPanel QPushButton#trayMediaDeviceFaceplate[deviceStatus="active"],
QWidget#trayPanel QPushButton#trayMediaDeviceFaceplate[deviceStatus="ok"] {{
    background-color: {tray.faceplate_enabled_bg};
    border-color: {tray.faceplate_enabled_border};
    color: {tray.faceplate_enabled_text};
}}

QWidget#trayPanel QPushButton#trayMediaDeviceFaceplate[deviceStatus="limited"],
QWidget#trayPanel QPushButton#trayMediaDeviceFaceplate[deviceStatus="warning"],
QWidget#trayPanel QPushButton#trayMediaDeviceFaceplate[deviceStatus="disabled"] {{
    background-color: {tray.faceplate_disabled_bg};
    border-color: {tray.faceplate_disabled_border};
    color: {tray.faceplate_disabled_text};
}}

QWidget#trayPanel QPushButton#trayMediaDeviceFaceplate[deviceStatus="full"],
QWidget#trayPanel QPushButton#trayMediaDeviceFaceplate[deviceStatus="disconnected"] {{
    background-color: {palette.danger};
    border-color: {palette.danger};
    color: {palette.danger_text};
}}

QWidget#trayPanel QPushButton#trayMediaDeviceFaceplate[deviceStatus="unavailable"] {{
    background-color: {tray.faceplate_unavailable_bg};
    border-color: {tray.faceplate_unavailable_border};
    color: {tray.faceplate_unavailable_text};
}}

QWidget#trayPanel QPushButton {{
    background-color: {tray.control};
    border: 1px solid {tray.border};
    border-radius: {metrics.radius_small}px;
    color: {tray.text};
    font-weight: 400;
    min-height: {metrics.control_height}px;
    padding: 4px 11px;
}}

QWidget#trayPanel QPushButton:hover {{
    background-color: {tray.control_hover};
}}

QWidget#trayPanel QPushButton:pressed {{
    background-color: {tray.control_pressed};
}}

QWidget#trayPanel QPushButton#trayDisplaysPopupButton,
QWidget#trayPanel QPushButton[trayPopupButton="true"],
QWidget#trayPanel QPushButton[iconOnlyButton="true"],
QWidget#trayPanel QPushButton#trayPanelComputerManagerButton {{
    min-height: {metrics.control_height}px;
    min-width: 32px;
    max-width: 32px;
    padding: 0px;
}}

QWidget#trayPanel QPushButton[role="primary"] {{
    background-color: {tray.accent};
    border-color: {tray.accent};
    color: {tray.accent_text};
}}

QWidget#trayPanel QPushButton[role="primary"]:hover {{
    background-color: {tray.accent_hover};
    border-color: {tray.accent_hover};
}}

QWidget#trayPanel QPushButton[role="primary"]:pressed {{
    background-color: {tray.accent_pressed};
    border-color: {tray.accent_pressed};
}}

QWidget#trayPanel QPushButton[surfaceAction="popup"],
QWidget#trayPanel QPushButton[surfaceAction="window"] {{
    background-color: {tray.accent_pressed};
    border-color: {tray.accent_pressed};
    color: {tray.accent_text};
}}

QWidget#trayPanel QPushButton[surfaceAction="popup"]:hover,
QWidget#trayPanel QPushButton[surfaceAction="window"]:hover {{
    background-color: {tray.accent};
    border-color: {tray.accent};
}}

QWidget#trayPanel QPushButton[surfaceAction="popup"]:pressed,
QWidget#trayPanel QPushButton[surfaceAction="popup"][popupOpen="true"],
QWidget#trayPanel QPushButton[surfaceAction="popup"][popupOpen="true"]:hover,
QWidget#trayPanel QPushButton[surfaceAction="window"]:pressed,
QWidget#trayPanel QPushButton[surfaceAction="window"][popupOpen="true"],
QWidget#trayPanel QPushButton[surfaceAction="window"][popupOpen="true"]:hover {{
    background-color: {tray.accent};
    border-color: {tray.accent};
    color: {tray.accent_text};
}}

QWidget#trayPanel QToolButton#trayProfileButton {{
    background-color: {tray.accent};
    border: 1px solid {tray.accent};
    border-radius: {metrics.radius_small}px;
    color: {tray.accent_text};
    font-size: 11px;
    font-weight: 500;
    min-height: 56px;
    padding: 4px;
}}

QWidget#trayPanel QToolButton#trayProfileButton:hover {{
    background-color: {tray.accent_hover};
    border-color: {tray.accent_hover};
}}

QWidget#trayPanel QToolButton#trayProfileButton:pressed {{
    background-color: {tray.accent_pressed};
    border-color: {tray.accent_pressed};
}}

QWidget#trayPanel QToolButton#trayProfileButton[profileState="active"] {{
    background-color: {tray.faceplate_primary_bg};
    border-color: {tray.faceplate_primary_border};
    color: {tray.faceplate_primary_text};
}}

QWidget#trayPanel QToolButton#trayProfileButton[profileState="active"]:hover {{
    background-color: {tray.faceplate_primary_bg};
    border-color: {tray.accent_hover};
}}

QWidget#trayPanel QToolButton#trayProfileButton[profileState="active"]:pressed {{
    background-color: {tray.faceplate_primary_bg};
    border-color: {tray.accent_pressed};
}}

QWidget#trayPanel QToolButton#trayProfileButton[profileState="missing"] {{
    background-color: {tray.faceplate_disabled_bg};
    border-color: {tray.faceplate_disabled_border};
    color: {tray.faceplate_disabled_text};
}}

QWidget#trayPanel QToolButton#trayProfileButton[profileState="missing"]:hover {{
    background-color: {tray.faceplate_disabled_bg};
    border-color: {tray.accent_hover};
}}

QWidget#trayPanel QToolButton#trayProfileButton[profileState="missing"]:pressed {{
    background-color: {tray.faceplate_disabled_bg};
    border-color: {tray.accent_pressed};
}}

QWidget#trayPanel QToolButton#trayProfileButton:disabled {{
    background-color: {tray.control_pressed};
    border-color: {tray.subtle_border};
    color: {tray.muted};
}}

QWidget#trayPanel QPushButton#trayDisplayToggleButton {{
    font-weight: 600;
    min-width: {toggle_width}px;
    max-width: {toggle_width}px;
    padding: 4px 0px;
}}

QWidget#trayPanel QPushButton#trayDisplayPowerButton {{
    min-width: {power_width}px;
    max-width: {power_width}px;
    padding: 4px 0px;
}}

QWidget#trayPanel QPushButton#trayDisplayMakePrimaryButton {{
    min-width: {toggle_width}px;
    max-width: {toggle_width}px;
    padding: 4px 0px;
}}

QWidget#trayPanel QLabel#trayDisplayPrimaryLabel {{
    background-color: {tray.accent};
    border-radius: {metrics.radius_small}px;
    color: {tray.accent_text};
    font-weight: 600;
    min-height: {metrics.display_action_row_height}px;
}}

QWidget#trayPanel QPushButton#trayDisplayToggleButton[displayState="on"] {{
    background-color: {tray.success};
    border-color: {tray.success};
    color: {tray.success_text};
}}

QWidget#trayPanel QPushButton#trayDisplayToggleButton[displayState="on"]:hover {{
    background-color: {tray.success_hover};
    border-color: {tray.success_hover};
}}

QWidget#trayPanel QPushButton#trayDisplayToggleButton[displayState="on"]:pressed {{
    background-color: {tray.success_pressed};
    border-color: {tray.success_pressed};
}}

QWidget#trayPanel QPushButton#trayDisplayToggleButton[displayState="off"] {{
    background-color: {tray.warning};
    border-color: {tray.warning};
    color: {tray.warning_text};
}}

QWidget#trayPanel QPushButton#trayDisplayToggleButton[displayState="off"]:hover {{
    background-color: {tray.warning_hover};
    border-color: {tray.warning_hover};
}}

QWidget#trayPanel QPushButton#trayDisplayToggleButton[displayState="off"]:pressed {{
    background-color: {tray.warning_pressed};
    border-color: {tray.warning_pressed};
}}

QWidget#trayPanel QPushButton:disabled,
QWidget#trayPanel QPushButton[role="primary"]:disabled,
QWidget#trayPanel QPushButton[surfaceAction="popup"]:disabled,
QWidget#trayPanel QPushButton[surfaceAction="window"]:disabled {{
    background-color: {tray.control_pressed};
    border-color: {tray.subtle_border};
    color: {tray.muted};
}}

QWidget#trayPanel QComboBox {{
    background-color: {tray.control};
    border: 1px solid {tray.border};
    border-radius: {metrics.radius_small}px;
    color: {tray.text};
    min-height: {metrics.control_height}px;
    padding: 3px 8px;
}}

QWidget#trayPanel QComboBox:hover {{
    background-color: {tray.control_hover};
}}

QWidget#trayPanel QComboBox:focus {{
    border-color: {tray.accent};
}}

QWidget#trayPanel QSlider::groove:horizontal {{
    background-color: {tray.subtle_border};
    border-radius: 2px;
    height: 4px;
}}

QWidget#trayPanel QSlider::sub-page:horizontal {{
    background-color: {tray.accent};
    border-radius: 2px;
}}

QWidget#trayPanel QSlider::handle:horizontal {{
    background-color: {tray.control};
    border: 1px solid {tray.border};
    border-radius: 8px;
    height: 16px;
    margin: -6px 0;
    width: 16px;
}}

QWidget#trayPanel QPushButton#trayPanelCloseButton {{
    background-color: transparent;
    border: none;
    border-radius: 5px;
    color: {tray.muted};
    font-size: 12px;
    font-weight: 400;
    min-height: 0;
    padding: 0;
}}

QWidget#trayPanel QPushButton#trayPanelCloseButton:hover {{
    background-color: {tray.close_hover};
    color: {tray.close_text};
}}

QWidget#trayPanel QPushButton#trayPanelCloseButton:pressed {{
    background-color: {tray.close_pressed};
    color: {tray.close_text};
}}

QWidget#trayPanel QTabWidget#trayMainTabs::pane {{
    border: none;
    border-radius: 0px;
    top: 0px;
}}

QWidget#trayPanel QTabWidget#trayMainTabs QTabBar {{
    qproperty-drawBase: 0;
}}

QWidget#trayPanel QTabWidget#trayMainTabs QTabBar::tab {{
    background-color: transparent;
    border: 1px solid transparent;
    border-radius: {metrics.radius_small}px;
    margin: 0px 1px 0px 0px;
    min-height: 26px;
    min-width: 36px;
    padding: 3px 8px 2px 8px;
}}

QWidget#trayPanel QTabWidget#trayMainTabs QTabBar::tab:hover {{
    background-color: {tray.control_hover};
}}

QWidget#trayPanel QTabWidget#trayMainTabs QTabBar::tab:selected {{
    background-color: {tray.control_hover};
    border-color: {tray.subtle_border};
}}

QWidget#trayPanel QTabWidget#trayNetworkKindTabs::pane {{
    border: none;
    border-radius: 0px;
    top: 0px;
}}

QWidget#trayPanel QTabWidget#trayNetworkKindTabs QTabBar {{
    qproperty-drawBase: 0;
}}

QWidget#trayPanel QTabWidget#trayNetworkKindTabs QTabBar::tab {{
    background-color: transparent;
    border: 1px solid transparent;
    border-radius: {metrics.radius_small}px;
    margin: 0px 1px 0px 0px;
    min-height: 26px;
    min-width: 36px;
    padding: 3px 8px 2px 8px;
}}

QWidget#trayPanel QTabWidget#trayNetworkKindTabs QTabBar::tab:hover {{
    background-color: {tray.control_hover};
}}

QWidget#trayPanel QTabWidget#trayNetworkKindTabs QTabBar::tab:selected {{
    background-color: {tray.control_hover};
    border-color: {tray.subtle_border};
}}
""".strip()


def _button_role_qss(name: str, role: ButtonRole) -> str:
    return f"""
QPushButton[role="{name}"], QToolButton[role="{name}"] {{
    background-color: {role.background};
    border-color: {role.border};
    color: {role.text};
}}

QPushButton[role="{name}"]:hover, QToolButton[role="{name}"]:hover {{
    background-color: {role.hover};
}}

QPushButton[role="{name}"]:pressed, QToolButton[role="{name}"]:pressed {{
    background-color: {role.pressed};
}}
""".rstrip()


def _disabled_button_qss(buttons: ButtonTheme) -> str:
    role_selectors = ",\n".join(
        f'QPushButton[role="{role}"]:disabled, QToolButton[role="{role}"]:disabled'
        for role in ("default", "primary", "success", "danger", "info", "accent")
    )
    return f"""
QPushButton:disabled,
QToolButton:disabled,
{role_selectors} {{
    background-color: {buttons.disabled_background};
    border-color: {buttons.disabled_border};
    color: {buttons.disabled_text};
}}
""".rstrip()
