# Club Training v1.10.0

## Fix how a player paid — even after the session is closed

Every player row on a session's summary page now has an edit (✎) button, so
an admin can change how that player paid (for instance Cash recorded, but it
was actually a Sports Voucher) — including on **closed** sessions, where
these mistakes usually come to light. Voucher balances follow the change
automatically: switching to Sports Voucher uses a session on the player's
oldest voucher with sessions left, switching away gives it back. Totals and
breakdowns recompute on save.

## See voucher balances before you pick Sports Voucher

In the check-in and change-payment windows, the Sports Voucher button now
shows the player's remaining sessions at a glance — e.g. **"Sports Voucher
(3 left)"** — and selecting it spells out which voucher will be used, or
warns in red when the player has none left. Fewer mistakes at the desk.

## Also in this release

- Fixed the register page's Check in / edit buttons, which could fail to
  open the check-in window for some players.
- The Sports Voucher / Visitor / Other buttons now show their colour
  properly when selected.
- Settings → About now shows the version, release date, project home,
  and a contact email.

## Installing / upgrading

Download the zip, right-click → Properties → **Unblock**, extract, run
`Club Training.cmd`, and point "Install to" at your existing Club Training
folder — your database and backups are kept.
