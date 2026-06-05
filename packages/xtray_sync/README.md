# XTray Sync

`xtray_sync` provides LAN discovery, encrypted bundle export/import, and
diagnostic-oriented helpers for XTray.

Runtime data is coordinated through the shared XTray settings store. The LAN
sync password is stored in the OS keyring/Credential Manager and never in
`settings.json`.
