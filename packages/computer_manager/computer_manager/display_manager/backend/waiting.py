"""Small wait/poll helpers for Windows display topology changes."""
from __future__ import annotations

import threading
import time
from collections.abc import Callable
from typing import TypeVar

T = TypeVar("T")


def wait_seconds(seconds: float) -> None:
    """Wait without tying callers directly to ``time.sleep``.

    Windows display changes have no reliable Python-level event callback here,
    so callers still need bounded waits. Using ``Event.wait`` keeps the wait
    interrupt-friendly and centralises the timing primitive for tests.
    """
    if seconds <= 0:
        return
    threading.Event().wait(seconds)


def poll_until(
    predicate: Callable[[], T | None],
    *,
    timeout: float,
    interval: float,
    initial_delay: float = 0,
    wait: Callable[[float], None] = wait_seconds,
) -> T | None:
    """Poll a predicate with an explicit timeout and injectable wait primitive."""
    deadline = time.monotonic() + max(timeout, 0)
    if initial_delay > 0:
        wait(initial_delay)
    while True:
        value = predicate()
        if value is not None:
            return value
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return None
        wait(min(interval, remaining))
