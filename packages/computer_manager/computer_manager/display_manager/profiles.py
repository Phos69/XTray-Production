"""Profile model, JSON persistence, validation, and apply orchestration."""
from __future__ import annotations

import json
import os
import re
import tempfile
import warnings
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from xtray import config
from xtray.core import app_logging, icons

from .. import paths
from ..audio_manager import core as audio
from . import backend as display

PROFILE_SCHEMA_VERSION = 3
DEPRECATED_PROFILE_SCHEMA_VERSIONS = frozenset({1, 2})
SUPPORTED_PROFILE_SCHEMA_VERSIONS = DEPRECATED_PROFILE_SCHEMA_VERSIONS | {
    PROFILE_SCHEMA_VERSION
}
PROFILE_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _.-]{0,63}$")
_DISPLAY_CONFIGURATION_FIELDS = (
    "primary",
    "width",
    "height",
    "refresh_hz",
    "orientation",
    "pos_x",
    "pos_y",
)

# Test and development override. When None, profiles live in AppData.
PROFILES_DIR: Path | None = None


class ProfileNotFound(Exception):
    pass


class InvalidProfile(Exception):
    pass


class ProfileAlreadyExists(Exception):
    """Raised when a profile would be overwritten without an explicit opt-in."""


@dataclass
class Profile:
    name: str
    displays: list[display.DisplayState]
    version: int = PROFILE_SCHEMA_VERSION
    favorite: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)
    audio_source: audio.AudioSource | None = None
    audio_volume_percent: int | None = None
    audio_muted: bool | None = None
    icon: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "version": self.version,
            "name": self.name,
            "favorite": self.favorite,
            "metadata": self.metadata,
            "displays": [display_state.to_dict() for display_state in self.displays],
        }
        if self.audio_source is not None:
            payload["audio_source"] = self.audio_source.to_dict()
        if self.audio_volume_percent is not None:
            payload["audio_volume_percent"] = self.audio_volume_percent
        if self.audio_muted is not None:
            payload["audio_muted"] = self.audio_muted
        if self.icon is not None:
            payload["icon"] = self.icon
        return payload

    @classmethod
    def from_dict(cls, data: dict[str, Any], *, source_name: str | None = None) -> Profile:
        if not isinstance(data, dict):
            raise InvalidProfile("profile must be a JSON object")
        version = data.get("version")
        if version not in SUPPORTED_PROFILE_SCHEMA_VERSIONS:
            raise InvalidProfile(f"unsupported profile version: {version}")
        if version in DEPRECATED_PROFILE_SCHEMA_VERSIONS:
            warnings.warn(
                (
                    f"profile schema version {version} is deprecated; "
                    f"save the profile again to migrate it to version {PROFILE_SCHEMA_VERSION}"
                ),
                DeprecationWarning,
                stacklevel=2,
            )

        name = data.get("name") or source_name
        if not isinstance(name, str):
            raise InvalidProfile("profile name is required")
        safe_name = normalize_name(name)

        favorite = data.get("favorite", False)
        if not isinstance(favorite, bool):
            raise InvalidProfile("profile favorite must be a boolean")

        raw_displays = data.get("displays")
        if not isinstance(raw_displays, list):
            raise InvalidProfile("profile displays must be a list")
        displays = [_display_from_profile_dict(item) for item in raw_displays]
        metadata = data.get("metadata", {})
        if metadata is None:
            metadata = {}
        if not isinstance(metadata, dict):
            raise InvalidProfile("profile metadata must be an object")
        audio_source = _audio_source_from_profile_dict(data.get("audio_source"))
        icon = icons.normalize_icon_name(data.get("icon"))

        profile = cls(
            name=safe_name,
            version=PROFILE_SCHEMA_VERSION,
            favorite=favorite,
            metadata=metadata,
            displays=displays,
            audio_source=audio_source,
            audio_volume_percent=_audio_volume_from_profile_dict(
                data.get("audio_volume_percent")
            ),
            audio_muted=_audio_muted_from_profile_dict(data.get("audio_muted")),
            icon=icon,
        )
        errors = validate_profile(profile, strict=True)
        if errors:
            raise InvalidProfile("; ".join(errors))
        return profile


def normalize_name(name: str) -> str:
    safe = name.strip()
    if (
        not safe
        or "/" in safe
        or "\\" in safe
        or safe.startswith(".")
        or not PROFILE_NAME_RE.match(safe)
    ):
        raise InvalidProfile(f"invalid profile name: {name!r}")
    return safe


def profiles_dir() -> Path:
    """Write target for profiles. Tests can override via PROFILES_DIR."""
    if PROFILES_DIR is not None:
        PROFILES_DIR.mkdir(parents=True, exist_ok=True)
        return PROFILES_DIR
    return paths.profiles_dir()


def _profile_search_paths() -> list[Path]:
    """Dirs to consult when reading. Test override takes precedence."""
    if PROFILES_DIR is not None:
        PROFILES_DIR.mkdir(parents=True, exist_ok=True)
        return [PROFILES_DIR]
    return paths.profile_search_paths()


def profile_path(name: str) -> Path:
    """Path used for writes: always the primary write target."""
    return profiles_dir() / f"{normalize_name(name)}.json"


def _existing_profile_path(name: str) -> Path | None:
    """First existing copy of `<name>.json` across all search dirs (None if missing)."""
    filename = f"{normalize_name(name)}.json"
    for directory in _profile_search_paths():
        candidate = directory / filename
        if candidate.exists():
            return candidate
    return None


def list_profiles() -> list[str]:
    """Profile names from all search dirs (new path wins on duplicates)."""
    seen: dict[str, None] = {}
    for directory in _profile_search_paths():
        for p in directory.glob("*.json"):
            seen.setdefault(p.stem, None)
    return sorted(seen)


def current_state(*, include_inactive: bool = False) -> display.SystemState:
    """Snapshot the live display state without exposing the WinAPI backend.

    Why: user-facing surfaces (CLI, GUI, API) should call ``profiles`` instead
    of importing the display backend directly (CLAUDE.md layering rule).
    """
    return display.get_state(include_inactive=include_inactive)


def list_available_displays() -> list[display.DisplayState]:
    """List active and known-inactive displays. Wrapper over the backend."""
    return display.list_available_displays()


def list_display_modes(adapter_name: str) -> list[display.DisplayMode]:
    """Enumerate the modes a Windows adapter supports. Wrapper over the backend."""
    return display.list_display_modes(adapter_name)


def list_favorite_profiles() -> list[str]:
    names: list[str] = []
    logger = app_logging.get_logger("profiles")
    for name in list_profiles():
        try:
            profile = load_profile(name)
        except (ProfileNotFound, InvalidProfile) as exc:
            logger.warning("skipping invalid favorite profile candidate %s: %s", name, exc)
            continue
        if profile.favorite:
            names.append(name)
    return names


def find_matching_profile(
    current: Profile,
    *,
    profile_names: Iterable[str] | None = None,
    match_audio: bool = True,
) -> Profile | None:
    """Return the saved profile whose applied configuration matches ``current``.

    Matching is based on enabled display topology and explicit audio settings.
    Disabled/saved-only displays are ignored because they are inventory hints,
    not part of the active Windows layout.
    """
    names = sorted(profile_names) if profile_names is not None else list_profiles()
    logger = app_logging.get_logger("profiles")
    best_profile: Profile | None = None
    best_score = -1
    for name in names:
        try:
            candidate = load_profile(name)
        except (ProfileNotFound, InvalidProfile) as exc:
            logger.warning("skipping invalid profile match candidate %s: %s", name, exc)
            continue
        if not profile_matches_current(candidate, current, match_audio=match_audio):
            continue
        score = _profile_match_specificity(candidate, match_audio=match_audio)
        if score > best_score:
            best_profile = candidate
            best_score = score
    return best_profile


def detect_current_profile(
    *,
    profile_names: Iterable[str] | None = None,
    match_audio: bool = False,
    include_inactive: bool = True,
) -> Profile | None:
    """Return the saved profile matching the live Windows display state.

    By default this is display-only, which is what Home Assistant needs for
    the current-profile select state: changing volume or audio output should
    not make the display profile become unknown.
    """
    state = current_state(include_inactive=include_inactive)
    audio_source: audio.AudioSource | None = None
    volume_percent: int | None = None
    muted: bool | None = None
    if match_audio:
        audio_source, volume_percent, muted = _capture_current_audio_settings()
    current = Profile(
        name="current",
        displays=state.displays,
        audio_source=audio_source,
        audio_volume_percent=volume_percent,
        audio_muted=muted,
    )
    return find_matching_profile(
        current,
        profile_names=profile_names,
        match_audio=match_audio,
    )


def profile_matches_current(
    profile: Profile,
    current: Profile,
    *,
    match_audio: bool = True,
) -> bool:
    """Return whether ``profile`` represents the live profile configuration."""
    if not _display_configuration_matches(profile.displays, current.displays):
        return False
    return not match_audio or _audio_configuration_matches(profile, current)


def load(name: str) -> dict[str, Any]:
    return load_profile(name).to_dict()


def load_profile(name: str) -> Profile:
    path = _existing_profile_path(name)
    if path is None:
        raise ProfileNotFound(name)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise InvalidProfile(f"invalid JSON in profile {name!r}") from exc
    return Profile.from_dict(data, source_name=path.stem)


def save(name: str, state: display.SystemState, *, overwrite: bool = False) -> Path:
    audio_source, volume_percent, muted = _capture_current_audio_settings()
    profile = Profile(
        name=normalize_name(name),
        displays=state.displays,
        metadata={"saved_at": _now_utc()},
        audio_source=audio_source,
        audio_volume_percent=volume_percent,
        audio_muted=muted,
    )
    return save_profile(profile, overwrite=overwrite)


def save_profile(profile: Profile, *, overwrite: bool = False) -> Path:
    errors = validate_profile(profile, strict=True)
    if errors:
        raise InvalidProfile("; ".join(errors))
    path = profile_path(profile.name)
    existing = _existing_profile_path(profile.name)
    if existing is not None and not overwrite:
        raise ProfileAlreadyExists(profile.name)
    payload = profile.to_dict()
    payload["version"] = PROFILE_SCHEMA_VERSION
    payload["metadata"] = {**payload.get("metadata", {}), "saved_at": _now_utc()}
    _atomic_write_json(path, payload)
    app_logging.get_logger("profiles").info("saved profile %s to %s", profile.name, path)
    return path


def delete(name: str) -> None:
    path = _existing_profile_path(name)
    if path is None:
        raise ProfileNotFound(name)
    path.unlink()
    app_logging.get_logger("profiles").info("deleted profile %s", name)


def apply(name: str, *, dry_run: bool = False) -> display.ApplyResult:
    profile = load_profile(name)
    state = display.SystemState(displays=profile.displays)
    pre_apply_warnings: list[display.ApplyWarning] = []
    if not dry_run:
        pre_apply_warnings = _apply_profile_display_power_services(
            profile,
            target_enabled=True,
        )
    result = display.apply_state(state, dry_run=dry_run)
    if pre_apply_warnings:
        result.warnings[0:0] = pre_apply_warnings
    display_apply_ok = result.ok
    if result.ok and not dry_run:
        _apply_profile_audio_settings(profile, result)
    if display_apply_ok and not dry_run:
        result.warnings.extend(
            _apply_profile_display_power_services(profile, target_enabled=False)
        )
    app_logging.get_logger("profiles").info(
        "apply profile %s dry_run=%s applied=%s ok=%s", name, dry_run, result.applied, result.ok
    )
    if result.ok and not dry_run:
        try:
            config.set_last_applied_profile(profile.name)
        except config.ConfigError as exc:
            app_logging.get_logger("profiles").warning(
                "could not persist last applied profile %s: %s", profile.name, exc
            )
    return result


def _apply_profile_display_power_services(
    profile: Profile,
    *,
    target_enabled: bool,
) -> list[display.ApplyWarning]:
    from . import inventory as display_inventory

    logger = app_logging.get_logger("profiles")
    service_key = "power_on_ha_service" if target_enabled else "power_off_ha_service"
    data_key = (
        "power_on_ha_service_data" if target_enabled else "power_off_ha_service_data"
    )
    action = "power on" if target_enabled else "power off"
    warnings: list[display.ApplyWarning] = []
    for display_state in profile.displays:
        if bool(display_state.enabled) != target_enabled:
            continue
        power_setting = display_inventory.home_assistant_power_setting(display_state)
        service_id = power_setting.get(service_key)
        if not service_id:
            continue
        service_data = power_setting.get(data_key)
        try:
            _call_home_assistant_service(service_id, service_data)
        except Exception as exc:
            logger.warning(
                "Home Assistant %s service failed for profile %s display %s: %s",
                action,
                profile.name,
                display_state.device_id,
                exc,
            )
            warnings.append(
                display.ApplyWarning(
                    f"Home Assistant {action} service failed",
                    display_id=display_state.device_id,
                    detail=f"{service_id}: {exc}",
                )
            )
    return warnings


def _call_home_assistant_service(
    service_id: str,
    service_data: dict[str, Any] | None = None,
) -> None:
    from xtray import ha_rest

    ha_rest.call_service(service_id, service_data)


def capture(name: str, *, overwrite: bool = False) -> Path:
    return save(name, display.get_state(), overwrite=overwrite)


def refresh_display_metadata(profile: Profile) -> None:
    """Refresh EDID-derived metadata on each display from the live registry.

    Why: ``Profile.from_dict`` is now pure and trusts the JSON. Callers that
    want fresh monitor metadata (e.g. the GUI editor when a new monitor is
    plugged in) opt in explicitly here. On non-Windows this is a no-op.
    """
    for display_state in profile.displays:
        display.enrich_display_metadata(display_state)


def validate(name: str) -> list[str]:
    profile = load_profile(name)
    return validate_profile(profile, strict=False)


def validate_profile(profile: Profile, *, strict: bool = False) -> list[str]:
    issues: list[str] = []
    try:
        normalize_name(profile.name)
    except InvalidProfile as exc:
        issues.append(str(exc))

    primary_count = sum(1 for display_state in profile.displays if display_state.primary)
    if primary_count > 1:
        issues.append("profile contains more than one primary display")
    if not profile.displays and not strict:
        issues.append("profile contains no displays")

    seen_identity_aliases: dict[str, str] = {}
    for index, display_state in enumerate(profile.displays):
        label = display_state.device_id or f"display[{index}]"
        if not display_state.device_id:
            issues.append(f"{label}: device_id is required")
        if not display_state.name:
            issues.append(f"{label}: name is required")
        identity_aliases = (
            set(display.display_identity_aliases(display_state))
            or {display.stable_display_key(display_state)}
        )
        duplicate_alias = next(
            (alias for alias in identity_aliases if alias in seen_identity_aliases),
            None,
        )
        if duplicate_alias is not None:
            issues.append(f"{label}: duplicate monitor identity ({duplicate_alias})")
        for alias in identity_aliases:
            seen_identity_aliases.setdefault(alias, label)
        if display_state.orientation not in display.VALID_ORIENTATIONS:
            issues.append(f"{label}: unsupported orientation {display_state.orientation}")
        for field_name in ("width", "height", "refresh_hz"):
            value = getattr(display_state, field_name)
            if value is not None and value <= 0:
                issues.append(f"{label}: {field_name} must be positive")
        for field_name in ("brightness", "contrast"):
            value = getattr(display_state, field_name)
            if value is not None and not 0 <= value <= 100:
                issues.append(f"{label}: {field_name} must be between 0 and 100")
        if not isinstance(display_state.pos_x, int) or not isinstance(display_state.pos_y, int):
            issues.append(f"{label}: display position must use integer coordinates")
    if profile.audio_volume_percent is not None:
        if isinstance(profile.audio_volume_percent, bool) or not isinstance(
            profile.audio_volume_percent, int
        ):
            issues.append("profile audio_volume_percent must be an integer")
        elif not 0 <= profile.audio_volume_percent <= 100:
            issues.append("profile audio_volume_percent must be between 0 and 100")
    if profile.audio_muted is not None and not isinstance(profile.audio_muted, bool):
        issues.append("profile audio_muted must be a boolean")
    return issues


def profile_missing_displays(
    profile: Profile,
    current_displays: list[display.DisplayState] | None = None,
) -> list[display.DisplayState]:
    """Return the enabled displays in ``profile`` that are not physically connected.

    Only the display identity is checked here — a connected monitor with a different
    saved configuration (resolution, position, refresh rate) is not considered missing.
    """
    if current_displays is None:
        current_displays = current_state(include_inactive=True).displays
    unmatched = list(current_displays)
    missing: list[display.DisplayState] = []
    for profile_display in profile.displays:
        if not profile_display.enabled:
            continue
        matched_index: int | None = None
        for index, current_display in enumerate(unmatched):
            if _display_identity_matches(profile_display, current_display):
                matched_index = index
                break
        if matched_index is None:
            missing.append(profile_display)
        else:
            unmatched.pop(matched_index)
    return missing


def profile_has_missing_displays(
    profile: Profile,
    current_displays: list[display.DisplayState] | None = None,
) -> bool:
    """Return True if any enabled display in ``profile`` is not connected."""
    return bool(profile_missing_displays(profile, current_displays))


def _display_configuration_matches(
    profile_displays: list[display.DisplayState],
    current_displays: list[display.DisplayState],
) -> bool:
    expected = [display_state for display_state in profile_displays if display_state.enabled]
    current = [display_state for display_state in current_displays if display_state.enabled]
    if len(expected) != len(current):
        return False
    unmatched = list(current)
    for profile_display in expected:
        matching_index = _matching_current_display_index(profile_display, unmatched)
        if matching_index is None:
            return False
        unmatched.pop(matching_index)
    return True


def _matching_current_display_index(
    profile_display: display.DisplayState,
    current_displays: list[display.DisplayState],
) -> int | None:
    for index, current_display in enumerate(current_displays):
        if _display_configuration_entry_matches(profile_display, current_display):
            return index
    return None


def _display_configuration_entry_matches(
    profile_display: display.DisplayState,
    current_display: display.DisplayState,
) -> bool:
    if not _display_identity_matches(profile_display, current_display):
        return False
    return all(
        getattr(profile_display, field_name) == getattr(current_display, field_name)
        for field_name in _DISPLAY_CONFIGURATION_FIELDS
    )


def _display_identity_matches(
    left: display.DisplayState,
    right: display.DisplayState,
) -> bool:
    if display.display_identity_matches(left, right):
        return True
    return display.stable_display_key(left) == display.stable_display_key(right)


def _audio_configuration_matches(profile: Profile, current: Profile) -> bool:
    return (
        _audio_source_matches(profile.audio_source, current.audio_source)
        and _optional_audio_value_matches(
            profile.audio_volume_percent,
            current.audio_volume_percent,
        )
        and _optional_audio_value_matches(profile.audio_muted, current.audio_muted)
    )


def _audio_source_matches(
    expected: audio.AudioSource | None,
    current: audio.AudioSource | None,
) -> bool:
    if expected is None:
        return True
    if current is None:
        return False
    if expected.endpoint_id and current.endpoint_id:
        return expected.endpoint_id == current.endpoint_id
    return expected.label() == current.label()


def _optional_audio_value_matches(expected: Any, current: Any) -> bool:
    return expected is None or expected == current


def _profile_match_specificity(profile: Profile, *, match_audio: bool = True) -> int:
    enabled_count = sum(1 for display_state in profile.displays if display_state.enabled)
    score = enabled_count * 10
    if not match_audio:
        return score
    if profile.audio_source is not None:
        score += 4
    if profile.audio_volume_percent is not None:
        score += 2
    if profile.audio_muted is not None:
        score += 1
    return score


def _display_from_profile_dict(data: Any) -> display.DisplayState:
    if not isinstance(data, dict):
        raise InvalidProfile("each display must be a JSON object")
    if "device_id" not in data or "name" not in data:
        raise InvalidProfile("each display requires device_id and name")
    try:
        return display.DisplayState.from_dict(data)
    except TypeError as exc:
        raise InvalidProfile(f"invalid display fields: {exc}") from exc


def _audio_source_from_profile_dict(data: Any) -> audio.AudioSource | None:
    if data is None:
        return None
    try:
        return audio.AudioSource.from_dict(data)
    except ValueError as exc:
        raise InvalidProfile(str(exc)) from exc


def _audio_volume_from_profile_dict(data: Any) -> int | None:
    if data is None:
        return None
    if isinstance(data, bool) or not isinstance(data, int):
        raise InvalidProfile("audio_volume_percent must be an integer")
    if not 0 <= data <= 100:
        raise InvalidProfile("audio_volume_percent must be between 0 and 100")
    return data


def _audio_muted_from_profile_dict(data: Any) -> bool | None:
    if data is None:
        return None
    if not isinstance(data, bool):
        raise InvalidProfile("audio_muted must be a boolean")
    return data


def _capture_current_audio_settings() -> tuple[audio.AudioSource | None, int | None, bool | None]:
    logger = app_logging.get_logger("profiles")
    source = audio.get_default_audio_source()
    if source is None:
        return None, None, None
    volume_percent: int | None = None
    muted: bool | None = None
    try:
        volume_percent = audio.get_output_volume_percent(source)
    except Exception:
        logger.exception("could not capture current audio volume")
    try:
        muted = audio.get_output_muted(source)
    except Exception:
        logger.exception("could not capture current audio mute state")
    return source, volume_percent, muted


def _apply_profile_audio_settings(profile: Profile, result: display.ApplyResult) -> None:
    if (
        profile.audio_source is None
        and profile.audio_volume_percent is None
        and profile.audio_muted is None
    ):
        return
    logger = app_logging.get_logger("profiles")
    target_source = profile.audio_source
    source_available = True
    if target_source is not None:
        try:
            audio.set_default_audio_source(target_source)
        except audio.AudioEndpointNotFound as exc:
            logger.warning("audio endpoint not found for profile %s: %s", profile.name, exc)
            result.errors.append(f"audio: endpoint not found ({exc})")
            source_available = False
        except audio.AudioApplyError as exc:
            logger.exception("Windows refused audio endpoint for profile %s", profile.name)
            result.errors.append(f"audio: {exc}")
            source_available = False
        except Exception as exc:
            logger.exception("unexpected error applying audio source for profile %s", profile.name)
            result.errors.append(f"audio: {exc}")
            source_available = False
    if not source_available:
        return
    if profile.audio_volume_percent is not None:
        try:
            audio.set_output_volume_percent(profile.audio_volume_percent, target_source)
        except audio.AudioEndpointNotFound as exc:
            logger.warning("audio endpoint not found for profile %s: %s", profile.name, exc)
            result.errors.append(f"audio: endpoint not found ({exc})")
        except audio.AudioApplyError as exc:
            logger.exception("Windows refused audio volume for profile %s", profile.name)
            result.errors.append(f"audio: {exc}")
        except Exception as exc:
            logger.exception("unexpected error applying audio volume for profile %s", profile.name)
            result.errors.append(f"audio: {exc}")
    if profile.audio_muted is not None:
        try:
            audio.set_output_muted(profile.audio_muted, target_source)
        except audio.AudioEndpointNotFound as exc:
            logger.warning("audio endpoint not found for profile %s: %s", profile.name, exc)
            result.errors.append(f"audio: endpoint not found ({exc})")
        except audio.AudioApplyError as exc:
            logger.exception("Windows refused audio mute state for profile %s", profile.name)
            result.errors.append(f"audio: {exc}")
        except Exception as exc:
            logger.exception("unexpected error applying audio mute state for profile %s", profile.name)
            result.errors.append(f"audio: {exc}")


def _now_utc() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    """Write JSON atomically: temp file in the same dir, fsync, then os.replace.

    Why: a crash during a direct ``path.write_text`` would leave a truncated
    profile that fails to load on next start. ``os.replace`` is atomic on
    Windows and POSIX when source and destination are on the same filesystem.
    """
    serialized = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    parent = path.parent
    parent.mkdir(parents=True, exist_ok=True)
    tmp_fd, tmp_name = tempfile.mkstemp(prefix=f".{path.stem}.", suffix=".tmp", dir=str(parent))
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as handle:
            handle.write(serialized)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, path)
    except BaseException:
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise
