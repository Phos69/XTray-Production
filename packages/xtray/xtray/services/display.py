"""Adapter from XTray UI surfaces to Computer Manager functionality."""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from typing import Any

from xtray import config, ha_rest
from xtray.core import app_logging

try:
    from computer_manager import audio_manager as audio
    from computer_manager.display_manager import backend as display
    from computer_manager.display_manager import inventory as display_inventory
    from computer_manager.display_manager import profiles
except ImportError:

    @dataclass(frozen=True)
    class _AudioSource:
        name: str
        endpoint_id: str | None = None
        interface_name: str | None = None
        role: str = "multimedia"
        state: str | None = None

        def to_dict(self) -> dict[str, Any]:
            return asdict(self)

        def label(self) -> str:
            if self.interface_name and self.interface_name != self.name:
                return f"{self.name} ({self.interface_name})"
            return self.name

    class _AudioModule:
        AudioSource = _AudioSource

        class AudioEndpointNotFound(Exception):
            pass

        class AudioApplyError(Exception):
            pass

        @staticmethod
        def list_audio_sources() -> list[_AudioSource]:
            return []

        @staticmethod
        def get_default_audio_source() -> _AudioSource | None:
            return None

        @staticmethod
        def get_output_volume_percent(_source: _AudioSource | None = None) -> int | None:
            return None

        @staticmethod
        def get_output_muted(_source: _AudioSource | None = None) -> bool | None:
            return None

        @staticmethod
        def set_default_audio_source(_source: _AudioSource) -> None:
            raise RuntimeError("computer_manager is not installed")

        @staticmethod
        def set_output_volume_percent(
            _percent: int,
            _source: _AudioSource | None = None,
        ) -> None:
            raise RuntimeError("computer_manager is not installed")

        @staticmethod
        def set_output_muted(_muted: bool, _source: _AudioSource | None = None) -> None:
            raise RuntimeError("computer_manager is not installed")

        @staticmethod
        def toggle_media_play_pause() -> None:
            raise RuntimeError("computer_manager is not installed")

    @dataclass
    class _DisplayState:
        device_id: str
        name: str
        primary: bool = False
        enabled: bool = True
        width: int | None = None
        height: int | None = None
        refresh_hz: int | None = None
        orientation: int = 0
        pos_x: int = 0
        pos_y: int = 0
        edid_hash: str | None = None
        stable_id: str | None = None

        def to_dict(self) -> dict[str, Any]:
            return asdict(self)

        @classmethod
        def from_dict(cls, data: dict[str, Any]) -> _DisplayState:
            allowed = cls.__dataclass_fields__.keys()
            return cls(**{key: value for key, value in data.items() if key in allowed})

    @dataclass
    class _ApplyWarning:
        message: str
        display_id: str | None = None
        detail: str | None = None

    @dataclass
    class _ApplyResult:
        applied: bool = False
        dry_run: bool = False
        warnings: list[_ApplyWarning] = field(default_factory=list)
        errors: list[str] = field(default_factory=list)

        @property
        def ok(self) -> bool:
            return not self.errors

        def to_dict(self) -> dict[str, Any]:
            return {
                "applied": self.applied,
                "dry_run": self.dry_run,
                "ok": self.ok,
                "warnings": [asdict(warning) for warning in self.warnings],
                "errors": self.errors,
            }

    @dataclass
    class _SystemState:
        displays: list[_DisplayState] = field(default_factory=list)

    class _DisplayModule:
        DisplayState = _DisplayState
        ApplyWarning = _ApplyWarning
        ApplyResult = _ApplyResult
        SystemState = _SystemState

        @staticmethod
        def stable_display_key(display_state: _DisplayState) -> str:
            return display_state.stable_id or display_state.edid_hash or display_state.device_id

        @staticmethod
        def display_identity_matches(left: _DisplayState, right: _DisplayState) -> bool:
            return _DisplayModule.stable_display_key(left) == _DisplayModule.stable_display_key(right)

        @staticmethod
        def apply_state(_state: _SystemState, *, dry_run: bool = False) -> _ApplyResult:
            return _ApplyResult(
                applied=False,
                dry_run=dry_run,
                errors=["computer_manager is not installed"],
            )

        @staticmethod
        def get_monitor_audio_volume_percent(_target: _DisplayState | None = None) -> int | None:
            return None

        @staticmethod
        def set_monitor_audio_volume_percent(
            _percent: int,
            _target: _DisplayState | None = None,
        ) -> int | None:
            raise RuntimeError("computer_manager is not installed")

    @dataclass
    class _DisplayInventoryItem:
        display: _DisplayState
        available: bool = False
        enabled: bool = False
        friendly_name: str | None = None
        volume_control: str = config.VOLUME_CONTROL_NONE
        volume_ha_entity: str | None = None

    class _DisplayInventoryModule:
        DisplayInventoryItem = _DisplayInventoryItem

        @staticmethod
        def collect_display_inventory() -> list[_DisplayInventoryItem]:
            return []

        @staticmethod
        def exposed_hdmi_volume_displays() -> list[_DisplayState]:
            return []

        @staticmethod
        def active_volume_display(*, source: _AudioSource | None = None) -> _DisplayInventoryItem | None:
            return None

        @staticmethod
        def display_title(display_state: _DisplayState) -> str:
            return display_state.name or display_state.device_id or "Display"

        @staticmethod
        def display_volume_entity_key(display_state: _DisplayState) -> str:
            return _DisplayInventoryModule.display_title(display_state).casefold().replace(" ", "_")

        @staticmethod
        def display_identity_keys(display_state: _DisplayState) -> list[str]:
            return [_DisplayModule.stable_display_key(display_state).casefold()]

        @staticmethod
        def display_matches_audio_source(
            _display_state: _DisplayState,
            _source: _AudioSource,
        ) -> bool:
            return False

        @staticmethod
        def home_assistant_power_setting(_display_state: _DisplayState) -> dict[str, Any]:
            return {
                "power_on_ha_service": None,
                "power_on_ha_service_data": None,
                "power_off_ha_service": None,
                "power_off_ha_service_data": None,
            }

        @staticmethod
        def set_hdmi_volume_exposed(_target: _DisplayState, _exposed: bool) -> None:
            raise RuntimeError("computer_manager is not installed")

        @staticmethod
        def apply_display_defaults(_state: _DisplayState) -> None:
            return None

    class _ProfilesModule:
        class ProfileNotFound(Exception):
            pass

        class InvalidProfile(Exception):
            pass

        @staticmethod
        def list_favorite_profiles() -> list[str]:
            return []

        @staticmethod
        def load_profile(_name: str) -> Any:
            raise _ProfilesModule.ProfileNotFound(_name)

        @staticmethod
        def detect_current_profile(
            *,
            profile_names: Any = None,
            match_audio: bool = False,
            include_inactive: bool = True,
        ) -> Any:
            return None

        @staticmethod
        def apply(_name: str) -> _ApplyResult:
            return _ApplyResult(errors=["computer_manager is not installed"])

    audio = _AudioModule()
    display = _DisplayModule()
    display_inventory = _DisplayInventoryModule()
    profiles = _ProfilesModule()


@dataclass(frozen=True)
class DisplayVolumeState:
    display_state: display.DisplayState
    key: str
    title: str
    mode: str
    ha_entity: str | None
    percent: int | None
    muted: bool | None = None


@dataclass(frozen=True)
class AudioPanelState:
    sources: list[audio.AudioSource]
    default_source: audio.AudioSource | None
    source_labels: dict[audio.AudioSource, str] = field(default_factory=dict)
    pc_volume_percent: int | None = None
    pc_muted: bool | None = None
    pc_volume_error: str | None = None
    display_volume: DisplayVolumeState | None = None
    display_volume_error: str | None = None


class DisplayService:
    """Thin facade over Computer Manager profiles, audio, and display inventory."""

    def list_favorite_profiles(self) -> list[str]:
        return profiles.list_favorite_profiles()

    def list_favorite_profile_icons(self) -> dict[str, str | None]:
        result: dict[str, str | None] = {}
        for name in profiles.list_favorite_profiles():
            try:
                profile = profiles.load_profile(name)
            except (profiles.ProfileNotFound, profiles.InvalidProfile) as exc:
                app_logging.get_logger("services").warning(
                    "could not read profile %s for icon lookup: %s", name, exc
                )
                result[name] = None
                continue
            result[name] = profile.icon
        return result

    def profile_missing_display_names(self, profile_name: str) -> list[str]:
        try:
            profile = profiles.load_profile(profile_name)
        except (profiles.ProfileNotFound, profiles.InvalidProfile) as exc:
            app_logging.get_logger("services").warning(
                "could not read profile %s for missing display lookup: %s",
                profile_name,
                exc,
            )
            return []
        try:
            current_displays = profiles.current_state(include_inactive=True).displays
        except Exception:
            app_logging.get_logger("services").exception(
                "could not query current display state"
            )
            return []
        missing = profiles.profile_missing_displays(profile, current_displays)
        return [display_inventory.display_title(item).strip() or item.name for item in missing]

    def profiles_missing_displays(
        self,
        profile_names: Iterable[str] | None = None,
    ) -> dict[str, bool]:
        names = list(profile_names) if profile_names is not None else self.list_favorite_profiles()
        if not names:
            return {}
        try:
            current_displays = profiles.current_state(include_inactive=True).displays
        except Exception:
            app_logging.get_logger("services").exception(
                "could not query current display state"
            )
            return {name: False for name in names}
        result: dict[str, bool] = {}
        for name in names:
            try:
                profile = profiles.load_profile(name)
            except (profiles.ProfileNotFound, profiles.InvalidProfile) as exc:
                app_logging.get_logger("services").warning(
                    "could not read profile %s for availability check: %s", name, exc
                )
                result[name] = True
                continue
            result[name] = profiles.profile_has_missing_displays(profile, current_displays)
        return result

    def detect_current_favorite_profile(
        self,
        profile_names: Iterable[str] | None = None,
    ) -> str | None:
        names = list(profile_names) if profile_names is not None else self.list_favorite_profiles()
        if not names:
            return None
        profile = profiles.detect_current_profile(
            profile_names=names,
            match_audio=False,
            include_inactive=True,
        )
        if profile is None:
            return None
        name = getattr(profile, "name", None)
        return str(name) if name else None

    def apply_profile(self, name: str) -> Any:
        return profiles.apply(name)

    def list_audio_sources(self) -> list[audio.AudioSource]:
        return audio.list_audio_sources()

    def get_default_audio_source(self) -> audio.AudioSource | None:
        return audio.get_default_audio_source()

    def load_audio_panel_state(self) -> AudioPanelState:
        """Collect tray audio state with one pass through the slower backends."""
        sources = self.list_audio_sources()
        default_source = self.get_default_audio_source()
        inventory_items: list[display_inventory.DisplayInventoryItem] | None = None
        try:
            inventory_items = display_inventory.collect_display_inventory()
        except Exception:
            app_logging.get_logger("services").exception(
                "failed to collect display inventory for audio labels"
            )
        source_labels = _audio_source_labels(sources, inventory_items or [])
        pc_volume_percent: int | None = None
        pc_volume_error: str | None = None
        try:
            pc_volume_percent = self.get_volume(None)
        except Exception as exc:
            app_logging.get_logger("services").exception("failed to read PC volume")
            pc_volume_error = str(exc)
        pc_muted: bool | None = None
        try:
            pc_muted = self.get_muted(default_source)
        except Exception:
            app_logging.get_logger("services").exception("failed to read PC muted state")

        display_volume: DisplayVolumeState | None = None
        display_volume_error: str | None = None
        try:
            if inventory_items is None:
                item = display_inventory.active_volume_display(source=default_source)
            else:
                item = _active_volume_display_from_items(default_source, inventory_items)
        except Exception:
            app_logging.get_logger("services").exception("failed to find active volume display")
            item = None
            display_volume_error = "Display volume unavailable"
        if item is None:
            display_volume_error = (
                display_volume_error or "No volume control for current audio output"
            )
        else:
            display_state = item.display
            title = display_inventory.display_title(display_state)
            mode = item.volume_control
            percent: int | None = None
            muted: bool | None = None
            if mode == config.VOLUME_CONTROL_HA_ENTITY:
                entity_id = item.volume_ha_entity
                if not entity_id:
                    display_volume_error = f"{title}: Home Assistant entity not configured"
                else:
                    try:
                        percent = self.get_ha_entity_volume_percent(entity_id)
                    except ha_rest.HaRestError as exc:
                        app_logging.get_logger("services").warning(
                            "HA volume read failed: %s", exc
                        )
                        display_volume_error = f"{title}: {exc}"
                    try:
                        muted = self.get_ha_entity_muted(entity_id)
                    except ha_rest.HaRestError as exc:
                        app_logging.get_logger("services").debug(
                            "HA muted state unavailable: %s",
                            exc,
                        )
            else:
                try:
                    percent = self.get_display_monitor_volume(display_state)
                except Exception:
                    app_logging.get_logger("services").exception(
                        "failed to read display monitor volume"
                    )
                    display_volume_error = "Display volume unavailable"
            if display_volume_error is None:
                display_volume = DisplayVolumeState(
                    display_state=display_state,
                    key=display_inventory.display_volume_entity_key(display_state),
                    title=title,
                    mode=mode,
                    ha_entity=item.volume_ha_entity,
                    percent=percent,
                    muted=muted,
                )

        return AudioPanelState(
            sources=sources,
            default_source=default_source,
            source_labels=source_labels,
            pc_volume_percent=pc_volume_percent,
            pc_muted=pc_muted,
            pc_volume_error=pc_volume_error,
            display_volume=display_volume,
            display_volume_error=display_volume_error,
        )

    def audio_source_labels(
        self,
        sources: list[audio.AudioSource],
    ) -> dict[audio.AudioSource, str]:
        try:
            items = display_inventory.collect_display_inventory()
        except Exception:
            app_logging.get_logger("services").exception(
                "failed to collect display inventory for audio labels"
            )
            return {}
        return _audio_source_labels(sources, items)

    def set_audio_source(self, source: audio.AudioSource) -> audio.AudioSource:
        audio.set_default_audio_source(source)
        return source

    def get_volume(self, source: audio.AudioSource | None = None) -> int | None:
        return audio.get_output_volume_percent(source)

    def set_volume(self, percent: int, source: audio.AudioSource | None = None) -> int:
        audio.set_output_volume_percent(percent, source)
        return percent

    def get_muted(self, source: audio.AudioSource | None = None) -> bool | None:
        return audio.get_output_muted(source)

    def set_muted(self, muted: bool, source: audio.AudioSource | None = None) -> bool:
        audio.set_output_muted(muted, source)
        return muted

    def toggle_media_play_pause(self) -> None:
        audio.toggle_media_play_pause()

    def get_monitor_volume(self) -> int | None:
        return display.get_monitor_audio_volume_percent()

    def set_monitor_volume(self, percent: int) -> int | None:
        return display.set_monitor_audio_volume_percent(percent)

    def list_display_inventory(self) -> list[display_inventory.DisplayInventoryItem]:
        return display_inventory.collect_display_inventory()

    def list_exposed_hdmi_volume_displays(self) -> list[display.DisplayState]:
        return display_inventory.exposed_hdmi_volume_displays()

    def get_active_volume_display(self) -> display_inventory.DisplayInventoryItem | None:
        return display_inventory.active_volume_display()

    def get_ha_entity_volume_percent(self, entity_id: str) -> int | None:
        return ha_rest.get_entity_volume_percent(entity_id)

    def set_ha_entity_volume_percent(self, entity_id: str, percent: int) -> int:
        ha_rest.set_entity_volume_percent(entity_id, percent)
        return int(percent)

    def get_ha_entity_muted(self, entity_id: str) -> bool | None:
        return ha_rest.get_entity_muted(entity_id)

    def set_ha_entity_muted(self, entity_id: str, muted: bool) -> bool:
        ha_rest.set_entity_muted(entity_id, muted)
        return bool(muted)

    def set_display_enabled(
        self,
        target: display.DisplayState,
        enabled: bool,
    ) -> display.ApplyResult:
        items = display_inventory.collect_display_inventory()
        target_key = display.stable_display_key(target)
        matched = False
        requested: list[display.DisplayState] = []
        for item in items:
            state = display.DisplayState.from_dict(item.display.to_dict())
            state.enabled = bool(item.enabled)
            if not state.enabled:
                state.primary = False
            if _same_display(state, target, target_key=target_key):
                matched = True
                state.enabled = bool(enabled)
                if not state.enabled:
                    state.primary = False
                else:
                    display_inventory.apply_display_defaults(state)
            requested.append(state)
        if not matched:
            raise ValueError("display is no longer available")
        if not any(state.enabled for state in requested):
            raise ValueError("cannot disable the last enabled display")
        return display.apply_state(display.SystemState(displays=requested))

    def set_display_primary(
        self,
        target: display.DisplayState,
    ) -> display.ApplyResult:
        items = display_inventory.collect_display_inventory()
        target_key = display.stable_display_key(target)
        matched = False
        requested: list[display.DisplayState] = []
        for item in items:
            state = display.DisplayState.from_dict(item.display.to_dict())
            state.enabled = bool(item.enabled)
            if _same_display(state, target, target_key=target_key):
                matched = True
                if not state.enabled:
                    raise ValueError("cannot make a disabled display primary")
                state.primary = True
            else:
                state.primary = False
            requested.append(state)
        if not matched:
            raise ValueError("display is no longer available")
        return display.apply_state(display.SystemState(displays=requested))

    def call_display_power_service(
        self,
        target: display.DisplayState,
        *,
        turn_on: bool,
    ) -> str:
        setting = display_inventory.home_assistant_power_setting(target)
        service_key = "power_on_ha_service" if turn_on else "power_off_ha_service"
        data_key = (
            "power_on_ha_service_data" if turn_on else "power_off_ha_service_data"
        )
        service_id = setting.get(service_key)
        if not service_id:
            action = "power on" if turn_on else "power off"
            raise ha_rest.HaRestError(f"Home Assistant {action} service is not configured")
        payload = setting.get(data_key)
        ha_rest.call_service(
            str(service_id),
            payload if isinstance(payload, dict) else None,
        )
        return str(service_id)

    def get_display_monitor_volume(self, target: display.DisplayState) -> int | None:
        return display.get_monitor_audio_volume_percent(target)

    def set_display_monitor_volume(
        self,
        target: display.DisplayState,
        percent: int,
    ) -> int | None:
        return display.set_monitor_audio_volume_percent(percent, target)

    def set_display_hdmi_volume_exposed(
        self,
        target: display.DisplayState,
        exposed: bool,
    ) -> None:
        display_inventory.set_hdmi_volume_exposed(target, exposed)


def _same_display(
    left: display.DisplayState,
    right: display.DisplayState,
    *,
    target_key: str | None = None,
) -> bool:
    if display.display_identity_matches(left, right):
        return True
    left_keys = set(display_inventory.display_identity_keys(left))
    right_keys = set(display_inventory.display_identity_keys(right))
    if target_key:
        right_keys.add(target_key.casefold())
    return bool(left_keys & right_keys)


def _audio_source_labels(
    sources: list[audio.AudioSource],
    items: list[display_inventory.DisplayInventoryItem],
) -> dict[audio.AudioSource, str]:
    labels: dict[audio.AudioSource, str] = {}
    for source in sources:
        item = _audio_source_display_item(source, items)
        friendly_name = getattr(item, "friendly_name", None) if item is not None else None
        if friendly_name:
            labels[source] = str(friendly_name)
    return labels


def _active_volume_display_from_items(
    source: audio.AudioSource | None,
    items: list[display_inventory.DisplayInventoryItem],
) -> display_inventory.DisplayInventoryItem | None:
    if source is None:
        return None
    for item in items:
        if item.volume_control == config.VOLUME_CONTROL_NONE:
            continue
        if display_inventory.display_matches_audio_source(item.display, source):
            return item
    return None


def _audio_source_display_item(
    source: audio.AudioSource,
    items: list[display_inventory.DisplayInventoryItem],
) -> display_inventory.DisplayInventoryItem | None:
    for item in items:
        if display_inventory.display_matches_audio_source(item.display, source):
            return item
    return None
