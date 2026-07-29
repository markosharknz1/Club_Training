# Club_Training App — Project Context

A fully local Flask web app for a junior badminton club to run day-to-day check-in, attendance,
payments, coaches, and Sports Voucher tracking. Built for the user (club admin) to run on their
own machine and demo to other club members (e.g. "Carol").

## Where things live

- **App root:** `C:\Club_Training\` (renamed from `C:\BadmintonClub` — was itself moved out of
  OneDrive early on, since SQLite + OneDrive sync can corrupt the database file, so it must
  **never** live in a cloud-synced folder).
- **GitHub:** private repo at https://github.com/markosharknz1/Club_Training (renamed from
  `BadmintonClub` via `gh repo rename`; `git remote origin` was updated automatically, branch
  `master`). Push only when the user explicitly asks ("push to github please").
- **Run it:** `run.bat` (runs `python app.py`). The Flask server still runs internally on
  `127.0.0.1` (no LAN/firewall exposure), but it's launched in a background thread and displayed
  in a **native desktop window via `pywebview`** — no browser tab, no URL bar, no need for
  Chrome/Edge/Firefox to be installed separately. It looks and feels like a real desktop app.
  If `pywebview` isn't installed (e.g. `install.bat` wasn't run), it falls back to opening the
  default browser instead, with a console message explaining why. On Windows, `pywebview` uses
  the Edge WebView2 runtime, which ships with Windows 10/11 by default — nothing extra to install
  there in practice.
- **Install deps:** `install.bat` → `pip install -r requirements.txt`
  (flask, flask-sqlalchemy, openpyxl, reportlab, requests, pywebview).
- **Database:** `badminton.db` (SQLite). **Never commit this** — `.gitignore` excludes `*.db*`.
  It contains real kids' personal data (names, guardians, Medicare numbers).

## Stack & conventions

- Flask + Flask-SQLAlchemy, server-rendered Jinja2 templates, Bootstrap 5.3 + vanilla JS (no
  frontend build step, no npm). AJAX via `fetch()` for interactive bits (check-in modal, edit
  modals, voucher creation).
- `config.py` resolves `DB_PATH` relative to the script/exe location.
- **Migrations are hand-rolled**: `create_app()` in `app.py` calls `db.create_all()` (creates
  missing *tables* only) then runs manual `PRAGMA table_info` + `ALTER TABLE ... ADD COLUMN`
  checks for columns added after the DB already existed (currently: `attendance.voucher_id`,
  `players.medicare_number`). **When adding a new column to an existing table, add a migration
  block here too** — `create_all()` alone won't add it to existing databases.
- Settings are a generic key/value store (`Setting` model, `Setting.get(key, default)` /
  `Setting.set(key, value)`), not dedicated columns. The `/settings` route dispatches by a hidden
  `section` form field (`general` / `testing_mode` / `square`) so each settings card can submit
  independently without clobbering the others.

## Data model (`models.py`)

- `SessionTemplate` — a recurring session definition (name, day of week, times, cash/card price).
  `SessionDate` — one specific date's occurrence of a template. `active_group_ids` (JSON) records
  which `Group`s ran that day; `day_active_groups` property decodes it (falls back to all groups
  if null).
- `Player` — name, DOB (or approximate, derived from an "age" entered at quick-add), guardian
  name/phone/email, `medicare_number` (optional), default session/group, siblings (self-referential
  m2m via `sibling_links`).
- `Attendance` — one row per player per `SessionDate` (unique constraint), `payment_type`
  (`Cash`/`Card`/`Sports Voucher`/`Visitor`/`Other`), `amount`, optional `voucher_id` FK.
- `Voucher` — a Sports Voucher registered against a player: `amount` (default $100),
  `sessions_total` (default 10), `date_issued`, `notes`. `sessions_used` / `sessions_remaining`
  are computed properties from linked `Attendance.voucher_id` rows.
- `Coach` — linked to `SessionDate` via `session_date_coaches` m2m (a coach can work multiple
  sessions on the same day).

## Feature map (chronological, roughly)

1. **Day-first workflow**: home redirects to today's `/day/<date>`. `before_request` auto-closes
   any still-`open` `SessionDate`s from a previous day on every GET.
2. **Plan Day** (`/day/<date>/plan`) → tick which sessions run + which groups are active (groups
   default **unchecked** — explicit opt-in per group per day). Posts to `/day/<date>/setup`, then
   always redirects to the check-in desk regardless of how many sessions were opened.
3. **Check-in desk** (`/day/<date>/checkin`, `templates/day/checkin.html`) — the main day-to-day
   screen. Two tables:
   - **Player Database** (top) — players not yet checked in today, sorted recent-attendees-first
     (attended in last 90 days) then alphabetical, then everyone else alphabetical. Shows Last
     Session / Last Group columns (most recent past attendance, for reference only).
   - **Checked In** (bottom) — players checked in today, showing session/group (no payment shown
     in the table itself, per explicit request).
   - **Double-click** a row anywhere → opens the check-in modal (session, group, payment type,
     amount — amount is **read-only**, auto-computed from the session's price settings, not
     editable by staff).
   - **Right-click** a row → opens the edit-player modal (name, DOB/age, guardian details,
     Medicare number, notes) via `/api/player/<id>` GET/POST.
   - **+ Add Player** button prefills from whatever's typed in the search box.
   - Session badges at top are clickable → link to `/register/<sd_id>`.
4. **Coaches per day**: `day/view.html` has a "Coaches Present" matrix (coaches × that day's
   sessions, checkboxes), posts to `/day/<date>/coaches`. Reuses the existing per-`SessionDate`
   `coaches` relationship — no schema change was needed.
5. **Sports Vouchers** (`/vouchers`, `templates/vouchers.html`):
   - Vouchers are **explicitly registered per child**, not an assumed yearly pool — a family might
     split their two annual vouchers across different activities (badminton + another sport), so
     each voucher used at this club must be created here first.
   - Limits (enforced in `_voucher_limit_error()` in `app.py`): **max 2 active at once** (has
     `sessions_remaining > 0`) and **max 2 issued per calendar year** (Jan–Dec, confirmed —
     not financial year). Unused vouchers **carry over** indefinitely — there's no expiry logic,
     so a 2025 voucher with sessions left is still usable in 2026+ (this already worked without
     extra code since nothing ever expires vouchers by date).
   - In the check-in modal, selecting **Sports Voucher** payment type shows a voucher picker
     (auto-selects the one with sessions left), a warning when 1–2 sessions remain, and an
     auto-prompt to create a new voucher if the existing one(s) are exhausted — this does **not**
     block check-in, it offers a one-click path to keep going.
   - Backend fallback: if a payment is marked "Sports Voucher" from a page with no voucher picker
     (e.g. `register/run.html`'s older bulk check-in), the server auto-picks the oldest voucher
     with sessions remaining rather than hard-failing.
   - **Per-voucher PDF export** (`/vouchers/<id>/pdf`, uses `reportlab`): child's name, Medicare
     number, voucher issue date/amount/sessions, and a table of every date it was used. Kept as an
     optional extra, not required for the core "just record it" ask.
6. **Player Database page** (`/players`, distinct from the check-in page's top table of the same
   name): list with search/filters, **Last Played** column, CSV import (`/players/import` —
   flexible header matching, `name` required, `age`/`guardian_name`/`guardian_phone`/
   `guardian_email` optional, headers match with underscores or spaces, case-insensitive).
   Player detail page (`/players/<id>`) has stat tiles (last 3 months / last calendar year /
   total) plus a dedicated last-3-months table above the full attendance history.
7. **Sessions setup** (`/sessions`): each session card now shows **Total kids checked in** and
   **Total collected** (all-time, via `SessionTemplate.total_checkins` / `.total_collected`
   properties) — for gauging the revenue impact of a future price change.
8. **Testing Mode**: Settings toggle (off by default). Gates the "Reset Day" button (deletes all
   sessions/attendance for a day, for repeatable local testing) so it doesn't show up during real
   club use.
9. **Square Terminal payments**: Settings → Payments (Square) has an **"Enable Square Terminal
   payments" toggle, off by default** — this is deliberate, explicit opt-in, not automatic just
   because credentials are saved (the user corrected this explicitly: "make the payment via Square
   optional, not hard coded"). Plus environment (sandbox/production), access token (write-only
   field, blank on save = keep existing, never redisplayed in plaintext), Location ID, Device ID.
   When enabled *and* configured, the check-in modal's Card payment type shows a **"💳 Charge on
   Terminal"** button → creates a Square Terminal Checkout via REST calls (`requests` library, no
   official Square SDK), polls `GET /v2/terminals/checkouts/{id}` every 2s, auto-confirms the
   check-in on `COMPLETED`, shows a clear message on `CANCELED`/error. Cancelling the modal cancels
   any pending terminal checkout. This has been verified against Square's real sandbox API (correct
   request shape, correct error parsing) but **not tested with real credentials/hardware** — the
   user will need their own Square Developer Dashboard access token + a paired Terminal device ID.
10. **Junior/Senior player categories & configurable fields**: `Player.category` ('Junior'/'Senior',
    default 'Junior') plus new optional fields `address`, `own_email`, `own_phone` (the player's
    own contact — distinct from the existing `guardian_email`/`guardian_phone`, which stay as
    "Parent Contact"). Settings → **Player Categories & Fields** lets the club independently
    configure, *per category*, an age bracket (`{cat}_age_min`/`{cat}_age_max`) and five toggles
    (`{cat}_track_age`/`address`/`email`/`phone`/`parent_contact`) — e.g. Juniors default to
    tracking age + parent contact only (no own phone/email/address, since a kid doesn't have
    their own), Seniors default to tracking their own address/email/phone and not parent contact.
    `_player_field_settings()` in `app.py` returns the resolved config; `applyFieldVisibility(prefix,
    category)` (duplicated in `players/list.html`, `players/edit.html`, `day/checkin.html`) shows/
    hides the corresponding form sections client-side when the Category select changes. Wired into:
    Add Player modal, Edit Player page, the check-in page's right-click edit modal, the player
    detail page display, and CSV import (`category`/`address`/`own_email`/`own_phone` are now
    optional import columns). **`SessionTemplate.category`** ('Junior'/'Senior'/'Mixed', default
    'Mixed') is a **label only** — shown as a badge on the session card in Sessions setup, does
    **not** restrict which players can check into a session (confirmed with the user — enforcement
    was explicitly not wanted "for now").
11. **Desktop-window conversion**: the user asked to make the app "not reliant on web/web apps."
    Given the choice between (a) wrapping the existing Flask app in a native window via
    `pywebview` — keeps every feature, days not weeks, near-zero regression risk — versus
    (b) a full native GUI rewrite (Tkinter/PySide, every screen rebuilt from scratch, genuinely
    weeks of work) — the user explicitly chose **(a)**. Do not start a native-toolkit rewrite
    without the user asking again specifically for that; the `pywebview` wrapper is the agreed
    solution. Entry point is in `app.py`'s `if __name__ == '__main__':` block: Flask runs on
    `127.0.0.1` in a background thread, `pywebview` opens a native window pointed at it, with a
    browser-open fallback if `pywebview` isn't installed. Verified working (WebView2-backed window
    successfully loaded the app, confirmed via server logs during testing).
12. **Vendor-change hardening** (the user called this "vital"): two upstream dependencies were
    identified as breakage risks and fixed —
    - **CDN dependencies removed.** Bootstrap CSS/JS and Chart.js were previously loaded from
      `cdn.jsdelivr.net` on every page load — meaning the *entire UI* would break with no internet,
      or if jsdelivr had an outage, or if that exact CDN version was ever pulled. They're now
      vendored locally at `static/vendor/bootstrap/` and `static/vendor/chartjs/` (exact same
      pinned versions: Bootstrap 5.3.3, Chart.js 4.4.2) and served via Flask's own `/static` route
      (`{{ url_for('static', filename=...) }}` in `base.html`/`reports.html`). The app is now
      genuinely offline-capable — no external network call happens on any page load. **If you ever
      need to upgrade Bootstrap or Chart.js, re-download the new version's file into the same
      `static/vendor/...` path and update the version number in this note** — don't reintroduce a
      CDN `<script>`/`<link>` tag.
    - **Python package versions pinned exactly** in `requirements.txt` (`flask==3.1.3`,
      `flask-sqlalchemy==3.1.1`, `sqlalchemy==2.0.36`, `openpyxl==3.1.5`, `reportlab==4.5.1`,
      `requests==2.32.3`, `pywebview==6.2.1`) instead of bare unpinned names. Previously, running
      `install.bat` on a different machine or at a later date would silently pull whatever the
      *latest* version of each package happened to be at that time — a future breaking major
      release (e.g. a new SQLAlchemy or Flask major version) could have broken the app with no
      warning. Now every install gets the exact versions this app was actually built and tested
      against. **When intentionally upgrading a dependency, update the pin here and re-test the
      whole app**, don't just bump it casually.
    - Square's Terminal API calls already pin `'Square-Version': '2024-06-04'` in the request
      headers (see `_square_headers()`), so Square can't silently change API behaviour under us
      either — this predates this hardening pass but is the same category of protection.

## Known open items (not yet built — need user input before building)

- **"Enter date" for voucher usage** — the user flagged wanting some way to manually
  record/backdate voucher usage outside the live check-in flow. Not yet scoped or built.
- **Vouchers used for membership** — the user said "need to look more at that" (i.e. vouchers
  might in future pay for annual membership, not just per-session fees). Explicitly deferred,
  do not build speculatively.
- Nothing else is mid-flight; the last few sessions ended with everything committed and pushed.

## Working-style notes specific to this project

- **Verify with live functional tests, not just syntax checks** — every change in this project has
  been validated by spinning up `create_app()` in a `flask.testing` test client and hitting the
  actual routes (and cleaning up any test data written to the real `badminton.db` afterwards).
  Keep doing this; a template that merely parses doesn't mean the feature works.
- **Don't restructure UI the user didn't ask for.** Early on, an unrequested full page restructure
  (splitting one page into multiple sections) drew a sharp correction: implement exactly what's
  asked, roll back extra changes if asked, and don't take "make X clickable" as license to also
  reorganize the page.
- Payment amounts are **whole dollars only** (no cents) throughout — `step="1"`, `| round | int`
  in templates, `Math.round()` in JS.
- When a request is genuinely ambiguous with materially different implementation paths (e.g. the
  Square integration method — in-browser card form vs. physical terminal vs. hosted checkout
  link), ask via targeted multiple-choice questions rather than guessing; this user has been happy
  to answer focused questions like that.

## Resuming after a context reset

1. `git log --oneline -10` and `git status` in `C:\Club_Training` to see the latest committed
   state and confirm nothing is stashed/uncommitted.
2. Re-read this file — it should stay accurate; update it as part of any future large feature work.
3. Check the "Known open items" section above before assuming a feature is finished.
