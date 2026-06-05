"""The paho-mqtt bridge, command parsing, and broker connection testing."""
from __future__ import annotations

import json
import socket
import ssl
import threading
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from .. import config
from ..core import app_logging
from ..services.display import display_inventory
from ..services.network import devices as network
from .discovery import (
    UNKNOWN,
    _audio_state_label,
    _binary_state,
    _entity_enabled,
    _wake_payload,
    audio_option_map,
    build_discovery_cleanup_messages,
    build_discovery_messages,
)
from .snapshot import MqttSnapshot, collect_snapshot
from .topics import (
    availability_topic,
    display_volume_command_topic,
    display_volume_discovery_topic,
    display_volume_entity_key,
    display_volume_state_topic,
    mqtt_command_topics,
    profile_discovery_topic,
    profile_entity_key,
    state_topics,
)

HOME_ASSISTANT_STATUS_TOPIC = "homeassistant/status"


@dataclass(frozen=True)
class MqttCommand:
    kind: str
    value: Any = None


@dataclass(frozen=True)
class MqttConnectionResult:
    ok: bool
    title: str
    detail: str


def parse_mqtt_command(
    settings: dict[str, Any],
    topic: str,
    payload: bytes | str,
    snapshot: MqttSnapshot,
) -> MqttCommand | None:
    text = _payload_text(payload).strip()
    topics = mqtt_command_topics(settings)
    if topic == topics["profile"]:
        profile_button_enabled = _entity_enabled(settings, profile_entity_key(text), default=True)
        profile_select_enabled = _entity_enabled(settings, "profile_select", default=True)
        if not (profile_button_enabled or profile_select_enabled):
            return None
        if text in snapshot.favorite_profiles:
            return MqttCommand("profile", text)
        return None
    if topic == topics["volume"]:
        if not _entity_enabled(settings, "volume", default=True):
            return None
        try:
            value = float(text)
        except ValueError:
            return None
        if not value.is_integer():
            return None
        percent = int(value)
        if not 0 <= percent <= 100:
            return None
        return MqttCommand("volume", percent)
    for display_state in snapshot.hdmi_volume_displays:
        key = display_inventory.display_volume_entity_key(display_state)
        entity_key = display_volume_entity_key(display_state)
        if topic != display_volume_command_topic(settings, key):
            continue
        if not _entity_enabled(settings, entity_key, default=True):
            return None
        try:
            value = float(text)
        except ValueError:
            return None
        if not value.is_integer():
            return None
        percent = int(value)
        if not 0 <= percent <= 100:
            return None
        return MqttCommand("display_volume", (display_state, percent))
    if topic == topics["audio_output"]:
        if not _entity_enabled(settings, "audio_output", default=True):
            return None
        source = audio_option_map(snapshot.audio_sources).get(text)
        if source is not None:
            return MqttCommand("audio_output", source)
        return None
    if topic == topics["media"]:
        if not _entity_enabled(settings, "play_pause", default=True):
            return None
        if text == "play_pause":
            return MqttCommand("media_play_pause")
        return None
    if topic == topics["mute"]:
        if text == "toggle" and _entity_enabled(settings, "mute_toggle", default=True):
            return MqttCommand("mute_toggle")
        if text == "mute" and _entity_enabled(settings, "mute", default=True):
            return MqttCommand("mute", True)
        if text == "unmute" and _entity_enabled(settings, "unmute", default=True):
            return MqttCommand("mute", False)
        return None
    if topic == topics["shutdown"] and text == "shutdown":
        if not _entity_enabled(settings, "shutdown", default=bool(settings.get("allow_shutdown"))):
            return None
        return MqttCommand("shutdown")
    if topic == topics["power"]:
        if not _entity_enabled(settings, "power", default=bool(settings.get("allow_shutdown"))):
            return None
        if text == "shutdown":
            return MqttCommand("shutdown")
        if text.startswith("wake"):
            return MqttCommand("wake", _wake_payload_mac(text) or snapshot.local_mac)
        return None
    return None


class HomeAssistantMqttBridge:
    """Small paho-mqtt wrapper that never touches Qt directly."""

    def __init__(
        self,
        settings: dict[str, Any],
        command_handler: Callable[[MqttCommand], None],
        *,
        client_factory: Callable[[], Any] | None = None,
        snapshot_factory: Callable[[], MqttSnapshot] = collect_snapshot,
        state_listener: Callable[[str, str], None] | None = None,
    ) -> None:
        self.settings = {**config.default_mqtt_settings(), **settings}
        self._command_handler = command_handler
        self._client_factory = client_factory
        self._snapshot_factory = snapshot_factory
        self._state_listener = state_listener
        self._client: Any | None = None
        self._last_snapshot: MqttSnapshot | None = None
        self._published_profile_names: set[str] = set()
        self._published_display_volume_keys: set[str] = set()
        self._stop_requested = False
        self._logger = app_logging.get_logger("ha_mqtt")

    def start(self) -> bool:
        if not self.settings.get("enabled"):
            return False
        if not self.settings.get("host"):
            self._logger.warning("MQTT is enabled but no host is configured")
            return False
        try:
            client = self._client_factory() if self._client_factory else self._create_paho_client()
        except ImportError:
            self._logger.error("paho-mqtt is not installed; install with: pip install -e .[tray]")
            return False
        except Exception as exc:
            self._logger.exception("could not create MQTT client: %s", exc)
            return False

        self._client = client
        self._stop_requested = False
        client.on_connect = self._on_connect
        client.on_message = self._on_message
        client.on_disconnect = self._on_disconnect

        username = self.settings.get("username")
        if username:
            client.username_pw_set(username, self.settings.get("password"))
        if self.settings.get("tls"):
            client.tls_set()
        client.will_set(availability_topic(self.settings), payload="offline", qos=0, retain=True)
        if hasattr(client, "reconnect_delay_set"):
            client.reconnect_delay_set(min_delay=2, max_delay=60)
        try:
            client.connect_async(
                self.settings["host"],
                int(self.settings.get("port", 1883)),
                keepalive=60,
            )
            client.loop_start()
            self._logger.info(
                "started MQTT client for %s:%s; waiting for broker connection",
                self.settings["host"],
                int(self.settings.get("port", 1883)),
            )
        except Exception as exc:
            self._logger.exception("could not start MQTT client: %s", exc)
            self._client = None
            return False
        return True

    def stop(self) -> None:
        client = self._client
        if client is None:
            return
        try:
            self._stop_requested = True
            self._publish(availability_topic(self.settings), "offline", retain=True)
            client.loop_stop()
            client.disconnect()
        except Exception:
            self._logger.exception("failed to stop MQTT client cleanly")
        finally:
            self._client = None

    def publish_snapshot(self) -> None:
        if self._client is None:
            return
        try:
            snapshot = self._snapshot_factory()
            self._last_snapshot = snapshot
            self._publish_discovery(snapshot)
            self._publish_state(snapshot)
        except Exception:
            self._logger.exception("failed to publish MQTT snapshot")

    def _create_paho_client(self) -> Any:
        return _create_paho_client(self.settings)

    def _on_connect(self, client: Any, _userdata: Any, *_args: Any) -> None:
        ok, reason = _connect_result_text(_args)
        if not ok:
            self._logger.error("MQTT broker refused connection: %s", reason)
            self._notify_state("disconnected", reason)
            return
        self._logger.info("connected to MQTT broker %s", self.settings.get("host"))
        for topic in mqtt_command_topics(self.settings).values():
            client.subscribe(topic)
        client.subscribe(HOME_ASSISTANT_STATUS_TOPIC)
        self._notify_state(
            "connected",
            f"{self.settings.get('host')}:{int(self.settings.get('port', 1883))}",
        )
        self.publish_snapshot()

    def _on_disconnect(self, _client: Any, _userdata: Any, *_args: Any) -> None:
        reason = _disconnect_reason_text(_args)
        if self._stop_requested:
            self._logger.info("disconnected from MQTT broker (%s)", reason)
            self._notify_state("disconnected", reason)
            return
        self._logger.warning(
            "disconnected from MQTT broker; reconnect will be retried (%s)",
            reason,
        )
        self._notify_state("disconnected", reason)

    def _notify_state(self, state: str, detail: str) -> None:
        if self._state_listener is None:
            return
        try:
            self._state_listener(state, detail)
        except Exception:
            self._logger.exception("MQTT state listener raised")

    def _on_message(self, _client: Any, _userdata: Any, message: Any) -> None:
        topic = str(getattr(message, "topic", ""))
        payload = getattr(message, "payload", b"")
        if topic == HOME_ASSISTANT_STATUS_TOPIC and _payload_text(payload).strip() == "online":
            self.publish_snapshot()
            return
        snapshot = self._last_snapshot
        if snapshot is None:
            snapshot = self._snapshot_factory()
            self._last_snapshot = snapshot
        command = parse_mqtt_command(self.settings, topic, payload, snapshot)
        if command is None:
            self._logger.warning("ignored unsupported MQTT command on %s", topic)
            return
        self._command_handler(command)

    def _publish_discovery(self, snapshot: MqttSnapshot) -> None:
        current_profiles = set(snapshot.favorite_profiles)
        for stale_name in sorted(self._published_profile_names - current_profiles):
            self._publish(profile_discovery_topic(self.settings, stale_name), "", retain=True)
        self._published_profile_names = current_profiles
        current_display_volume_keys = {
            display_inventory.display_volume_entity_key(display_state)
            for display_state in snapshot.hdmi_volume_displays
        }
        for stale_key in sorted(self._published_display_volume_keys - current_display_volume_keys):
            self._publish(display_volume_discovery_topic(self.settings, stale_key), "", retain=True)
        self._published_display_volume_keys = current_display_volume_keys
        for message in build_discovery_cleanup_messages(self.settings, snapshot):
            self._publish(message.topic, message.payload, retain=message.retain)
        for message in build_discovery_messages(self.settings, snapshot):
            self._publish(message.topic, message.payload, retain=message.retain)

    def _publish_state(self, snapshot: MqttSnapshot) -> None:
        topics = state_topics(self.settings)
        option_map = audio_option_map(snapshot.audio_sources)
        audio_state = _audio_state_label(snapshot.default_audio_source, option_map) or "Unavailable"
        volume_state = (
            str(snapshot.volume_percent) if snapshot.volume_percent is not None else UNKNOWN
        )
        muted_state = _binary_state(snapshot.muted)
        self._publish(availability_topic(self.settings), "online", retain=True)
        self._publish(topics["online"], "ON", retain=True)
        self._publish(topics["current_profile"], snapshot.current_profile or UNKNOWN, retain=True)
        self._publish(topics["volume"], volume_state, retain=True)
        self._publish(topics["audio_output"], audio_state, retain=True)
        self._publish(topics["muted"], muted_state, retain=True)
        for display_state in snapshot.hdmi_volume_displays:
            key = display_inventory.display_volume_entity_key(display_state)
            value = snapshot.hdmi_volume_percents.get(key)
            state = str(value) if value is not None else UNKNOWN
            self._publish(display_volume_state_topic(self.settings, key), state, retain=True)
        self._publish(
            topics["power_attributes"],
            {
                "mac": snapshot.local_mac or UNKNOWN,
                "wake_payload": _wake_payload(snapshot.local_mac),
            },
            retain=True,
        )

    def _publish(self, topic: str, payload: dict[str, Any] | str, *, retain: bool) -> None:
        client = self._client
        if client is None:
            return
        if isinstance(payload, dict):
            body = json.dumps(payload, separators=(",", ":"), sort_keys=True)
        else:
            body = payload
        client.publish(topic, body, qos=0, retain=retain)


def _disconnect_reason_text(args: tuple[Any, ...]) -> str:
    for candidate in args:
        if candidate is None:
            continue
        class_name = type(candidate).__name__.casefold()
        if "flags" in class_name or "properties" in class_name:
            continue
        reason_code = getattr(candidate, "value", candidate)
        if reason_code in (0, "0"):
            return "rc=0"
        return str(candidate)
    return "reason=unknown"


def test_mqtt_connection(
    settings: dict[str, Any],
    *,
    timeout: float = 5.0,
    client_factory: Callable[[], Any] | None = None,
) -> MqttConnectionResult:
    try:
        normalized = config.normalize_mqtt_settings(
            {**config.default_mqtt_settings(), **settings},
            require_host=True,
        )
        client = client_factory() if client_factory else _create_paho_client(normalized)
    except config.ConfigError as exc:
        return MqttConnectionResult(False, "Connection settings incomplete", str(exc))
    except ImportError:
        return MqttConnectionResult(
            False,
            "MQTT library missing",
            "paho-mqtt is not installed. Install the tray extra with: pip install -e .[tray]",
        )
    except Exception as exc:
        return MqttConnectionResult(False, "Connection setup failed", str(exc))

    event = threading.Event()
    outcome: dict[str, MqttConnectionResult] = {}

    def on_connect(_client: Any, _userdata: Any, *_args: Any) -> None:
        ok, reason = _connect_result_text(_args)
        if ok:
            outcome["result"] = MqttConnectionResult(
                True,
                "Connected",
                f"Connected to {normalized['host']}:{normalized['port']}.",
            )
        else:
            outcome["result"] = MqttConnectionResult(
                False,
                "Broker refused connection",
                reason,
            )
        event.set()

    def on_disconnect(_client: Any, _userdata: Any, *_args: Any) -> None:
        if "result" not in outcome:
            outcome["result"] = MqttConnectionResult(
                False,
                "Disconnected before connect",
                _disconnect_reason_text(_args),
            )
            event.set()

    client.on_connect = on_connect
    client.on_disconnect = on_disconnect

    try:
        username = normalized.get("username")
        if username:
            client.username_pw_set(username, normalized.get("password"))
        if normalized.get("tls"):
            client.tls_set()
        client.connect(normalized["host"], int(normalized["port"]), keepalive=30)
        client.loop_start()
        if not event.wait(timeout):
            outcome["result"] = MqttConnectionResult(
                False,
                "Connection timed out",
                (
                    f"No MQTT response from {normalized['host']}:{normalized['port']} "
                    f"within {timeout:g}s."
                ),
            )
    except socket.gaierror as exc:
        outcome["result"] = MqttConnectionResult(
            False,
            "Broker host not found",
            f"DNS lookup failed for {normalized['host']}: {exc}",
        )
    except TimeoutError as exc:
        outcome["result"] = MqttConnectionResult(False, "Connection timed out", str(exc))
    except ssl.SSLError as exc:
        outcome["result"] = MqttConnectionResult(False, "TLS error", str(exc))
    except OSError as exc:
        outcome["result"] = MqttConnectionResult(False, "Socket error", str(exc))
    except Exception as exc:
        outcome["result"] = MqttConnectionResult(False, "Connection failed", str(exc))
    finally:
        try:
            client.loop_stop()
        except Exception:
            pass
        try:
            client.disconnect()
        except Exception:
            pass

    return outcome.get(
        "result",
        MqttConnectionResult(False, "Connection failed", "No result was reported."),
    )


def _create_paho_client(settings: dict[str, Any]) -> Any:
    from paho.mqtt import client as mqtt  # type: ignore[import-not-found]

    kwargs: dict[str, Any] = {"client_id": settings.get("client_id") or ""}
    if hasattr(mqtt, "CallbackAPIVersion"):
        kwargs["callback_api_version"] = mqtt.CallbackAPIVersion.VERSION2
    return mqtt.Client(**kwargs)


def _connect_result_text(args: tuple[Any, ...]) -> tuple[bool, str]:
    for candidate in args:
        if candidate is None:
            continue
        class_name = type(candidate).__name__.casefold()
        if isinstance(candidate, dict) or "flags" in class_name or "properties" in class_name:
            continue
        reason_code = getattr(candidate, "value", candidate)
        if reason_code in (0, "0"):
            return True, "rc=0"
        return False, _connect_reason_text(candidate)
    return True, "rc=0"


def _connect_reason_text(reason: Any) -> str:
    value = getattr(reason, "value", reason)
    legacy = {
        1: "unacceptable protocol version",
        2: "client identifier rejected",
        3: "server unavailable",
        4: "bad username or password",
        5: "not authorized",
    }
    if value in legacy:
        return f"{legacy[value]} (rc={value})"
    return str(reason)


def _payload_text(payload: bytes | str) -> str:
    if isinstance(payload, bytes):
        return payload.decode("utf-8", errors="replace")
    return str(payload)


def _wake_payload_mac(payload: str) -> str | None:
    if not payload.startswith("wake:"):
        return None
    raw = payload.split(":", 1)[1].strip()
    try:
        return network.normalize_mac(raw)
    except Exception:
        return raw or None
