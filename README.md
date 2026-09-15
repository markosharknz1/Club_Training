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
2. Right-click the downloaded zip → **Properties** → tick **Unblock** → OK.
   (This clears Windows' "downloaded from the internet" mark so nothing is
   blocked; entirely safe to skip if you don't see the tickbox.)
3. Extract the zip anywhere and double-click **`Club Training.cmd`**.
4. A small setup window asks where to install (default `C:\Apps\Club_Training`)
   and offers a desktop shortcut — then the app starts. A fresh database is
   created on first start.
5. Set your club's name, icon and options under **Setup → Club Settings**.

**Upgrading?** Run the new version's `Club Training.cmd` and point "Install
to" at your existing Club Training folder — your database and backups are
kept, only the app files are refreshed.

There is no `.exe` of ours to run: the app is plain Python source, started by
the official python.org runtime bundled in the zip (signed by the Python
Software Foundation). That's why there's no SmartScreen warning — and you can
read every line of what you're running.

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
pip install -r requirements.txt
run.bat        # or: python app.py
```

Python 3.12 recommended. The release zip is assembled by
`scripts/build_dist.py` (app source + pure-Python dependencies + the official
python.org embeddable runtime — no PyInstaller, no compiled code of ours).

## Safety & verification

Each release ships with a SHA-256 checksum and a VirusTotal scan link —
see [SECURITY.md](SECURITY.md) for how to check them and what the app does
(and doesn't do) with your data.
