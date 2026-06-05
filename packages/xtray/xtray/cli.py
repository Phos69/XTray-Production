"""Click-based CLI for XTray."""
from __future__ import annotations

import json
import os
import sys
from collections import deque
from pathlib import Path
from typing import Any

import click

from . import __version__, config
from .core import app_logging


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
@click.version_option(__version__, prog_name="xtray")
def main() -> None:
    """Manage XTray tray, Home Assistant, and web services."""
    app_logging.configure_logging(component="cli")


@main.command("tray")
def cmd_tray() -> None:
    """Start the Windows tray app."""
    from .tray import main as tray_main

    tray_main([])


@main.group("config")
def cmd_config() -> None:
    """Manage local XTray settings."""


@cmd_config.command("token")
@click.option("--set", "set_value", help="Set an explicit API token.")
@click.option("--generate", is_flag=True, help="Generate and store a new API token.")
def cmd_config_token(set_value: str | None, generate: bool) -> None:
    """Show or create the API bearer token used by Home Assistant."""
    if set_value and generate:
        raise click.UsageError("use either --set or --generate")
    try:
        token = config.set_api_token(set_value) if set_value else config.ensure_api_token(force=generate)
    except config.ConfigError as exc:
        click.echo(str(exc), err=True)
        sys.exit(2)
    click.echo(token)


@cmd_config.command("mqtt")
@click.option("--enable/--disable", "enabled", default=None, help="Enable or disable MQTT.")
@click.option("--host", help="MQTT broker host or IP address.")
@click.option("--port", type=int, help="MQTT broker port.")
@click.option("--username", help="MQTT username.")
@click.option("--password", help="MQTT password.")
@click.option("--tls/--no-tls", "tls", default=None, help="Enable or disable MQTT TLS.")
@click.option("--client-id", help="MQTT client ID.")
@click.option("--base-topic", help="XTray MQTT base topic.")
@click.option("--discovery-prefix", help="Home Assistant MQTT discovery prefix.")
@click.option(
    "--allow-shutdown/--deny-shutdown",
    "allow_shutdown",
    default=None,
    help="Allow Home Assistant to power off Windows via the MQTT shutdown button.",
)
def cmd_config_mqtt(
    enabled: bool | None,
    host: str | None,
    port: int | None,
    username: str | None,
    password: str | None,
    tls: bool | None,
    client_id: str | None,
    base_topic: str | None,
    discovery_prefix: str | None,
    allow_shutdown: bool | None,
) -> None:
    """Show or update Home Assistant MQTT settings used by the tray."""
    updates: dict[str, Any] = {}
    if enabled is not None:
        updates["enabled"] = enabled
    if host is not None:
        updates["host"] = host
    if port is not None:
        updates["port"] = port
    if username is not None:
        updates["username"] = username or None
    if password is not None:
        updates["password"] = password or None
    if tls is not None:
        updates["tls"] = tls
    if client_id is not None:
        updates["client_id"] = client_id
    if base_topic is not None:
        updates["base_topic"] = base_topic
    if discovery_prefix is not None:
        updates["discovery_prefix"] = discovery_prefix
    if allow_shutdown is not None:
        updates["allow_shutdown"] = allow_shutdown

    try:
        settings = config.set_mqtt_settings(**updates) if updates else config.get_mqtt_settings()
    except config.ConfigError as exc:
        click.echo(str(exc), err=True)
        sys.exit(2)
    click.echo(json.dumps(config.redact_mqtt_settings(settings), indent=2, sort_keys=True))


@cmd_config.command("theme")
@click.argument("name", required=False)
def cmd_config_theme(name: str | None) -> None:
    """Show or update the GUI/tray theme."""
    try:
        value = config.set_theme_name(name) if name is not None else config.get_theme_name()
    except config.ConfigError as exc:
        click.echo(str(exc), err=True)
        sys.exit(2)
    click.echo(value)


@cmd_config.command("experimental")
@click.option(
    "--network-manager-full/--no-network-manager-full",
    "network_manager_full",
    default=None,
    help="Enable or disable the full Network Manager experimental UI.",
)
def cmd_config_experimental(network_manager_full: bool | None) -> None:
    """Show or update local experimental feature flags."""
    updates: dict[str, Any] = {}
    if network_manager_full is not None:
        updates["network_manager_full"] = network_manager_full
    try:
        features = (
            config.set_experimental_features(**updates)
            if updates
            else config.get_experimental_features()
        )
    except config.ConfigError as exc:
        click.echo(str(exc), err=True)
        sys.exit(2)
    click.echo(json.dumps(features, indent=2, sort_keys=True))


@main.group("api")
def cmd_api() -> None:
    """Run the REST API."""


@cmd_api.command("serve")
@click.option("--host", default="127.0.0.1", show_default=True)
@click.option("--port", default=8765, show_default=True, type=int)
@click.option("--reload", is_flag=True, help="Enable uvicorn reload for development.")
@click.option(
    "--unsafe-no-auth",
    is_flag=True,
    help="Allow mutating API calls without a token. Never use on an untrusted network.",
)
def cmd_api_serve(host: str, port: int, reload: bool, unsafe_no_auth: bool) -> None:
    """Serve the FastAPI app with safe bind checks."""
    try:
        config.assert_safe_api_bind(host, unsafe_no_auth=unsafe_no_auth)
    except config.ConfigError as exc:
        click.echo(str(exc), err=True)
        sys.exit(2)
    if unsafe_no_auth:
        os.environ[config.ENV_UNSAFE_NO_AUTH] = "1"
    try:
        import uvicorn
    except ImportError:
        click.echo("uvicorn is not installed. Install with: pip install -e .[api]", err=True)
        sys.exit(2)
    uvicorn.run("xtray.api:app", host=host, port=port, reload=reload)


@main.group("diagnostics")
def cmd_diagnostics() -> None:
    """Read redacted logs and create diagnostics bundles."""


@cmd_diagnostics.command("tail")
@click.option("--lines", "-n", default=120, show_default=True, type=int)
def cmd_diagnostics_tail(lines: int) -> None:
    """Print the last lines of the redacted XTray log."""
    log_path = app_logging.log_dir() / "xtray.log"
    if not log_path.exists():
        click.echo(f"log file not found: {log_path}", err=True)
        sys.exit(1)
    tail: deque[str] = deque(maxlen=max(1, int(lines)))
    try:
        with log_path.open("r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                tail.append(app_logging.redact(line.rstrip("\n")))
    except OSError as exc:
        click.echo(f"could not read log file: {exc}", err=True)
        sys.exit(1)
    for line in tail:
        click.echo(line)


@cmd_diagnostics.command("bundle")
@click.option(
    "--output-dir",
    type=click.Path(file_okay=False, dir_okay=True, path_type=Path),
    help="Directory where the diagnostics ZIP should be written.",
)
def cmd_diagnostics_bundle(output_dir: Path | None) -> None:
    """Create a diagnostics ZIP with logs and redacted runtime metadata."""
    path = app_logging.create_diagnostics_bundle(component="cli", output_dir=output_dir)
    click.echo(path)


@main.group("sync")
def cmd_sync() -> None:
    """Configure LAN sync and import from discovered XTray peers."""


@cmd_sync.command("configure")
@click.option("--enable/--disable", "enabled", default=None, help="Enable or disable LAN sync.")
@click.option("--peer-name", help="Friendly name announced to other XTray PCs.")
@click.option("--port", type=int, help="HTTP port used by the LAN sync peer.")
@click.option("--discovery-port", type=int, help="UDP broadcast port used for discovery.")
@click.option("--password", help="Sync password to store in the OS credential manager.")
def cmd_sync_configure(
    enabled: bool | None,
    peer_name: str | None,
    port: int | None,
    discovery_port: int | None,
    password: str | None,
) -> None:
    """Show or update LAN sync settings."""
    try:
        from xtray_sync import config as sync_config
    except ImportError as exc:
        click.echo(f"xtray-sync is not installed: {exc}", err=True)
        sys.exit(2)
    try:
        settings = sync_config.set_sync_settings(
            enabled=enabled,
            peer_name=peer_name,
            port=port,
            discovery_port=discovery_port,
            password=password,
        )
    except config.ConfigError as exc:
        click.echo(str(exc), err=True)
        sys.exit(2)
    payload = settings.to_dict()
    payload["password_configured"] = sync_config.password_available()
    click.echo(json.dumps(payload, indent=2, sort_keys=True))


@cmd_sync.command("status")
def cmd_sync_status() -> None:
    """Print LAN sync configuration status."""
    try:
        from xtray_sync import config as sync_config
    except ImportError as exc:
        click.echo(f"xtray-sync is not installed: {exc}", err=True)
        sys.exit(2)
    click.echo(json.dumps(sync_config.status_summary(), indent=2, sort_keys=True))


@cmd_sync.command("peers")
@click.option("--timeout", default=2.0, show_default=True, type=float)
def cmd_sync_peers(timeout: float) -> None:
    """Discover XTray sync peers on the LAN."""
    try:
        from xtray_sync.discovery import discover_peers
    except ImportError as exc:
        click.echo(f"xtray-sync is not installed: {exc}", err=True)
        sys.exit(2)
    peers = [peer.to_dict() for peer in discover_peers(timeout=timeout)]
    click.echo(json.dumps({"peers": peers}, indent=2, sort_keys=True))


@cmd_sync.command("import")
@click.argument("target", required=False)
@click.option("--password", help="Sync password. Defaults to the saved sync password.")
@click.option("--timeout", default=15.0, show_default=True, type=float)
@click.option("--skip-network-settings", is_flag=True)
@click.option("--skip-network-devices", is_flag=True)
@click.option("--skip-network-passwords", is_flag=True)
@click.option("--skip-display-profiles", is_flag=True)
def cmd_sync_import(
    target: str | None,
    password: str | None,
    timeout: float,
    skip_network_settings: bool,
    skip_network_devices: bool,
    skip_network_passwords: bool,
    skip_display_profiles: bool,
) -> None:
    """Import network data and display profiles from a LAN peer."""
    try:
        from xtray_sync import config as sync_config
        from xtray_sync.bundle import ImportOptions
        from xtray_sync.client import import_from_peer, peer_from_discovery_target
        from xtray_sync.discovery import discover_peers
    except ImportError as exc:
        click.echo(f"xtray-sync is not installed: {exc}", err=True)
        sys.exit(2)
    peers = discover_peers(timeout=2.0)
    try:
        peer = peer_from_discovery_target(target, peers)
    except Exception as exc:
        click.echo(str(exc), err=True)
        sys.exit(2)
    secret = password or sync_config.get_password()
    if not secret:
        secret = click.prompt("Sync password", hide_input=True)
    options = ImportOptions(
        network_settings=not skip_network_settings,
        network_devices=not skip_network_devices,
        network_passwords=not skip_network_passwords,
        display_profiles=not skip_display_profiles,
    )
    try:
        result = import_from_peer(peer, secret, options=options, timeout=timeout)
    except Exception as exc:
        click.echo(f"sync import failed: {exc}", err=True)
        sys.exit(1)
    click.echo(json.dumps(result.to_dict(), indent=2, sort_keys=True))
    if not result.ok:
        sys.exit(1)


if __name__ == "__main__":
    main()
