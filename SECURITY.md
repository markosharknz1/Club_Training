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

## What's actually in the zip

- **The app as readable Python source** (`app.py` and friends, plus its
  open-source libraries in `lib\`) — nothing is compiled or obfuscated, so
  anyone can inspect exactly what runs.
- **The official Python runtime** from python.org in `python\` — every
  `.exe`/`.dll` in the zip is Authenticode-signed by the Python Software
  Foundation, and the release build verifies this and fails if anything
  unsigned slips in. We ship no executable of our own at all.
- **One small script**, `Club Training.cmd`, whose only job is to start the
  signed `pythonw.exe` with the app.
- The app's window is Microsoft Edge (already on your PC, signed by
  Microsoft) in app mode — no embedded browser is bundled.

Because there is no unsigned program to run, Windows SmartScreen has nothing
to warn about, and the PyInstaller-style antivirus false positives that
affect many packaged Python apps don't apply. If Windows' stricter **Smart
App Control** is enabled on your machine, right-click the downloaded zip →
Properties → **Unblock** before extracting (the install step already says
this).

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
