"""MQTT and Home Assistant status helpers for :class:`TrayApp`."""
from __future__ import annotations

import queue
from typing import Any

from .. import config, ha_mqtt, ha_rest
from ..core import app_logging


def start_mqtt_bridge(app: Any) -> None:
    try:
        settings = config.get_mqtt_settings()
    except config.ConfigError as exc:
        app_logging.get_logger("tray").warning("invalid MQTT settings: %s", exc)
        return
    if not settings.get("enabled"):
        return
    app._mqtt_bridge = ha_mqtt.HomeAssistantMqttBridge(
        settings,
        app._mqtt_commands.put,
        state_listener=app._mqtt_state_dispatcher.notify,
    )
    if app._mqtt_bridge.start():
        app._mqtt_command_timer.start()
        app._mqtt_refresh_timer.start()


def stop_mqtt_bridge(app: Any) -> None:
    app._mqtt_command_timer.stop()
    app._mqtt_refresh_timer.stop()
    if app._mqtt_bridge is not None:
        app._mqtt_bridge.stop()
        app._mqtt_bridge = None
    while True:
        try:
            app._mqtt_commands.get_nowait()
        except queue.Empty:
            return


def restart_mqtt_bridge(app: Any) -> None:
    stop_mqtt_bridge(app)
    start_mqtt_bridge(app)
    refresh_mqtt_indicator(app)
    refresh_ha_status(app)


def refresh_mqtt_indicator(app: Any) -> None:
    if app._mqtt_bridge is None:
        set_mqtt_indicator(app, "disabled", "MQTT bridge not running")
        return
    host = str(app._mqtt_bridge.settings.get("host") or "broker")
    set_mqtt_indicator(app, "disconnected", f"connecting to {host}...")


def set_mqtt_indicator(app: Any, state: str, detail: str) -> None:
    try:
        indicator = app.panel.mqtt_indicator
    except (AttributeError, RuntimeError):
        return
    try:
        indicator.set_state(state, detail)
    except RuntimeError:
        return


def set_ha_indicator(app: Any, state: str, detail: str) -> None:
    try:
        indicator = app.panel.ha_indicator
    except (AttributeError, RuntimeError):
        return
    try:
        indicator.set_state(state, detail)
    except RuntimeError:
        return


def refresh_ha_status(app: Any) -> None:
    if app._ha_status_refreshing:
        return
    try:
        settings = config.get_mqtt_settings()
    except config.ConfigError as exc:
        app_logging.get_logger("tray").warning("invalid Home Assistant settings: %s", exc)
        set_ha_indicator(app, "disabled", "Home Assistant settings invalid")
        return
    if not settings.get("home_assistant_enabled"):
        set_ha_indicator(app, "disabled", "Home Assistant disabled")
        return
    app._ha_status_refreshing = True

    def run_ping() -> tuple[str, str]:
        return ha_rest.ping()

    def on_success(result: tuple[str, str]) -> None:
        state, detail = result
        set_ha_indicator(app, state, detail)

    def on_failure(message: str) -> None:
        set_ha_indicator(app, "disconnected", message)

    def cleanup() -> None:
        app._ha_status_refreshing = False

    app._run_in_thread(run_ping, on_success, on_failure, cleanup)


def publish_mqtt_snapshot(app: Any) -> None:
    if app._mqtt_bridge is None or app._mqtt_publish_in_progress:
        return
    app._mqtt_publish_in_progress = True
    bridge = app._mqtt_bridge

    def run_publish() -> None:
        bridge.publish_snapshot()

    def on_success(_result: None) -> None:
        return

    def on_failure(message: str) -> None:
        app_logging.get_logger("tray").warning("MQTT snapshot publish failed: %s", message)

    def cleanup() -> None:
        app._mqtt_publish_in_progress = False

    app._run_in_thread(run_publish, on_success, on_failure, cleanup)


def drain_mqtt_commands(app: Any) -> None:
    while True:
        try:
            command = app._mqtt_commands.get_nowait()
        except queue.Empty:
            return
        handle_mqtt_command(app, command)


def handle_mqtt_command(app: Any, command: ha_mqtt.MqttCommand) -> None:
    if command.kind == "profile":
        app.apply_profile(str(command.value))
        return
    if command.kind == "audio_output":
        app.apply_audio_source(command.value)
        return
    if command.kind == "volume":
        source = app._display_service().get_default_audio_source()
        if source is None:
            app.notify("XTray", "No default audio output is available.", error=True)
            return
        app.apply_volume_percent(source, int(command.value))
        return
    if command.kind == "display_volume":
        target, percent = command.value
        app.apply_display_volume_percent(target, int(percent))
        return
    if command.kind == "media_play_pause":
        app.toggle_media_play_pause()
        return
    if command.kind == "mute_toggle":
        app.toggle_muted()
        return
    if command.kind == "mute":
        app.apply_muted(bool(command.value))
        return
    if command.kind == "wake":
        app.notify("XTray", "Wake command received while the PC is already online.")
        publish_mqtt_snapshot(app)
        return
    if command.kind == "shutdown":
        app.shutdown_windows()
