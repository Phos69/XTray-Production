# Changelog

## 0.1.1b4 - 2026-06-05

- Migrated the obsolete saved `media.audio_output` icon from
  `mdi:audio-input-rca` to the current `mdi:volume-high` default so older local
  settings do not keep showing the legacy audio input icon.

## 0.1.1b3 - 2026-06-05

- Fixed C#/WPF audio icons so volume, mute, PC audio, and display audio controls
  render from bundled SVGs even on a fresh install with an empty icon cache.
- Restored display output mute controls for Home Assistant media-player volume
  targets and routed HA display volume changes through the backend.
- Replaced the quick update prompt with a release picker dialog that can show or
  hide public beta releases, download the selected installer with progress, and
  hand off installation with progress status.

## 0.1.1b2 - 2026-06-05

- Rebuilt the tray shell in C#/WPF while restoring the legacy Python/Qt layout,
  skins, popup chrome, and iconography.
- Added C# tray crash logging and stabilized frameless resize handling.
- Fixed startup/autostart paths so Windows launches the C# tray instead of the
  legacy Python tray.
- Cached static tray icons and restored the legacy tray glyph for hide buttons.

## 0.1.1b1 - 2026-06-03

- Added release gates for lint, pytest, compileall, dependency checks, wheel
  audit, and PyInstaller build verification.
- Declared Windows display dependencies for Computer Manager packaging.
- Added root/package license files and packaging tests for bundled assets.
- Documented legacy migration policy and deprecated `network_manager.client`.
- Added root pytest configuration for the monorepo test suite.
- Added production source export, Device-only Network Manager default, private
  experimental feature gating, and Inno Setup installer packaging.
- Added an optional installer checkbox to start XTray with Windows.
- Added GitHub Releases update checks and silent installer handoff for
  installed XTray builds.
