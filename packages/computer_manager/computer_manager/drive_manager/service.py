"""Windows logical drive and SMB mapping service."""
from __future__ import annotations

import subprocess
from typing import Any

from xtray.core.computer_models import DriveInfo

from .._powershell import (
    as_list as _as_list,
)
from .._powershell import (
    int_or_none as _int_or_none,
)
from .._powershell import (
    ps_quote as _ps_quote,
)
from .._powershell import (
    run_powershell as _shared_run_powershell,
)
from .._powershell import (
    run_powershell_json as _shared_run_powershell_json,
)
from .._powershell import (
    text as _text,
)


class DriveServiceError(RuntimeError):
    """Raised when drive inventory or mapping commands fail."""


DRIVE_TYPES = {
    0: "Unknown",
    1: "No root",
    2: "Removable",
    3: "Local",
    4: "Network",
    5: "CD-ROM",
    6: "RAM disk",
}


class DriveService:
    def list_drives(self) -> list[DriveInfo]:
        payload = _run_powershell_json(_drive_inventory_script())
        return _parse_drive_inventory(payload)

    def open_drive(self, drive: DriveInfo) -> None:
        subprocess.Popen(["explorer.exe", drive.open_target], shell=False)

    def map_network_drive(
        self,
        *,
        letter: str,
        remote_path: str,
        username: str | None = None,
        password: str | None = None,
        persistent: bool = True,
    ) -> None:
        normalized_letter = _normalize_letter(letter)
        if not remote_path.strip().startswith("\\\\"):
            raise DriveServiceError("network drive path must be a UNC path")
        persistent_value = "$true" if persistent else "$false"
        command = (
            "New-SmbMapping "
            f"-LocalPath {_ps_quote(normalized_letter + ':')} "
            f"-RemotePath {_ps_quote(remote_path.strip())} "
            f"-Persistent {persistent_value} "
            "-ErrorAction Stop"
        )
        if username:
            command += f" -UserName {_ps_quote(username.strip())}"
        if password:
            command += f" -Password {_ps_quote(password)}"
        _run_powershell(command)


def _drive_inventory_script() -> str:
    return r"""
$logical = Get-CimInstance Win32_LogicalDisk | Select-Object `
    DeviceID, DriveType, VolumeName, FileSystem, Size, FreeSpace, ProviderName
$smb = Get-SmbMapping | Select-Object LocalPath, RemotePath, Status
[pscustomobject]@{
    LogicalDisks = @($logical)
    SmbMappings = @($smb)
} | ConvertTo-Json -Depth 5
""".strip()


def _parse_drive_inventory(payload: Any) -> list[DriveInfo]:
    if not isinstance(payload, dict):
        raise DriveServiceError("drive inventory did not return an object")
    mappings = {
        str(entry.get("LocalPath") or "").rstrip("\\").upper(): entry
        for entry in _as_list(payload.get("SmbMappings"))
        if isinstance(entry, dict)
    }
    drives: list[DriveInfo] = []
    for raw in _as_list(payload.get("LogicalDisks")):
        if not isinstance(raw, dict):
            continue
        device_id = str(raw.get("DeviceID") or "").rstrip("\\")
        if not device_id.endswith(":"):
            continue
        letter = device_id[:-1].upper()
        mapping = mappings.get(device_id.upper(), {})
        drive_type_id = _int_or_none(raw.get("DriveType"))
        drive_type = DRIVE_TYPES.get(drive_type_id or 0, "Unknown")
        remote_path = _text(mapping.get("RemotePath")) or _text(raw.get("ProviderName"))
        drives.append(
            DriveInfo(
                letter=letter,
                drive_type=drive_type,
                label=_text(raw.get("VolumeName")),
                filesystem=_text(raw.get("FileSystem")),
                size=_int_or_none(raw.get("Size")),
                free_space=_int_or_none(raw.get("FreeSpace")),
                provider_name=_text(raw.get("ProviderName")),
                remote_path=remote_path,
                status=_text(mapping.get("Status")),
                raw=raw,
            )
        )
    return sorted(drives, key=lambda drive: drive.letter)


def _run_powershell_json(script: str) -> Any:
    return _shared_run_powershell_json(script, DriveServiceError)


def _run_powershell(script: str) -> str:
    return _shared_run_powershell(script, DriveServiceError)


def _normalize_letter(value: str) -> str:
    text = str(value or "").strip().rstrip(":").upper()
    if len(text) != 1 or not ("A" <= text <= "Z"):
        raise DriveServiceError("drive letter must be A-Z")
    return text
