# What's new

**First run is now a proper setup.** Double-clicking `Club_Training.exe` for the first time opens a small setup window instead of dropping you wherever the zip was extracted:

- Choose **where to install** (default `C:\Apps\Club_Training`, with Browse). Setup refuses the Documents folder and anything OneDrive syncs — sync services corrupt the app's live database. (Your daily *backups* still go to Documents automatically.)
- Optional **desktop shortcut**.
- Setup copies the app to the chosen folder and starts it from there. Running the downloaded copy again later just opens your installed app.

**Upgrades got easier too:** installing over an existing Club Training folder refreshes the app and **keeps that club's database and backups untouched** — no more copying `badminton.db` by hand.

## Install / update

1. Download `Club_Training_v1.8.0.zip` below and unzip anywhere. No Python or internet needed.
2. Double-click `Club_Training.exe` and follow the setup window. **Updating?** Point "Install to" at your existing Club Training folder — your data is kept.
