# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files


REPO_ROOT = Path(SPECPATH).resolve().parent
PACKAGE_PATHS = [
    str(REPO_ROOT / "packages" / "xtray"),
    str(REPO_ROOT / "packages" / "computer_manager"),
    str(REPO_ROOT / "packages" / "network_manager"),
    str(REPO_ROOT / "packages" / "xtray_sync"),
]
datas = (
    collect_data_files("xtray", includes=["assets/*.svg"])
    + collect_data_files(
        "xtray.core",
        includes=["assets/mdi/*.svg", "assets/mdi/LICENSE", "assets/mdi/README.md"],
    )
)
hiddenimports = [
    # xtray
    "xtray.api",
    "xtray.cli",
    "xtray.ha_mqtt",
    "xtray.ha_mqtt.bridge",
    "xtray.ha_mqtt.discovery",
    "xtray.ha_mqtt.snapshot",
    "xtray.ha_mqtt.topics",
    "xtray.ha_rest",
    "xtray.autostart",
    "xtray.updater",
    "xtray.tray",
    "xtray.tray.app",
    "xtray.services",
    "xtray.services.hotkeys",
    "xtray.core",
    "xtray.core.app_identity",
    "xtray.core.app_logging",
    "xtray.core.icons",
    "xtray.core.qt_assets",
    "xtray.core.qt_helpers",
    "xtray.core.theme",
    "xtray.core.computer_models",
    "xtray.core.config_base",
    # computer_manager (optional but bundled in the desktop installer)
    "computer_manager",
    "computer_manager.app",
    "computer_manager.cli",
    "computer_manager.config",
    "computer_manager.paths",
    "computer_manager.export",
    "computer_manager.adapter_manager",
    "computer_manager.adapter_manager.service",
    "computer_manager.drive_manager",
    "computer_manager.drive_manager.service",
    "computer_manager.audio_manager",
    "computer_manager.audio_manager.core",
    "computer_manager.display_manager",
    "computer_manager.display_manager.backend",
    "computer_manager.display_manager.backend.ddcci",
    "computer_manager.display_manager.backend.hdr",
    "computer_manager.display_manager.backend.models",
    "computer_manager.display_manager.backend.waiting",
    "computer_manager.display_manager.inventory",
    "computer_manager.display_manager.geometry",
    "computer_manager.display_manager.profiles",
    "computer_manager.display_manager.messages",
    "computer_manager.display_manager.service",
    "computer_manager.display_manager.ui_model",
    "computer_manager.display_manager.ui_panels",
    # network_manager
    "network_manager",
    "network_manager.app_config",
    "network_manager.app",
    "network_manager.gui_entry",
    "network_manager.mac",
    "network_manager.storage_utils",
    "network_manager.device_manager",
    "network_manager.device_manager._async_runner",
    "network_manager.device_manager._dhcp_status",
    "network_manager.device_manager.actions",
    "network_manager.device_manager.manager",
    "network_manager.device_manager.models",
    "network_manager.device_manager.scanner",
    "network_manager.device_manager.storage",
    "network_manager.device_manager.switch_models",
    # xtray_sync
    "xtray_sync",
    "xtray_sync.bundle",
    "xtray_sync.client",
    "xtray_sync.config",
    "xtray_sync.crypto",
    "xtray_sync.discovery",
    "xtray_sync.server",
    "xtray_sync.service",
    # 3rd-party + Windows
    "cryptography",
    "keyring",
    "paho.mqtt.client",
    "win32api",
    "win32con",
    "win32gui",
]

a = Analysis(
    ["xtray_launcher.py"],
    pathex=PACKAGE_PATHS,
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="XTray",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    icon="XTray.ico",
    version="XTray.version",
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
