"""Pure helpers used by the PySide6 display preview."""
from __future__ import annotations

from dataclasses import dataclass

from computer_manager.display_manager.backend import DisplayMode, DisplayState, stable_display_key
from computer_manager.display_manager.geometry import (
    display_number,
    display_pixel_size,
    normalize_display_geometry,
)

COMMON_RESOLUTIONS: list[tuple[int, int]] = [
    (640, 480),
    (800, 600),
    (1024, 768),
    (1280, 720),
    (1280, 800),
    (1280, 1024),
    (1366, 768),
    (1440, 900),
    (1600, 900),
    (1680, 1050),
    (1920, 1080),
    (1920, 1200),
    (2048, 1152),
    (2560, 1080),
    (2560, 1440),
    (2560, 1600),
    (2880, 1620),
    (3440, 1440),
    (3840, 1600),
    (3840, 2160),
    (5120, 1440),
    (5120, 2160),
    (5120, 2880),
    (7680, 4320),
]

COMMON_REFRESH_RATES: list[int] = [
    24, 30, 50, 60, 75, 90, 100, 120, 144, 165, 180, 200, 240, 360,
]

ORIENTATION_CHOICES: list[tuple[int, str]] = [
    (0, "Landscape"),
    (90, "Portrait"),
    (180, "Landscape (flipped)"),
    (270, "Portrait (flipped)"),
]

_RESOLUTION_LABELS: dict[tuple[int, int], str] = {
    (1280, 720): "HD",
    (1366, 768): "WXGA",
    (1600, 900): "HD+",
    (1920, 1080): "Full HD",
    (1920, 1200): "WUXGA",
    (2560, 1440): "QHD",
    (2560, 1600): "WQXGA",
    (3440, 1440): "UWQHD",
    (3840, 2160): "4K UHD",
    (5120, 2880): "5K",
    (7680, 4320): "8K",
}


@dataclass(frozen=True)
class PreviewRect:
    device_id: str
    object_id: str
    name: str
    display_number: str
    x: int
    y: int
    width: int
    height: int
    primary: bool


@dataclass(frozen=True)
class PreviewLayout:
    origin_x: int
    origin_y: int
    rects: list[PreviewRect]


@dataclass(frozen=True)
class ProfileObjectRect:
    kind: str
    object_id: str
    name: str
    x: int
    y: int
    width: int
    height: int
    primary: bool = False


@dataclass(frozen=True)
class ProfileObjectLayout:
    rects: list[ProfileObjectRect]
    width: int
    height: int


def snap_value(value: int, *, step: int = 20) -> int:
    if step <= 0:
        return value
    return round(value / step) * step


def snap_position(x: int, y: int, *, step: int = 20) -> tuple[int, int]:
    return snap_value(x, step=step), snap_value(y, step=step)


def preview_layout(displays: list[DisplayState], *, scale: float = 0.12) -> PreviewLayout:
    if not displays:
        return PreviewLayout(origin_x=0, origin_y=0, rects=[])
    normalized = [DisplayState.from_dict(display.to_dict()) for display in displays]
    normalize_display_geometry(normalized)
    min_x = min(display.pos_x for display in normalized)
    min_y = min(display.pos_y for display in normalized)
    rects: list[PreviewRect] = []
    for index, display in enumerate(normalized, start=1):
        display_width, display_height = display_pixel_size(display)
        width = max(int(display_width * scale), 80)
        height = max(int(display_height * scale), 50)
        rects.append(
            PreviewRect(
                device_id=display.device_id,
                object_id=display_object_id(display),
                name=display.display_label(),
                display_number=display_number(display, fallback=index),
                x=int((display.pos_x - min_x) * scale),
                y=int((display.pos_y - min_y) * scale),
                width=width,
                height=height,
                primary=display.primary,
            )
        )
    return PreviewLayout(origin_x=min_x, origin_y=min_y, rects=rects)


def preview_rects(displays: list[DisplayState], *, scale: float = 0.12) -> list[PreviewRect]:
    return preview_layout(displays, scale=scale).rects


def profile_object_layout(
    displays: list[DisplayState],
    *,
    available_displays: list[DisplayState] | None = None,
    audio_label: str = "Default audio",
) -> ProfileObjectLayout:
    rects = [
        ProfileObjectRect(
            kind="audio",
            object_id="audio",
            name=audio_label,
            x=0,
            y=12,
            width=260,
            height=54,
        )
    ]
    x = 292
    profile_displays = (
        _available_displays_not_enabled_in_profile(displays, available_displays)
        if available_displays is not None
        else [display for display in displays if not display.enabled]
    )
    for display in profile_displays:
        rects.append(
            ProfileObjectRect(
                kind="display",
                object_id=display_object_id(display),
                name=display.display_label(),
                x=x,
                y=0,
                width=150,
                height=78,
                primary=display.primary,
            )
        )
        x += 166
    width = max((rect.x + rect.width for rect in rects), default=0)
    height = max((rect.y + rect.height for rect in rects), default=0)
    return ProfileObjectLayout(rects=rects, width=width, height=height)


def _available_displays_not_enabled_in_profile(
    profile_displays: list[DisplayState],
    available_displays: list[DisplayState],
) -> list[DisplayState]:
    used_tokens = {
        display_object_id(display)
        for display in profile_displays
        if display.enabled
    }
    seen_tokens: set[str] = set()
    unused: list[DisplayState] = []
    for display in available_displays:
        token = display_object_id(display)
        if token in used_tokens:
            continue
        if token in seen_tokens:
            continue
        seen_tokens.add(token)
        unused.append(display)
    return unused


def display_object_id(display: DisplayState) -> str:
    return stable_display_key(display)


def disambiguate_labels(displays: list[DisplayState]) -> dict[str, str]:
    """Return ``stable_id -> suffix`` for display labels that would otherwise collide.

    Why: two distinct physical monitors can share the same ``display_label()``
    (e.g. two unbranded ``Generic PnP Monitor`` panels). The shelf would render
    them as visually identical tiles even though their ``stable_id`` differs.
    A short suffix derived from the EDID hash or the Windows adapter route
    breaks the tie without adding noise when no collision is present.
    """
    label_counts: dict[str, int] = {}
    for display_state in displays:
        label = display_state.display_label()
        label_counts[label] = label_counts.get(label, 0) + 1
    suffixes: dict[str, str] = {}
    for display_state in displays:
        if label_counts.get(display_state.display_label(), 0) <= 1:
            continue
        key = stable_display_key(display_state)
        if key.startswith("edid:") or key.startswith("container:"):
            tail = key.rsplit(":", 1)[-1]
            suffixes[key] = f" · {tail[-4:].upper()}" if tail else ""
        elif display_state.adapter_name:
            suffixes[key] = f" · {display_state.adapter_name.split(chr(92))[-1]}"
        else:
            suffixes[key] = ""
    return suffixes


def format_resolution(width: int | None, height: int | None) -> str:
    if not width or not height:
        return ""
    base = f"{width}×{height}"
    label = _RESOLUTION_LABELS.get((width, height))
    return f"{base} ({label})" if label else base


def parse_resolution(text: str) -> tuple[int, int] | None:
    cleaned = text.split("(", 1)[0].strip()
    for sep in ("×", "x", "X", "*"):
        if sep in cleaned:
            parts = cleaned.split(sep, 1)
            try:
                return int(parts[0].strip()), int(parts[1].strip())
            except (ValueError, IndexError):
                return None
    return None


def resolution_options(
    modes: list[DisplayMode],
    *,
    current: tuple[int, int] | None = None,
) -> list[tuple[int, int]]:
    if modes:
        resolutions = sorted({(m.width, m.height) for m in modes})
    else:
        resolutions = list(COMMON_RESOLUTIONS)
    if current and current[0] > 0 and current[1] > 0 and current not in resolutions:
        resolutions.append(current)
        resolutions.sort()
    return resolutions


def refresh_rate_options(
    modes: list[DisplayMode],
    width: int | None,
    height: int | None,
    *,
    current: int | None = None,
) -> list[int]:
    if modes and width and height:
        rates = sorted({m.refresh_hz for m in modes if m.width == width and m.height == height})
    elif modes:
        rates = sorted({m.refresh_hz for m in modes})
    else:
        rates = list(COMMON_REFRESH_RATES)
    if current and current > 0 and current not in rates:
        rates.append(current)
        rates.sort()
    return rates


def scene_to_display_position(
    x: float,
    y: float,
    *,
    scale: float = 0.12,
    origin_x: int = 0,
    origin_y: int = 0,
) -> tuple[int, int]:
    raw_x = int(round(x / scale)) + origin_x
    raw_y = int(round(y / scale)) + origin_y
    return snap_position(raw_x, raw_y)
