"""GitHub release updater for installed XTray builds."""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from . import __version__, config

DEFAULT_UPDATE_REPO = "Phos69/XTray-Production"
ENV_UPDATE_API_URL = "XTRAY_UPDATE_API_URL"
ENV_UPDATE_REPO = "XTRAY_UPDATE_REPO"
ENV_DISABLE_UPDATE_CHECKS = "XTRAY_DISABLE_UPDATE_CHECKS"
ENV_FORCE_UPDATE_CHECKS = "XTRAY_FORCE_UPDATE_CHECKS"

DEFAULT_CONNECT_TIMEOUT_SECONDS = 10
DEFAULT_DOWNLOAD_TIMEOUT_SECONDS = 60
AUTO_CHECK_DELAY_MS = 30_000
INSTALLER_NAME_RE = re.compile(r"^XTray-Setup-(?P<version>.+)\.exe$", re.IGNORECASE)
DEFAULT_INSTALLER_ARGS = (
    "/VERYSILENT",
    "/SUPPRESSMSGBOXES",
    "/NORESTART",
    "/CLOSEAPPLICATIONS",
    "/RESTARTAPPLICATIONS",
)


class UpdateError(RuntimeError):
    """Raised when an update check, download, or launch cannot complete."""


@dataclass(frozen=True)
class ReleaseAsset:
    name: str
    download_url: str
    size: int | None = None


@dataclass(frozen=True)
class UpdateInfo:
    version: str
    release_url: str
    asset: ReleaseAsset
    title: str = ""
    published_at: str = ""


def _env_truthy(name: str) -> bool:
    return str(os.environ.get(name) or "").strip().casefold() in {"1", "true", "yes", "on"}


def release_api_url() -> str:
    override = os.environ.get(ENV_UPDATE_API_URL)
    if override:
        return override
    repo = (os.environ.get(ENV_UPDATE_REPO) or DEFAULT_UPDATE_REPO).strip()
    return f"https://api.github.com/repos/{repo}/releases/latest"


def update_checks_supported() -> bool:
    return sys.platform == "win32"


def automatic_checks_enabled() -> bool:
    if _env_truthy(ENV_DISABLE_UPDATE_CHECKS):
        return False
    if _env_truthy(ENV_FORCE_UPDATE_CHECKS):
        return update_checks_supported()
    return update_checks_supported() and bool(getattr(sys, "frozen", False))


def updates_dir() -> Path:
    path = config.log_dir().parent / "updates"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _version_key(value: str) -> tuple[int, ...]:
    text = str(value or "").strip()
    if text[:1].casefold() == "v":
        text = text[1:]
    text = text.split("+", 1)[0].split("-", 1)[0]
    parts = [int(part) for part in re.findall(r"\d+", text)]
    while len(parts) > 1 and parts[-1] == 0:
        parts.pop()
    return tuple(parts or [0])


def is_newer_version(candidate: str, current: str = __version__) -> bool:
    return _version_key(candidate) > _version_key(current)


def _asset_version(asset_name: str) -> str | None:
    match = INSTALLER_NAME_RE.match(asset_name)
    if not match:
        return None
    return match.group("version")


def _asset_from_payload(value: Any) -> ReleaseAsset | None:
    if not isinstance(value, dict):
        return None
    name = str(value.get("name") or "").strip()
    download_url = str(value.get("browser_download_url") or "").strip()
    if not name or not download_url or _asset_version(name) is None:
        return None
    size_value = value.get("size")
    size = size_value if isinstance(size_value, int) and size_value >= 0 else None
    return ReleaseAsset(name=name, download_url=download_url, size=size)


def _select_installer_asset(payload: dict[str, Any], version: str) -> ReleaseAsset | None:
    assets = [
        asset
        for asset in (_asset_from_payload(item) for item in payload.get("assets") or [])
        if asset is not None
    ]
    if not assets:
        return None

    release_key = _version_key(version)
    for asset in assets:
        asset_version = _asset_version(asset.name)
        if asset_version is not None and _version_key(asset_version) == release_key:
            return asset
    return assets[0]


def update_from_release_payload(
    payload: dict[str, Any],
    *,
    current_version: str = __version__,
) -> UpdateInfo | None:
    if payload.get("draft") or payload.get("prerelease"):
        return None

    version = str(payload.get("tag_name") or payload.get("name") or "").strip()
    if version[:1].casefold() == "v":
        version = version[1:]
    if not version or not is_newer_version(version, current_version):
        return None

    asset = _select_installer_asset(payload, version)
    if asset is None:
        raise UpdateError(f"release {version} does not include an XTray installer asset")

    return UpdateInfo(
        version=version,
        release_url=str(payload.get("html_url") or ""),
        asset=asset,
        title=str(payload.get("name") or ""),
        published_at=str(payload.get("published_at") or ""),
    )


def _load_json_url(url: str, *, timeout: int = DEFAULT_CONNECT_TIMEOUT_SECONDS) -> dict[str, Any]:
    request = Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": f"XTray/{__version__} updater",
        },
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            data = response.read()
    except HTTPError as exc:
        if exc.code == 404:
            raise UpdateError("no public XTray release was found") from exc
        raise UpdateError(f"GitHub update check failed: HTTP {exc.code}") from exc
    except URLError as exc:
        reason = getattr(exc, "reason", exc)
        raise UpdateError(f"GitHub update check failed: {reason}") from exc
    except OSError as exc:
        raise UpdateError(f"GitHub update check failed: {exc}") from exc

    try:
        payload = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise UpdateError("GitHub update response was not valid JSON") from exc
    if not isinstance(payload, dict):
        raise UpdateError("GitHub update response had an unexpected shape")
    return payload


def check_for_update(
    *,
    current_version: str = __version__,
    timeout: int = DEFAULT_CONNECT_TIMEOUT_SECONDS,
) -> UpdateInfo | None:
    if not update_checks_supported():
        raise UpdateError("XTray updates are only supported on Windows.")
    payload = _load_json_url(release_api_url(), timeout=timeout)
    return update_from_release_payload(payload, current_version=current_version)


def _safe_asset_name(name: str) -> str:
    candidate = Path(name).name
    if candidate != name or _asset_version(candidate) is None:
        raise UpdateError(f"unsafe update asset name: {name!r}")
    return candidate


def download_update_installer(
    update: UpdateInfo,
    *,
    target_dir: Path | None = None,
    timeout: int = DEFAULT_DOWNLOAD_TIMEOUT_SECONDS,
) -> Path:
    target_root = target_dir or updates_dir()
    target_root.mkdir(parents=True, exist_ok=True)
    target = target_root / _safe_asset_name(update.asset.name)
    temp = target.with_suffix(target.suffix + ".download")

    request = Request(
        update.asset.download_url,
        headers={"User-Agent": f"XTray/{__version__} updater"},
    )
    try:
        with urlopen(request, timeout=timeout) as response, temp.open("wb") as handle:
            shutil.copyfileobj(response, handle)
    except (HTTPError, URLError, OSError) as exc:
        temp.unlink(missing_ok=True)
        raise UpdateError(f"could not download XTray update: {exc}") from exc

    if update.asset.size is not None and temp.stat().st_size != update.asset.size:
        actual_size = temp.stat().st_size
        temp.unlink(missing_ok=True)
        raise UpdateError(
            f"downloaded installer size mismatch: expected {update.asset.size}, got {actual_size}"
        )

    temp.replace(target)
    return target


def default_install_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    root = os.environ.get("LOCALAPPDATA")
    if root:
        return Path(root) / "Programs" / "XTray"
    return Path.home() / "AppData" / "Local" / "Programs" / "XTray"


def _ps_quote(value: str | Path) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def _helper_script_text(
    *,
    installer_path: Path,
    install_dir: Path,
    wait_pid: int,
    start_after_install: bool,
    installer_args: tuple[str, ...],
) -> str:
    args = ", ".join(_ps_quote(arg) for arg in installer_args)
    launch_block = ""
    if start_after_install:
        launch_block = """
if ($exitCode -eq 0) {
    $exe = Join-Path $installDir 'XTray.exe'
    if (Test-Path -LiteralPath $exe) {
        Start-Process -FilePath $exe -WindowStyle Hidden
    }
}
"""
    return f"""$ErrorActionPreference = 'SilentlyContinue'
$installer = {_ps_quote(installer_path)}
$installDir = {_ps_quote(install_dir)}
$waitPid = {int(wait_pid)}
$arguments = @({args})

try {{
    Wait-Process -Id $waitPid -Timeout 30
}} catch {{
}}

$process = Start-Process -FilePath $installer -ArgumentList $arguments -Wait -PassThru -WindowStyle Hidden
$exitCode = 1
if ($null -ne $process) {{
    $exitCode = $process.ExitCode
}}
{launch_block}
Start-Sleep -Seconds 2
Remove-Item -LiteralPath $PSCommandPath -Force -ErrorAction SilentlyContinue
"""


def start_update_installer(
    installer_path: Path,
    *,
    install_dir: Path | None = None,
    wait_pid: int | None = None,
    start_after_install: bool = True,
    installer_args: tuple[str, ...] = DEFAULT_INSTALLER_ARGS,
) -> Path:
    if sys.platform != "win32":
        raise UpdateError("XTray updates are only supported on Windows.")

    installer = Path(installer_path).resolve()
    if not installer.exists():
        raise UpdateError(f"update installer not found: {installer}")

    powershell = shutil.which("powershell.exe") or shutil.which("powershell")
    if not powershell:
        raise UpdateError("PowerShell was not found; cannot launch the update installer.")

    helper = updates_dir() / f"xtray-update-{os.getpid()}-{int(time.time())}.ps1"
    helper.write_text(
        _helper_script_text(
            installer_path=installer,
            install_dir=(install_dir or default_install_dir()).resolve(),
            wait_pid=wait_pid or os.getpid(),
            start_after_install=start_after_install,
            installer_args=installer_args,
        ),
        encoding="utf-8",
    )
    subprocess.Popen(
        [
            powershell,
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-WindowStyle",
            "Hidden",
            "-File",
            str(helper),
        ],
        close_fds=True,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    return helper
