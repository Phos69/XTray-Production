"""Production-safe switch model labels used by the Device tab.

This module contains only stable identifiers and display labels. Router client
implementations live under the private experimental switch manager modules.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SwitchModel:
    key: str
    label: str


SWITCH_MODELS: dict[str, SwitchModel] = {
    "huawei_dn8245x6": SwitchModel("huawei_dn8245x6", "Huawei DN8245X6"),
    "netgear_ex6120": SwitchModel("netgear_ex6120", "Netgear EX6120"),
    "technicolor_agmy2020": SwitchModel("technicolor_agmy2020", "Technicolor AGMY2020"),
    "tplink_tl_wa850re": SwitchModel("tplink_tl_wa850re", "TP-Link TL-WA850RE"),
}


def switch_model_label(key: str, *, default: str = "Unsupported") -> str:
    model = SWITCH_MODELS.get(str(key or "").casefold())
    return model.label if model is not None else default
