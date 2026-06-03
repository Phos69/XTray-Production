"""Registry-based and subprocess fallbacks when Core Audio is unavailable."""
from __future__ import annotations

import os
import shlex
import subprocess
from typing import Any

from xtray.core import app_logging

ENV_AUDIO_FALLBACK_COMMAND = "DISPLAYMANAGER_AUDIO_FALLBACK_COMMAND"


def _list_audio_sources_registry() -> list:
    from .core import AudioSource

    try:
        import winreg
    except ImportError:
        return []

    path = r"Software\Microsoft\ActiveMovie\devenum\{E0F158E1-CB04-11D0-BD4E-00A0C911CE86}"
    sources: list = []
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path) as root:
            index = 0
            while True:
                try:
                    key_name = winreg.EnumKey(root, index)
                except OSError:
                    break
                index += 1
                if not key_name.lower().startswith("wave:"):
                    continue
                try:
                    with winreg.OpenKey(root, key_name) as key:
                        name = _registry_value(key, "FriendlyName")
                        endpoint_id = _registry_value(key, "EndpointId")
                        state = "active" if _registry_value(key, "WaveOutId") is not None else None
                except OSError:
                    continue
                if name:
                    sources.append(
                        AudioSource(
                            name=name,
                            endpoint_id=endpoint_id,
                            role="multimedia",
                            state=state,
                        )
                    )
    except OSError:
        return []
    return sources


def _get_default_audio_source_registry():
    sources = _list_audio_sources_registry()
    if not sources:
        return None
    return sources[0]


def _registry_value(key: Any, name: str) -> str | None:
    import winreg

    try:
        value, _kind = winreg.QueryValueEx(key, name)
    except OSError:
        return None
    if value is None:
        return None
    return str(value)


def _try_set_default_audio_source_fallback(
    source,
    endpoint_id: str,
    original_error: Exception,
) -> bool:
    from .core import AudioApplyError

    template = os.environ.get(ENV_AUDIO_FALLBACK_COMMAND)
    if not template:
        app_logging.get_logger("audio").debug(
            "audio fallback command is not configured after IPolicyConfig failure: %s",
            original_error,
        )
        return False
    command = template.format(
        name=source.name,
        label=source.label(),
        endpoint_id=endpoint_id,
    )
    args = _split_fallback_command(command)
    if not args:
        raise AudioApplyError("audio fallback command is empty") from original_error
    try:
        completed = subprocess.run(
            args,
            check=False,
            capture_output=True,
            text=True,
            timeout=15,
        )
    except Exception as exc:
        raise AudioApplyError(
            f"IPolicyConfig failed and audio fallback command could not be started: {exc}"
        ) from original_error
    if completed.returncode == 0:
        app_logging.get_logger("audio").warning(
            "used configured audio fallback command after IPolicyConfig failure: %s",
            original_error,
        )
        return True
    detail = (completed.stderr or completed.stdout or "").strip()
    suffix = f": {detail}" if detail else ""
    raise AudioApplyError(
        "IPolicyConfig failed and audio fallback command exited "
        f"with code {completed.returncode}{suffix}"
    ) from original_error


def _split_fallback_command(command: str) -> list[str]:
    return [part.strip("\"'") for part in shlex.split(command, posix=False)]
