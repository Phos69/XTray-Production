# XTray Package

`xtray` provides the tray application, Home Assistant MQTT/REST integration,
CLI, autostart support, and shared `xtray.core` utilities used by the manager
packages.

The base package only requires `click`. Install extras for runtime surfaces:

```powershell
pip install -e .\packages\xtray[tray,api]
pip install -e .\packages\xtray[full,dev]
```

- `tray`: PySide6 tray UI and MQTT bridge dependencies.
- `api`: FastAPI/uvicorn REST API dependencies.
- `integrations`: `computer_manager` and `network-manager`.
- `full`: tray, API, and manager integrations.
- `build`: PyInstaller build dependencies for `dist\XTray.exe`; the release
  installer is built with `scripts\build_installer.ps1`.

Without the manager packages, XTray imports successfully and starts with
read-only or empty manager-backed panels. Mutating actions report that the
optional package is not installed.

## Commands

```powershell
xtray-tray
xtray config token
xtray api serve --host 127.0.0.1 --port 8765
```

From the repository root, `.\run-tray.bat` prefers
`.venv\Scripts\xtray-tray.exe` so Windows shows a named GUI process.

## Build

```powershell
.\.venv\Scripts\python.exe -m pip install -e .\packages\xtray[build]
.\.venv\Scripts\pyinstaller.exe .\packaging\XTray.spec --clean --noconfirm
.\scripts\build_installer.ps1
```

## Data

- Settings: `%APPDATA%\XTray\settings.json`
- Logs and diagnostics ZIPs: `%LOCALAPPDATA%\XTray\logs\`
- Downloaded update installers: `%LOCALAPPDATA%\XTray\updates\`
- Tray icon assets: bundled under `xtray/assets`
- MDI icon set: bundled under `xtray/core/assets/mdi`
