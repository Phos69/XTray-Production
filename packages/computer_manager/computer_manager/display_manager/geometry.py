"""Display geometry helpers shared by the GUI preview and Windows apply path."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

_DISPLAY_NUMBER_RE = re.compile(r"DISPLAY(\d+)$", re.IGNORECASE)
_PORTRAIT_ORIENTATIONS = {90, 270}
_LANDSCAPE_ORIENTATIONS = {0, 180}
_DEFAULT_SIZE = (800, 600)


@dataclass
class _DisplayBox:
    display: Any
    index: int
    desired_x: int
    desired_y: int
    width: int
    height: int
    x: int = 0
    y: int = 0

    @property
    def right(self) -> int:
        return self.x + self.width

    @property
    def bottom(self) -> int:
        return self.y + self.height


def display_number(display: Any, *, fallback: int | str | None = None) -> str:
    """Return the Windows DISPLAY number from an adapter name, or a fallback."""
    adapter_name = str(getattr(display, "adapter_name", "") or "")
    match = _DISPLAY_NUMBER_RE.search(adapter_name)
    if match:
        return match.group(1)
    return "" if fallback is None else str(fallback)


def display_pixel_size(
    display: Any, *, fallback: tuple[int, int] = _DEFAULT_SIZE
) -> tuple[int, int]:
    """Return the visible width/height after applying the display orientation."""
    width = _positive_int(getattr(display, "width", None)) or fallback[0]
    height = _positive_int(getattr(display, "height", None)) or fallback[1]
    normalized_width, normalized_height = normalized_mode_size(
        width, height, getattr(display, "orientation", 0)
    )
    return int(normalized_width or width), int(normalized_height or height)


def normalized_mode_size(
    width: int | None,
    height: int | None,
    orientation: int,
) -> tuple[int | None, int | None]:
    """Return mode dimensions with portrait/landscape orientation reflected."""
    if width is None or height is None:
        return width, height
    if width <= 0 or height <= 0:
        return width, height
    if _should_swap_dimensions(width, height, orientation):
        return height, width
    return width, height


def normalize_display_mode(display: Any) -> bool:
    """Mutate one display so width/height match its orientation."""
    old_width = getattr(display, "width", None)
    old_height = getattr(display, "height", None)
    width, height = normalized_mode_size(
        old_width,
        old_height,
        int(getattr(display, "orientation", 0)),
    )
    if width == old_width and height == old_height:
        return False
    display.width = width
    display.height = height
    return True


def normalize_display_geometry(displays: list[Any]) -> bool:
    """Mutate enabled displays into one Windows-legal adjacent arrangement.

    The primary display is anchored at (0, 0). Each additional display is moved
    to the nearest edge-adjacent position relative to the already placed group,
    preserving the user's rough direction while removing unsupported gaps.
    """
    changed = False
    enabled = [display for display in displays if getattr(display, "enabled", True)]
    for display in enabled:
        changed = normalize_display_mode(display) or changed
    if not enabled:
        return changed

    anchor_display = next(
        (display for display in enabled if getattr(display, "primary", False)),
        enabled[0],
    )
    anchor_x = int(getattr(anchor_display, "pos_x", 0))
    anchor_y = int(getattr(anchor_display, "pos_y", 0))
    boxes = [
        _DisplayBox(
            display=display,
            index=index,
            desired_x=int(getattr(display, "pos_x", 0)) - anchor_x,
            desired_y=int(getattr(display, "pos_y", 0)) - anchor_y,
            width=display_pixel_size(display)[0],
            height=display_pixel_size(display)[1],
        )
        for index, display in enumerate(enabled)
    ]
    anchor = boxes[enabled.index(anchor_display)]
    anchor.x = 0
    anchor.y = 0
    placed = [anchor]
    remaining = [box for box in boxes if box is not anchor]
    remaining.sort(key=lambda box: (_distance_squared(box, anchor), box.index))

    for box in remaining:
        box.x, box.y = _nearest_adjacent_position(box, placed)
        placed.append(box)

    for box in boxes:
        old_x = getattr(box.display, "pos_x", 0)
        old_y = getattr(box.display, "pos_y", 0)
        if old_x != box.x or old_y != box.y:
            box.display.pos_x = box.x
            box.display.pos_y = box.y
            changed = True
    return changed


def ensure_enabled_primary(displays: list[Any], *, preferred: Any | None = None) -> bool:
    """Ensure enabled displays have one primary and disabled displays have none."""
    enabled = [display for display in displays if getattr(display, "enabled", True)]
    active_primaries = [
        display for display in enabled if getattr(display, "primary", False)
    ]
    if active_primaries:
        primary_display = active_primaries[0]
    elif preferred is not None and any(display is preferred for display in enabled):
        primary_display = preferred
    elif enabled:
        primary_display = enabled[0]
    else:
        primary_display = None

    changed = False
    for display in displays:
        primary = display is primary_display
        if bool(getattr(display, "primary", False)) != primary:
            display.primary = primary
            changed = True
    return changed


def _positive_int(value: Any) -> int | None:
    try:
        ivalue = int(value)
    except (TypeError, ValueError):
        return None
    return ivalue if ivalue > 0 else None


def _should_swap_dimensions(width: int, height: int, orientation: int) -> bool:
    if orientation in _PORTRAIT_ORIENTATIONS:
        return width > height
    if orientation in _LANDSCAPE_ORIENTATIONS:
        return height > width
    return False


def _distance_squared(left: _DisplayBox, right: _DisplayBox) -> int:
    return (left.desired_x - right.desired_x) ** 2 + (left.desired_y - right.desired_y) ** 2


def _nearest_adjacent_position(box: _DisplayBox, placed: list[_DisplayBox]) -> tuple[int, int]:
    candidates: list[tuple[int, int]] = []
    for target in placed:
        candidates.extend(_edge_candidates(box, target))
    return min(
        candidates,
        key=lambda candidate: _candidate_score(box, candidate[0], candidate[1], placed),
    )


def _edge_candidates(box: _DisplayBox, target: _DisplayBox) -> list[tuple[int, int]]:
    y_values = _edge_offsets(
        preferred=box.desired_y,
        start=target.y - box.height + 1,
        end=target.y + target.height - 1,
        align_start=target.y,
        align_end=target.bottom - box.height,
    )
    x_values = _edge_offsets(
        preferred=box.desired_x,
        start=target.x - box.width + 1,
        end=target.x + target.width - 1,
        align_start=target.x,
        align_end=target.right - box.width,
    )
    candidates: list[tuple[int, int]] = []
    for y in y_values:
        candidates.append((target.x - box.width, y))
        candidates.append((target.right, y))
    for x in x_values:
        candidates.append((x, target.y - box.height))
        candidates.append((x, target.bottom))
    return candidates


def _edge_offsets(
    *,
    preferred: int,
    start: int,
    end: int,
    align_start: int,
    align_end: int,
) -> list[int]:
    center = align_start + (align_end - align_start) // 2
    values = [
        _clamp(preferred, start, end),
        _clamp(align_start, start, end),
        _clamp(align_end, start, end),
        _clamp(center, start, end),
    ]
    return list(dict.fromkeys(values))


def _candidate_score(
    box: _DisplayBox,
    x: int,
    y: int,
    placed: list[_DisplayBox],
) -> tuple[int, int, int]:
    overlap = sum(_overlap_area(x, y, box, target) for target in placed)
    distance = (x - box.desired_x) ** 2 + (y - box.desired_y) ** 2
    return (overlap, distance, abs(x) + abs(y))


def _overlap_area(x: int, y: int, box: _DisplayBox, target: _DisplayBox) -> int:
    overlap_width = min(x + box.width, target.right) - max(x, target.x)
    overlap_height = min(y + box.height, target.bottom) - max(y, target.y)
    if overlap_width <= 0 or overlap_height <= 0:
        return 0
    return overlap_width * overlap_height


def _clamp(value: int, minimum: int, maximum: int) -> int:
    if minimum > maximum:
        return minimum
    return max(minimum, min(maximum, value))
