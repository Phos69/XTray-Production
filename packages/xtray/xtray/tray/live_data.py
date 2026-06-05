"""In-memory live data hub for tray widget state.

The hub owns the cache/refresh lifecycle; callers provide the concrete
loaders and renderers so this module stays free of Qt imports and service
dependencies.
"""
from __future__ import annotations

import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, replace
from enum import Enum
from typing import Any


class LiveDataKey(str, Enum):
    PROFILES = "profiles"
    ACTIVE_PROFILE = "active_profile"
    AUDIO = "audio"
    DISPLAYS = "displays"
    NETWORK = "network"
    ADAPTERS = "adapters"
    DRIVES = "drives"


@dataclass(frozen=True)
class LiveSnapshot:
    value: Any = None
    error: str | None = None
    loaded: bool = False
    refreshing: bool = False
    updated_at: float | None = None
    version: int = 0


@dataclass(frozen=True)
class LiveDataSource:
    key: LiveDataKey
    load: Callable[[], Any]
    apply_value: Callable[[Any], None]
    apply_error: Callable[[str, LiveSnapshot], None]
    show_loading: Callable[[], None] = lambda: None


RunInThread = Callable[
    [Callable[[], Any], Callable[[Any], None], Callable[[str], None], Callable[[], None]],
    None,
]
StateChanged = Callable[[LiveDataKey, LiveSnapshot], None]


class TrayLiveDataHub:
    """Caches tray live data and serializes refreshes per source key."""

    def __init__(
        self,
        run_in_thread: RunInThread,
        *,
        clock: Callable[[], float] = time.monotonic,
        on_state_changed: StateChanged | None = None,
    ) -> None:
        self._run_in_thread = run_in_thread
        self._clock = clock
        self._on_state_changed = on_state_changed
        self._sources: dict[LiveDataKey, LiveDataSource] = {}
        self._snapshots: dict[LiveDataKey, LiveSnapshot] = {}
        # Identity of the last snapshot we rendered for each key. Frozen
        # LiveSnapshot instances are replaced (never mutated) so an `is`
        # match means "nothing has changed since we last drew this" — lets
        # apply_cached skip the expensive widget rebuild on a panel reopen.
        self._last_applied_snapshot: dict[LiveDataKey, LiveSnapshot] = {}

    def register(self, source: LiveDataSource) -> None:
        key = LiveDataKey(source.key)
        self._sources[key] = replace(source, key=key)
        self._snapshots.setdefault(key, LiveSnapshot())

    def snapshot(self, key: LiveDataKey | str) -> LiveSnapshot:
        live_key = LiveDataKey(key)
        return self._snapshots.get(live_key, LiveSnapshot())

    def snapshots(self) -> dict[LiveDataKey, LiveSnapshot]:
        return dict(self._snapshots)

    def is_refreshing(self, key: LiveDataKey | str) -> bool:
        return self.snapshot(key).refreshing

    def prime_all(self) -> None:
        self.refresh_many(self._sources, reason="initial")

    def apply_cached(self, keys: Iterable[LiveDataKey | str]) -> int:
        applied = 0
        for raw_key in keys:
            key = LiveDataKey(raw_key)
            source = self._sources.get(key)
            if source is None:
                continue
            snapshot = self.snapshot(key)
            if not (snapshot.loaded or snapshot.error):
                continue
            if self._last_applied_snapshot.get(key) is snapshot:
                continue
            if snapshot.loaded:
                source.apply_value(snapshot.value)
            else:
                source.apply_error(snapshot.error, snapshot)
            self._last_applied_snapshot[key] = snapshot
            applied += 1
        return applied

    def refresh_many(
        self,
        keys: Iterable[LiveDataKey | str],
        *,
        reason: str = "",
        show_loading: bool | None = None,
    ) -> dict[LiveDataKey, bool]:
        return {
            LiveDataKey(key): self.refresh(
                key,
                reason=reason,
                show_loading=show_loading,
            )
            for key in keys
        }

    def patch_snapshot(
        self,
        key: LiveDataKey | str,
        mutate: Callable[[Any], Any],
    ) -> bool:
        """Update the cached value via a mutator and re-render that key.

        Skipped when no value has been loaded yet (an external event has no
        baseline to patch) and when a refresh is already in flight (the
        upcoming result will publish the authoritative state). Returns True
        when the cache was patched.
        """
        live_key = LiveDataKey(key)
        source = self._sources.get(live_key)
        if source is None:
            return False
        current = self.snapshot(live_key)
        if not current.loaded or current.refreshing:
            return False
        new_value = mutate(current.value)
        updated = replace(
            current,
            value=new_value,
            updated_at=self._clock(),
        )
        self._set_snapshot(live_key, updated)
        source.apply_value(new_value)
        self._last_applied_snapshot[live_key] = updated
        return True

    def refresh(
        self,
        key: LiveDataKey | str,
        *,
        reason: str = "",
        show_loading: bool | None = None,
    ) -> bool:
        del reason  # reserved for future logging/telemetry without API churn
        live_key = LiveDataKey(key)
        source = self._sources[live_key]
        current = self.snapshot(live_key)
        if current.refreshing:
            return False

        should_show_loading = not current.loaded if show_loading is None else show_loading
        if should_show_loading:
            source.show_loading()

        token = current.version + 1
        self._set_snapshot(
            live_key,
            replace(current, refreshing=True, version=token),
        )

        def on_success(value: Any) -> None:
            active = self.snapshot(live_key)
            if active.version != token:
                return
            updated = LiveSnapshot(
                value=value,
                error=None,
                loaded=True,
                refreshing=False,
                updated_at=self._clock(),
                version=token,
            )
            self._set_snapshot(live_key, updated)
            source.apply_value(value)
            self._last_applied_snapshot[live_key] = updated

        def on_failure(message: str) -> None:
            active = self.snapshot(live_key)
            if active.version != token:
                return
            updated = replace(
                active,
                error=message,
                refreshing=False,
                updated_at=self._clock(),
            )
            self._set_snapshot(live_key, updated)
            source.apply_error(message, updated)
            self._last_applied_snapshot[live_key] = updated

        self._run_in_thread(source.load, on_success, on_failure, lambda: None)
        return True

    def _set_snapshot(self, key: LiveDataKey, snapshot: LiveSnapshot) -> None:
        self._snapshots[key] = snapshot
        if self._on_state_changed is not None:
            self._on_state_changed(key, snapshot)
