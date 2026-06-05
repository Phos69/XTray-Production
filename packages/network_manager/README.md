# Network Manager

Network Manager is the saved-device window used by XTray. The public build is
focused on the **Device** view: named IPv4 devices, optional MAC/URL/icon
metadata, ping/open actions, local network scan, and the device list consumed by
the XTray popup.

The private development tree can also contain experimental router tooling
behind `experimental_features.network_manager_full`. Those modules are excluded
from the production source export and from the official installer.

## Requirements

- Windows 10 / 11
- Python 3.10+
- PySide6 for the GUI

## Installation

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e .[gui]
```

After install:

```powershell
network-manager
network-manager-devices
python -m network_manager
```

All three commands open the Device-focused UI in production builds.

## Data

Saved devices are stored under:

```text
%APPDATA%\Network_Manager\network_devices.json
```

Legacy DisplayManager device files are imported once when the new file does not
exist.

## License

[MIT](LICENSE).
