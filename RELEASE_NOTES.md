# Club Training v1.9.0

## No more `.exe` — no more Windows warnings

The app is no longer packaged as an executable. The zip now contains the
app as **readable Python source** plus the **official python.org runtime**
(signed by the Python Software Foundation) — the only program Windows ever
runs is that signed runtime, so there is **no SmartScreen "Windows protected
your PC" screen and nothing for antivirus engines to false-flag**. The app's
window is Microsoft Edge in app mode (already on every Windows PC); it looks
and works exactly as before.

## Installing

1. Download the zip, right-click it → Properties → tick **Unblock** → OK.
2. Extract anywhere and double-click **`Club Training.cmd`**.
3. The setup window asks where to install (default `C:\Apps\Club_Training`,
   never Documents/OneDrive) and offers a desktop shortcut, then starts the
   app.

## Upgrading from v1.8.0 or earlier

Run the new `Club Training.cmd` and point **Install to** at your existing
Club Training folder — your database and backups are kept, the app files are
refreshed, and the old `Club_Training.exe` is cleaned up. **Tick the desktop
shortcut box** so your shortcut points at the new app (the old one pointed at
the removed exe).

## Also in this release

- Opening the app while it's already running now just brings up a window on
  the running copy instead of starting a second one.
- The release build now verifies every binary in the zip is
  Authenticode-signed before publishing.
