"""Central defaults for tray action labels and icons."""
from __future__ import annotations

from copy import deepcopy
from typing import Any

from .validators import ConfigError

_DEFAULT_TRAY_ACTION_ICONS: dict[str, dict[str, str]] = {
    "header.computer_manager": {
        "label": "Open Computer Manager",
        "icon": "mdi:desktop-tower-monitor",
        "fallback_label": "PC",
    },
    "header.restart": {
        "label": "Restart tray",
        "icon": "mdi:restart",
        "fallback_label": "R",
    },
    "header.hide": {
        "label": "Hide",
        "icon": "mdi:close",
        "fallback_label": "X",
    },
    "tab.media": {
        "label": "Media",
        "icon": "mdi:multimedia",
        "fallback_label": "Media",
    },
    "tab.network": {
        "label": "Network",
        "icon": "mdi:lan",
        "fallback_label": "Network",
    },
    "tab.adapters": {
        "label": "Network adapters",
        "icon": "mdi:lan-connect",
        "fallback_label": "Adapters",
    },
    "tab.drives": {
        "label": "Drives",
        "icon": "mdi:harddisk",
        "fallback_label": "Drives",
    },
    "media.audio_output": {
        "label": "Audio",
        "icon": "mdi:volume-high",
        "fallback_label": "Audio",
    },
    "media.pc_volume": {
        "label": "PC volume",
        "icon": "mdi:desktop-tower-monitor",
        "fallback_label": "PC",
    },
    "media.display_volume": {
        "label": "Display volume",
        "icon": "mdi:television",
        "fallback_label": "TV",
    },
    "profile.fallback": {
        "label": "Display profile",
        "icon": "mdi:monitor",
        "fallback_label": "Profile",
    },
    "display.popup": {
        "label": "Displays",
        "icon": "mdi:monitor-multiple",
        "fallback_label": "Displays",
    },
    "display.refresh": {
        "label": "Refresh displays",
        "icon": "mdi:refresh",
        "fallback_label": "Refresh",
    },
    "display.enable": {
        "label": "Enable display",
        "icon": "mdi:monitor",
        "fallback_label": "Enable",
    },
    "display.disable": {
        "label": "Disable display",
        "icon": "mdi:monitor-off",
        "fallback_label": "Disable",
    },
    "display.make_primary": {
        "label": "Make primary",
        "icon": "mdi:monitor-star",
        "fallback_label": "Make primary",
    },
    "display.primary": {
        "label": "Primary",
        "icon": "mdi:monitor-star",
        "fallback_label": "Primary",
    },
    "display.power_on": {
        "label": "Power on",
        "icon": "mdi:power-on",
        "fallback_label": "On",
    },
    "display.power_off": {
        "label": "Power off",
        "icon": "mdi:power-off",
        "fallback_label": "Off",
    },
    "network.refresh": {
        "label": "Refresh network devices",
        "icon": "mdi:wifi-refresh",
        "fallback_label": "Refresh",
    },
    "network.manage": {
        "label": "Manage network devices",
        "icon": "mdi:application-cog",
        "fallback_label": "Manage",
    },
    "network.device.ping": {
        "label": "Ping",
        "icon": "mdi:network-pos",
        "fallback_label": "Ping",
    },
    "network.device.open": {
        "label": "Open network device",
        "icon": "mdi:open-in-new",
        "fallback_label": "Open",
    },
    "network.kind.network": {
        "label": "Network",
        "icon": "mdi:router-network",
        "fallback_label": "Network",
    },
    "network.kind.iot": {
        "label": "IoT",
        "icon": "mdi:lightbulb-on",
        "fallback_label": "IoT",
    },
    "network.kind.media": {
        "label": "Media",
        "icon": "mdi:television",
        "fallback_label": "Media",
    },
    "network.kind.personal": {
        "label": "Personal devices",
        "icon": "mdi:cellphone",
        "fallback_label": "Personal",
    },
    "adapter.refresh": {
        "label": "Refresh network adapters",
        "icon": "mdi:refresh",
        "fallback_label": "Refresh",
    },
    "adapter.popup": {
        "label": "Adapters",
        "icon": "mdi:lan",
        "fallback_label": "Adapters",
    },
    "adapter.network_connections": {
        "label": "Network Connections",
        "icon": "mdi:lan-connect",
        "fallback_label": "Network Connections",
    },
    "adapter.enable": {
        "label": "Enable adapter",
        "icon": "mdi:lan-connect",
        "fallback_label": "Enable",
    },
    "adapter.disable": {
        "label": "Disable adapter",
        "icon": "mdi:lan-disconnect",
        "fallback_label": "Disable",
    },
    "adapter.info": {
        "label": "Adapter info",
        "icon": "mdi:information-outline",
        "fallback_label": "Info",
    },
    "adapter.properties": {
        "label": "Adapter properties",
        "icon": "mdi:cog",
        "fallback_label": "Properties",
    },
    "drive.refresh": {
        "label": "Refresh drives",
        "icon": "mdi:refresh",
        "fallback_label": "Refresh",
    },
    "drive.popup": {
        "label": "Drives",
        "icon": "mdi:harddisk",
        "fallback_label": "Drives",
    },
    "drive.add_network": {
        "label": "Add network drive",
        "icon": "mdi:plus-network",
        "fallback_label": "Add network",
    },
    "drive.open": {
        "label": "Open drive",
        "icon": "mdi:folder-open",
        "fallback_label": "Open",
    },
    "fallback.options": {
        "label": "Options",
        "icon": "mdi:cog",
        "fallback_label": "Options",
    },
}


def default_tray_action_icons() -> dict[str, dict[str, str]]:
    return deepcopy(_DEFAULT_TRAY_ACTION_ICONS)


def normalize_tray_action_icons(value: Any) -> dict[str, dict[str, str]]:
    if value is None:
        raw: dict[str, Any] = {}
    elif isinstance(value, dict):
        raw = value
    else:
        raise ConfigError("tray_options.action_icons must be an object")

    defaults = default_tray_action_icons()
    unknown = sorted(str(key) for key in raw if str(key) not in defaults)
    if unknown:
        raise ConfigError(f"unknown tray action icon: {', '.join(unknown)}")

    normalized: dict[str, dict[str, str]] = {}
    for action_id, default in defaults.items():
        action_raw = raw.get(action_id, default)
        if action_raw is None:
            action_raw = {}
        if not isinstance(action_raw, dict):
            raise ConfigError(f"tray_options.action_icons.{action_id} must be an object")
        label = _text_setting(
            action_raw.get("label", default["label"]),
            default["label"],
            name=f"tray_options.action_icons.{action_id}.label",
        )
        icon = _icon_setting(
            action_raw.get("icon", default["icon"]),
            default["icon"],
            name=f"tray_options.action_icons.{action_id}.icon",
        )
        fallback_label = _text_setting(
            action_raw.get("fallback_label", default["fallback_label"]),
            default["fallback_label"],
            name=f"tray_options.action_icons.{action_id}.fallback_label",
        )
        normalized[action_id] = {
            "label": label,
            "icon": icon,
            "fallback_label": fallback_label,
        }
    return normalized


def tray_action_icon(options: dict[str, Any], action_id: str) -> dict[str, str]:
    action_icons = options.get("action_icons")
    if not isinstance(action_icons, dict) or action_id not in action_icons:
        action_icons = default_tray_action_icons()
    return dict(action_icons[action_id])


def _text_setting(value: Any, default: str, *, name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ConfigError(f"{name} must be a non-empty string")
    return text


def _icon_setting(value: Any, default: str, *, name: str) -> str:
    text = str(value or "").strip()
    if not text:
        return default
    if not text.startswith("mdi:"):
        raise ConfigError(f"{name} must be an mdi:<name> icon")
    return text
