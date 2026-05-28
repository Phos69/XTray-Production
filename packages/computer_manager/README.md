# Computer Manager

Computer Manager is the desktop window and engine for everything physically
attached to the user's PC: displays, audio, local network adapters, and drives.

It is optional for XTray. XTray reads an exported inventory JSON when Computer
Manager is not installed.

Sub-packages:

- `computer_manager.display_manager`: display profiles, DDC/CI, inventory.
- `computer_manager.audio_manager`: Windows audio device selection, volume,
  media keys.
- `computer_manager.adapter_manager`: network adapter inventory and static IP.
- `computer_manager.drive_manager`: drive inventory and network mapping.

## Requirements

- Windows 10 / 11
- Python 3.10+
- `pywin32` for display topology operations on Windows
- `monitorcontrol` for optional DDC/CI brightness, contrast, and input-source
  operations
- `PySide6` when using the GUI extra

## Data

- Profiles: `%APPDATA%\ComputerManager\profiles\`
- Inventory export consumed by XTray:
  `%APPDATA%\ComputerManager\computer_inventory.json`
- Legacy DisplayManager profiles are read as a fallback only. New saves always
  go to `%APPDATA%\ComputerManager\profiles\`.

## Live Display Stress Tests

The live display stress suite changes the real Windows monitor topology. It is
skipped unless explicitly enabled:

```powershell
$env:XTRAY_LIVE_DISPLAY_TESTS = "1"
.\.venv\Scripts\python.exe -m pytest packages\computer_manager\tests\test_display_live_stress.py -s
```

Optional controls: `XTRAY_LIVE_DISPLAY_SEED`, `XTRAY_LIVE_DISPLAY_ROUNDS`,
`XTRAY_LIVE_DISPLAY_CHURN_BEFORE_PROFILE`, and
`XTRAY_LIVE_DISPLAY_PROFILES=All,Lateral`.
