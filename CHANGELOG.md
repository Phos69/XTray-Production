# Changelog

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
