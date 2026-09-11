# Is Club Training safe?

Club Training runs sports clubs' attendance, payments and Sports Voucher records —
including children's names and guardian contact details — so it is built to keep
that data on the club's own computer.

## What the app does with your data

- **Everything stays local.** All club data lives in a single file,
  `badminton.db`, in the app's folder on your machine. There is no cloud
  service, no account, no sign-up, and the app works entirely offline.
- **No telemetry.** The app sends no usage data, analytics, or crash reports to
  anyone — including the developer.
- **The web server is local-only.** The app runs a small internal web server
  bound to `127.0.0.1` — it is not reachable from your network or the internet.
- **The only network traffic is what you configure.** If (and only if) you set
  up email sending, the app talks to the provider you chose — SMTP2GO, Mailgun
  or Gmail — to deliver the emails you write. If you set up Square Terminal
  payments, it talks to Square. Both are off by default.
- **Backups are yours.** A daily copy of the database is written to a `backups`
  folder next to the app and to `Documents\Club_Training Backups` (so a
  OneDrive-backed Documents folder gives you an off-machine copy under your
  own account).

## Verifying a download

Every release on the
[Releases page](https://github.com/markosharknz1/Club_Training/releases)
includes:

- a **SHA-256 checksum** — after downloading, run
  `Get-FileHash Club_Training_vX.Y.Z.zip` in PowerShell and compare;
- a **VirusTotal link** — the exact published file scanned by 70+ antivirus
  engines. You can also upload your own downloaded copy to
  [virustotal.com](https://www.virustotal.com) and compare the hash;
- a **build-provenance link** — releases are built by GitHub Actions directly
  from the tagged source code (see `.github/workflows/release.yml`), so the
  download provably matches the code in this repository, with the build log
  linked from every release.

**About antivirus false positives:** the app is packaged with PyInstaller
(which bundles the Python runtime into `Club_Training.exe`). A small number of
lesser-known antivirus engines heuristically flag *all* PyInstaller apps.
What matters is that the major engines (Microsoft, Kaspersky, Bitdefender,
ESET, etc.) report it clean — check the VirusTotal link on any release.

**About the Windows SmartScreen warning:** the first time you run the app,
Windows may show "Windows protected your PC" because the app is not
code-signed (signing certificates cost money clubs don't need to spend).
Click *More info → Run anyway*. The checksum and VirusTotal steps above are
how you satisfy yourself before doing so.

## Recommendations for club machines

- Turn on **BitLocker / Device Encryption** (Windows Settings → Privacy &
  security → Device encryption) so a lost or stolen machine doesn't expose
  club data.
- Keep the app folder **out of synced folders** (OneDrive/Dropbox) — live
  database files can be corrupted by sync. The daily backups are the supported
  way to get cloud copies.

## Reporting a problem

If you find a security issue, contact the maintainer via GitHub
(@markosharknz1) rather than posting details publicly.
