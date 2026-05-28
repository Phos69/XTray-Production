"""Click-based CLI for XTray."""
from __future__ import annotations

import json
import os
import sys
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


if __name__ == "__main__":
    main()
