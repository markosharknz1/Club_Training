# Club Training v1.11.0

## A second check-in desk, on another PC

Setup → Club Settings → Security & Privacy gains **Allow other computers on
this network**. Turn it on, set a **check-in PIN** (required — the database
holds kids' details), restart, and any other PC on the club's network can
run the same register through the new
[Club Training Companion](https://github.com/markosharknz1/Club_Training_Companion)
(or a browser). One database, both desks live. Off by default; other
machines must enter the PIN once; ten wrong attempts locks them out.

## Emailed day and month reports

History gains **Email a report**: an end-of-day or whole-month summary —
payments by type with cash/card totals, coaches present, new players, and
any injuries — sent to addresses you choose (remembered for next time),
through your default or chosen email provider.

## Check-in fixes and duty-of-care

- **Fixed: tapping an already checked-in player on the check-in page did
  nothing**, so a wrongly added kid couldn't be removed or edited. Works
  now — Remove deletes the record, payment details and all, and gives a
  voucher session back.
- Closed sessions: the session summary's edit window gains **Remove from
  this session** for mistakes found after the night is closed.
- New **Left injured** tick on a checked-in player (check-in page, register
  and closed-session summary) — shows as a red badge and in the emailed
  reports.
- The session summary's Coaches card now actually lists the coaches who
  were marked present.

## Email setup made clearer

Each provider card (SMTP2GO, Mailgun, Gmail) now spells out exactly what
you need — account, domain or app password — with links to the right pages,
and the default provider is labelled on its card.

## Installing / upgrading

Download the zip, right-click → Properties → **Unblock**, extract, run
`Club Training.cmd`, and point "Install to" at your existing Club Training
folder — your database and backups are kept.
