"""Windows built-in ping and network discovery helpers."""
from __future__ import annotations

import ipaddress
import json
import logging
import platform
import re
import subprocess
import sys
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Any

from .models import DiscoveredDevice, NetworkAdapter, NetworkDevice, NetworkStatus, normalize_mac

DEFAULT_PING_TIMEOUT_MS = 800
DEFAULT_SCAN_WORKERS = 64
log = logging.getLogger("network_manager.devices")


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str = ""
    stderr: str = ""


CommandRunner = Callable[[list[str], int | None], CommandResult]


def list_adapters(*, runner: CommandRunner | None = None) -> list[NetworkAdapter]:
    runner = runner or run_command
    result = runner(_powershell_adapter_command(), 10)
    if result.returncode != 0:
        log.warning(
            "Get-NetIPConfiguration failed: %s",
            result.stderr.strip() or result.stdout.strip(),
        )
        return []
    return _parse_adapter_json(result.stdout)


def local_adapter_mac(*, runner: CommandRunner | None = None) -> str | None:
    for adapter in list_adapters(runner=runner):
        if adapter.mac:
            return adapter.mac
    return None


def ping_device(
    device: NetworkDevice,
    *,
    timeout_ms: int = DEFAULT_PING_TIMEOUT_MS,
    runner: CommandRunner | None = None,
) -> NetworkStatus:
    online, latency_ms, detail = ping_ip(device.ip, timeout_ms=timeout_ms, runner=runner)
    return NetworkStatus(device=device, online=online, latency_ms=latency_ms, detail=detail)


def ping_ip(
    ip: str,
    *,
    timeout_ms: int = DEFAULT_PING_TIMEOUT_MS,
    runner: CommandRunner | None = None,
) -> tuple[bool, int | None, str | None]:
    runner = runner or run_command
    result = runner(_ping_command(ip, timeout_ms), max(1, timeout_ms // 1000 + 2))
    output = "\n".join(part for part in (result.stdout, result.stderr) if part).strip()
    latency_ms = _parse_ping_latency(output)
    online = result.returncode == 0 or latency_ms is not None or "ttl=" in output.casefold()
    if online:
        return True, latency_ms, None
    return False, None, output or f"ping exited with {result.returncode}"


def scan_adapter(
    adapter: NetworkAdapter,
    *,
    timeout_ms: int = DEFAULT_PING_TIMEOUT_MS,
    max_workers: int = DEFAULT_SCAN_WORKERS,
    runner: CommandRunner | None = None,
) -> list[DiscoveredDevice]:
    runner = runner or run_command
    hosts = _scan_hosts(adapter)
    neighbor_map = _neighbor_mac_map(adapter, runner=runner)
    discovered: list[DiscoveredDevice] = []
    with ThreadPoolExecutor(max_workers=max(1, max_workers)) as executor:
        futures = {
            executor.submit(ping_ip, host, timeout_ms=timeout_ms, runner=runner): host
            for host in hosts
        }
        for future in as_completed(futures):
            host = futures[future]
            try:
                online, _latency_ms, _detail = future.result()
            except Exception as exc:
                log.debug(
                    "ping failed during scan for %s: %s", host, exc, exc_info=True
                )
                continue
            if online:
                discovered.append(
                    DiscoveredDevice.create(
                        ip=host,
                        mac=neighbor_map.get(host),
                        name=f"Device {host}",
                    )
                )
    return sorted(discovered, key=lambda item: ipaddress.ip_address(item.ip))


def run_command(args: list[str], timeout_seconds: int | None = None) -> CommandResult:
    try:
        completed = subprocess.run(
            args,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            **_hidden_subprocess_kwargs(),
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return CommandResult(returncode=1, stderr=str(exc))
    return CommandResult(
        returncode=int(completed.returncode),
        stdout=completed.stdout or "",
        stderr=completed.stderr or "",
    )


def _hidden_subprocess_kwargs() -> dict[str, Any]:
    if sys.platform != "win32":
        return {}

    kwargs: dict[str, Any] = {}
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    if creationflags:
        kwargs["creationflags"] = creationflags

    startupinfo_factory = getattr(subprocess, "STARTUPINFO", None)
    if startupinfo_factory is not None:
        startupinfo = startupinfo_factory()
        startupinfo.dwFlags |= getattr(subprocess, "STARTF_USESHOWWINDOW", 0)
        startupinfo.wShowWindow = getattr(subprocess, "SW_HIDE", 0)
        kwargs["startupinfo"] = startupinfo

    return kwargs


def _powershell_adapter_command() -> list[str]:
    script = (
        "Get-NetIPConfiguration | "
        "Where-Object { $_.IPv4Address -ne $null } | "
        "ForEach-Object { [PSCustomObject]@{"
        "Name=$_.InterfaceAlias;"
        "InterfaceIndex=$_.InterfaceIndex;"
        "IPAddress=$_.IPv4Address.IPAddress;"
        "PrefixLength=$_.IPv4Address.PrefixLength;"
        "MacAddress=$_.NetAdapter.MacAddress"
        "} } | ConvertTo-Json -Compress"
    )
    return ["powershell", "-NoProfile", "-Command", script]


def _powershell_neighbor_command(interface_index: int) -> list[str]:
    script = (
        "Get-NetNeighbor "
        f"-InterfaceIndex {interface_index} -AddressFamily IPv4 "
        "-ErrorAction SilentlyContinue | "
        "Where-Object { $_.IPAddress -ne $null -and $_.LinkLayerAddress -ne $null } | "
        "Select-Object IPAddress,LinkLayerAddress,State | ConvertTo-Json -Compress"
    )
    return ["powershell", "-NoProfile", "-Command", script]


def _ping_command(ip: str, timeout_ms: int) -> list[str]:
    if sys.platform == "win32" or platform.system().casefold() == "windows":
        return ["ping", "-n", "1", "-w", str(timeout_ms), ip]
    timeout_seconds = max(1, round(timeout_ms / 1000))
    return ["ping", "-c", "1", "-W", str(timeout_seconds), ip]


def _parse_adapter_json(text: str) -> list[NetworkAdapter]:
    text = text.strip()
    if not text:
        return []
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return []
    items = data if isinstance(data, list) else [data]
    adapters: list[NetworkAdapter] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        try:
            adapters.append(
                NetworkAdapter.from_values(
                    name=str(item.get("Name") or item.get("InterfaceAlias") or ""),
                    interface_index=int(item.get("InterfaceIndex") or 0),
                    ip=str(item.get("IPAddress") or item.get("IPv4Address") or ""),
                    prefix_length=int(item.get("PrefixLength") or 24),
                    mac=str(item.get("MacAddress") or ""),
                )
            )
        except Exception:
            log.debug(
                "ignored invalid adapter payload: %r", item, exc_info=True
            )
    return adapters


def _neighbor_mac_map(
    adapter: NetworkAdapter,
    *,
    runner: CommandRunner,
) -> dict[str, str]:
    result = runner(_powershell_neighbor_command(adapter.interface_index), 10)
    neighbors = _parse_neighbor_json(result.stdout) if result.returncode == 0 else {}
    if neighbors:
        return neighbors
    arp_result = runner(["arp", "-a"], 10)
    if arp_result.returncode == 0:
        return _parse_arp_table(arp_result.stdout)
    return {}


def _parse_neighbor_json(text: str) -> dict[str, str]:
    text = text.strip()
    if not text:
        return {}
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return {}
    items = data if isinstance(data, list) else [data]
    values: dict[str, str] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        ip = str(item.get("IPAddress") or "").strip()
        raw_mac = str(item.get("LinkLayerAddress") or "").strip()
        try:
            mac = normalize_mac(raw_mac)
        except Exception:
            continue
        if ip and mac:
            values[ip] = mac
    return values


def _parse_arp_table(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in text.splitlines():
        match = re.search(
            r"(?P<ip>\d{1,3}(?:\.\d{1,3}){3})\s+"
            r"(?P<mac>[0-9A-Fa-f]{2}(?:[:-][0-9A-Fa-f]{2}){5})",
            line,
        )
        if match is None:
            continue
        try:
            mac = normalize_mac(match.group("mac"))
        except Exception:
            continue
        if mac:
            values[match.group("ip")] = mac
    return values


def _parse_ping_latency(text: str) -> int | None:
    patterns = (
        r"time[=<]\s*(?P<ms>\d+)\s*ms",
        r"tempo[=<]\s*(?P<ms>\d+)\s*ms",
        r"durata[=<]\s*(?P<ms>\d+)\s*ms",
    )
    folded = text.casefold()
    for pattern in patterns:
        match = re.search(pattern, folded)
        if match is not None:
            return int(match.group("ms"))
    return None


def _scan_hosts(adapter: NetworkAdapter) -> list[str]:
    network = ipaddress.ip_network(f"{adapter.ip}/{adapter.prefix_length}", strict=False)
    if network.num_addresses > 256:
        network = ipaddress.ip_network(f"{adapter.ip}/24", strict=False)
    return [str(host) for host in network.hosts()]
