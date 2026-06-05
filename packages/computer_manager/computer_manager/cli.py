"""Click-based CLI for DisplayManager."""
from __future__ import annotations

import json
import os
import sys
from typing import Any

import click
from xtray.core import app_logging

from computer_manager.display_manager import profiles

from . import __version__, config


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
@click.version_option(__version__, prog_name="displaymanager")
def main() -> None:
    """Manage Windows display profiles."""
    app_logging.configure_logging(component="computer_manager_cli")


@main.command("list")
def cmd_list() -> None:
    """List currently connected displays."""
    from computer_manager.display_manager import backend as display

    try:
        for d in display.list_displays():
            _echo_json(d.to_dict())
    except RuntimeError as exc:
        click.echo(str(exc), err=True)
        sys.exit(2)


@main.command("current")
def cmd_current() -> None:
    """Print the current display state as JSON."""
    from computer_manager.display_manager import backend as display

    try:
        _echo_json(display.get_state().to_dict())
    except RuntimeError as exc:
        click.echo(str(exc), err=True)
        sys.exit(2)


@main.command("inventory")
def cmd_inventory() -> None:
    """Print all available active/inactive displays with monitor metadata."""
    from computer_manager.display_manager import backend as display

    try:
        _echo_json({"displays": [item.to_dict() for item in display.list_available_displays()]})
    except RuntimeError as exc:
        click.echo(str(exc), err=True)
        sys.exit(2)


@main.command("audio")
def cmd_audio() -> None:
    """Print current and available Windows playback endpoints."""
    from computer_manager import audio_manager as audio

    default = audio.get_default_audio_source()
    volume_percent = None
    muted = None
    if default is not None:
        try:
            volume_percent = audio.get_output_volume_percent(default)
        except Exception:
            app_logging.get_logger("cli").exception("failed to read default audio volume")
        try:
            muted = audio.get_output_muted(default)
        except Exception:
            app_logging.get_logger("cli").exception("failed to read default audio mute state")
    _echo_json(
        {
            "default": default.to_dict() if default else None,
            "volume_percent": volume_percent,
            "muted": muted,
            "sources": [source.to_dict() for source in audio.list_audio_sources()],
        }
    )


@main.command("profiles")
def cmd_profiles() -> None:
    """List saved profiles."""
    names = profiles.list_profiles()
    if not names:
        click.echo("(no profiles saved)")
        return
    for n in names:
        click.echo(n)


@main.command("save")
@click.option("--force", "-f", is_flag=True, help="Overwrite an existing profile with the same name.")
@click.argument("name")
def cmd_save(name: str, force: bool) -> None:
    """Capture the current display configuration into a named profile."""
    try:
        path = profiles.capture(name, overwrite=force)
    except profiles.ProfileAlreadyExists:
        click.echo(
            f"profile already exists: {name} (use --force to overwrite)",
            err=True,
        )
        sys.exit(1)
    except (RuntimeError, profiles.InvalidProfile) as exc:
        click.echo(str(exc), err=True)
        sys.exit(2)
    click.echo(f"saved {path}")


@main.command("apply")
@click.option("--dry-run", is_flag=True, help="Validate the profile without applying it.")
@click.argument("name")
def cmd_apply(name: str, dry_run: bool) -> None:
    """Apply a saved profile by name."""
    try:
        result = profiles.apply(name, dry_run=dry_run)
    except profiles.ProfileNotFound:
        click.echo(f"profile not found: {name}", err=True)
        sys.exit(1)
    except (RuntimeError, profiles.InvalidProfile) as exc:
        click.echo(str(exc), err=True)
        sys.exit(2)
    _print_apply_result(name, result)
    if not result.ok:
        sys.exit(2)


@main.command("plan")
@click.argument("name")
def cmd_plan(name: str) -> None:
    """Print the Windows display apply plan without changing displays."""
    from computer_manager.display_manager import backend as display

    try:
        profile = profiles.load_profile(name)
        win32api, win32con = display._win32()
        requested = display._normalized_requested_display_copies(profile.displays)
        result = display.ApplyResult()
        plan = display._build_display_apply_plan(
            win32api,
            win32con,
            requested,
            result,
        )
    except profiles.ProfileNotFound:
        click.echo(f"profile not found: {name}", err=True)
        sys.exit(1)
    except (RuntimeError, profiles.InvalidProfile) as exc:
        click.echo(str(exc), err=True)
        sys.exit(2)
    _echo_json(
        {
            "profile": name,
            "current": [item.to_dict() for item in plan.current],
            "known": [item.to_dict() for item in plan.known],
            "requested": [item.to_dict() for item in plan.requested],
            "planned": [
                {
                    "current": item.current.to_dict(),
                    "target": item.target.to_dict(),
                }
                for item in plan.planned
            ],
            "requires_desktop_extend": display._requires_desktop_extend(plan.planned),
            "warnings": [item.to_dict() for item in result.warnings],
            "errors": result.errors,
        }
    )
    if result.errors:
        sys.exit(2)


@main.command("validate")
@click.argument("name")
def cmd_validate(name: str) -> None:
    """Validate a saved profile without touching displays."""
    try:
        issues = profiles.validate(name)
    except profiles.ProfileNotFound:
        click.echo(f"profile not found: {name}", err=True)
        sys.exit(1)
    except profiles.InvalidProfile as exc:
        click.echo(str(exc), err=True)
        sys.exit(2)
    if not issues:
        click.echo(f"{name}: valid")
        return
    click.echo(f"{name}: valid with warnings")
    for issue in issues:
        click.echo(f"- {issue}")


@main.command("delete")
@click.argument("name")
def cmd_delete(name: str) -> None:
    """Delete a saved profile."""
    try:
        profiles.delete(name)
    except profiles.ProfileNotFound:
        click.echo(f"profile not found: {name}", err=True)
        sys.exit(1)
    click.echo(f"deleted {name}")


@main.group("config")
def cmd_config() -> None:
    """Manage local Computer Manager settings (shared with XTray)."""


@cmd_config.command("token")
@click.option("--set", "set_value", help="Set an explicit API token.")
@click.option("--generate", is_flag=True, help="Generate and store a new API token.")
def cmd_config_token(set_value: str | None, generate: bool) -> None:
    """Show or create the API bearer token used by Home Assistant."""
    if set_value and generate:
        raise click.UsageError("use either --set or --generate")
    try:
        if set_value:
            token = config.set_api_token(set_value)
        else:
            token = config.ensure_api_token(force=generate)
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
@click.option("--base-topic", help="MQTT base topic.")
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
        settings = (
            config.set_mqtt_settings(**updates)
            if updates
            else config.get_mqtt_settings()
        )
    except config.ConfigError as exc:
        click.echo(str(exc), err=True)
        sys.exit(2)
    _echo_json(config.redact_mqtt_settings(settings))


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
    from xtray import config as xtray_config

    try:
        xtray_config.assert_safe_api_bind(host, unsafe_no_auth=unsafe_no_auth)
    except xtray_config.ConfigError as exc:
        click.echo(str(exc), err=True)
        sys.exit(2)
    if unsafe_no_auth:
        os.environ[xtray_config.ENV_UNSAFE_NO_AUTH] = "1"
    try:
        import uvicorn
    except ImportError:
        click.echo("uvicorn is not installed. Install XTray with: pip install -e .[api]", err=True)
        sys.exit(2)
    uvicorn.run("xtray.api:app", host=host, port=port, reload=reload)


def _echo_json(data: dict) -> None:
    click.echo(json.dumps(data, indent=2, sort_keys=True))


def _print_apply_result(name: str, result: Any) -> None:
    data = result.to_dict()
    if data["dry_run"]:
        click.echo(f"validated {name} (dry run)")
    elif data["applied"] and not data["ok"]:
        click.echo(f"partially applied {name}")
    elif data["applied"]:
        click.echo(f"applied {name}")
    else:
        click.echo(f"did not apply {name}")
    for warning in data["warnings"]:
        display_id = f" [{warning['display_id']}]" if warning.get("display_id") else ""
        detail = f": {warning['detail']}" if warning.get("detail") else ""
        click.echo(f"warning{display_id}: {warning['message']}{detail}", err=True)
    for error in data["errors"]:
        click.echo(f"error: {error}", err=True)


if __name__ == "__main__":
    main()
