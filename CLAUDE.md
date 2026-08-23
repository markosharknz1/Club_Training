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
- **Run it:** `run.bat` (launches via `pythonw` — **windowless**, no console; closing the app
  window stops everything). `run_debug.bat` is the same launch with a visible console for
  troubleshooting. A "Club Training" desktop shortcut (pythonw target, app icon) exists on the
  user's Desktop. The Flask server still runs internally on
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
- `Coach` — name/phone/email plus pay fields: `pay_rate` (whole dollars; 0 = volunteer, see
  `is_volunteer`), `pay_basis` (`'session'` | `'hour'`), `notes`.
- `CoachAttendance` — one row per coach per `SessionDate` (unique constraint), the source of
  truth for who coached what and what they're owed. Carries a **snapshot** of the coach's
  rate/basis at marking time (`rate_snapshot`/`basis_snapshot`) plus computed `amount`, optional
  `hours` (hourly coaches; defaults to the session's scheduled duration), `adjustment` +
  `adjustment_reason`, and `marked_at`. `net_amount` = amount + adjustment. Historic pay is
  NEVER recomputed from the coach's current rate. The old `session_date_coaches` m2m still
  exists (add-only convention) but is **dormant** — a one-time idempotent migration in
  `create_app()` copied its rows into `CoachAttendance` (snapshotting each coach's
  then-current rate) and nothing reads or writes it any more.

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
    - **Offline Python package installs.** `vendor_wheels/` holds prebuilt `.whl` files for every
      pinned package *and all of their transitive dependencies* (28 wheels total, ~15MB, built via
      `pip wheel -r requirements.txt -w vendor_wheels` — this correctly handles `proxy_tools`,
      pywebview's one dependency that only ships as a source distribution, by building a wheel for
      it locally). `install.bat` now tries `pip install --no-index --find-links=vendor_wheels -r
      requirements.txt` first (zero internet needed) and only falls back to a normal
      `pip install -r requirements.txt` (needs internet) if that fails — which it would if the
      target machine's Python version doesn't match the platform-specific wheels (built against
      cp312/win_amd64). Verified end-to-end: a completely fresh venv with `--no-index` (no PyPI
      access at all) installed all 28 packages successfully and the app ran correctly against them.
      **When bumping a pinned version, regenerate `vendor_wheels/` too**
      (`pip wheel -r requirements.txt -w vendor_wheels`, after clearing the old contents) — an
      out-of-date `vendor_wheels/` just means the fallback path kicks in, but the offline
      install would still work, so it's for the maximum belt-and-braces from
      `requirements.txt` itself.
    - **Bundled WebView2 Runtime installer.** `pywebview` needs the Edge WebView2 Runtime, which
      ships with Windows 10/11 by default — but on the off chance a target machine somehow lacks
      it (e.g. a very stripped-down build), `vendor_installers/MicrosoftEdgeWebview2Setup.exe`
      (Microsoft's official Evergreen Bootstrapper, ~1.6MB, downloaded from their documented
      permalink `https://go.microsoft.com/fwlink/p/?LinkId=2124703`) is bundled. `install.bat`
      checks the well-known WebView2 registry key
      (`{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}` under `HKLM\...\EdgeUpdate\Clients\` or
      `HKCU\...`) and silently runs the bundled installer only if the runtime isn't already
      present.
    - **Soft Python-version check** at the top of `app.py`'s `if __name__ == '__main__':` block —
      warns (doesn't block) if running outside the tested range (3.9–3.14), pointing at Python
      3.12 as the known-good version. Purely informational, for diagnosing "why doesn't it work on
      this machine" rather than preventing startup.
13. **Reports simplified to player counts, long-term trend focus.** The user found the original
    Reports page (cash/card totals, a payment-type-by-month chart, a per-group-size chart) not
    useful and flagged that comparing differently-sized groups on one chart is confusing. Rebuilt
    around `_reports_data(months, session_filter)` (module-level helper, shared between the page
    and its export so they never drift) — money is gone entirely, the only metric is player
    check-in counts. One chart: total monthly check-ins over time (all sessions combined, or just
    the filtered session — never multiple differently-sized series on the same chart, which is
    exactly what was confusing before). Default period changed from 12 months to 24, plus an
    "All time" option (`months=0`), since the user wants long-term/year-over-year comparison
    ("is there more people this summer than last") rather than a short window. **New `/reports/
    export` route** — a "↓ Download Excel" button exports the exact on-screen monthly + per-session
    data as `.xlsx`, since the user was unsure the on-screen charts add value over raw numbers they
    can pivot themselves. The original single-month detailed payment/coach reconciliation export
    (`/export/excel`, linked from Settings → Export Data) is untouched — that's a different,
    deliberately kept feature.
    - **Bug fixed along the way** (pre-existing, not introduced by this change): the Reports
      session filter (`SessionDate.query.join(SessionTemplate).filter_by(session_id=...)`) crashed
      with a SQLAlchemy `InvalidRequestError` — `filter_by` after a `.join()` resolves against the
      *last-joined* entity (`SessionTemplate`, which has no `session_id` column), not `SessionDate`
      where that column actually lives. Fixed to an explicit `.filter(SessionDate.session_id ==
      ...)`. **If you ever see this exact error again elsewhere, it's this same footgun** — always
      use an explicit `.filter(Model.column == ...)` instead of `.filter_by()` on a query that has
      joined another table.
    - **Coaches sheet in the monthly Excel export was also fixed**: column headers were date-only
      (`'01 Jul'`), so two sessions on the same day produced *duplicate, ambiguous column headers*
      — impossible to tell which session a coach worked. Headers now read `'01 Jul - Sunday
      Advanced - 9-1030'` (date + session name), wrapped and sized to stay readable. This is what
      the user meant by "the coach export needs to be included in the month, and shown what
      coaches, and how many sessions they were at" — the data was already there, the ambiguous
      headers were the actual problem.
14. **Sessions setup page** — removed the "Total kids checked in" / "Total collected" stat row
    from each session card (added a couple of sessions ago, user decided they don't need it). Card
    now shows just day/time, prices, and groups — the user called this "simple."
15. **Medicare number removed entirely** from the player-facing UI — the field itself, and the
    "not actually needed" framing, means it's gone from: Add/Edit Player forms, the player detail
    page, the check-in page's right-click edit modal, the API get/save routes, and the Sports
    Voucher PDF export's info table. The underlying `players.medicare_number` DB column and its
    migration were **left in place** (unused, harmless) rather than dropped — this project's
    established pattern is migrations only ever add columns, never remove them, to avoid risky
    schema surgery on a real production SQLite file with no rollback story.

16. **Automatic database backups.** `_backup_database()` in `app.py` runs at the very top of
    `create_app()` — *before* `db.init_app`/migrations, so even a bad migration can never damage
    a file that wasn't backed up first. One copy per day into `backups/badminton_YYYY-MM-DD.db`,
    keeping the newest 30. `backups/` is gitignored (personal data, same as the live DB). Restore
    = close the app, copy a backup file over `badminton.db`, restart. Off-machine safety (USB
    copy) is still on the user.
17. **End-of-day summary** (`/day/<date>/summary`, `templates/day/summary.html`) — the
    reconciliation view from the original spec: day totals (kids, cash-to-count, card, voucher
    sessions), a per-session table with payment mix, and a **Coaches table (coach → which
    sessions they coached + count)**, per explicit request. Print button with print-friendly
    header (`d-print-none` / `d-print-block`). Shortcut button **"📋 Day Summary" lives on the
    check-in screen header** — the user asked for it there specifically, for easy access at
    pack-up time. Note: this page deliberately DOES show money (cash to count against the till)
    even though Reports doesn't — reconciliation vs trend-reporting are different jobs.
18. **Duplicate-player protection** (soft warnings, never hard blocks — same-name players are
    legitimately possible): Add Player modal on the Players page checks the typed name against
    every existing player (incl. inactive) client-side and asks confirm(); the check-in page's
    quick-add API returns `duplicate: true` unless `force` is sent, and the client confirms then
    retries with force; CSV import silently *skips* rows whose name already exists (in the DB or
    earlier in the same file) and lists them in the result message, pointing at + Add Player for
    genuine same-name cases.
19. **Long-absent players prompt** — on the Players page, a warning banner lists active players
    whose last attendance is **over a year ago** (user chose 1 year over my suggested 6 months;
    never-attended players count from their `created_at`), with a one-click "Mark all inactive"
    bulk action (`POST /players/mark-inactive`). Nothing is automatic — it only ever *offers*.
    Inactive players keep all history and can be reactivated via Edit.

20. **Voucher numbers + voucher CSV import.** `Voucher.voucher_number` (add-only migration) —
    the number printed on the physical/government voucher. Shown as a "Voucher #" column on the
    Vouchers page, a field in the New Voucher modal (which rejects already-registered numbers),
    prefixed in the check-in voucher-picker labels, and on the per-voucher PDF. **`/vouchers/
    import`** (↑ Import CSV button on the Vouchers page, `templates/vouchers_import.html`) bulk-
    imports vouchers: columns `name` (must match an existing player, case-insensitive),
    `voucher_number`, `amount`, `sessions`, `date_issued` (ISO or `dd/mm/yyyy`), `notes` — only
    `name` required. Rows are validated against the normal 2-active/2-per-year limits, unknown
    players and duplicate numbers are skipped and itemised in the result message.

21. **Excel import + real GBC file formats.** Both importers (`/players/import`,
    `/vouchers/import`) accept `.xlsx` as well as `.csv` via the shared `_read_tabular_rows()`
    helper (openpyxl; stops after 20 consecutive blank rows because real Excel files report ~1M
    ghost rows). Built against the club's actual files (`E:\GBC\GBC Juniors for Mark.xlsx`,
    `E:\GBC\GBC Sports Vouchers for Mark.xlsx` — real kids' data, **never commit these or copy
    them into the repo**):
    - Player import understands separate `Given`/`Surname` columns (combined into one name), an
      `SV` column (`Y` → notes = "Sports Voucher"), and strips `^` markers from names
      (`_clean_person_name`). Name-dedup makes re-imports safe.
    - Voucher import handles a **carryover balance sheet**: header row found anywhere in the
      first 30 rows (title rows above are fine), a "Remaining lessons"-style column (or, failing
      that, the numeric column next to the names), and a `d/m/yy` date in the title used as
      `date_issued`. Each row becomes a voucher whose `sessions_total` = the remaining count
      (amount = remaining × $10). **Re-importing a balance sheet duplicates vouchers** — warned
      on the import page.
    - **Name matching across files** (`_build_player_matcher` + `_norm_name`): exact normalised
      (accents/curly-quotes/markers/whitespace) → unique first+last token (handles middle names,
      e.g. "Neville Rui Yee Tan" → "Neville Tan") → guarded fuzzy (similarity ≥ .88, clear margin
      over runner-up, first-name similarity ≥ .8 — deliberately refuses to guess between siblings
      like Ometh/Okitha/Onadi Karunathilaka, and won't map nicknames like Rudolph→Rudi). All
      non-exact matches are itemised in the result message as "matched by name similarity —
      please check". Verified against the real files: 165/165 players, 30/36 vouchers, the 6
      unmatched genuinely absent from the juniors list.

22. **Standalone .exe build (PyInstaller).** The user asked to "install all its dependencies as a
    PWA" — clarified to mean *one-click install on any Windows PC with nothing else needed*. A
    PWA can't do that (browser-side only, can't carry the Python server), so the agreed solution
    is a PyInstaller bundle: run **`build_exe.bat`** → `dist\Club_Training\` (~79MB folder) with
    `Club_Training.exe` inside — Python + every dependency baked in. Hand the whole folder to
    someone (zip/USB); double-click the exe, done. Key mechanics: `_resource_dir()` in `app.py`
    points Flask's `template_folder`/`static_folder` at `sys._MEIPASS` when frozen, while the
    database + `backups/` stay next to the exe via `config.BASE_DIR`'s existing `sys.frozen`
    branch — so bundled assets and persistent data are cleanly separated. Hidden imports
    `webview.platforms.edgechromium`/`.winforms` are required for pywebview. `build/`, `dist/`,
    `*.spec` are gitignored. Verified end-to-end: built exe launched its own window, served
    pages and bundled static assets, and created a fresh DB beside itself. To ship real club
    data with it, copy `badminton.db` into the folder next to the exe. Rebuild after any code
    change — the exe is a frozen snapshot, it does not pick up edits to the .py files.
    **App icon:** `static/icon.ico` (multi-size 16–256px, shuttlecock on the navbar navy,
    generated programmatically with Pillow — regeneration code is in the session that added it;
    tweak by redrawing at 512px and re-saving with `sizes=[...]`). Baked into the exe via
    `--icon` in `build_exe.bat`; for a shortcut to `run.bat` on the dev machine, point the
    shortcut's Change Icon dialog at that file.
    **Distribution via GitHub Releases** (the user's preferred "download from GitHub" flow —
    Code → Download ZIP only ever gives source, so built apps ship as release assets instead;
    first release: v1.0.0). To publish a new version after code changes:
    1. `build_exe.bat` (fresh exe in `dist\Club_Training\`)
    2. confirm no `*.db`/`backups/` inside `dist\Club_Training\` (never ship data)
    3. `Compress-Archive -Path dist\Club_Training -DestinationPath dist\Club_Training_vX.Y.Z_windows.zip -Force`
    4. `gh release create vX.Y.Z dist\Club_Training_vX.Y.Z_windows.zip --title "Club Training vX.Y.Z" --notes "..."`
    Downloaders: repo page → Releases (right-hand side) → download the zip → unzip →
    double-click `Club_Training.exe`. Note the repo is **private**, so downloaders must be
    signed into a GitHub account with access (add collaborators under repo Settings → Access),
    or the repo must be made public — the release asset itself contains no club data either way.

23. **Groups feature toggle.** Settings → Groups → "Use groups within sessions" switch
    (`groups_enabled` Setting, default on, exposed app-wide via the context processor). When off,
    every group picker/column/badge disappears: Plan Day group checkboxes, check-in modal group
    select (hidden but present in DOM so the JS keeps working), Last Group / Group columns on the
    check-in tables (the JS row-builders and empty-state colspans are group-aware via a
    `GROUPS_ENABLED` const), Sessions setup Groups section, day-view badges, Players list
    filter/column/add-modal select, player edit/detail, and the register pages. No data is
    deleted — flipping back on restores everything. `day_checkin` also sends empty `groups`
    arrays to the modal JS when off.
24. **Coach Database.** The Coaches page was promoted from Setup → Coaches to a top-level
    **Coach Database** nav item (parallel to Player Database; removed from the Setup dropdown).
    Each coach card now shows sessions coached this year, all-time, and last-coached date
    (computed in the `coaches()` route by walking `SessionDate.coaches`). Add/edit/deactivate
    unchanged.

25. **Email announcements (SMTP2GO).** Settings → **Email (SMTP2GO)** card: enable toggle (off
    by default, same opt-in pattern as Square), SMTP host/port (defaults `mail.smtp2go.com:2525`),
    username, write-only password (blank = keep), from address (must be a verified SMTP2GO
    sender) and from name. New top-level **Email** nav page (`/email`, `templates/email.html`):
    pick an audience window ("played in the last 1/3/6/12 months"), see the resolved recipient
    list (juniors → guardian email first, seniors → own email first; **deduped by address so a
    family with several kids gets one copy**) plus an explicit "no email on file" list, compose
    subject + plain-text body, send. `_send_bulk_email()` sends one individual email per address
    over a single STARTTLS SMTP connection — never a shared To/CC line, so parents' addresses
    stay private from each other. Verified with a fake SMTP double (correct headers, dedupe,
    graceful auth-failure handling); **not yet tested against real SMTP2GO credentials**.
    ⚠️ The imported GBC juniors have **no email addresses** (the juniors spreadsheet had none),
    so the recipient list is empty until guardian emails are added — either via Player Database →
    Edit, or a future CSV/Excel re-import that includes an email column (the player importer
    already maps `guardian_email`, but note it skips existing names, so an email-updating
    re-import would need an update-in-place mode that doesn't exist yet).

26. **Email session filter + Senior "Emergency contact" relabel.** The Email page audience picker
    gained a Session dropdown (`_recent_player_emails(months, session_id)`; the filter is carried
    through the send form as a hidden field) — different sessions have different audiences, so a
    tournament notice can target just one session's players. Separately, the guardian_* fields
    keep their DB names but are **labelled by category**: "Guardian …" for Juniors, "Emergency
    contact …" for Seniors — server-side on the player detail page, JS-swapped in
    `applyFieldVisibility()` (all three copies) on the add/edit forms, and the Settings checkbox
    for Seniors reads "Track emergency contact".
27. **⚠ DATA-LOSS INCIDENT (2026-08-18) + backup hardening.** A cleanup command intended for
    `dist\` (`rm -f badminton.db && rm -rf backups`) ran in the project root instead — the
    `cd X && exe &` line before it backgrounded the *whole* chain including the `cd`, so the
    shell's cwd never changed. The live DB and all backups were deleted in one stroke; recovery
    was only possible because the club hadn't gone live and everything real could be re-imported
    from `E:\GBC` (165 players + 30 voucher balances re-imported identically; sessions/groups/
    coaches/settings rebuilt by hand). **Never run destructive commands with relative paths —
    see the `feedback-destructive-command-safety` memory.** Hardening added: `_backup_database()`
    now writes daily backups to **two independent locations** — `backups/` beside the app AND
    `Documents\Club_Training Backups\` — so no single folder deletion can take out the data
    and every backup together. One location failing never blocks the other. Documents is
    resolved via the registry (`User Shell Folders\Personal`) because OneDrive redirects it —
    on this machine backups land in `C:\Users\mhami\OneDrive\Documents\Club_Training Backups\`,
    so **OneDrive syncs them to the cloud** for genuine off-machine protection. The LIVE
    database must still never live in OneDrive (sync corrupts actively-written SQLite files);
    backups are write-once copies, so syncing them is safe. (An earlier LOCALAPPDATA mirror was
    superseded by Documents; copies already there remain as a bonus archive.)

28. **Membership register import** (built for `E:\GBC\GBC Member 31Jul26 for Mark.xlsx` —
    columns `Rego #`, `Full Name`, gender, `Mbshp Type` (Junior/Social/Comp A–C), `Status`).
    `Player` gains `rego_number` / `membership_type` / `membership_status` (add-only migration),
    shown as a "Membership" row on the player detail page. `/players/import` detects
    rego/membership columns and switches modes: matched players are **updated in place** (no
    skip-existing), unmatched members are **added** as new players (Junior type → Junior, all
    else → Senior; ALL-CAPS surnames from the register are title-cased). Live result: 10 existing
    juniors updated, 107 members added → 272 players (171 Junior / 101 Senior), 117 with rego
    numbers. The fuzzy-match full-name cutoff was raised **0.88 → 0.90** after the dry run caught
    a false positive ("Leo ZHANG" → "Leo Huang" scores 0.889 — different people); all known-good
    typo matches score ≥ 0.92 and still pass. Always dry-run imports against a copy of the DB
    before touching the live one.

29. **Manage Database panel** (⚙ button on the Player Database page, modal in
    `players/list.html`): two admin tools. **Merge duplicate players**
    (`POST /players/merge`): moves the duplicate's attendance to the keeper (same-session-date
    conflicts keep the keeper's record and drop the duplicate's), moves vouchers, re-points
    sibling links, fills the keeper's blank fields from the duplicate (never overwrites),
    appends notes, keeps `active` if either was active, then deletes the duplicate — built for
    cases like the register's "Gursangeet KHARA"/"Gersangeet Khara" spelling variants.
    **Permanently delete a player** (`POST /players/delete`): removes the player + all
    attendance + vouchers + sibling links — for junk entries only; the modal text steers
    "player left the club" cases to Edit → inactive instead. Both have strong JS confirms.
    Tested end-to-end against a temp copy of the DB (the post-incident standard for anything
    destructive).

30. **Coach attendance & end-of-month pay** (workstream 1 of the user's pasted spec; user's
    answers: coach and player records fully separate; flat rate per session — a coach working
    two sessions on the same day is paid for both; coach pay is completely separate from money
    the club takes; volunteers = rate 0, shown but never payable; month extract is "just a list
    for whoever pays", plain CSVs).
    - **Coach Database** (`/coaches`): add/edit now includes pay rate ($, whole dollars),
      paid-per (session/hour) and notes. Editing the rate/basis flashes a warning that the
      change affects **future sessions only**. Cards show the rate or a "Volunteer (unpaid)"
      badge and link to Coach Payments.
    - **Coaches Present matrix** (day view): now instant AJAX (`POST /api/coach-attendance`) —
      each tick immediately creates a `CoachAttendance` row with rate/basis snapshots; untick
      deletes it. Hourly coaches get an hours input (prefilled with the session's scheduled
      duration, editable, amount recomputes against the **snapshot** rate) and each session
      column shows a live "Pay total" footer. The register run page's coach checkboxes
      (`POST /register/<id>/coaches`) write `CoachAttendance` the same way.
    - **Coach Payments** (`/coach-payments?month=YYYY-MM`, linked from Coach Database):
      per-coach month summary (sessions, hours, gross, adjustments, net) with collapsible
      per-session detail; adjustments (whole dollars, ± with reason) editable inline via
      `POST /api/coach-attendance/adjust`. Volunteers listed but excluded from the payable
      total. Two CSV exports (stdlib csv, UTF-8-sig): `coach-payments-YYYY-MM.csv` (summary
      + TOTAL PAYABLE row) and `coach-payments-detail-YYYY-MM.csv` (every row incl.
      adjustment reasons).
    - **Finalise month**: sets Setting `coach_month_final_YYYY-MM`. Once finalised, coach
      ticks/hours/adjustments for that month get a JS confirm ("finalised — change anyway?")
      which resends with `force: true`; re-open any time from the same page. The register-page
      coach form just refuses with a flash when the month is finalised (no JS there).
    - Tested end-to-end on a temp DB copy (32 checks, all green): m2m migration + idempotency,
      same-day double pay, hourly maths incl. duration default, snapshot survival across rate
      changes, volunteer exclusion, adjustments, finalise/force/re-open, CSV parse + sum
      reconciliation, and regressions on day view/summary, register run, coach DB and the
      monthly Excel export (whose Coaches sheet now reads `CoachAttendance`).
    Workstream 2 of that spec (PII protection: admin password gate, audit log, recovery codes,
    envelope encryption) is **not built yet** — see spec notes in chat history; it needs a
    Flask/SQLAlchemy redesign of the doc's sql.js design before building.

31. **Rebrand to "Club Training" + selectable club icon** (item 1 of the user's five-item
    change spec, v1.4.0). All "My Badminton Club" defaults are now "Club Training"; window/tab
    title format is `Club Training — {club name}` (bare "Club Training" when no name set) via
    `app_title` in the context processor — page `{% block title %}` blocks all use `app_title`.
    Navbar 🏸 replaced with the club icon. 28 bundled single-colour SVG icons live in
    `static/icons/sports/` (Tabler Icons v3.31.0, MIT, vendored from unpkg; `badminton.svg`
    hand-drawn in Tabler style; see LICENSE.md there; registry = `BUNDLED_ICONS` in app.py).
    `/api/branding/icon` serves bundled SVG or custom PNG with an ETag keyed on Setting
    `club_icon_ver` (bumped on every icon change for cache busting). Custom upload (Settings →
    Club Identity): client-side `<canvas>` cover-crop/resize to 256×256 PNG data URL (no
    Pillow dependency), server accepts only `data:image/png` + sniffs the PNG magic bytes,
    2 MB cap, SVG uploads rejected (script risk). Stored base64 in Settings
    (`club_icon_type/key/blob/mime` — Setting.value is TEXT, fits fine). Bundled icons get
    `filter:brightness(0) invert(1)` in the dark navbar; custom logos don't (guarded by
    `club_icon_is_bundled`).

32. **Settings restructured into sections** (item 4). `/settings` → redirect;
    `/settings/<section>` deep-linkable with left-nav layout (`templates/settings/_layout.html`
    + one template per section): identity, players (old Player Categories & Fields), sessions
    (groups toggle), payments (Square), vouchers, coaches, email, security (placeholder →
    BitLocker advice until encryption ships), data (Excel export, backups info, testing mode),
    about (APP_VERSION in app.py). POST dispatch lives in `_settings_save(section)`; saves are
    per-section; `_layout.html` has a dirty-state ● marker + beforeunload warning. Voucher
    rules are now Settings (`voucher_amount/sessions/max_active/max_per_year` via
    `_voucher_defaults()`, wired into `_voucher_limit_error` and all creation fallbacks —
    the old constants remain only as fallback defaults). Old `templates/settings.html` deleted.

33. **Email gating — TWO separate toggles** (item 3; user explicitly chose two independent
    switches). `email_sending_enabled` (default off; migrated from the old `email_enabled`
    setting on startup) gates the Email nav item, `/email` pages, `_email_configured()` and
    the SMTP fields; Settings → Email also has the SMTP2GO sending-limits link and a
    "Send test email" button (`/settings/email/test`). `email_fields_enabled` (default on)
    gates player email UI: `_player_field_settings()` force-disables the per-category `email`
    flag (kills own-email fields everywhere), guardian-email inputs are Jinja-gated in
    players/edit, players/list add-modal, day/checkin edit-modal, players/detail, and the
    import column map drops `own_email`/`guardian_email`. CRITICAL pattern: edit routes only
    update email columns when the key is PRESENT in the form/JSON (`'guardian_email' in
    request.form` / `in data`) so hidden fields never blank stored addresses — the check-in
    edit modal omits those keys via Jinja when fields are off.

34. **Coach tracking modes off/simple/advanced + mark-as-paid** (item 2; default `simple`,
    setting `coach_tracking_mode`, chosen in Settings → Coaches). Schema is ALWAYS full
    (mode gates UI only, per spec): CoachAttendance gained `paid`, `paid_date`,
    `payment_reference` (add-only migration). `off` hides the Coach Database nav + day-page
    and register-page coach sections + summary coaches card, and `/coaches` +
    `/api/coach-attendance` refuse. `simple` = tick matrix only — all rate badges, hours
    inputs, amounts, pay totals, payments link and modal pay fields hidden (`adv` flag in
    day/view.html; day-view JS null-guards the missing elements); ticks still snapshot the
    current rate silently so a later upgrade keeps history. IMPORTANT: coach edit POST only
    updates pay fields when `pay_rate` is present in the form, so editing a coach in simple
    mode can't reset a stored rate to 0. `advanced` = everything from v1.3.0 plus per-coach
    per-month **Mark paid** (`POST /coach-payments/mark-paid`, optional reference, sets
    row-level paid flags; undo supported; Paid columns added to both CSVs) and the optional
    **backfill** (`POST /settings/coaches/backfill`): applies current rates to $0-rate
    markings from a chosen date, labelled an estimate, never touches rows with an amount.
    Mode switches warn via JS (advanced→other: "hidden but not deleted").

35. **"New player" tickbox at check-in** (user: "flag new members with a tickbox… might/might
    not be a payment type, but we want to record new people"). `Attendance.new_member` boolean
    (add-only migration), fully independent of payment type. Tickbox appears in BOTH check-in
    modals (day/checkin.html player-first flow and register/run.html). It **always starts
    UNTICKED** — v1.5.0 auto-pre-ticked first-timers and the user asked for that to be
    removed in v1.5.3 ("defaulting to ticking the new player box… set to unflagged"); do not
    reintroduce it. Editing a check-in keeps/toggles the saved flag
    (carried in the row's `data-checkin` JSON / openModal args). Yellow NEW badges on
    register + checked-in rows; day summary gains a "New Players Today" card (names +
    sessions) and `day_totals['new']`; Reports gains a New Players tile + monthly "New"
    column (`_reports_data` row['new'], total_new); both Excel exports gained New Players
    columns (monthly export Session Summary sheet + reports Monthly Attendance sheet).
    The register "Check in all" bulk path never sets the flag.

36. **Voucher carryover representation fix + "Clear Old Calendar Entries"** (user: "imported
    are showing 0 sessions used, not 4/10" and "need a way to clear all of the old calendar
    entries"). Root cause: the carryover import stored REMAINING as `sessions_total` (4 left →
    a 4-session $40 voucher → "0/4 used"). Fix: `Voucher.sessions_used_before` (add-only
    migration; sessions with no attendance row in this app) and `sessions_used` = that +
    live attendance rows. One-time repair runs when the column is added: every voucher whose
    notes start "Imported balance" becomes standard-size (`ceil(remaining/10)*10` sessions,
    $10/session → 4 left = 10 total / 6 used; 12 left = 20 total / 8 used); verified total
    remaining across all 30 live vouchers unchanged (226). The import path now writes the
    same shape. **Purge tool** (Settings → Data & Backup, `POST /settings/data/purge-sessions`,
    requires typing DELETE + JS confirm, refuses future cut-offs): deletes every SessionDate
    before a date (attendance via cascade, CoachAttendance explicitly) and FOLDS voucher
    check-ins into `sessions_used_before` so balances never change. Players/vouchers/coaches
    untouched. NOTE: the dev DB in C:\Club_Training has zero session_dates — the user's live
    data lives in their unzipped release folder, so diagnose from descriptions/screenshots,
    not the dev copy.

37. **Voucher editing: dated uses, hide, linking** (user: "edit/change the Sports Vouchers —
    change dates used, add dates, and hide old vouchers. New voucher should link to the old").
    New `VoucherUse` table (voucher_id, used_date nullable = unknown, note): every voucher
    session used OUTSIDE a live check-in — imported carryover balances, manual backdated uses,
    and check-ins folded in by the calendar purge. `Voucher.sessions_used` = manual_uses +
    attendance rows (+ legacy `sessions_used_before`, which a one-time migration converts to
    VoucherUse rows, recovering dates from the "used: …" part of import notes via
    `_parse_loose_date` — day/month-only dates take the issue year, rolling forward if before
    issue). `Voucher.hidden` + `continues_from_id` (self-FK; backref `continued_by`) added
    (migration ORDER matters: these ALTERs must run before any ORM Voucher query in
    create_app — they sit before the sessions_used_before block). Importer accepts a
    **"Used Dates"** column (comma-separated; the converter for the user's slot-by-slot sheet
    emits ISO dates) else falls back to the note. Vouchers page: **Edit** dialog (number, amount,
    sessions, date issued, notes, hidden, "continues from" select of the child's other
    vouchers) with a usage list — check-ins read-only, manual rows date/note-editable +
    removable + "Add used date" (instant AJAX: `GET /api/voucher/<id>`, `POST
    /api/voucher/<id>/use`, `POST|DELETE /api/voucher/<id>/use/<use_id>`); page reloads on
    dialog close if uses changed. Hide/Unhide per row, "Hide all used-up vouchers", "Show
    hidden (n)" toggle; hidden vouchers are excluded from the check-in picker and fallback
    but still count for yearly limits. New vouchers (page form AND on-the-spot create at
    check-in) auto-link to the child's most recent used-up voucher with no follow-on
    (`_voucher_to_continue`); list shows "↳ continues …" / "→ followed by …". PDF lists
    manual uses too ("Date unknown" rows last). Converter script for the user's
    `sports-vouchers.xlsx` lives only in the session scratchpad (real kids' data — never in
    the repo); output `sports-vouchers-import.xlsx` in the user's Downloads.

## Known open items (not yet built — need user input before building)

- **"Enter date" for voucher usage** — the user flagged wanting some way to manually
  record/backdate voucher usage outside the live check-in flow. Not yet scoped or built.
- **Vouchers used for membership** — the user said "need to look more at that" (i.e. vouchers
  might in future pay for annual membership, not just per-session fees). Explicitly deferred,
  do not build speculatively.
- **Item 5 — PII encryption at rest** — PARKED by the user (2026-08-21, "lets leave it for
  now") after the design evolved. Where it landed: the user chose **Option B** — NO password
  prompt; DEK wrapped by **Windows DPAPI** (auto-unlock tied to the Windows login) + a
  printable base32 **Recovery Key** shown at enable time for new-machine/restore recovery;
  AES-256-GCM whole-file encryption with the DB held in an in-memory sqlite3 connection
  (`serialize`/`deserialize`, needs Python 3.11+; StaticPool + `creator` for SQLAlchemy;
  save on every `after_commit`, atomic tmp+fsync+replace writes, `.enc.bak` rotation,
  single-instance lock file since in-memory mode loses SQLite file locking). The original
  two-admin-passwords + scrypt design was dropped with the user's agreement. OPEN QUESTION
  when resumed: B alone vs **B + RSA-4096 developer escrow slot** (DEK also wrapped to a
  developer public key in the keystore so the developer can recover a club that lost both
  the Windows account and the paper key; recommended, mandatory-but-disclosed, decrypt tool
  in a separate private repo) — the user was leaning informed but stopped before deciding.
  A complete `securedb.py` module (DPAPI ctypes, AESGCM file format `CLUBENC1`+nonce+ct,
  recovery-key encode/decode with checksum, keystore.json with dek_sha256, prepare()/
  activate()/save_active(), decrypt-on-restart flag, pid lock) was written and then deleted
  uncommitted when parked — retrieve it from this session's transcript or rewrite from this
  note. `cryptography` 44.0.0 is ALREADY installed and already bundled by PyInstaller.
  NOTE: until this ships, OneDrive-synced backups contain plaintext PII — BitLocker on the
  club machine is the standing advice (Settings → Security & Privacy says so).
- Nothing else is mid-flight beyond spec item 5.

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

## Remote work (claude.ai/code cloud sessions)

The user also works on this project remotely via Claude Code on the web, where sessions run in a
Linux cloud sandbox cloned from GitHub. Rules for those sessions:

- **The real database is not in the repo and never will be** (kids' personal data). The app
  auto-creates an empty `badminton.db` on first run. For realistic testing, run
  `python seed_demo_data.py` first — it builds ~24 fictional players, 3 sessions, coaches,
  vouchers, and ~26 weeks of attendance history. It **refuses to run** if the database already
  contains any data, so it can never pollute a real DB; to re-seed, delete `badminton.db` first.
- **Push to a branch, not `master`.** Remote changes can't be verified against the real database
  or the real Windows machine, so they're "proposed until the user pulls and runs them at home."
  The user merges (or asks for a merge) and then `git pull`s in `C:\Club_Training`.
- **Verify with the Flask test client** (same as local practice) — `pywebview` won't open a
  window in a sandbox, and that's fine; the entry-point fallback and all routes work headless.
- **Can't be tested remotely** (write the code, flag it for at-home verification): the pywebview
  desktop window itself, `install.bat`/WebView2 behaviour, Square Terminal hardware, printing.
- Linux is case-sensitive and uses `/` paths — the app code is already portable, keep it that way.

## Resuming after a context reset

1. `git log --oneline -10` and `git status` in `C:\Club_Training` to see the latest committed
   state and confirm nothing is stashed/uncommitted.
2. Re-read this file — it should stay accurate; update it as part of any future large feature work.
3. Check the "Known open items" section above before assuming a feature is finished.
