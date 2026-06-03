"""Windows local network adapter inventory + static IP service."""
from .service import (
    AdapterIpSettings,
    AdapterService,
    AdapterServiceError,
    NetworkAdapter,
)

__all__ = [
    "AdapterIpSettings",
    "AdapterService",
    "AdapterServiceError",
    "NetworkAdapter",
]
