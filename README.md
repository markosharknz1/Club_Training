# Club Training

A fully local desktop app for running a sports club's training days: player
check-in, payments, Sports Voucher tracking, coach attendance and pay, new-player
tracking, reports, and bulk email — built for volunteer-run clubs, originally a
badminton club in South Australia.

**All data stays on your computer.** One database file, no cloud, no accounts,
works offline. See [SECURITY.md](SECURITY.md) for the full safety story and how
to verify a download.

## Install (2 minutes)

1. Download the latest `Club_Training_vX.Y.Z.zip` from the
   [Releases page](https://github.com/markosharknz1/Club_Training/releases).
2. Unzip it anywhere (e.g. `C:\Club Training`). No Python, no installer, no
   internet needed.
3. Double-click `Club_Training.exe`. A fresh database is created on first run.
4. Set your club's name, icon and options under **Setup → Club Settings**.

**Moving to a new machine?** Copy `badminton.db` (and the `backups` folder)
from the old app folder into the new one — that file is all your club data.

## What it does

- **Check-in desk** — fast player-first check-in per session, payment types
  (cash/card/voucher/free), walk-ins, sibling awareness, new-player flagging
- **Sports Vouchers** — register, track balances session by session, edit
  usage dates, import balances from spreadsheets, per-child PDF statements
- **Coaches** — off / simple (who coached) / advanced (pay rates with
  snapshots, month-end payment reports, mark-as-paid, CSV extracts)
- **Players** — database with membership details, imports from CSV/Excel,
  merge/cleanup tools, per-player attendance history
- **Email** — announcements to recent players via SMTP2GO, Mailgun or Gmail,
  with a rich-text editor, attachments, and per-recipient selection
- **Reports** — attendance trends, new players, Excel exports
- Everything configurable per club: player fields, groups, voucher rules,
  payment types, branding icon

## Running from source

```
install.bat    # installs pinned dependencies (offline wheels included)
run.bat        # launches the app windowless
```

Python 3.12 recommended. The standalone exe is built with `build_exe.bat`
(PyInstaller).

## Safety & verification

Each release ships with a SHA-256 checksum and a VirusTotal scan link —
see [SECURITY.md](SECURITY.md) for how to check them and what the app does
(and doesn't do) with your data.
