"""Shared validation for Home Assistant entity/service identifiers."""
from __future__ import annotations

import re

#: A Home Assistant service/action id, e.g. ``script.tv_on`` or ``light.turn_off``.
#: Both the config layer and the REST client validate ids against this pattern.
HA_SERVICE_RE = re.compile(r"^[a-z0-9_]+\.[a-z0-9_]+$")


def is_ha_service_id(value: str) -> bool:
    """True when ``value`` is a syntactically valid ``domain.service`` id."""
    return bool(HA_SERVICE_RE.match(value))
