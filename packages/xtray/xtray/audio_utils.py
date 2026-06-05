"""Shared helpers for working with Computer Manager audio sources.

Both the tray UI and the MQTT bridge need to compare audio endpoints and
filter out disconnected outputs; keeping the logic here avoids two copies
drifting apart.
"""
from __future__ import annotations

from .services.display import audio


def same_audio_source(
    left: audio.AudioSource | None,
    right: audio.AudioSource | None,
) -> bool:
    """True when two audio sources refer to the same physical endpoint.

    Prefers the stable ``endpoint_id`` when both sides expose one, and falls
    back to the human-readable label otherwise.
    """
    if left is None or right is None:
        return False
    if left.endpoint_id and right.endpoint_id:
        return left.endpoint_id == right.endpoint_id
    return left.label() == right.label()


def active_audio_sources(sources: list[audio.AudioSource]) -> list[audio.AudioSource]:
    """Filter a list of audio sources down to the ones currently active.

    Sources with an unknown state are kept; only outputs explicitly reported
    as inactive/disconnected are dropped.
    """
    return [
        source
        for source in sources
        if source.state is None or source.state.split("|", 1)[0] == "active"
    ]
