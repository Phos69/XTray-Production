"""Public display backend data models."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

VALID_ORIENTATIONS = {0, 90, 180, 270}
HDR_NOT_MANAGED_LABEL = "HDR: not managed"


@dataclass
class DisplayState:
    device_id: str
    name: str
    primary: bool = False
    enabled: bool = True
    width: int | None = None
    height: int | None = None
    refresh_hz: int | None = None
    orientation: int = 0  # 0/90/180/270
    pos_x: int = 0
    pos_y: int = 0
    brightness: int | None = None  # 0-100, DDC/CI
    contrast: int | None = None
    input_source: int | None = None
    adapter_name: str | None = None
    manufacturer_id: str | None = None
    manufacturer: str | None = None
    product_code: str | None = None
    model: str | None = None
    serial_number: str | None = None
    physical_width_cm: int | None = None
    physical_height_cm: int | None = None
    diagonal_inches: float | None = None
    manufacture_year: int | None = None
    container_id: str | None = None
    edid_hash: str | None = None
    stable_id: str | None = None
    hdr_supported: bool | None = None
    hdr_enabled: bool | None = None  # read-only; DisplayManager does not apply HDR state

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DisplayState:
        allowed = cls.__dataclass_fields__.keys()
        return cls(**{key: value for key, value in data.items() if key in allowed})

    def display_label(self) -> str:
        title_parts = []
        if self.model:
            if self.manufacturer and self.model.lower().startswith(self.manufacturer.lower()):
                title_parts.append(self.model)
            else:
                if self.manufacturer:
                    title_parts.append(self.manufacturer)
                title_parts.append(self.model)
        elif self.manufacturer:
            title_parts.append(self.manufacturer)
        if not title_parts:
            title_parts.append(self.name)
        if self.diagonal_inches:
            title_parts.append(f'{self.diagonal_inches:g}"')
        title = " ".join(title_parts)
        mode = f"{self.width or '?'}x{self.height or '?'}"
        if self.refresh_hz:
            mode = f"{mode}@{self.refresh_hz}Hz"
        return f"{title}\n{mode}\n{hdr_status_label(self)}"


def hdr_status_label(display_state: DisplayState) -> str:
    if display_state.hdr_supported is False:
        return "HDR: not supported"
    if display_state.hdr_enabled is True:
        return "HDR: on (read-only)"
    if display_state.hdr_enabled is False:
        return "HDR: off (read-only)"
    return HDR_NOT_MANAGED_LABEL


@dataclass
class SystemState:
    displays: list[DisplayState] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"displays": [d.to_dict() for d in self.displays]}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SystemState:
        displays = data.get("displays", [])
        if not isinstance(displays, list):
            raise ValueError("system state displays must be a list")
        return cls(displays=[DisplayState.from_dict(d) for d in displays])


@dataclass
class ApplyWarning:
    message: str
    display_id: str | None = None
    detail: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ApplyResult:
    applied: bool = False
    dry_run: bool = False
    warnings: list[ApplyWarning] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    def to_dict(self) -> dict[str, Any]:
        return {
            "applied": self.applied,
            "dry_run": self.dry_run,
            "ok": self.ok,
            "warnings": [warning.to_dict() for warning in self.warnings],
            "errors": self.errors,
        }


@dataclass(frozen=True)
class PlannedDisplayChange:
    current: DisplayState
    target: DisplayState


@dataclass
class DisplayApplyPlan:
    current: list[DisplayState]
    known: list[DisplayState]
    requested: list[DisplayState]
    planned: list[PlannedDisplayChange]


@dataclass(frozen=True)
class DisplayMode:
    width: int
    height: int
    refresh_hz: int
