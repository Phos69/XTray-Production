"""DisplayManager operations exposed to UI packages without Qt dependencies."""
from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from xtray import ha_rest
from xtray.core import app_logging

from computer_manager import audio_manager as audio
from computer_manager.display_manager import backend as display
from computer_manager.display_manager import inventory as display_inventory
from computer_manager.display_manager import profiles


class DisplayManagerService:
    """Thin stable facade over profiles and audio operations.

    UI packages should depend on this facade instead of reaching into the
    profile/audio modules directly. The return types intentionally stay the
    existing public model objects so current callers do not need adapters.
    """

    def list_favorite_profiles(self) -> list[str]:
        return profiles.list_favorite_profiles()

    def list_favorite_profile_icons(self) -> dict[str, str | None]:
        """Map favorite profile name -> icon identifier (or None).

        Why: the tray needs to render a button per favorite *and* know its
        icon. Doing the JSON load once here avoids the tray taking a hard
        dependency on the profiles module structure.
        """
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
        """Audio volume of the first DDC/CI monitor that responds to VCP 0x62."""
        return display.get_monitor_audio_volume_percent()

    def set_monitor_volume(self, percent: int) -> int | None:
        """Set audio volume on the first DDC/CI monitor that accepts VCP 0x62.

        Returns the applied percent, or None when no monitor accepted the command.
        """
        return display.set_monitor_audio_volume_percent(percent)

    def list_display_inventory(self) -> list[display_inventory.DisplayInventoryItem]:
        return display_inventory.collect_display_inventory()

    def list_exposed_hdmi_volume_displays(self) -> list[display.DisplayState]:
        return display_inventory.exposed_hdmi_volume_displays()

    def get_active_volume_display(self) -> display_inventory.DisplayInventoryItem | None:
        return display_inventory.active_volume_display()

    def get_ha_entity_volume_percent(self, entity_id: str) -> int | None:
        """Read a HA volume entity (``number.*`` or ``media_player.*``) as 0-100 %."""
        return ha_rest.get_entity_volume_percent(entity_id)

    def set_ha_entity_volume_percent(self, entity_id: str, percent: int) -> int:
        """Apply a 0-100 % value to a HA volume entity, dispatching by domain."""
        ha_rest.set_entity_volume_percent(entity_id, percent)
        return int(percent)

    def get_ha_number_value(self, entity_id: str) -> int | None:
        """Deprecated alias kept for backwards compatibility."""
        return self.get_ha_entity_volume_percent(entity_id)

    def set_ha_number_value(self, entity_id: str, value: int) -> int:
        """Deprecated alias kept for backwards compatibility."""
        return self.set_ha_entity_volume_percent(entity_id, value)

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
