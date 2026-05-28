# MDI icon assets

Complete SVG distribution of Material Design Icons from `@mdi/svg@7.4.47`.

This folder contains 7447 24x24 SVG files. The files are
vendored from the official Pictogrammers package and normalized so SVG paths use
`fill="currentColor"`, allowing the tray and editor UIs to tint icons for the
active theme.

The file name without `.svg` is the icon identifier and is saved in profile /
device JSON as `"mdi:<name>"`.

Source: https://www.npmjs.com/package/@mdi/svg
License: Apache-2.0, copied in `LICENSE`.

To refresh these assets, run:

```powershell
python scripts/sync_mdi_icons.py
```
