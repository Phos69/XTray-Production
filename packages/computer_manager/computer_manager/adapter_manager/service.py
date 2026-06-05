"""Windows local network adapter service."""
from __future__ import annotations

import base64
import subprocess
import sys
from typing import Any

from xtray.core.computer_models import AdapterIpSettings, NetworkAdapter

from .._powershell import (
    as_list as _as_list,
)
from .._powershell import (
    hidden_subprocess_creationflags as _hidden_subprocess_creationflags,
)
from .._powershell import (
    int_or_none as _int_or_none,
)
from .._powershell import (
    ps_quote as _ps_quote,
)
from .._powershell import (
    run_powershell_json as _shared_run_powershell_json,
)
from .._powershell import (
    text as _text,
)


class AdapterServiceError(RuntimeError):
    """Raised when Windows adapter commands fail."""


class AdapterService:
    def list_adapters(self) -> list[NetworkAdapter]:
        payload = _run_powershell_json(_adapter_inventory_script())
        return _parse_adapter_inventory(payload)

    def open_network_connections(self) -> None:
        _open_network_connections()

    def open_adapter_properties(self, adapter: NetworkAdapter) -> None:
        _open_adapter_properties(adapter)

    def set_adapter_enabled(self, adapter: NetworkAdapter, enabled: bool) -> None:
        command = "Enable-NetAdapter" if enabled else "Disable-NetAdapter"
        script = (
            f"{command} -Name {_ps_quote(adapter.name)} -Confirm:$false "
            "-ErrorAction Stop"
        )
        _run_elevated_powershell(script)

    def set_ip_settings(
        self,
        adapter: NetworkAdapter,
        settings: AdapterIpSettings,
    ) -> None:
        if settings.dhcp_enabled:
            script = "\n".join(
                [
                    (
                        "Set-NetIPInterface "
                        f"-InterfaceIndex {adapter.if_index} -AddressFamily IPv4 "
                        "-Dhcp Enabled -ErrorAction Stop"
                    ),
                    (
                        "Set-DnsClientServerAddress "
                        f"-InterfaceIndex {adapter.if_index} -ResetServerAddresses "
                        "-ErrorAction Stop"
                    ),
                ]
            )
            _run_elevated_powershell(script)
            return

        if not settings.ip_address or settings.prefix_length is None:
            raise AdapterServiceError("static IP address and prefix length are required")

        gateway = (
            f" -DefaultGateway {_ps_quote(settings.gateway)}"
            if settings.gateway
            else ""
        )
        if settings.dns_servers:
            dns_values = ", ".join(_ps_quote(server) for server in settings.dns_servers)
            dns_command = (
                "Set-DnsClientServerAddress "
                f"-InterfaceIndex {adapter.if_index} -ServerAddresses @({dns_values}) "
                "-ErrorAction Stop"
            )
        else:
            dns_command = (
                "Set-DnsClientServerAddress "
                f"-InterfaceIndex {adapter.if_index} -ResetServerAddresses "
                "-ErrorAction Stop"
            )
        script = "\n".join(
            [
                (
                    "Set-NetIPInterface "
                    f"-InterfaceIndex {adapter.if_index} -AddressFamily IPv4 "
                    "-Dhcp Disabled -ErrorAction Stop"
                ),
                (
                    "Get-NetIPAddress "
                    f"-InterfaceIndex {adapter.if_index} -AddressFamily IPv4 "
                    "-ErrorAction SilentlyContinue | "
                    "Where-Object {$_.PrefixOrigin -ne 'WellKnown'} | "
                    "Remove-NetIPAddress -Confirm:$false -ErrorAction SilentlyContinue"
                ),
                (
                    "New-NetIPAddress "
                    f"-InterfaceIndex {adapter.if_index} "
                    f"-IPAddress {_ps_quote(settings.ip_address)} "
                    f"-PrefixLength {int(settings.prefix_length)}"
                    f"{gateway} -ErrorAction Stop"
                ),
                dns_command,
            ]
        )
        _run_elevated_powershell(script)


def _adapter_inventory_script() -> str:
    return r"""
$adapters = Get-NetAdapter | Select-Object `
    Name, InterfaceDescription, Status, MacAddress, LinkSpeed, ifIndex
$configs = Get-NetIPConfiguration | Select-Object `
    InterfaceAlias, InterfaceIndex, `
    @{Name='IPv4Address';Expression={@($_.IPv4Address | ForEach-Object {$_.IPAddress})}}, `
    @{Name='IPv4PrefixLength';Expression={@($_.IPv4Address | ForEach-Object {$_.PrefixLength})}}, `
    @{Name='IPv4DefaultGateway';Expression={ `
        @($_.IPv4DefaultGateway | ForEach-Object {$_.NextHop}) `
    }}, `
    @{Name='DNSServer';Expression={@($_.DNSServer.ServerAddresses)}}
$interfaces = Get-NetIPInterface -AddressFamily IPv4 | Select-Object `
    InterfaceAlias, InterfaceIndex, Dhcp, ConnectionState
[pscustomobject]@{
    Adapters = @($adapters)
    Configurations = @($configs)
    Interfaces = @($interfaces)
} | ConvertTo-Json -Depth 6
""".strip()


def _open_network_connections() -> None:
    try:
        subprocess.Popen(
            ["control.exe", "ncpa.cpl"],
            shell=False,
            creationflags=_hidden_subprocess_creationflags(),
        )
    except OSError as exc:
        raise AdapterServiceError(f"could not open Network Connections: {exc}") from exc


def _open_adapter_properties(adapter: NetworkAdapter) -> None:
    script = r"""
$adapterName = __ADAPTER_NAME__
$shell = New-Object -ComObject Shell.Application
$folder = $shell.Namespace(0x31)
if ($null -eq $folder) {
    Start-Process -FilePath "control.exe" -ArgumentList "ncpa.cpl"
    return
}
$item = @($folder.Items()) | Where-Object { $_.Name -eq $adapterName } | Select-Object -First 1
if ($null -eq $item) {
    Start-Process -FilePath "control.exe" -ArgumentList "ncpa.cpl"
    return
}
$propertiesVerb = @($item.Verbs()) | Where-Object {
    $name = ($_.Name -replace "&", "").Trim().ToLowerInvariant()
    $name -like "*propert*" -or
        $name -like "*propriet*" -or
        $name -like "*propiedad*" -or
        $name -like "*propri*" -or
        $name -like "*eigenschaft*"
} | Select-Object -First 1
if ($null -eq $propertiesVerb) {
    Start-Process -FilePath "control.exe" -ArgumentList "ncpa.cpl"
    return
}
$propertiesVerb.DoIt()
Start-Sleep -Milliseconds 250
""".strip().replace("__ADAPTER_NAME__", _ps_quote(adapter.name))
    _run_powershell_detached(script)


def _parse_adapter_inventory(payload: Any) -> list[NetworkAdapter]:
    if not isinstance(payload, dict):
        raise AdapterServiceError("adapter inventory did not return an object")
    configs = {
        int(config.get("InterfaceIndex")): config
        for config in _as_list(payload.get("Configurations"))
        if isinstance(config, dict) and _int_or_none(config.get("InterfaceIndex")) is not None
    }
    interfaces = {
        int(entry.get("InterfaceIndex")): entry
        for entry in _as_list(payload.get("Interfaces"))
        if isinstance(entry, dict) and _int_or_none(entry.get("InterfaceIndex")) is not None
    }
    adapters: list[NetworkAdapter] = []
    for raw_adapter in _as_list(payload.get("Adapters")):
        if not isinstance(raw_adapter, dict):
            continue
        if_index = _int_or_none(raw_adapter.get("ifIndex"))
        if if_index is None:
            continue
        config = configs.get(if_index, {})
        interface = interfaces.get(if_index, {})
        adapters.append(
            NetworkAdapter(
                name=str(raw_adapter.get("Name") or ""),
                description=str(raw_adapter.get("InterfaceDescription") or ""),
                status=str(raw_adapter.get("Status") or ""),
                mac_address=_text(raw_adapter.get("MacAddress")),
                link_speed=_text(raw_adapter.get("LinkSpeed")),
                if_index=if_index,
                dhcp_enabled=_is_dhcp_enabled(interface.get("Dhcp")),
                connection_state=_text(interface.get("ConnectionState")),
                ipv4_addresses=tuple(
                    str(value) for value in _ps_values(config.get("IPv4Address")) if value
                ),
                ipv4_prefix_lengths=tuple(
                    int(value)
                    for value in _ps_values(config.get("IPv4PrefixLength"))
                    if _int_or_none(value) is not None
                ),
                gateway=next(
                    (
                        str(value)
                        for value in _ps_values(config.get("IPv4DefaultGateway"))
                        if value
                    ),
                    None,
                ),
                dns_servers=tuple(
                    str(value) for value in _ps_values(config.get("DNSServer")) if value
                ),
                raw=raw_adapter,
            )
        )
    return sorted(adapters, key=lambda adapter: adapter.name.casefold())


def _is_dhcp_enabled(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    number = _int_or_none(value)
    if number is not None:
        return number == 1
    return str(value or "").strip().casefold() in {
        "enabled",
        "enable",
        "true",
        "yes",
        "on",
    }


def _ps_values(value: Any) -> list[Any]:
    if isinstance(value, dict) and "Count" in value:
        if "value" in value:
            return _as_list(value.get("value"))
        if "Value" in value:
            return _as_list(value.get("Value"))
    return _as_list(value)


def _run_powershell_json(script: str) -> Any:
    return _shared_run_powershell_json(script, AdapterServiceError)


def _run_powershell_detached(script: str) -> None:
    encoded = base64.b64encode(script.encode("utf-16le")).decode("ascii")
    try:
        subprocess.Popen(
            [
                "powershell",
                "-NoProfile",
                "-STA",
                "-ExecutionPolicy",
                "Bypass",
                "-EncodedCommand",
                encoded,
            ],
            shell=False,
            creationflags=_hidden_subprocess_creationflags(),
        )
    except OSError as exc:
        raise AdapterServiceError(f"could not open adapter properties: {exc}") from exc


def _run_elevated_powershell(script: str) -> None:
    if sys.platform != "win32":
        raise AdapterServiceError("adapter changes are only available on Windows")
    import ctypes
    from ctypes import wintypes

    encoded = base64.b64encode(script.encode("utf-16le")).decode("ascii")
    params = (
        f"-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass "
        f"-EncodedCommand {encoded}"
    )
    shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    class SHELLEXECUTEINFO(ctypes.Structure):
        _fields_ = [
            ("cbSize", wintypes.DWORD),
            ("fMask", wintypes.ULONG),
            ("hwnd", wintypes.HWND),
            ("lpVerb", wintypes.LPCWSTR),
            ("lpFile", wintypes.LPCWSTR),
            ("lpParameters", wintypes.LPCWSTR),
            ("lpDirectory", wintypes.LPCWSTR),
            ("nShow", ctypes.c_int),
            ("hInstApp", wintypes.HINSTANCE),
            ("lpIDList", ctypes.c_void_p),
            ("lpClass", wintypes.LPCWSTR),
            ("hkeyClass", wintypes.HKEY),
            ("dwHotKey", wintypes.DWORD),
            ("hIcon", wintypes.HANDLE),
            ("hProcess", wintypes.HANDLE),
        ]

    SEE_MASK_NOCLOSEPROCESS = 0x00000040
    SW_HIDE = 0
    WAIT_OBJECT_0 = 0x00000000
    INFINITE = 0xFFFFFFFF
    info = SHELLEXECUTEINFO()
    info.cbSize = ctypes.sizeof(SHELLEXECUTEINFO)
    info.fMask = SEE_MASK_NOCLOSEPROCESS
    info.lpVerb = "runas"
    info.lpFile = "powershell.exe"
    info.lpParameters = params
    info.nShow = SW_HIDE
    if not shell32.ShellExecuteExW(ctypes.byref(info)):
        raise AdapterServiceError("elevated PowerShell command was cancelled or failed")
    wait_result = kernel32.WaitForSingleObject(info.hProcess, INFINITE)
    exit_code = wintypes.DWORD()
    kernel32.GetExitCodeProcess(info.hProcess, ctypes.byref(exit_code))
    kernel32.CloseHandle(info.hProcess)
    if wait_result != WAIT_OBJECT_0 or exit_code.value != 0:
        raise AdapterServiceError("elevated PowerShell command failed")
