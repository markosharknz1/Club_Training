"""
Club Training — club session management
Run:  python app.py
"""
import calendar as _cal_mod
import base64
import glob, json, os, shutil, smtplib, socket, sys, threading, time, webbrowser
import requests
from email.mime.text import MIMEText
from collections import defaultdict, OrderedDict
from datetime import date, datetime, timedelta

from flask import (Flask, jsonify, flash, redirect, render_template,
                   request, url_for)

import config
from models import (db, Setting, SessionTemplate, Group, Coach, Player,
                    sibling_links, SessionDate, Attendance, Voucher,
                    CoachAttendance,
                    PAYMENT_TYPES, AMOUNT_TYPES, DAY_NAMES, PAYMENT_COLORS,
                    DEFAULT_VOUCHER_AMOUNT, DEFAULT_VOUCHER_SESSIONS)


APP_VERSION = '1.4.0'

# ─── Branding ───────────────────────────────────────────────────────
# Bundled club icons (static/icons/sports/<key>.svg — see LICENSE.md there).
BUNDLED_ICONS = [
    ('badminton',       'Badminton'),
    ('ball-tennis',     'Tennis'),
    ('ping-pong',       'Table tennis'),
    ('ball-basketball', 'Basketball / Netball'),
    ('ball-football',   'Football (soccer)'),
    ('ball-volleyball', 'Volleyball'),
    ('ball-baseball',   'Baseball / Softball'),
    ('cricket',         'Cricket'),
    ('golf',            'Golf'),
    ('play-handball',   'Handball / Hockey'),
    ('swimming',        'Swimming'),
    ('run',             'Running / Athletics'),
    ('bike',            'Cycling'),
    ('gymnastics',      'Gymnastics'),
    ('karate',          'Martial arts'),
    ('ice-skating',     'Skating'),
    ('curling',         'Curling'),
    ('music',           'Dance / Music'),
    ('ball-bowling',    'Bowling / Generic ball'),
    ('trophy',          'Trophy'),
    ('medal',           'Medal'),
    ('award',           'Award'),
    ('star',            'Star'),
    ('calendar-event',  'Calendar'),
    ('flag',            'Flag'),
    ('users-group',     'Group of people'),
    ('clipboard-list',  'Clipboard / Roster'),
    ('stopwatch',       'Stopwatch'),
]


# ─── App factory ────────────────────────────────────────────────────

def _documents_dir():
    """The user's real Documents folder. On OneDrive-managed machines Documents
    is redirected (e.g. C:\\Users\\x\\OneDrive\\Documents), so resolve it from
    the registry rather than assuming ~/Documents."""
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                r'Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders') as key:
            value, _type = winreg.QueryValueEx(key, 'Personal')
        return os.path.expandvars(value)
    except OSError:
        return os.path.join(os.path.expanduser('~'), 'Documents')


def _backup_dirs():
    """Two independent backup locations: one beside the app, and one in the
    user's Documents folder — which on OneDrive-backed machines syncs the
    backups to the cloud. (The LIVE database must never live in OneDrive —
    sync can corrupt a file that's actively written — but backups are
    write-once copies, so syncing them is safe and gives off-machine
    protection.) No single folder deletion can destroy the data AND every
    backup of it at the same time."""
    return [os.path.join(config.BASE_DIR, 'backups'),
            os.path.join(_documents_dir(), 'Club_Training Backups')]


def _backup_database(keep=30):
    """Daily safety copy of the SQLite file into each backup location,
    keeping the newest `keep` in each. Runs before the app touches the
    database, so even a bad migration can't damage a file that hasn't
    been backed up first."""
    if not os.path.exists(config.DB_PATH):
        return
    for backup_dir in _backup_dirs():
        try:
            os.makedirs(backup_dir, exist_ok=True)
            dest = os.path.join(backup_dir, f'badminton_{date.today().isoformat()}.db')
            if not os.path.exists(dest):
                shutil.copy2(config.DB_PATH, dest)
            old_backups = sorted(glob.glob(os.path.join(backup_dir, 'badminton_*.db')))
            for old in old_backups[:-keep]:
                try:
                    os.remove(old)
                except OSError:
                    pass
        except OSError:
            continue  # one location failing must never block the other


def _resource_dir():
    """Where bundled read-only assets (templates/, static/) live. In a
    PyInstaller build they're unpacked to sys._MEIPASS; in normal runs
    they sit next to this file. The database is separate — it always
    lives next to the exe/script (config.BASE_DIR) so data persists."""
    if getattr(sys, 'frozen', False):
        return sys._MEIPASS
    return os.path.dirname(os.path.abspath(__file__))


def create_app():
    _backup_database()
    res = _resource_dir()
    app = Flask(__name__,
                template_folder=os.path.join(res, 'templates'),
                static_folder=os.path.join(res, 'static'))
    app.secret_key = 'bc-club-local-2025'
    app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{config.DB_PATH}'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    db.init_app(app)

    with app.app_context():
        db.create_all()
        if not Setting.query.get('club_name'):
            db.session.add(Setting(key='club_name', value='Club Training'))
        # Rename migration: the single email_enabled flag became
        # email_sending_enabled (fields have their own toggle, default on).
        if (not Setting.query.get('email_sending_enabled')
                and Setting.query.get('email_enabled')):
            db.session.add(Setting(key='email_sending_enabled',
                                   value=Setting.query.get('email_enabled').value))
            db.session.commit()
        # Lightweight migrations: older DBs won't have these columns yet.
        cols = [row[1] for row in db.session.execute(db.text("PRAGMA table_info(attendance)")).fetchall()]
        if 'voucher_id' not in cols:
            db.session.execute(db.text("ALTER TABLE attendance ADD COLUMN voucher_id INTEGER REFERENCES vouchers(id)"))
            db.session.commit()
        player_cols = [row[1] for row in db.session.execute(db.text("PRAGMA table_info(players)")).fetchall()]
        if 'medicare_number' not in player_cols:
            db.session.execute(db.text("ALTER TABLE players ADD COLUMN medicare_number VARCHAR(30)"))
            db.session.commit()
        if 'category' not in player_cols:
            db.session.execute(db.text("ALTER TABLE players ADD COLUMN category VARCHAR(10) NOT NULL DEFAULT 'Junior'"))
            db.session.commit()
        if 'address' not in player_cols:
            db.session.execute(db.text("ALTER TABLE players ADD COLUMN address VARCHAR(250)"))
            db.session.commit()
        if 'own_email' not in player_cols:
            db.session.execute(db.text("ALTER TABLE players ADD COLUMN own_email VARCHAR(150)"))
            db.session.commit()
        if 'own_phone' not in player_cols:
            db.session.execute(db.text("ALTER TABLE players ADD COLUMN own_phone VARCHAR(30)"))
            db.session.commit()
        if 'rego_number' not in player_cols:
            db.session.execute(db.text("ALTER TABLE players ADD COLUMN rego_number VARCHAR(20)"))
            db.session.execute(db.text("ALTER TABLE players ADD COLUMN membership_type VARCHAR(30)"))
            db.session.execute(db.text("ALTER TABLE players ADD COLUMN membership_status VARCHAR(30)"))
            db.session.commit()
        coach_cols = [row[1] for row in db.session.execute(db.text("PRAGMA table_info(coaches)")).fetchall()]
        if 'pay_rate' not in coach_cols:
            db.session.execute(db.text("ALTER TABLE coaches ADD COLUMN pay_rate NUMERIC(8,2) NOT NULL DEFAULT 0"))
            db.session.execute(db.text("ALTER TABLE coaches ADD COLUMN pay_basis VARCHAR(10) NOT NULL DEFAULT 'session'"))
            db.session.execute(db.text("ALTER TABLE coaches ADD COLUMN notes VARCHAR(200)"))
            db.session.commit()
        ca_cols = [row[1] for row in db.session.execute(db.text("PRAGMA table_info(coach_attendance)")).fetchall()]
        if ca_cols and 'paid' not in ca_cols:
            db.session.execute(db.text("ALTER TABLE coach_attendance ADD COLUMN paid BOOLEAN NOT NULL DEFAULT 0"))
            db.session.execute(db.text("ALTER TABLE coach_attendance ADD COLUMN paid_date DATE"))
            db.session.execute(db.text("ALTER TABLE coach_attendance ADD COLUMN payment_reference VARCHAR(100)"))
            db.session.commit()
        # One-time: carry historic coach markings (old session_date_coaches m2m)
        # into CoachAttendance, snapshotting each coach's CURRENT rate.
        if CoachAttendance.query.count() == 0:
            old_rows = db.session.execute(db.text(
                "SELECT session_date_id, coach_id FROM session_date_coaches")).fetchall()
            if old_rows:
                for sd_id, c_id in old_rows:
                    c  = db.session.get(Coach, c_id)
                    sd = db.session.get(SessionDate, sd_id)
                    if not c or not sd:
                        continue
                    amount, hours = _coach_pay_amount(c, sd.template)
                    db.session.add(CoachAttendance(
                        session_date_id=sd_id, coach_id=c_id, hours=hours,
                        rate_snapshot=c.pay_rate, basis_snapshot=c.pay_basis,
                        amount=amount))
                db.session.commit()
        session_tmpl_cols = [row[1] for row in db.session.execute(db.text("PRAGMA table_info(session_templates)")).fetchall()]
        if 'category' not in session_tmpl_cols:
            db.session.execute(db.text("ALTER TABLE session_templates ADD COLUMN category VARCHAR(10) NOT NULL DEFAULT 'Mixed'"))
            db.session.commit()
        voucher_cols = [row[1] for row in db.session.execute(db.text("PRAGMA table_info(vouchers)")).fetchall()]
        if voucher_cols and 'voucher_number' not in voucher_cols:
            db.session.execute(db.text("ALTER TABLE vouchers ADD COLUMN voucher_number VARCHAR(50)"))
            db.session.commit()

    # ── Auto-close stale sessions ─────────────────────────────────────

    @app.before_request
    def auto_close_stale():
        if request.method != 'GET':
            return
        if (request.endpoint or '').startswith('api_'):
            return
        today = date.today()
        stale = SessionDate.query.filter(
            SessionDate.status == 'open',
            SessionDate.date < today
        ).all()
        if stale:
            for sd in stale:
                sd.status    = 'closed'
                sd.closed_at = datetime.utcnow()
            db.session.commit()
            n = len(stale)
            flash(f'{n} session{"s" if n > 1 else ""} from a previous day '
                  f'{"were" if n > 1 else "was"} automatically closed.', 'info')

    # ── Context ──────────────────────────────────────────────────────

    @app.context_processor
    def _ctx():
        ep = request.endpoint or ''
        page = ('players'  if ep.startswith('player')    else
                'register' if ep.startswith('register')  else
                'day'      if ep.startswith('day_')      else
                'calendar' if ep.startswith('calendar')  else
                'history'  if ep == 'history'            else
                'reports'  if ep == 'reports'            else
                'vouchers' if ep == 'vouchers'           else
                'email'    if ep.startswith('email')     else
                'sessions' if ep == 'sessions'           else
                'coaches'  if ep == 'coaches'            else
                'settings' if ep == 'settings'           else '')
        club = Setting.get('club_name', 'Club Training')
        return {
            'club_name':      club,
            'app_title':      (f'Club Training — {club}'
                               if club and club != 'Club Training'
                               else 'Club Training'),
            'club_icon_href': url_for('branding_icon') + '?v='
                              + Setting.get('club_icon_ver', '0'),
            'club_icon_is_bundled':
                Setting.get('club_icon_type', 'bundled') == 'bundled',
            'today':          date.today(),
            'active_page':    page,
            'testing_mode':   Setting.get('testing_mode', '0') == '1',
            'groups_enabled': Setting.get('groups_enabled', '1') == '1',
            'email_sending_enabled': Setting.get('email_sending_enabled', '0') == '1',
            'email_fields_enabled':  Setting.get('email_fields_enabled', '1') == '1',
            'coach_tracking_mode':   Setting.get('coach_tracking_mode', 'simple'),
        }

    # ── Branding (club icon) ──────────────────────────────────────────

    @app.route('/api/branding/icon')
    def branding_icon():
        from flask import Response
        ver  = Setting.get('club_icon_ver', '0')
        etag = f'"icon-{ver}"'
        if request.headers.get('If-None-Match') == etag:
            return Response(status=304, headers={'ETag': etag})
        if Setting.get('club_icon_type', 'bundled') == 'custom':
            try:
                blob = base64.b64decode(Setting.get('club_icon_blob', ''))
            except Exception:
                blob = b''
            if blob:
                return Response(blob,
                                mimetype=Setting.get('club_icon_mime', 'image/png'),
                                headers={'ETag': etag,
                                         'Cache-Control': 'max-age=3600'})
        key = Setting.get('club_icon_key', 'badminton')
        if key not in {k for k, _ in BUNDLED_ICONS}:
            key = 'badminton'
        path = os.path.join(app.static_folder, 'icons', 'sports', f'{key}.svg')
        with open(path, 'rb') as f:
            return Response(f.read(), mimetype='image/svg+xml',
                            headers={'ETag': etag, 'Cache-Control': 'max-age=3600'})

    # ── Home → redirect to today's day view ──────────────────────────

    @app.route('/')
    def home():
        return redirect(url_for('day_view', date_iso=date.today().isoformat()))

    # ── Day view ──────────────────────────────────────────────────────

    @app.route('/day/<date_iso>')
    def day_view(date_iso):
        try:
            d = date.fromisoformat(date_iso)
        except ValueError:
            return redirect(url_for('home'))

        session_dates  = (SessionDate.query.filter_by(date=d)
                          .order_by(SessionDate.session_id).all())
        all_templates  = (SessionTemplate.query.filter_by(active=True)
                          .order_by(SessionTemplate.day_of_week,
                                    SessionTemplate.start_time).all())
        used_ids       = {sd.session_id for sd in session_dates}
        prev_day       = (d - timedelta(days=1)).isoformat()
        next_day       = (d + timedelta(days=1)).isoformat()
        is_today       = d == date.today()
        is_future      = d > date.today()
        coaches        = Coach.query.filter_by(active=True).order_by(Coach.name).all()

        # Coach attendance map: ca_map[sd.id][coach.id] = CoachAttendance row
        sd_ids = [sd.id for sd in session_dates]
        ca_map = {sid: {} for sid in sd_ids}
        if sd_ids:
            for ca in CoachAttendance.query.filter(
                    CoachAttendance.session_date_id.in_(sd_ids)).all():
                ca_map[ca.session_date_id][ca.coach_id] = ca
        session_pay_totals = {
            sid: round(sum(ca.net_amount for ca in cas.values()))
            for sid, cas in ca_map.items()}

        return render_template('day/view.html',
                               d=d, session_dates=session_dates,
                               all_templates=all_templates,
                               used_ids=used_ids,
                               prev_day=prev_day, next_day=next_day,
                               is_today=is_today, is_future=is_future,
                               coaches=coaches, ca_map=ca_map,
                               session_pay_totals=session_pay_totals,
                               month_finalised=_coach_month_finalised(d.year, d.month),
                               PAYMENT_COLORS=PAYMENT_COLORS)

    @app.route('/api/coach-attendance', methods=['POST'])
    def api_coach_attendance():
        """Instant coach mark/unmark (and hours edit) for one session occurrence.
        Body: {sd_id, coach_id, present, hours?, force?}"""
        if _coach_mode() == 'off':
            return jsonify({'ok': False, 'error': 'Coach tracking is turned off.'})
        data     = request.get_json()
        sd       = SessionDate.query.get_or_404(int(data['sd_id']))
        coach    = Coach.query.get_or_404(int(data['coach_id']))
        present  = bool(data.get('present'))

        if (_coach_month_finalised(sd.date.year, sd.date.month)
                and not data.get('force')):
            return jsonify({'ok': False, 'needs_confirm': True, 'error':
                f'{sd.date.strftime("%B %Y")} coach payments are finalised. '
                'Change anyway?'})

        ca = CoachAttendance.query.filter_by(
            session_date_id=sd.id, coach_id=coach.id).first()
        if not present:
            if ca:
                db.session.delete(ca)
        else:
            hours = data.get('hours')
            if hours is not None:
                try:
                    hours = max(0.0, float(hours))
                except (TypeError, ValueError):
                    hours = None
            if ca:
                # Hours edit — keep the ORIGINAL snapshot, recompute amount
                if ca.basis_snapshot == 'hour' and hours is not None:
                    ca.hours  = hours
                    ca.amount = round(float(ca.rate_snapshot or 0) * hours, 2)
            else:
                amount, h = _coach_pay_amount(coach, sd.template, hours)
                ca = CoachAttendance(
                    session_date_id=sd.id, coach_id=coach.id, hours=h,
                    rate_snapshot=coach.pay_rate, basis_snapshot=coach.pay_basis,
                    amount=amount)
                db.session.add(ca)
        db.session.commit()

        total = round(sum(
            row.net_amount for row in
            CoachAttendance.query.filter_by(session_date_id=sd.id).all()))
        return jsonify({
            'ok': True,
            'present': present and ca is not None,
            'hours': float(ca.hours) if (present and ca and ca.hours is not None) else None,
            'amount': round(ca.net_amount) if (present and ca) else 0,
            'session_total': total,
        })

    @app.route('/day/<date_iso>/plan')
    def day_plan(date_iso):
        try:
            d = date.fromisoformat(date_iso)
        except ValueError:
            return redirect(url_for('home'))
        session_dates  = SessionDate.query.filter_by(date=d).all()
        all_templates  = (SessionTemplate.query.filter_by(active=True)
                          .order_by(SessionTemplate.day_of_week,
                                    SessionTemplate.start_time).all())
        used_ids       = {sd.session_id for sd in session_dates}
        is_today       = d == date.today()
        return render_template('day/plan.html',
                               d=d, all_templates=all_templates,
                               used_ids=used_ids, is_today=is_today)

    @app.route('/day/<date_iso>/setup', methods=['POST'])
    def day_setup(date_iso):
        try:
            d = date.fromisoformat(date_iso)
        except ValueError:
            return redirect(url_for('home'))

        session_ids = request.form.getlist('session_ids')
        new_sds = []
        for sid_str in session_ids:
            try:
                sid = int(sid_str)
            except ValueError:
                continue
            if SessionDate.query.filter_by(session_id=sid, date=d).first():
                continue
            group_ids = request.form.getlist(f'groups_{sid}')
            gids_json = json.dumps([int(g) for g in group_ids]) if group_ids else None
            sd = SessionDate(session_id=sid, date=d, active_group_ids=gids_json)
            db.session.add(sd)
            new_sds.append(sd)

        if new_sds:
            db.session.commit()
        else:
            flash('No new sessions to add.', 'warning')
            return redirect(url_for('day_view', date_iso=date_iso))
        return redirect(url_for('day_checkin', date_iso=date_iso))

    @app.route('/day/<date_iso>/reset', methods=['POST'])
    def day_reset(date_iso):
        """Delete all sessions for a date (for testing — resets to plan page)."""
        try:
            d = date.fromisoformat(date_iso)
        except ValueError:
            return redirect(url_for('home'))

        sds = SessionDate.query.filter_by(date=d).all()
        for sd in sds:
            Attendance.query.filter_by(session_date_id=sd.id).delete()
            db.session.delete(sd)
        db.session.commit()
        flash(f'Day reset — all sessions for {d.strftime("%d %b %Y")} deleted.', 'warning')
        return redirect(url_for('day_plan', date_iso=date_iso))

    @app.route('/day/<date_iso>/summary')
    def day_summary(date_iso):
        """End-of-day reconciliation: kids, money to count, vouchers, coaches."""
        try:
            d = date.fromisoformat(date_iso)
        except ValueError:
            return redirect(url_for('home'))

        session_dates = (SessionDate.query.filter_by(date=d)
                         .order_by(SessionDate.session_id).all())

        # Coach → list of session names they coached today
        coach_map = OrderedDict()
        for sd in session_dates:
            for ca in sorted(sd.coach_attendance, key=lambda x: x.coach.name):
                coach_map.setdefault(ca.coach.name, []).append(sd.template.name)

        day_totals = {
            'kids':  sum(sd.total_attending for sd in session_dates),
            'cash':  sum(sd.total_cash for sd in session_dates),
            'card':  sum(sd.total_card for sd in session_dates),
            'by_type': defaultdict(int),
        }
        for sd in session_dates:
            for pt, cnt in sd.payment_summary.items():
                day_totals['by_type'][pt] += cnt
        day_totals['by_type'] = dict(day_totals['by_type'])

        return render_template('day/summary.html',
                               d=d, session_dates=session_dates,
                               coach_map=coach_map, day_totals=day_totals,
                               PAYMENT_TYPES=PAYMENT_TYPES,
                               PAYMENT_COLORS=PAYMENT_COLORS)

    # ── Calendar ──────────────────────────────────────────────────────

    @app.route('/calendar')
    @app.route('/calendar/<int:year>/<int:month>')
    def calendar_view(year=None, month=None):
        today = date.today()
        if year is None:
            year, month = today.year, today.month

        weeks = _cal_mod.Calendar(firstweekday=0).monthdatescalendar(year, month)

        first = date(year, month, 1)
        last  = date(year + (month // 12), (month % 12) + 1, 1) - timedelta(days=1)

        sds = (SessionDate.query
               .filter(SessionDate.date >= first, SessionDate.date <= last)
               .all())
        day_map = {}
        for sd in sds:
            day_map.setdefault(sd.date, []).append(sd)

        prev_year  = year - 1 if month == 1  else year
        prev_month = 12       if month == 1  else month - 1
        next_year  = year + 1 if month == 12 else year
        next_month = 1        if month == 12 else month + 1

        return render_template('calendar.html',
                               year=year, month=month,
                               month_name=_cal_mod.month_name[month],
                               weeks=weeks, day_map=day_map, today=today,
                               prev_year=prev_year, prev_month=prev_month,
                               next_year=next_year, next_month=next_month)

    # ── Players ──────────────────────────────────────────────────────

    @app.route('/players')
    def players():
        q           = request.args.get('q', '').strip()
        session_id  = request.args.get('session_id', '')
        group_id    = request.args.get('group_id', '')
        show_inactive = request.args.get('inactive') == '1'

        query = Player.query
        if not show_inactive:
            query = query.filter_by(active=True)
        if q:
            query = query.filter(Player.name.ilike(f'%{q}%'))
        if session_id:
            query = query.filter_by(default_session_id=int(session_id))
        if group_id:
            query = query.filter_by(default_group_id=int(group_id))

        player_list     = query.order_by(Player.name).all()
        sessions        = (SessionTemplate.query.filter_by(active=True)
                           .order_by(SessionTemplate.day_of_week).all())
        all_groups      = (Group.query.join(SessionTemplate)
                           .filter(SessionTemplate.active == True, Group.active == True)
                           .order_by(SessionTemplate.name, Group.sort_order).all())
        all_active_players = (Player.query.filter_by(active=True)
                              .order_by(Player.name).all())

        last_attendance_map = {}
        for a, sd_row in (db.session.query(Attendance, SessionDate)
                          .join(SessionDate, Attendance.session_date_id == SessionDate.id)
                          .order_by(SessionDate.date.desc())
                          .all()):
            if a.player_id not in last_attendance_map:
                last_attendance_map[a.player_id] = {
                    'date':         sd_row.date,
                    'session_name': sd_row.template.name,
                    'group_name':   a.group.name if a.group else None,
                }

        # For the Add Player duplicate warning (includes inactive players)
        all_player_names = [n for (n,) in db.session.query(Player.name).all()]

        # Active players not seen in over a year (never-attended players count
        # from when they were added) — offered for bulk mark-inactive.
        cutoff = date.today() - timedelta(days=365)
        stale_players = []
        for p in Player.query.filter_by(active=True).all():
            last = last_attendance_map.get(p.id)
            if last:
                if last['date'] < cutoff:
                    stale_players.append((p, last['date']))
            elif p.created_at and p.created_at.date() < cutoff:
                stale_players.append((p, None))
        stale_players.sort(key=lambda t: t[0].name.lower())

        return render_template('players/list.html',
                               players=player_list, sessions=sessions, all_groups=all_groups,
                               all_active_players=all_active_players,
                               all_player_names=all_player_names,
                               stale_players=stale_players,
                               manage_players=Player.query.order_by(Player.name).all(),
                               last_attendance_map=last_attendance_map,
                               field_cfg=_player_field_settings(),
                               q=q, session_id=session_id, group_id=group_id,
                               show_inactive=show_inactive)

    @app.route('/players/mark-inactive', methods=['POST'])
    def players_mark_inactive():
        """Bulk-deactivate players who haven't attended in over a year."""
        ids = [int(x) for x in request.form.getlist('player_ids') if x.isdigit()]
        count = 0
        for p in Player.query.filter(Player.id.in_(ids)).all() if ids else []:
            if p.active:
                p.active = False
                count += 1
        db.session.commit()
        flash(f'{count} player{"s" if count != 1 else ""} marked inactive. '
              'They keep their history and can be reactivated any time via Edit.', 'success')
        return redirect(url_for('players'))

    @app.route('/players/merge', methods=['POST'])
    def players_merge():
        """Merge a duplicate player into a keeper: move attendance, vouchers
        and sibling links across, fill in the keeper's blank fields from the
        duplicate, then delete the duplicate."""
        keep_id   = request.form.get('keep_id', type=int)
        remove_id = request.form.get('remove_id', type=int)
        if not keep_id or not remove_id or keep_id == remove_id:
            flash('Pick two different players to merge.', 'danger')
            return redirect(url_for('players'))
        keep = db.session.get(Player, keep_id)
        rem  = db.session.get(Player, remove_id)
        if not keep or not rem:
            flash('Player not found.', 'danger')
            return redirect(url_for('players'))

        # Attendance: move across; where both attended the same session date,
        # keep the keeper's record and drop the duplicate's.
        keep_sds = {a.session_date_id for a in keep.attendance_records}
        moved_att, dropped_att = 0, 0
        for a in Attendance.query.filter_by(player_id=remove_id).all():
            if a.session_date_id in keep_sds:
                db.session.delete(a)
                dropped_att += 1
            else:
                a.player_id = keep_id
                moved_att += 1

        moved_vouchers = 0
        for v in Voucher.query.filter_by(player_id=remove_id).all():
            v.player_id = keep_id
            moved_vouchers += 1

        # Sibling links: re-point the duplicate's siblings at the keeper.
        rows = db.session.execute(sibling_links.select().where(
            (sibling_links.c.player_a_id == remove_id) |
            (sibling_links.c.player_b_id == remove_id))).fetchall()
        partners = {(r.player_a_id if r.player_b_id == remove_id else r.player_b_id) for r in rows}
        db.session.execute(sibling_links.delete().where(
            (sibling_links.c.player_a_id == remove_id) |
            (sibling_links.c.player_b_id == remove_id)))
        existing_partners = {s.id for s in keep.siblings}
        for pid in partners:
            if pid != keep_id and pid not in existing_partners:
                db.session.execute(sibling_links.insert().values(
                    player_a_id=keep_id, player_b_id=pid))

        # Fill the keeper's blanks from the duplicate; never overwrite.
        filled = []
        for f in ('date_of_birth', 'guardian_name', 'guardian_phone', 'guardian_email',
                  'address', 'own_email', 'own_phone', 'rego_number', 'membership_type',
                  'membership_status', 'default_session_id', 'default_group_id'):
            if not getattr(keep, f) and getattr(rem, f):
                setattr(keep, f, getattr(rem, f))
                filled.append(f)
        if rem.notes and rem.notes != keep.notes:
            keep.notes = f'{keep.notes} | {rem.notes}' if keep.notes else rem.notes
        keep.active = keep.active or rem.active

        removed_name = rem.name
        db.session.flush()
        db.session.delete(rem)
        db.session.commit()

        msg = (f'Merged "{removed_name}" into "{keep.name}": moved {moved_att} attendance '
               f'record{"s" if moved_att != 1 else ""}')
        if dropped_att:
            msg += f' ({dropped_att} duplicate same-day record{"s" if dropped_att != 1 else ""} dropped)'
        if moved_vouchers:
            msg += f', {moved_vouchers} voucher{"s" if moved_vouchers != 1 else ""}'
        if filled:
            msg += f', filled in {len(filled)} blank field{"s" if len(filled) != 1 else ""}'
        flash(msg + '.', 'success')
        return redirect(url_for('player_detail', pid=keep_id))

    @app.route('/players/delete', methods=['POST'])
    def players_delete():
        """Permanently delete a player and ALL their history. Irreversible
        (apart from the daily backups) — meant for junk/mistake entries."""
        pid = request.form.get('player_id', type=int)
        p = db.session.get(Player, pid) if pid else None
        if not p:
            flash('Player not found.', 'danger')
            return redirect(url_for('players'))
        name = p.name
        n_att = Attendance.query.filter_by(player_id=pid).count()
        vouchers = Voucher.query.filter_by(player_id=pid).all()
        for v in vouchers:
            Attendance.query.filter_by(voucher_id=v.id).update(
                {'voucher_id': None}, synchronize_session=False)
            db.session.delete(v)
        db.session.execute(sibling_links.delete().where(
            (sibling_links.c.player_a_id == pid) |
            (sibling_links.c.player_b_id == pid)))
        db.session.delete(p)   # attendance cascades with the player
        db.session.commit()
        flash(f'Permanently deleted "{name}" ({n_att} attendance record{"s" if n_att != 1 else ""}, '
              f'{len(vouchers)} voucher{"s" if len(vouchers) != 1 else ""}). '
              'If this was a mistake, restore from a backup in the backups folder.', 'warning')
        return redirect(url_for('players'))

    @app.route('/players/add', methods=['POST'])
    def players_add():
        dob_str = request.form.get('date_of_birth', '').strip()
        p = Player(
            name=request.form['name'].strip(),
            date_of_birth=date.fromisoformat(dob_str) if dob_str else None,
            category=request.form.get('category', 'Junior'),
            guardian_name=request.form.get('guardian_name', '').strip(),
            guardian_phone=request.form.get('guardian_phone', '').strip(),
            guardian_email=request.form.get('guardian_email', '').strip(),
            address=request.form.get('address', '').strip() or None,
            own_email=request.form.get('own_email', '').strip() or None,
            own_phone=request.form.get('own_phone', '').strip() or None,
            default_session_id=_int(request.form.get('session_id')),
            default_group_id=_int(request.form.get('group_id')),
            notes=request.form.get('notes', '').strip(),
        )
        db.session.add(p)
        db.session.flush()
        _save_siblings(p.id, request.form.getlist('sibling_ids'))
        db.session.commit()
        flash(f'{p.name} added.', 'success')
        return redirect(url_for('players'))

    @app.route('/players/import', methods=['GET', 'POST'])
    def players_import():
        if request.method == 'POST':
            file = request.files.get('csv_file')
            if not file or not file.filename:
                flash('Choose a CSV or Excel file first.', 'danger')
                return redirect(url_for('players_import'))

            rows = _read_tabular_rows(file)
            if not rows:
                flash('That file appears to be empty.', 'danger')
                return redirect(url_for('players_import'))

            # Flexible header matching — case/space-insensitive. A full "name"
            # column OR separate given/surname columns both work.
            field_map = {
                'name':      {'name', 'full name', 'player', 'player name'},
                'given':     {'given', 'given name', 'first', 'first name'},
                'surname':   {'surname', 'last name', 'family name', 'last'},
                'sv':        {'sv', 'sports voucher', 'voucher'},
                'age':       {'age'},
                'category':  {'category', 'junior/senior', 'type'},
                'address':   {'address'},
                'own_email': {'own email', 'player email'},
                'own_phone': {'own phone', 'player phone'},
                'guardian_name':  {'guardian', 'guardian name', 'parent', 'parent name'},
                'guardian_phone': {'guardian phone', 'phone', 'contact', 'guardian contact'},
                'guardian_email': {'guardian email', 'email'},
                'rego':              {'rego', 'rego #', 'rego number', 'registration', 'member #', 'member number'},
                'membership_type':   {'mbshp type', 'membership type'},
                'membership_status': {'status', 'membership status'},
            }
            header_cells = [str(h or '').strip().lower().replace('_', ' ') for h in rows[0]]
            col = {}
            for field, aliases in field_map.items():
                for j, h in enumerate(header_cells):
                    if h in aliases:
                        col[field] = j
                        break
            # Email columns are ignored entirely when email fields are off
            # (Settings → Email), so imports can't sneak addresses back in.
            if Setting.get('email_fields_enabled', '1') != '1':
                col.pop('own_email', None)
                col.pop('guardian_email', None)

            if 'name' not in col and not ('given' in col or 'surname' in col):
                flash('Could not find a name column (looked for "name" or "given"/"surname" headers).', 'danger')
                return redirect(url_for('players_import'))

            def cell(row, field):
                j = col.get(field)
                if j is None or j >= len(row) or row[j] is None:
                    return ''
                v = str(row[j]).strip()
                return v[:-2] if v.endswith('.0') else v

            # ── Membership-register mode ─────────────────────────────
            # A file with Rego/Membership columns (e.g. the club's member
            # export) UPDATES matched players in place and ADDS unmatched
            # members as new players, rather than skipping existing names.
            if 'rego' in col or 'membership_type' in col:
                find_player, fuzzy_notes = _build_player_matcher(Player.query.all())
                updated, added, skipped = 0, 0, 0
                for row in rows[1:]:
                    name = _clean_person_name(
                        cell(row, 'name') or f"{cell(row, 'given')} {cell(row, 'surname')}")
                    if not name:
                        skipped += 1
                        continue
                    rego    = cell(row, 'rego') or None
                    mtype   = cell(row, 'membership_type') or None
                    mstatus = cell(row, 'membership_status') or None
                    p = find_player(name)
                    if p:
                        p.rego_number       = rego or p.rego_number
                        p.membership_type   = mtype or p.membership_type
                        p.membership_status = mstatus or p.membership_status
                        updated += 1
                    else:
                        # Tidy SHOUTING surnames from the register (KIM ATKINS → Kim Atkins)
                        display = ' '.join(w.title() if w.isupper() and len(w) > 1 else w
                                           for w in name.split())
                        db.session.add(Player(
                            name=display,
                            category='Junior' if (mtype or '').lower() == 'junior' else 'Senior',
                            rego_number=rego, membership_type=mtype, membership_status=mstatus,
                        ))
                        added += 1
                db.session.commit()
                msg = (f'Membership register: updated {updated} existing player'
                       f'{"s" if updated != 1 else ""}, added {added} new member'
                       f'{"s" if added != 1 else ""} as players.')
                if skipped:
                    msg += f' {skipped} row{"s" if skipped != 1 else ""} skipped (missing name).'
                if fuzzy_notes:
                    msg += (f' {len(fuzzy_notes)} matched by name similarity — please check: '
                            + '; '.join(sorted(set(fuzzy_notes))) + '.')
                flash(msg, 'success')
                return redirect(url_for('players'))

            added, skipped = 0, 0
            duplicates = []
            existing_names = {n.lower() for (n,) in db.session.query(Player.name).all()}
            today = date.today()
            for row in rows[1:]:
                name = _clean_person_name(
                    cell(row, 'name') or f"{cell(row, 'given')} {cell(row, 'surname')}")
                if not name:
                    skipped += 1
                    continue
                if name.lower() in existing_names:
                    duplicates.append(name)
                    continue
                existing_names.add(name.lower())

                dob = None
                age_str = cell(row, 'age')
                if age_str:
                    try:
                        dob = today.replace(year=today.year - int(float(age_str)))
                    except (ValueError, TypeError):
                        pass

                category = cell(row, 'category').capitalize()
                if category not in ('Junior', 'Senior'):
                    category = 'Junior'

                notes = 'Sports Voucher' if cell(row, 'sv').lower() in ('y', 'yes', '1', 'true') else None

                db.session.add(Player(
                    name=name,
                    date_of_birth=dob,
                    category=category,
                    notes=notes,
                    address=cell(row, 'address') or None,
                    own_email=cell(row, 'own_email') or None,
                    own_phone=cell(row, 'own_phone') or None,
                    guardian_name=cell(row, 'guardian_name') or None,
                    guardian_phone=cell(row, 'guardian_phone') or None,
                    guardian_email=cell(row, 'guardian_email') or None,
                ))
                added += 1

            db.session.commit()
            msg = f'{added} player{"s" if added != 1 else ""} imported.'
            if skipped:
                msg += f' {skipped} row{"s" if skipped != 1 else ""} skipped (missing name).'
            if duplicates:
                shown = ', '.join(duplicates[:8]) + ('…' if len(duplicates) > 8 else '')
                msg += (f' {len(duplicates)} skipped as already in the database: {shown} '
                        '(add them individually via + Add Player if they really are different people).')
            flash(msg, 'success' if added else 'warning')
            return redirect(url_for('players'))

        return render_template('players/import.html')

    @app.route('/players/<int:pid>')
    def player_detail(pid):
        p      = Player.query.get_or_404(pid)
        recent = (Attendance.query.filter_by(player_id=pid)
                  .join(SessionDate)
                  .order_by(SessionDate.date.desc())
                  .limit(25).all())

        cutoff_3mo = date.today() - timedelta(days=90)
        recent_3mo = (Attendance.query.filter_by(player_id=pid)
                      .join(SessionDate)
                      .filter(SessionDate.date >= cutoff_3mo)
                      .order_by(SessionDate.date.desc()).all())

        last_year       = date.today().year - 1
        last_year_count = (Attendance.query.filter_by(player_id=pid)
                           .join(SessionDate)
                           .filter(db.extract('year', SessionDate.date) == last_year)
                           .count())

        return render_template('players/detail.html', player=p, recent=recent,
                               recent_3mo=recent_3mo,
                               last_year=last_year, last_year_count=last_year_count,
                               field_cfg=_player_field_settings(),
                               PAYMENT_COLORS=PAYMENT_COLORS)

    @app.route('/players/<int:pid>/edit', methods=['GET', 'POST'])
    def player_edit(pid):
        p          = Player.query.get_or_404(pid)
        sessions   = (SessionTemplate.query.filter_by(active=True)
                      .order_by(SessionTemplate.day_of_week).all())
        all_players = (Player.query
                       .filter(Player.active == True, Player.id != pid)
                       .order_by(Player.name).all())

        if request.method == 'POST':
            dob_str = request.form.get('date_of_birth', '').strip()
            p.name               = request.form['name'].strip()
            p.date_of_birth      = date.fromisoformat(dob_str) if dob_str else None
            p.category           = request.form.get('category', 'Junior')
            p.guardian_name      = request.form.get('guardian_name', '').strip()
            p.guardian_phone     = request.form.get('guardian_phone', '').strip()
            # Email inputs are absent from the form when email fields are
            # turned off — don't blank stored addresses in that case.
            if 'guardian_email' in request.form:
                p.guardian_email = request.form.get('guardian_email', '').strip()
            p.address            = request.form.get('address', '').strip() or None
            if 'own_email' in request.form:
                p.own_email      = request.form.get('own_email', '').strip() or None
            p.own_phone          = request.form.get('own_phone', '').strip() or None
            p.default_session_id = _int(request.form.get('session_id'))
            p.default_group_id   = _int(request.form.get('group_id'))
            p.notes              = request.form.get('notes', '').strip()
            p.active             = request.form.get('active') == 'on'

            db.session.execute(sibling_links.delete().where(
                (sibling_links.c.player_a_id == pid) |
                (sibling_links.c.player_b_id == pid)
            ))
            db.session.flush()
            _save_siblings(pid, request.form.getlist('sibling_ids'))
            db.session.commit()
            flash(f'{p.name} updated.', 'success')
            return redirect(url_for('player_detail', pid=pid))

        groups = (Group.query.filter_by(session_id=p.default_session_id, active=True).all()
                  if p.default_session_id else [])
        current_sib_ids = [s.id for s in p.siblings]
        return render_template('players/edit.html',
                               player=p, sessions=sessions, groups=groups,
                               all_players=all_players, current_sib_ids=current_sib_ids,
                               field_cfg=_player_field_settings())

    # ── Sessions ─────────────────────────────────────────────────────

    @app.route('/sessions', methods=['GET', 'POST'])
    def sessions():
        if request.method == 'POST':
            action = request.form.get('action')

            if action == 'add':
                s = SessionTemplate(
                    name=request.form['name'].strip(),
                    day_of_week=int(request.form['day_of_week']),
                    start_time=request.form['start_time'],
                    end_time=request.form['end_time'],
                    price_cash=float(request.form.get('price_cash') or 0),
                    price_card=float(request.form.get('price_card') or 0),
                    category=request.form.get('category', 'Mixed'),
                )
                db.session.add(s)
                db.session.flush()
                db.session.add(Group(session_id=s.id, name='Group 1', sort_order=0))
                db.session.commit()
                flash(f'Session "{s.name}" added.', 'success')

            elif action == 'edit':
                s = SessionTemplate.query.get_or_404(int(request.form['session_id']))
                s.name         = request.form['name'].strip()
                s.day_of_week  = int(request.form['day_of_week'])
                s.start_time   = request.form['start_time']
                s.end_time     = request.form['end_time']
                s.price_cash   = float(request.form.get('price_cash') or 0)
                s.price_card   = float(request.form.get('price_card') or 0)
                s.category     = request.form.get('category', 'Mixed')
                db.session.commit()
                flash('Session updated.', 'success')

            elif action == 'save_groups':
                sid = int(request.form['session_id'])
                Group.query.filter_by(session_id=sid).delete()
                db.session.flush()
                for i, name in enumerate(request.form.getlist('group_name')):
                    name = name.strip()
                    if name:
                        db.session.add(Group(session_id=sid, name=name, sort_order=i))
                db.session.commit()
                flash('Groups saved.', 'success')

            elif action == 'deactivate':
                s = SessionTemplate.query.get_or_404(int(request.form['session_id']))
                s.active = False
                db.session.commit()
                flash('Session removed.', 'success')

            return redirect(url_for('sessions'))

        all_sessions = (SessionTemplate.query.filter_by(active=True)
                        .order_by(SessionTemplate.day_of_week, SessionTemplate.start_time).all())
        return render_template('sessions/list.html', sessions=all_sessions, day_names=DAY_NAMES)

    # ── Register ─────────────────────────────────────────────────────

    @app.route('/register')
    def register_select():
        return redirect(url_for('day_view', date_iso=date.today().isoformat()))

    @app.route('/register/start', methods=['POST'])
    def register_start():
        session_id = int(request.form['session_id'])
        reg_date   = date.fromisoformat(request.form['date'])
        existing   = SessionDate.query.filter_by(session_id=session_id, date=reg_date).first()
        if existing:
            return redirect(url_for('register_run', sd_id=existing.id))
        sd = SessionDate(session_id=session_id, date=reg_date)
        db.session.add(sd)
        db.session.commit()
        return redirect(url_for('register_run', sd_id=sd.id))

    # ── Day check-in desk (player-first workflow) ────────────────────

    @app.route('/day/<date_iso>/checkin')
    def day_checkin(date_iso):
        try:
            d = date.fromisoformat(date_iso)
        except ValueError:
            return redirect(url_for('home'))

        session_dates = (SessionDate.query
                         .filter_by(date=d, status='open')
                         .order_by(SessionDate.session_id).all())

        all_players = Player.query.filter_by(active=True).order_by(Player.name).all()

        # Map player_id → attendance info for today
        attendance_map = {}
        for sd in session_dates:
            for a in sd.attendance:
                attendance_map[a.player_id] = {
                    'sd_id':        sd.id,
                    'session_name': sd.template.name,
                    'group_id':     a.group_id,
                    'group_name':   a.group.name if a.group else None,
                    'payment_type': a.payment_type,
                    'amount':       float(a.amount or 0),
                    'voucher_id':   a.voucher_id,
                }

        # Players who attended within the last 3 months → prioritised in the waiting list
        cutoff = d - timedelta(days=90)
        recent_ids = {
            pid for (pid,) in db.session.query(Attendance.player_id)
                .join(SessionDate, Attendance.session_date_id == SessionDate.id)
                .filter(SessionDate.date < d, SessionDate.date >= cutoff)
                .distinct()
        }

        checked_players = [p for p in all_players if p.id in attendance_map]
        waiting_players = [p for p in all_players if p.id not in attendance_map]
        waiting_players.sort(key=lambda p: (p.id not in recent_ids, p.name.lower()))

        # Map player_id → most recent past session/group attended (for reference only)
        last_attendance_map = {}
        past = (db.session.query(Attendance, SessionDate)
                .join(SessionDate, Attendance.session_date_id == SessionDate.id)
                .filter(SessionDate.date < d)
                .order_by(SessionDate.date.desc())
                .all())
        for a, sd_row in past:
            if a.player_id not in last_attendance_map:
                last_attendance_map[a.player_id] = {
                    'session_name': sd_row.template.name,
                    'group_name':   a.group.name if a.group else None,
                }

        # Sessions data for JS modal (no group options when groups are disabled)
        use_groups = Setting.get('groups_enabled', '1') == '1'
        sessions_js = [
            {
                'sd_id':       sd.id,
                'name':        sd.template.name,
                'price_cash':  int(round(float(sd.template.price_cash or 0))),
                'price_card':  int(round(float(sd.template.price_card or 0))),
                'groups':      [{'id': g.id, 'name': g.name}
                                for g in sd.day_active_groups] if use_groups else [],
            }
            for sd in session_dates
        ]

        return render_template('day/checkin.html',
                               d=d,
                               session_dates=session_dates,
                               checked_players=checked_players,
                               waiting_players=waiting_players,
                               attendance_map=attendance_map,
                               recent_ids=recent_ids,
                               last_attendance_map=last_attendance_map,
                               sessions_js=json.dumps(sessions_js),
                               PAYMENT_TYPES=PAYMENT_TYPES,
                               AMOUNT_TYPES=list(AMOUNT_TYPES),
                               PAYMENT_COLORS=PAYMENT_COLORS,
                               DEFAULT_VOUCHER_AMOUNT=_voucher_defaults()['amount'],
                               DEFAULT_VOUCHER_SESSIONS=_voucher_defaults()['sessions'],
                               square_configured=_square_configured(),
                               field_cfg=_player_field_settings())

    @app.route('/register/<int:sd_id>/select', methods=['GET', 'POST'])
    def register_select_players(sd_id):
        sd = SessionDate.query.get_or_404(sd_id)
        if sd.status == 'closed':
            return redirect(url_for('register_detail', sd_id=sd_id))

        tmpl = sd.template

        if request.method == 'POST':
            selected_ids = {int(x) for x in request.form.getlist('player_ids')}
            existing_ids = {a.player_id for a in sd.attendance}
            active_gids  = {g.id for g in sd.day_active_groups}

            # Add newly selected players with Cash default
            for pid in selected_ids - existing_ids:
                p = Player.query.get(pid)
                if not p:
                    continue
                gid = p.default_group_id if p.default_group_id in active_gids else None
                db.session.add(Attendance(
                    session_date_id=sd_id, player_id=pid,
                    group_id=gid,
                    payment_type='Cash',
                    amount=float(tmpl.price_cash or 0),
                ))

            # Remove deselected players (only if not yet edited past default)
            for pid in existing_ids - selected_ids:
                Attendance.query.filter_by(session_date_id=sd_id, player_id=pid).delete()

            db.session.commit()
            return redirect(url_for('register_run', sd_id=sd_id))

        regulars     = (Player.query.filter_by(active=True, default_session_id=tmpl.id)
                        .order_by(Player.name).all())
        regular_ids  = {p.id for p in regulars}
        others       = (Player.query.filter_by(active=True)
                        .filter(~Player.id.in_(regular_ids))
                        .order_by(Player.name).all())
        attending_ids = {a.player_id for a in sd.attendance}

        return render_template('register/select_players.html',
                               sd=sd, tmpl=tmpl,
                               regulars=regulars, others=others,
                               attending_ids=attending_ids,
                               day_groups=sd.day_active_groups)

    @app.route('/register/<int:sd_id>')
    def register_run(sd_id):
        sd = SessionDate.query.get_or_404(sd_id)
        if sd.status == 'closed':
            return redirect(url_for('register_detail', sd_id=sd_id))

        tmpl    = sd.template
        regular = (Player.query
                   .filter_by(active=True, default_session_id=tmpl.id)
                   .order_by(Player.name).all())

        # Walk-ins: checked in but not regular members of this session
        regular_ids   = {p.id for p in regular}
        checked_in_ids = {a.player_id for a in sd.attendance}
        walkin_ids    = checked_in_ids - regular_ids
        walkins       = Player.query.filter(Player.id.in_(walkin_ids)).all() if walkin_ids else []

        # Other players available to add as walk-ins
        all_player_ids = regular_ids | walkin_ids
        others = (Player.query.filter_by(active=True)
                  .filter(~Player.id.in_(all_player_ids))
                  .order_by(Player.name).all())

        attendance_map = {a.player_id: a for a in sd.attendance}
        coaches        = Coach.query.filter_by(active=True).order_by(Coach.name).all()
        coach_ids      = {ca.coach_id for ca in
                          CoachAttendance.query.filter_by(session_date_id=sd.id).all()}

        return render_template('register/run.html',
                               sd=sd, tmpl=tmpl,
                               players=regular + walkins,
                               others=others,
                               attendance_map=attendance_map,
                               coaches=coaches, coach_ids=coach_ids,
                               totals=_totals(sd),
                               day_groups=sd.day_active_groups,
                               PAYMENT_TYPES=PAYMENT_TYPES,
                               AMOUNT_TYPES=list(AMOUNT_TYPES),
                               PAYMENT_COLORS=PAYMENT_COLORS)

    @app.route('/register/<int:sd_id>/checkin', methods=['POST'])
    def register_checkin(sd_id):
        sd = SessionDate.query.get_or_404(sd_id)
        if sd.status == 'closed':
            return jsonify({'ok': False, 'error': 'Session is closed.'})

        data         = request.get_json()
        player_id    = int(data['player_id'])
        payment_type = data.get('payment_type', 'Cash')
        amount       = float(data.get('amount') or 0)
        group_id     = _int(data.get('group_id'))
        voucher_id   = _int(data.get('voucher_id'))

        rec = Attendance.query.filter_by(session_date_id=sd_id, player_id=player_id).first()

        if payment_type == 'Sports Voucher':
            already_id = rec.voucher_id if rec else None
            if voucher_id:
                voucher = Voucher.query.filter_by(id=voucher_id, player_id=player_id).first()
                if not voucher:
                    return jsonify({'ok': False, 'error': 'Voucher not found for this player.'})
            else:
                # No specific voucher chosen (e.g. checked in from a page without a
                # voucher picker) — fall back to the oldest voucher with sessions left.
                voucher = None
                for v in (Voucher.query.filter_by(player_id=player_id)
                          .order_by(Voucher.date_issued).all()):
                    eff_remaining = v.sessions_remaining + (1 if v.id == already_id else 0)
                    if eff_remaining > 0:
                        voucher = v
                        break
                if not voucher:
                    return jsonify({'ok': False, 'error':
                        'No Sports Voucher on file with sessions remaining for this child. '
                        'Register one on the Vouchers page.'})
                voucher_id = voucher.id

            already_this_voucher = rec is not None and rec.voucher_id == voucher_id
            effective_remaining = voucher.sessions_remaining + (1 if already_this_voucher else 0)
            if effective_remaining <= 0:
                return jsonify({'ok': False, 'error': 'That voucher has no sessions remaining.'})
        else:
            voucher_id = None

        if rec:
            rec.payment_type = payment_type
            rec.amount       = amount
            rec.group_id     = group_id
            rec.voucher_id   = voucher_id
        else:
            db.session.add(Attendance(
                session_date_id=sd_id, player_id=player_id,
                group_id=group_id, payment_type=payment_type, amount=amount,
                voucher_id=voucher_id,
            ))
        db.session.commit()
        db.session.refresh(sd)
        return jsonify({'ok': True, 'totals': _totals(sd)})

    @app.route('/register/<int:sd_id>/undo', methods=['POST'])
    def register_undo(sd_id):
        sd = SessionDate.query.get_or_404(sd_id)
        if sd.status == 'closed':
            return jsonify({'ok': False, 'error': 'Session is closed.'})
        data = request.get_json()
        Attendance.query.filter_by(session_date_id=sd_id,
                                   player_id=int(data['player_id'])).delete()
        db.session.commit()
        db.session.refresh(sd)
        return jsonify({'ok': True, 'totals': _totals(sd)})

    @app.route('/register/<int:sd_id>/coaches', methods=['POST'])
    def register_coaches(sd_id):
        sd = SessionDate.query.get_or_404(sd_id)
        if _coach_month_finalised(sd.date.year, sd.date.month):
            flash(f'{sd.date.strftime("%B %Y")} coach payments are finalised — '
                  'edit coaches from the day page instead.', 'warning')
            return redirect(url_for('register_run', sd_id=sd_id))
        wanted = {int(c) for c in request.form.getlist('coach_ids') if c}
        existing = {ca.coach_id: ca for ca in
                    CoachAttendance.query.filter_by(session_date_id=sd.id).all()}
        for cid, ca in existing.items():
            if cid not in wanted:
                db.session.delete(ca)
        for cid in wanted - set(existing):
            coach = Coach.query.get(cid)
            if not coach:
                continue
            amount, hours = _coach_pay_amount(coach, sd.template)
            db.session.add(CoachAttendance(
                session_date_id=sd.id, coach_id=cid, hours=hours,
                rate_snapshot=coach.pay_rate, basis_snapshot=coach.pay_basis,
                amount=amount))
        db.session.commit()
        return redirect(url_for('register_run', sd_id=sd_id))

    @app.route('/register/<int:sd_id>/close', methods=['POST'])
    def register_close(sd_id):
        sd = SessionDate.query.get_or_404(sd_id)
        sd.status    = 'closed'
        sd.closed_at = datetime.utcnow()
        sd.notes     = request.form.get('notes', '').strip()
        db.session.commit()
        flash('Session closed and saved.', 'success')
        return redirect(url_for('register_detail', sd_id=sd_id))

    @app.route('/register/<int:sd_id>/detail')
    def register_detail(sd_id):
        sd = SessionDate.query.get_or_404(sd_id)
        return render_template('register/detail.html', sd=sd,
                               PAYMENT_TYPES=PAYMENT_TYPES,
                               PAYMENT_COLORS=PAYMENT_COLORS)

    @app.route('/register/<int:sd_id>/reopen', methods=['POST'])
    def register_reopen(sd_id):
        sd = SessionDate.query.get_or_404(sd_id)
        sd.status    = 'open'
        sd.closed_at = None
        db.session.commit()
        flash('Session reopened.', 'info')
        return redirect(url_for('register_run', sd_id=sd_id))

    @app.route('/register/<int:sd_id>/delete', methods=['POST'])
    def register_delete(sd_id):
        sd = SessionDate.query.get_or_404(sd_id)
        db.session.delete(sd)
        db.session.commit()
        flash('Session record deleted.', 'warning')
        return redirect(url_for('history'))

    # ── History ──────────────────────────────────────────────────────

    @app.route('/history')
    def history():
        session_filter = request.args.get('session_id', '')
        months         = request.args.get('months', 3, type=int)
        start          = date.today() - timedelta(days=months * 30)

        q = SessionDate.query.filter(SessionDate.date >= start)
        if session_filter:
            q = q.filter_by(session_id=int(session_filter))
        dates    = q.order_by(SessionDate.date.desc()).all()
        sessions = SessionTemplate.query.order_by(SessionTemplate.day_of_week).all()

        return render_template('history.html',
                               dates=dates, sessions=sessions,
                               session_filter=session_filter, months=months,
                               PAYMENT_COLORS=PAYMENT_COLORS)

    # ── Sports Vouchers ──────────────────────────────────────────────

    @app.route('/vouchers', methods=['GET', 'POST'])
    def vouchers():
        if request.method == 'POST':
            action = request.form.get('action')
            if action == 'add':
                player_id   = int(request.form['player_id'])
                voucher_num = request.form.get('voucher_number', '').strip() or None
                amount      = float(request.form.get('amount') or _voucher_defaults()['amount'])
                sessions    = int(request.form.get('sessions_total') or _voucher_defaults()['sessions'])
                issued_str  = request.form.get('date_issued') or date.today().isoformat()
                issued_date = date.fromisoformat(issued_str)
                notes       = request.form.get('notes', '').strip() or None
                limit_error = _voucher_limit_error(player_id, issued_date)
                if voucher_num and Voucher.query.filter(
                        db.func.lower(Voucher.voucher_number) == voucher_num.lower()).first():
                    limit_error = f'Voucher number "{voucher_num}" is already registered.'
                if limit_error:
                    flash(limit_error, 'danger')
                else:
                    db.session.add(Voucher(
                        player_id=player_id, voucher_number=voucher_num,
                        amount=amount, sessions_total=sessions,
                        date_issued=issued_date, notes=notes,
                    ))
                    db.session.commit()
                    flash('Voucher created.', 'success')
            elif action == 'delete':
                v = Voucher.query.get_or_404(int(request.form['voucher_id']))
                if v.sessions_used:
                    flash('Cannot delete a voucher that has already been used.', 'danger')
                else:
                    db.session.delete(v)
                    db.session.commit()
                    flash('Voucher deleted.', 'success')
            return redirect(url_for('vouchers', year=request.form.get('year', '')))

        year = request.args.get('year', date.today().year, type=int)
        voucher_list = (Voucher.query.join(Player)
                        .filter(db.extract('year', Voucher.date_issued) == year)
                        .order_by(Player.name, Voucher.date_issued).all())

        available_years = sorted({
            y for (y,) in db.session.query(db.extract('year', Voucher.date_issued)).distinct().all()
        }, reverse=True) or [date.today().year]

        active_players = Player.query.filter_by(active=True).order_by(Player.name).all()

        return render_template('vouchers.html',
                               voucher_list=voucher_list, year=year, available_years=available_years,
                               active_players=active_players,
                               DEFAULT_VOUCHER_AMOUNT=_voucher_defaults()['amount'],
                               DEFAULT_VOUCHER_SESSIONS=_voucher_defaults()['sessions'])

    @app.route('/vouchers/<int:voucher_id>/pdf')
    def voucher_pdf(voucher_id):
        import io
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.units import mm
        from reportlab.lib import colors
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
        from flask import send_file

        v = Voucher.query.get_or_404(voucher_id)
        p = v.player
        usage = (Attendance.query.filter_by(voucher_id=v.id)
                 .join(SessionDate)
                 .order_by(SessionDate.date).all())

        buf    = io.BytesIO()
        doc    = SimpleDocTemplate(buf, pagesize=A4, topMargin=20 * mm, bottomMargin=20 * mm)
        styles = getSampleStyleSheet()
        club_name = Setting.get('club_name', 'Club Training')
        elements = [
            Paragraph(club_name, styles['Title']),
            Paragraph('Sports Voucher Usage Record', styles['Heading2']),
            Spacer(1, 8 * mm),
        ]

        info_data = [
            ['Player name:',        p.name],
            ['Voucher number:',     v.voucher_number or '—'],
            ['Voucher date issued:', v.date_issued.strftime('%d %b %Y')],
            ['Voucher amount:',     f'${int(round(float(v.amount)))}'],
            ['Sessions total:',     str(v.sessions_total)],
            ['Sessions used:',      str(v.sessions_used)],
            ['Sessions remaining:', str(v.sessions_remaining)],
        ]
        info_table = Table(info_data, colWidths=[50 * mm, 100 * mm])
        info_table.setStyle(TableStyle([
            ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
            ('TOPPADDING', (0, 0), (-1, -1), 4),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ]))
        elements.append(info_table)
        elements.append(Spacer(1, 10 * mm))
        elements.append(Paragraph('Sessions Attended Using This Voucher', styles['Heading3']))
        elements.append(Spacer(1, 4 * mm))

        table_data = [['Date', 'Session', 'Group']]
        for a in usage:
            table_data.append([
                a.session_date.date.strftime('%d %b %Y'),
                a.session_date.template.name,
                a.group.name if a.group else '—',
            ])
        if len(table_data) == 1:
            table_data.append(['No sessions recorded yet.', '', ''])

        usage_table = Table(table_data, colWidths=[40 * mm, 70 * mm, 40 * mm])
        usage_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1a3a5c')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f4f6f9')]),
            ('TOPPADDING', (0, 0), (-1, -1), 5),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
        ]))
        elements.append(usage_table)
        elements.append(Spacer(1, 10 * mm))
        elements.append(Paragraph(f'Generated {date.today().strftime("%d %b %Y")}', styles['Normal']))

        doc.build(elements)
        buf.seek(0)

        safe_name = ''.join(c if c.isalnum() else '_' for c in p.name)
        filename = f'voucher_{safe_name}_{v.date_issued.isoformat()}.pdf'
        return send_file(buf, mimetype='application/pdf', as_attachment=True, download_name=filename)

    @app.route('/vouchers/import', methods=['GET', 'POST'])
    def vouchers_import():
        if request.method == 'POST':
            import re as _re
            file = request.files.get('csv_file')
            if not file or not file.filename:
                flash('Choose a CSV or Excel file first.', 'danger')
                return redirect(url_for('vouchers_import'))

            rows = _read_tabular_rows(file)
            if not rows:
                flash('That file appears to be empty.', 'danger')
                return redirect(url_for('vouchers_import'))

            field_map = {
                'name':           {'name', 'player', 'player name', 'child', 'child name', 'full name'},
                'voucher_number': {'voucher number', 'voucher no', 'voucher', 'number', 'voucher id', 'voucher code', 'code'},
                'amount':         {'amount', 'value'},
                'sessions':       {'sessions', 'sessions total'},
                'remaining':      {'remaining', 'remaining lessons', 'remaining sessions', 'lessons left', 'balance'},
                'date_issued':    {'date issued', 'issued', 'date'},
                'notes':          {'notes'},
            }

            # The header row isn't always row 1 — balance sheets have title rows
            # above it. Find the first row containing a name-style header.
            header_idx = None
            for i, row in enumerate(rows[:30]):
                cells = [str(c or '').strip().lower().replace('_', ' ') for c in row]
                if any(c in field_map['name'] for c in cells):
                    header_idx, header_cells = i, cells
                    break
            if header_idx is None:
                flash('Could not find a header row with a "name" column in that file.', 'danger')
                return redirect(url_for('vouchers_import'))

            col = {}
            for field, aliases in field_map.items():
                for j, h in enumerate(header_cells):
                    if h in aliases:
                        col[field] = j
                        break

            # Balance-sheet extras, drawn from the rows above the header:
            # a "Remaining lessons ..." column label and a carryover date.
            issued_default = date.today()
            for row in rows[:header_idx + 1]:
                for j, c in enumerate(row):
                    s = str(c or '').lower()
                    if 'remaining' not in col and ('remaining' in s or 'lesson' in s):
                        col['remaining'] = j
                    m = _re.search(r'(\d{1,2})/(\d{1,2})/(\d{2,4})', str(c or ''))
                    if m:
                        dd, mm, yy = (int(x) for x in m.groups())
                        yy = yy + 2000 if yy < 100 else yy
                        try:
                            issued_default = date(yy, mm, dd)
                        except ValueError:
                            pass

            # Last resort: a numeric column next to the names is the balance.
            data_rows = rows[header_idx + 1:]
            if 'remaining' not in col and not any(k in col for k in ('voucher_number', 'sessions', 'amount')):
                name_j = col['name']
                width = max((len(r) for r in data_rows), default=0)
                for j in range(width):
                    if j == name_j:
                        continue
                    vals = [r[j] for r in data_rows if j < len(r) and r[j] is not None and str(r[j]).strip()]
                    if vals and all(str(v).strip().replace('.', '', 1).isdigit() for v in map(str, vals)):
                        col['remaining'] = j
                        break

            def cell(row, field):
                j = col.get(field)
                if j is None or j >= len(row) or row[j] is None:
                    return ''
                return str(row[j]).strip()

            def parse_issued(s):
                for fmt in ('%Y-%m-%d', '%d/%m/%Y', '%d/%m/%y'):
                    try:
                        return datetime.strptime(s, fmt).date()
                    except ValueError:
                        continue
                return None

            vd_ = _voucher_defaults()
            per_session = float(vd_['amount']) / vd_['sessions']
            find_player, fuzzy_notes = _build_player_matcher(Player.query.all())
            existing_numbers = {v.voucher_number.lower()
                                for v in Voucher.query.filter(Voucher.voucher_number.isnot(None)).all()}

            added, skipped = 0, 0
            unknown, duplicates, blocked = [], [], []
            for row in data_rows:
                name = _clean_person_name(cell(row, 'name'))
                if not name:
                    skipped += 1
                    continue
                player = find_player(name)
                if not player:
                    unknown.append(name)
                    continue
                vnum = cell(row, 'voucher_number') or None
                if vnum and vnum.lower() in existing_numbers:
                    duplicates.append(vnum)
                    continue
                issued = parse_issued(cell(row, 'date_issued')) or issued_default
                limit_error = _voucher_limit_error(player.id, issued)
                if limit_error:
                    blocked.append(f'{name} ({limit_error.rstrip(".")})')
                    continue

                remaining = None
                rem_str = cell(row, 'remaining')
                if rem_str:
                    try:
                        remaining = int(float(rem_str))
                    except ValueError:
                        pass

                if remaining is not None:
                    # Carryover balance: the voucher enters the app with exactly
                    # this many sessions left on it.
                    sessions = remaining
                    amount   = int(round(remaining * per_session))
                    notes    = cell(row, 'notes') or f'Imported balance — {remaining} sessions remaining'
                else:
                    try:
                        amount = float(cell(row, 'amount') or _voucher_defaults()['amount'])
                    except ValueError:
                        amount = _voucher_defaults()['amount']
                    try:
                        sessions = int(float(cell(row, 'sessions') or _voucher_defaults()['sessions']))
                    except ValueError:
                        sessions = _voucher_defaults()['sessions']
                    notes = cell(row, 'notes') or None

                db.session.add(Voucher(
                    player_id=player.id, voucher_number=vnum,
                    amount=amount, sessions_total=sessions,
                    date_issued=issued, notes=notes,
                ))
                db.session.flush()   # so the limit check sees this voucher for repeat names
                if vnum:
                    existing_numbers.add(vnum.lower())
                added += 1

            db.session.commit()
            msg = f'{added} voucher{"s" if added != 1 else ""} imported.'
            if fuzzy_notes:
                msg += (f' {len(fuzzy_notes)} matched by name similarity — please check: '
                        + '; '.join(fuzzy_notes) + '.')
            if skipped:
                msg += f' {skipped} row{"s" if skipped != 1 else ""} skipped (missing player name).'
            if unknown:
                shown = ', '.join(unknown[:8]) + ('…' if len(unknown) > 8 else '')
                msg += f' {len(unknown)} skipped — player not found: {shown} (add them in the Player Database first).'
            if duplicates:
                shown = ', '.join(duplicates[:8]) + ('…' if len(duplicates) > 8 else '')
                msg += f' {len(duplicates)} skipped — voucher number already registered: {shown}.'
            if blocked:
                msg += f' {len(blocked)} blocked by voucher limits: {"; ".join(blocked[:5])}.'
            flash(msg, 'success' if added else 'warning')
            return redirect(url_for('vouchers'))

        return render_template('vouchers_import.html')

    @app.route('/api/player/<int:player_id>/vouchers')
    def api_player_vouchers(player_id):
        vs = Voucher.query.filter_by(player_id=player_id).order_by(Voucher.date_issued.desc()).all()
        return jsonify(ok=True, vouchers=[{
            'id':                 v.id,
            'label':              (f"#{v.voucher_number} — " if v.voucher_number else '')
                                  + f"{v.date_issued.strftime('%d %b %Y')} — {v.sessions_used}/{v.sessions_total} used, {v.sessions_remaining} left",
            'sessions_total':     v.sessions_total,
            'sessions_used':      v.sessions_used,
            'sessions_remaining': v.sessions_remaining,
        } for v in vs])

    @app.route('/api/player/<int:player_id>/vouchers', methods=['POST'])
    def api_player_voucher_create(player_id):
        Player.query.get_or_404(player_id)
        data     = request.get_json() or {}
        amount   = float(data.get('amount') or _voucher_defaults()['amount'])
        sessions = int(data.get('sessions_total') or _voucher_defaults()['sessions'])
        issued_date = date.today()
        limit_error = _voucher_limit_error(player_id, issued_date)
        if limit_error:
            return jsonify(ok=False, error=limit_error)
        v = Voucher(player_id=player_id, amount=amount, sessions_total=sessions, date_issued=issued_date)
        db.session.add(v)
        db.session.commit()
        return jsonify(ok=True, voucher={
            'id':                 v.id,
            'label':              f"{v.date_issued.strftime('%d %b %Y')} — 0/{v.sessions_total} used, {v.sessions_remaining} left",
            'sessions_total':     v.sessions_total,
            'sessions_used':      0,
            'sessions_remaining': v.sessions_remaining,
        })

    # ── Coaches ──────────────────────────────────────────────────────

    def _coach_mode():
        return Setting.get('coach_tracking_mode', 'simple')

    @app.route('/coaches', methods=['GET', 'POST'])
    def coaches():
        if _coach_mode() == 'off':
            flash('Coach tracking is turned off — enable it in Club Settings → Coaches.', 'warning')
            return redirect(url_for('settings_section', section='coaches'))
        if request.method == 'POST':
            action = request.form.get('action')

            def _pay_fields():
                try:
                    rate = max(0, int(request.form.get('pay_rate') or 0))
                except ValueError:
                    rate = 0
                basis = request.form.get('pay_basis', 'session')
                if basis not in ('session', 'hour'):
                    basis = 'session'
                return rate, basis, request.form.get('notes', '').strip()

            if action == 'add':
                rate, basis, notes = _pay_fields()
                db.session.add(Coach(
                    name=request.form['name'].strip(),
                    phone=request.form.get('phone', '').strip(),
                    email=request.form.get('email', '').strip(),
                    pay_rate=rate, pay_basis=basis, notes=notes,
                ))
                db.session.commit()
                flash('Coach added.', 'success')
            elif action == 'edit':
                c = Coach.query.get_or_404(int(request.form['coach_id']))
                rate, basis, notes = _pay_fields()
                # Pay fields are absent from the form in Simple mode — never
                # reset a stored rate just because the inputs were hidden.
                if 'pay_rate' not in request.form:
                    rate, basis = c.pay_rate, c.pay_basis
                rate_changed = (int(float(c.pay_rate or 0)) != int(float(rate or 0))
                                or c.pay_basis != basis)
                c.name  = request.form['name'].strip()
                c.phone = request.form.get('phone', '').strip()
                c.email = request.form.get('email', '').strip()
                c.pay_rate, c.pay_basis, c.notes = rate, basis, notes
                db.session.commit()
                if rate_changed:
                    flash('Coach updated. The new rate applies to future '
                          'sessions only — already-marked sessions keep the '
                          'rate they were marked at.', 'warning')
                else:
                    flash('Coach updated.', 'success')
            elif action == 'deactivate':
                c = Coach.query.get_or_404(int(request.form['coach_id']))
                c.active = False
                db.session.commit()
                flash('Coach removed.', 'success')
            return redirect(url_for('coaches'))

        all_coaches = Coach.query.filter_by(active=True).order_by(Coach.name).all()

        # Coaching stats: sessions coached ever/this year, and last coached date
        coach_stats = {}
        this_year = date.today().year
        for ca in CoachAttendance.query.join(SessionDate).all():
            sd = ca.session_date
            st = coach_stats.setdefault(ca.coach_id,
                                        {'total': 0, 'this_year': 0, 'last': None})
            st['total'] += 1
            if sd.date.year == this_year:
                st['this_year'] += 1
            if st['last'] is None or sd.date > st['last']:
                st['last'] = sd.date

        return render_template('coaches.html', coaches=all_coaches,
                               coach_stats=coach_stats, this_year=this_year)

    # ── Coach payments (end of month) ─────────────────────────────────

    def _coach_month_data(year, month):
        """Per-coach pay summary + detail rows for one calendar month."""
        start = date(year, month, 1)
        end   = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)
        rows = (CoachAttendance.query.join(SessionDate)
                .filter(SessionDate.date >= start, SessionDate.date < end)
                .order_by(SessionDate.date).all())
        by_coach = OrderedDict()
        for ca in sorted(rows, key=lambda x: (x.coach.name, x.session_date.date)):
            e = by_coach.setdefault(ca.coach_id, {
                'coach': ca.coach, 'sessions': 0, 'hours': 0.0,
                'gross': 0.0, 'adjust': 0.0, 'net': 0.0, 'rows': [],
                'all_paid': True, 'paid_date': None, 'paid_ref': ''})
            e['sessions'] += 1
            if ca.basis_snapshot == 'hour' and ca.hours is not None:
                e['hours'] += float(ca.hours)
            e['gross']  += float(ca.amount or 0)
            e['adjust'] += float(ca.adjustment or 0)
            e['net']    += ca.net_amount
            e['rows'].append(ca)
            if ca.paid:
                e['paid_date'] = ca.paid_date or e['paid_date']
                e['paid_ref']  = ca.payment_reference or e['paid_ref']
            else:
                e['all_paid'] = False
        payable    = [e for e in by_coach.values() if not e['coach'].is_volunteer]
        volunteers = [e for e in by_coach.values() if e['coach'].is_volunteer]
        totals = {
            'sessions': sum(e['sessions'] for e in payable),
            'gross':    sum(e['gross'] for e in payable),
            'adjust':   sum(e['adjust'] for e in payable),
            'net':      sum(e['net'] for e in payable),
        }
        return payable, volunteers, totals

    @app.route('/coach-payments')
    def coach_payments():
        if _coach_mode() != 'advanced':
            flash('Coach payments need Advanced coach tracking — switch modes in '
                  'Club Settings → Coaches.', 'warning')
            return redirect(url_for('settings_section', section='coaches'))
        month_str = request.args.get('month', '')
        try:
            year, month = (int(x) for x in month_str.split('-'))
            date(year, month, 1)
        except (ValueError, TypeError):
            today = date.today()
            year, month = today.year, today.month
        payable, volunteers, totals = _coach_month_data(year, month)
        prev_y, prev_m = (year - 1, 12) if month == 1 else (year, month - 1)
        next_y, next_m = (year + 1, 1) if month == 12 else (year, month + 1)
        return render_template('coach_payments.html',
                               year=year, month=month,
                               month_label=date(year, month, 1).strftime('%B %Y'),
                               month_key=f'{year:04d}-{month:02d}',
                               prev_month=f'{prev_y:04d}-{prev_m:02d}',
                               next_month=f'{next_y:04d}-{next_m:02d}',
                               payable=payable, volunteers=volunteers,
                               totals=totals,
                               finalised=_coach_month_finalised(year, month))

    @app.route('/coach-payments/finalise', methods=['POST'])
    def coach_payments_finalise():
        month_key = request.form.get('month', '')
        try:
            year, month = (int(x) for x in month_key.split('-'))
            date(year, month, 1)
        except (ValueError, TypeError):
            return redirect(url_for('coach_payments'))
        finalise = request.form.get('finalise') == '1'
        Setting.set(f'coach_month_final_{year:04d}-{month:02d}',
                    '1' if finalise else '0')
        if finalise:
            flash(f'{date(year, month, 1).strftime("%B %Y")} coach payments '
                  'finalised. Session changes for this month now ask for '
                  'confirmation first.', 'success')
        else:
            flash(f'{date(year, month, 1).strftime("%B %Y")} re-opened for '
                  'changes.', 'warning')
        return redirect(url_for('coach_payments', month=month_key))

    @app.route('/coach-payments/mark-paid', methods=['POST'])
    def coach_payments_mark_paid():
        """Mark (or unmark) one coach's whole month as paid, with an optional
        payment reference. Row-level flags so partial months still make sense."""
        if _coach_mode() != 'advanced':
            return redirect(url_for('settings_section', section='coaches'))
        month_key = request.form.get('month', '')
        try:
            year, month = (int(x) for x in month_key.split('-'))
            start = date(year, month, 1)
        except (ValueError, TypeError):
            return redirect(url_for('coach_payments'))
        end = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)
        coach = Coach.query.get_or_404(int(request.form['coach_id']))
        rows = (CoachAttendance.query.join(SessionDate)
                .filter(CoachAttendance.coach_id == coach.id,
                        SessionDate.date >= start, SessionDate.date < end).all())
        if request.form.get('unmark'):
            for ca in rows:
                ca.paid, ca.paid_date, ca.payment_reference = False, None, None
            db.session.commit()
            flash(f'{coach.name} — {start.strftime("%B %Y")} marked as UNPAID again.', 'warning')
        else:
            ref = request.form.get('reference', '').strip()[:100]
            for ca in rows:
                ca.paid = True
                ca.paid_date = date.today()
                if ref:
                    ca.payment_reference = ref
            db.session.commit()
            flash(f'{coach.name} — {start.strftime("%B %Y")} marked as paid'
                  f'{f" (ref: {ref})" if ref else ""}.', 'success')
        return redirect(url_for('coach_payments', month=month_key))

    @app.route('/api/coach-attendance/adjust', methods=['POST'])
    def api_coach_adjust():
        """Set a one-off adjustment (+/- whole dollars) on one attendance row."""
        data = request.get_json()
        ca = CoachAttendance.query.get_or_404(int(data['ca_id']))
        d  = ca.session_date.date
        if _coach_month_finalised(d.year, d.month) and not data.get('force'):
            return jsonify({'ok': False, 'needs_confirm': True, 'error':
                f'{d.strftime("%B %Y")} coach payments are finalised. '
                'Change anyway?'})
        try:
            ca.adjustment = int(float(data.get('adjustment') or 0))
        except (TypeError, ValueError):
            return jsonify({'ok': False, 'error': 'Adjustment must be a whole-dollar number.'})
        ca.adjustment_reason = (data.get('reason') or '').strip()[:200]
        db.session.commit()
        return jsonify({'ok': True, 'net': round(ca.net_amount)})

    @app.route('/coach-payments/export')
    def coach_payments_export():
        import csv as csv_mod
        import io
        from flask import send_file
        month_key = request.args.get('month', '')
        try:
            year, month = (int(x) for x in month_key.split('-'))
            date(year, month, 1)
        except (ValueError, TypeError):
            return redirect(url_for('coach_payments'))
        kind = request.args.get('kind', 'summary')
        payable, volunteers, totals = _coach_month_data(year, month)

        buf = io.StringIO()
        w = csv_mod.writer(buf)
        if kind == 'detail':
            w.writerow(['Coach', 'Date', 'Session', 'Basis', 'Hours', 'Rate',
                        'Amount', 'Adjustment', 'Adjustment Reason', 'Net',
                        'Paid', 'Paid Date', 'Payment Reference'])
            for e in payable + volunteers:
                for ca in e['rows']:
                    w.writerow([
                        e['coach'].name,
                        ca.session_date.date.isoformat(),
                        ca.session_date.template.name,
                        ca.basis_snapshot,
                        float(ca.hours) if ca.hours is not None else '',
                        round(float(ca.rate_snapshot or 0)),
                        round(float(ca.amount or 0)),
                        round(float(ca.adjustment or 0)),
                        ca.adjustment_reason or '',
                        round(ca.net_amount),
                        'Yes' if ca.paid else '',
                        ca.paid_date.isoformat() if ca.paid_date else '',
                        ca.payment_reference or ''])
            fname = f'coach-payments-detail-{year:04d}-{month:02d}.csv'
        else:
            w.writerow(['Coach', 'Sessions', 'Hours', 'Gross', 'Adjustments',
                        'Net Pay', 'Status', 'Paid'])
            for e in payable:
                w.writerow([e['coach'].name, e['sessions'],
                            e['hours'] or '', round(e['gross']),
                            round(e['adjust']), round(e['net']), 'Payable',
                            'Yes' if e['all_paid'] and e['rows'] else ''])
            for e in volunteers:
                w.writerow([e['coach'].name, e['sessions'], '', 0, 0, 0,
                            'Volunteer', ''])
            w.writerow([])
            w.writerow(['TOTAL PAYABLE', totals['sessions'], '',
                        round(totals['gross']), round(totals['adjust']),
                        round(totals['net']), ''])
            fname = f'coach-payments-{year:04d}-{month:02d}.csv'
        out = io.BytesIO(buf.getvalue().encode('utf-8-sig'))
        return send_file(out, as_attachment=True, download_name=fname,
                         mimetype='text/csv')

    # ── Reports ──────────────────────────────────────────────────────

    @app.route('/reports')
    def reports():
        months         = request.args.get('months', 24, type=int)
        session_filter = request.args.get('session_id', '')
        data           = _reports_data(months, session_filter)
        all_sessions   = SessionTemplate.query.order_by(SessionTemplate.day_of_week).all()

        return render_template('reports.html',
            months=months, session_filter=session_filter, all_sessions=all_sessions,
            monthly_labels=json.dumps([m['label'] for m in data['monthly_summary']]),
            monthly_totals=json.dumps([m['total'] for m in data['monthly_summary']]),
            monthly_summary=data['monthly_summary'],
            session_summary=data['session_summary'],
            total_sessions=data['total_sessions'], total_att=data['total_att'],
        )

    @app.route('/reports/export')
    def reports_export():
        import io
        import openpyxl
        from openpyxl.styles import Font, PatternFill
        from flask import send_file

        months         = request.args.get('months', 24, type=int)
        session_filter = request.args.get('session_id', '')
        data           = _reports_data(months, session_filter)

        hdr_fill = PatternFill('solid', fgColor='1F4E79')
        hdr_font = Font(color='FFFFFF', bold=True)

        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = 'Monthly Attendance'
        ws.append(['Month', 'Total Check-ins', 'Sessions Run', 'Avg per Session'])
        for cell in ws[1]:
            cell.font = hdr_font; cell.fill = hdr_fill
        for row in data['monthly_summary']:
            ws.append([row['label'], row['total'], row['sessions'], row['avg']])
        for col, width in zip('ABCD', (14, 16, 14, 16)):
            ws.column_dimensions[col].width = width

        ws2 = wb.create_sheet('Per Session')
        ws2.append(['Session', 'Occurrences', 'Total Check-ins', 'Avg per Session'])
        for cell in ws2[1]:
            cell.font = hdr_font; cell.fill = hdr_fill
        for row in data['session_summary'].values():
            ws2.append([row['name'], row['count'], row['total_att'], row['avg']])
        for col, width in zip('ABCD', (28, 14, 16, 16)):
            ws2.column_dimensions[col].width = width

        buf = io.BytesIO()
        wb.save(buf); buf.seek(0)
        club  = Setting.get('club_name', 'Club Training')
        fname = f"{club.replace(' ', '_')}_Attendance_Trends.xlsx"
        return send_file(buf, as_attachment=True, download_name=fname,
                         mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')

    # ── Settings ─────────────────────────────────────────────────────

    SETTINGS_SECTIONS = [
        ('identity', 'Club Identity'),
        ('players',  'Players'),
        ('sessions', 'Sessions & Groups'),
        ('payments', 'Payments'),
        ('vouchers', 'Vouchers'),
        ('coaches',  'Coaches'),
        ('email',    'Email'),
        ('security', 'Security & Privacy'),
        ('data',     'Data & Backup'),
        ('about',    'About'),
    ]

    @app.route('/settings')
    def settings():
        return redirect(url_for('settings_section', section='identity'))

    @app.route('/settings/<section>', methods=['GET', 'POST'])
    def settings_section(section):
        if section not in {s for s, _ in SETTINGS_SECTIONS}:
            return redirect(url_for('settings_section', section='identity'))

        if request.method == 'POST':
            err = _settings_save(section)
            if err:
                flash(err, 'danger')
            else:
                flash('Settings saved.', 'success')
            return redirect(url_for('settings_section', section=section))

        ctx = {'sections': SETTINGS_SECTIONS, 'section': section}
        if section == 'identity':
            ctx.update(
                bundled_icons=BUNDLED_ICONS,
                icon_type=Setting.get('club_icon_type', 'bundled'),
                icon_key=Setting.get('club_icon_key', 'badminton'))
        elif section == 'players':
            ctx.update(field_cfg=_player_field_settings())
        elif section == 'payments':
            ctx.update(
                square_enabled=Setting.get('square_enabled', '0') == '1',
                square_environment=Setting.get('square_environment', 'sandbox'),
                square_location_id=Setting.get('square_location_id', ''),
                square_device_id=Setting.get('square_device_id', ''),
                square_token_set=bool(Setting.get('square_access_token', '')))
        elif section == 'vouchers':
            ctx.update(vd=_voucher_defaults())
        elif section == 'email':
            ctx.update(
                smtp_host=Setting.get('smtp_host', 'mail.smtp2go.com'),
                smtp_port=Setting.get('smtp_port', '2525'),
                smtp_username=Setting.get('smtp_username', ''),
                email_from=Setting.get('email_from', ''),
                email_from_name=Setting.get('email_from_name', ''),
                smtp_password_set=bool(Setting.get('smtp_password', '')))
        elif section == 'about':
            ctx.update(app_version=APP_VERSION)
        return render_template(f'settings/{section}.html', **ctx)

    def _settings_save(section):
        """Apply one settings section's POST. Returns an error string or None."""
        if section == 'identity':
            action = request.form.get('icon_action', '')
            if action == 'bundled':
                key = request.form.get('icon_key', 'badminton')
                if key not in {k for k, _ in BUNDLED_ICONS}:
                    return 'Unknown icon.'
                Setting.set('club_icon_type', 'bundled')
                Setting.set('club_icon_key', key)
                _bump_icon_ver()
            elif action == 'custom':
                data_url = request.form.get('icon_data', '')
                prefix = 'data:image/png;base64,'
                if not data_url.startswith(prefix):
                    return 'Icon upload failed — expected a PNG image.'
                try:
                    blob = base64.b64decode(data_url[len(prefix):])
                except Exception:
                    return 'Icon upload failed — the image data was not valid.'
                # Sniff magic bytes: never trust the declared type
                if not blob.startswith(b'\x89PNG\r\n\x1a\n'):
                    return 'Icon upload failed — the file is not a valid PNG.'
                if len(blob) > 2 * 1024 * 1024:
                    return 'Icon upload failed — the image is over 2 MB.'
                Setting.set('club_icon_type', 'custom')
                Setting.set('club_icon_blob', base64.b64encode(blob).decode())
                Setting.set('club_icon_mime', 'image/png')
                _bump_icon_ver()
            elif action == 'remove_custom':
                Setting.set('club_icon_type', 'bundled')
                Setting.set('club_icon_blob', '')
                _bump_icon_ver()
            name = request.form.get('club_name', '').strip() or 'Club Training'
            Setting.set('club_name', name)
        elif section == 'players':
            for cat, default_min, default_max in (('junior', '0', '17'), ('senior', '18', '99')):
                age_min = request.form.get(f'{cat}_age_min', '').strip()
                age_max = request.form.get(f'{cat}_age_max', '').strip()
                Setting.set(f'{cat}_age_min', age_min or default_min)
                Setting.set(f'{cat}_age_max', age_max or default_max)
                for field in ('age', 'address', 'email', 'parent_contact', 'phone'):
                    key = f'{cat}_track_{field}'
                    Setting.set(key, '1' if request.form.get(key) else '0')
        elif section == 'sessions':
            Setting.set('groups_enabled', '1' if request.form.get('groups_enabled') else '0')
        elif section == 'payments':
            Setting.set('square_enabled', '1' if request.form.get('square_enabled') else '0')
            Setting.set('square_environment', request.form.get('square_environment', 'sandbox'))
            Setting.set('square_location_id', request.form.get('square_location_id', '').strip())
            Setting.set('square_device_id', request.form.get('square_device_id', '').strip())
            new_token = request.form.get('square_access_token', '').strip()
            if new_token:
                Setting.set('square_access_token', new_token)
        elif section == 'vouchers':
            for key, default in (('voucher_amount', '100'),
                                 ('voucher_sessions', '10'),
                                 ('voucher_max_active', '2'),
                                 ('voucher_max_per_year', '2')):
                raw = request.form.get(key, '').strip()
                try:
                    val = max(1, int(raw))
                except ValueError:
                    val = int(default)
                Setting.set(key, str(val))
        elif section == 'coaches':
            mode = request.form.get('coach_tracking_mode', 'simple')
            if mode not in ('off', 'simple', 'advanced'):
                mode = 'simple'
            Setting.set('coach_tracking_mode', mode)
        elif section == 'email':
            Setting.set('email_sending_enabled', '1' if request.form.get('email_sending_enabled') else '0')
            Setting.set('email_fields_enabled', '1' if request.form.get('email_fields_enabled') else '0')
            Setting.set('smtp_host', request.form.get('smtp_host', '').strip() or 'mail.smtp2go.com')
            Setting.set('smtp_port', request.form.get('smtp_port', '').strip() or '2525')
            Setting.set('smtp_username', request.form.get('smtp_username', '').strip())
            Setting.set('email_from', request.form.get('email_from', '').strip())
            Setting.set('email_from_name', request.form.get('email_from_name', '').strip())
            new_pwd = request.form.get('smtp_password', '').strip()
            if new_pwd:
                Setting.set('smtp_password', new_pwd)
        elif section == 'data':
            Setting.set('testing_mode', '1' if request.form.get('testing_mode') else '0')
        return None

    def _bump_icon_ver():
        Setting.set('club_icon_ver',
                    str(int(Setting.get('club_icon_ver', '0') or '0') + 1))

    @app.route('/settings/email/test', methods=['POST'])
    def settings_email_test():
        to = request.form.get('test_to', '').strip()
        if not to:
            flash('Enter an address to send the test to.', 'warning')
            return redirect(url_for('settings_section', section='email'))
        if not _email_configured():
            flash('Fill in and save the SMTP details first.', 'warning')
            return redirect(url_for('settings_section', section='email'))
        club = Setting.get('club_name', 'Club Training')
        try:
            sent, failures = _send_bulk_email(
                f'{club} — test email',
                f'This is a test email from {club} (Club Training app). '
                'If you can read this, email sending is working.',
                [to])
        except (smtplib.SMTPException, OSError) as e:
            flash(f'Test email failed: {e} — check the SMTP details.', 'danger')
            return redirect(url_for('settings_section', section='email'))
        if sent:
            flash(f'Test email sent to {to} — check the inbox (and spam folder).', 'success')
        else:
            flash(f'Test email failed: {failures[0] if failures else "unknown error"}', 'danger')
        return redirect(url_for('settings_section', section='email'))

    @app.route('/settings/coaches/backfill', methods=['POST'])
    def settings_coaches_backfill():
        """Optional estimate: apply each coach's CURRENT rate to old $0 markings
        from a chosen date. Rows that already carry an amount are never touched."""
        try:
            from_date = date.fromisoformat(request.form.get('from_date', ''))
        except ValueError:
            flash('Pick a valid from-date for the backfill.', 'warning')
            return redirect(url_for('settings_section', section='coaches'))
        rows = (CoachAttendance.query.join(SessionDate)
                .filter(SessionDate.date >= from_date,
                        CoachAttendance.amount == 0,
                        CoachAttendance.rate_snapshot == 0).all())
        updated = 0
        for ca in rows:
            coach = ca.coach
            if float(coach.pay_rate or 0) <= 0:
                continue
            amount, hours = _coach_pay_amount(coach, ca.session_date.template,
                                              float(ca.hours) if ca.hours is not None else None)
            ca.rate_snapshot  = coach.pay_rate
            ca.basis_snapshot = coach.pay_basis
            ca.hours          = hours
            ca.amount         = amount
            updated += 1
        db.session.commit()
        if updated:
            flash(f'Backfilled {updated} past marking{"s" if updated != 1 else ""} '
                  'with current rates (estimate).', 'success')
        else:
            flash('Nothing to backfill — no $0 markings from that date for coaches '
                  'with a rate set.', 'info')
        return redirect(url_for('settings_section', section='coaches'))


    # ── Email players ────────────────────────────────────────────────

    @app.route('/email')
    def email_players():
        if Setting.get('email_sending_enabled', '0') != '1':
            flash('Email sending is turned off — enable it in Club Settings → Email.', 'warning')
            return redirect(url_for('settings_section', section='email'))
        months     = request.args.get('months', 3, type=int)
        session_id = request.args.get('session_id', type=int)
        email_map, missing = _recent_player_emails(months, session_id)
        all_sessions = (SessionTemplate.query.filter_by(active=True)
                        .order_by(SessionTemplate.day_of_week, SessionTemplate.start_time).all())
        return render_template('email.html',
                               months=months, session_id=session_id,
                               all_sessions=all_sessions,
                               email_map=email_map, missing=missing,
                               email_configured=_email_configured())

    @app.route('/email/send', methods=['POST'])
    def email_players_send():
        if not _email_configured():
            flash('Email is not set up yet — add your SMTP2GO details in Club Settings first.', 'danger')
            return redirect(url_for('email_players'))

        months     = request.form.get('months', 3, type=int)
        session_id = request.form.get('session_id', type=int)
        subject    = request.form.get('subject', '').strip()
        body       = request.form.get('body', '').strip()
        if not subject or not body:
            flash('Subject and message are both required.', 'danger')
            return redirect(url_for('email_players', months=months, session_id=session_id))

        email_map, _ = _recent_player_emails(months, session_id)
        if not email_map:
            flash('No recipients found for that period.', 'warning')
            return redirect(url_for('email_players', months=months, session_id=session_id))

        try:
            sent, failures = _send_bulk_email(subject, body, list(email_map.keys()))
        except (smtplib.SMTPException, OSError) as e:
            flash(f'Could not send: {e} — check the SMTP details in Club Settings.', 'danger')
            return redirect(url_for('email_players', months=months, session_id=session_id))

        msg = f'Sent to {sent} address{"es" if sent != 1 else ""}.'
        if failures:
            msg += f' {len(failures)} failed: {", ".join(failures[:5])}{"…" if len(failures) > 5 else ""}.'
        flash(msg, 'success' if sent and not failures else 'warning')
        return redirect(url_for('email_players', months=months, session_id=session_id))

    # ── Export ───────────────────────────────────────────────────────

    @app.route('/export/excel')
    def export_excel():
        import io, calendar
        import openpyxl
        from openpyxl.styles import Font, PatternFill, Alignment
        from flask import send_file

        month_str = request.args.get('month', date.today().strftime('%Y-%m'))
        year, month = int(month_str[:4]), int(month_str[5:7])
        first = date(year, month, 1)
        if month < 12:
            last = date(year, month + 1, 1) - timedelta(days=1)
        else:
            last = date(year + 1, 1, 1) - timedelta(days=1)

        sds = (SessionDate.query
               .filter(SessionDate.date >= first, SessionDate.date <= last)
               .order_by(SessionDate.date).all())
        all_players = Player.query.filter_by(active=True).order_by(Player.name).all()
        all_coaches = Coach.query.filter_by(active=True).order_by(Coach.name).all()
        club = Setting.get('club_name', 'Club Training')
        month_label = f"{calendar.month_name[month]} {year}"

        hdr_fill = PatternFill('solid', fgColor='1F4E79')
        alt_fill = PatternFill('solid', fgColor='D6E4F0')
        hdr_font = Font(color='FFFFFF', bold=True)
        center   = Alignment(horizontal='center')

        wb = openpyxl.Workbook()

        # Sheet 1 — Attendance matrix
        ws = wb.active
        ws.title = 'Attendance'
        ws.append(['Player', 'Session', 'Group']
                  + [sd.date.strftime('%d %b') for sd in sds] + ['Total'])
        for cell in ws[1]:
            cell.font = hdr_font; cell.fill = hdr_fill; cell.alignment = center

        att_map = {(a.session_date_id, a.player_id): a
                   for sd in sds for a in sd.attendance}
        for i, p in enumerate(all_players):
            row = ([p.name,
                    p.default_session.name if p.default_session else '',
                    p.default_group.name   if p.default_group   else '']
                   + [att_map.get((sd.id, p.id), {}) and
                      att_map[(sd.id, p.id)].payment_type[:2]
                      if (sd.id, p.id) in att_map else ''
                      for sd in sds]
                   + [sum(1 for sd in sds if (sd.id, p.id) in att_map)])
            ws.append(row)
            if i % 2:
                for cell in ws[ws.max_row]: cell.fill = alt_fill

        # Sheet 2 — Payment summary
        ws2 = wb.create_sheet('Payment Summary')
        ws2.append(['Player', 'Session', 'Group']
                   + PAYMENT_TYPES + ['Sessions', 'Cash Total', 'Card Total'])
        for cell in ws2[1]:
            cell.font = hdr_font; cell.fill = hdr_fill

        for i, p in enumerate(all_players):
            counts = {pt: 0 for pt in PAYMENT_TYPES}
            cash_total = card_total = 0.0
            for sd in sds:
                a = att_map.get((sd.id, p.id))
                if a:
                    counts[a.payment_type] = counts.get(a.payment_type, 0) + 1
                    if a.payment_type == 'Cash': cash_total += float(a.amount or 0)
                    if a.payment_type == 'Card': card_total += float(a.amount or 0)
            ws2.append([p.name,
                        p.default_session.name if p.default_session else '',
                        p.default_group.name   if p.default_group   else '']
                       + [counts[pt] for pt in PAYMENT_TYPES]
                       + [sum(counts.values()), round(cash_total, 2), round(card_total, 2)])
            if i % 2:
                for cell in ws2[ws2.max_row]: cell.fill = alt_fill

        # Sheet 3 — Session summary
        ws3 = wb.create_sheet('Session Summary')
        ws3.append(['Date', 'Session', 'Total', 'Cash', 'Card', 'Voucher', 'Visit Pass', 'Free',
                    'Cash Total', 'Card Total'])
        for cell in ws3[1]:
            cell.font = hdr_font; cell.fill = hdr_fill

        for i, sd in enumerate(sds):
            ps = sd.payment_summary
            ws3.append([sd.date.strftime('%d %b %Y'), sd.template.name,
                        sd.total_attending,
                        ps.get('Cash', 0), ps.get('Card', 0), ps.get('Voucher', 0),
                        ps.get('Visit Pass', 0), ps.get('Free', 0),
                        round(sd.total_cash, 2), round(sd.total_card, 2)])
            if i % 2:
                for cell in ws3[ws3.max_row]: cell.fill = alt_fill

        # Sheet 4 — Coaches
        ws4 = wb.create_sheet('Coaches')
        ws4.append(['Coach'] + [f"{sd.date.strftime('%d %b')} - {sd.template.name}" for sd in sds]
                   + ['Total Sessions'])
        for cell in ws4[1]:
            cell.font = hdr_font; cell.fill = hdr_fill; cell.alignment = Alignment(wrap_text=True, vertical='top')
        ws4.row_dimensions[1].height = 45
        sd_ids_month = [sd.id for sd in sds]
        coached_map = defaultdict(set)   # coach_id -> {sd_id}
        if sd_ids_month:
            for ca in CoachAttendance.query.filter(
                    CoachAttendance.session_date_id.in_(sd_ids_month)).all():
                coached_map[ca.coach_id].add(ca.session_date_id)
        for i, coach in enumerate(all_coaches):
            coached = coached_map.get(coach.id, set())
            ws4.append([coach.name]
                       + ['Yes' if sd.id in coached else '' for sd in sds]
                       + [len(coached)])
            if i % 2:
                for cell in ws4[ws4.max_row]: cell.fill = alt_fill
        ws4.column_dimensions['A'].width = 20
        for col_idx in range(2, len(sds) + 2):
            ws4.column_dimensions[ws4.cell(row=1, column=col_idx).column_letter].width = 14

        buf = io.BytesIO()
        wb.save(buf); buf.seek(0)
        fname = f"{club.replace(' ','_')}_{month_label.replace(' ','_')}.xlsx"
        return send_file(buf, as_attachment=True, download_name=fname,
                         mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')

    # ── Square Terminal payments ──────────────────────────────────────

    def _square_base_url():
        env = Setting.get('square_environment', 'sandbox')
        return 'https://connect.squareupsandbox.com' if env == 'sandbox' else 'https://connect.squareup.com'

    def _square_headers():
        return {
            'Square-Version':  '2024-06-04',
            'Authorization':   f"Bearer {Setting.get('square_access_token', '')}",
            'Content-Type':    'application/json',
        }

    def _square_configured():
        enabled = Setting.get('square_enabled', '0') == '1'
        return enabled and bool(Setting.get('square_access_token', '') and Setting.get('square_device_id', ''))

    def _square_error(resp_json):
        errs = resp_json.get('errors') or []
        return errs[0].get('detail', 'Square API error.') if errs else 'Square API error.'

    @app.route('/api/square/checkout', methods=['POST'])
    def square_create_checkout():
        if not _square_configured():
            return jsonify(ok=False, error='Square is not set up yet. Add your access token and device ID in Settings.')
        data   = request.get_json() or {}
        amount = float(data.get('amount') or 0)
        if amount <= 0:
            return jsonify(ok=False, error='Amount must be greater than zero.')

        import uuid
        body = {
            'idempotency_key': str(uuid.uuid4()),
            'checkout': {
                'amount_money':   {'amount': int(round(amount * 100)), 'currency': 'AUD'},
                'device_options': {'device_id': Setting.get('square_device_id')},
                'reference_id':   str(data.get('reference') or '')[:40],
            },
        }
        try:
            resp = requests.post(f'{_square_base_url()}/v2/terminals/checkouts',
                                 headers=_square_headers(), json=body, timeout=10)
            result = resp.json()
        except requests.RequestException as e:
            return jsonify(ok=False, error=f'Could not reach Square: {e}')
        if resp.status_code >= 300:
            return jsonify(ok=False, error=_square_error(result))

        checkout = result.get('checkout', {})
        return jsonify(ok=True, checkout_id=checkout.get('id'), status=checkout.get('status'))

    @app.route('/api/square/checkout/<checkout_id>/status')
    def square_checkout_status(checkout_id):
        try:
            resp = requests.get(f'{_square_base_url()}/v2/terminals/checkouts/{checkout_id}',
                                headers=_square_headers(), timeout=10)
            result = resp.json()
        except requests.RequestException as e:
            return jsonify(ok=False, error=str(e))
        if resp.status_code >= 300:
            return jsonify(ok=False, error=_square_error(result))

        checkout = result.get('checkout', {})
        return jsonify(ok=True, status=checkout.get('status'))

    @app.route('/api/square/checkout/<checkout_id>/cancel', methods=['POST'])
    def square_checkout_cancel(checkout_id):
        try:
            resp = requests.post(f'{_square_base_url()}/v2/terminals/checkouts/{checkout_id}/cancel',
                                 headers=_square_headers(), timeout=10)
            result = resp.json()
        except requests.RequestException as e:
            return jsonify(ok=False, error=str(e))
        if resp.status_code >= 300:
            return jsonify(ok=False, error=_square_error(result))

        checkout = result.get('checkout', {})
        return jsonify(ok=True, status=checkout.get('status'))

    # ── API ──────────────────────────────────────────────────────────

    @app.route('/api/groups/<int:session_id>')
    def api_groups(session_id):
        groups = (Group.query.filter_by(session_id=session_id, active=True)
                  .order_by(Group.sort_order).all())
        return jsonify([{'id': g.id, 'name': g.name} for g in groups])

    @app.route('/api/player/<int:player_id>')
    def api_player_get(player_id):
        p = Player.query.get_or_404(player_id)
        return jsonify(ok=True, player={
            'id':            p.id,
            'name':          p.name,
            'category':      p.category,
            'dob':           p.date_of_birth.isoformat() if p.date_of_birth else '',
            'age':           p.age,
            'guardian_name':  p.guardian_name or '',
            'guardian_phone': p.guardian_phone or '',
            'guardian_email': p.guardian_email or '',
            'address':       p.address or '',
            'own_email':     p.own_email or '',
            'own_phone':     p.own_phone or '',
            'notes':         p.notes or '',
        })

    @app.route('/api/player/<int:player_id>', methods=['POST'])
    def api_player_save(player_id):
        p = Player.query.get_or_404(player_id)
        data = request.get_json()
        name = (data.get('name') or '').strip()
        if not name:
            return jsonify(ok=False, error='Name is required.')
        p.name          = name
        p.category       = data.get('category') or p.category
        p.guardian_name  = (data.get('guardian_name') or '').strip() or None
        p.guardian_phone = (data.get('guardian_phone') or '').strip() or None
        # Keys are omitted by the check-in edit form when email fields are
        # turned off — never blank stored addresses because a field was hidden.
        if 'guardian_email' in data:
            p.guardian_email = (data.get('guardian_email') or '').strip() or None
        p.address        = (data.get('address') or '').strip() or None
        if 'own_email' in data:
            p.own_email  = (data.get('own_email') or '').strip() or None
        p.own_phone      = (data.get('own_phone') or '').strip() or None
        p.notes         = (data.get('notes') or '').strip() or None
        dob_str = (data.get('dob') or '').strip()
        if dob_str:
            try:
                from datetime import date as _d
                p.date_of_birth = _d.fromisoformat(dob_str)
            except ValueError:
                pass
        elif data.get('age'):
            try:
                today = date.today()
                p.date_of_birth = today.replace(year=today.year - int(data['age']))
            except (ValueError, TypeError):
                pass
        db.session.commit()
        return jsonify(ok=True, player={
            'id':           p.id,
            'name':         p.name,
            'age':          p.age,
            'guardian_name':  p.guardian_name or '',
            'guardian_phone': p.guardian_phone or '',
        })

    @app.route('/api/player/quick-add', methods=['POST'])
    def api_player_quick_add():
        data = request.get_json()
        name = (data.get('name') or '').strip()
        if not name:
            return jsonify(ok=False, error='Name is required.')
        if not data.get('force'):
            existing = Player.query.filter(db.func.lower(Player.name) == name.lower()).first()
            if existing:
                status = 'an active' if existing.active else 'an inactive'
                return jsonify(ok=False, duplicate=True,
                               error=f'"{existing.name}" already exists as {status} player.')
        dob = None
        age = data.get('age')
        if age:
            try:
                today = date.today()
                dob = today.replace(year=today.year - int(age))
            except (ValueError, TypeError):
                pass
        p = Player(name=name,
                   date_of_birth=dob,
                   guardian_name=(data.get('guardian_name') or '').strip() or None,
                   guardian_phone=(data.get('guardian_phone') or '').strip() or None)
        db.session.add(p)
        db.session.commit()
        return jsonify(ok=True, player={'id': p.id, 'name': p.name,
                                        'age': p.age, 'guardian_phone': p.guardian_phone})

    return app


# ─── Helpers ────────────────────────────────────────────────────────

def _int(v):
    try:
        return int(v) if v else None
    except (TypeError, ValueError):
        return None


def _player_field_settings():
    """Which optional player fields each category (Junior/Senior) records, and their
    age brackets — configured on the Settings page under 'Player Categories & Fields'."""
    def cat_cfg(cat, default_age_min, default_age_max, defaults):
        return {
            'age_min':        int(Setting.get(f'{cat}_age_min', default_age_min) or default_age_min),
            'age_max':        int(Setting.get(f'{cat}_age_max', default_age_max) or default_age_max),
            'age':            Setting.get(f'{cat}_track_age', defaults['age']) == '1',
            'address':        Setting.get(f'{cat}_track_address', defaults['address']) == '1',
            'email':          Setting.get(f'{cat}_track_email', defaults['email']) == '1',
            'parent_contact': Setting.get(f'{cat}_track_parent_contact', defaults['parent_contact']) == '1',
            'phone':          Setting.get(f'{cat}_track_phone', defaults['phone']) == '1',
        }
    cfg = {
        'junior': cat_cfg('junior', 0, 17, {
            'age': '1', 'address': '0', 'email': '0', 'parent_contact': '1', 'phone': '0',
        }),
        'senior': cat_cfg('senior', 18, 99, {
            'age': '1', 'address': '1', 'email': '1', 'parent_contact': '0', 'phone': '1',
        }),
    }
    # Global kill-switch (Settings → Email): hides player email fields
    # everywhere without losing the per-category preference underneath.
    if Setting.get('email_fields_enabled', '1') != '1':
        for c in cfg.values():
            c['email'] = False
    return cfg


def _read_tabular_rows(file_storage):
    """Uploaded .xlsx or .csv → list of row tuples. Stops after a long run of
    blank rows (Excel files often report a million ghost rows)."""
    filename = (file_storage.filename or '').lower()
    if filename.endswith(('.xlsx', '.xlsm')):
        import io
        import openpyxl
        wb = openpyxl.load_workbook(io.BytesIO(file_storage.read()),
                                    read_only=True, data_only=True)
        ws = wb.active
        rows, empty_streak = [], 0
        for row in ws.iter_rows(values_only=True):
            if any(c is not None and str(c).strip() for c in row):
                empty_streak = 0
            else:
                empty_streak += 1
                if empty_streak > 20:
                    break
            rows.append(tuple(row))
        wb.close()
    else:
        import csv, io
        text = file_storage.read().decode('utf-8-sig', errors='replace')
        rows = [tuple(r) for r in csv.reader(io.StringIO(text))]
    while rows and not any(c is not None and str(c).strip() for c in rows[-1]):
        rows.pop()
    return rows


def _clean_person_name(value):
    """Normalise an imported name: drop marker characters like ^ and *, and
    collapse whitespace. Parenthesised preferred names are kept."""
    s = str(value or '').replace('^', ' ').replace('*', ' ')
    return ' '.join(s.split())


def _norm_name(value):
    """Aggressive normalisation for *matching* names across files: lowercase,
    accents stripped, curly quotes/dashes unified, markers and stray
    punctuation dropped, all whitespace collapsed."""
    import unicodedata
    s = unicodedata.normalize('NFKD', str(value or ''))
    s = ''.join(ch for ch in s if not unicodedata.combining(ch))
    s = (s.replace('’', "'").replace('‘', "'")
          .replace('–', '-').replace('—', '-'))
    s = ''.join(ch if (ch.isalnum() or ch in " '-") else ' ' for ch in s)
    return ' '.join(s.lower().split())


def _build_player_matcher(players):
    """Returns (find, fuzzy_notes). find(raw_name) resolves an imported name to
    a Player via, in order: exact normalised match; unique first+last token
    match (handles middle names); careful fuzzy match for typos — requiring a
    high similarity, a clear margin over the runner-up, and a similar first
    name, so it can never guess between siblings who share a surname.
    Non-exact matches are recorded in fuzzy_notes for the result message."""
    import difflib

    by_norm, by_first_last = {}, {}
    for p in players:
        n = _norm_name(p.name)
        by_norm.setdefault(n, []).append(p)
        toks = n.split()
        if toks:
            by_first_last.setdefault((toks[0], toks[-1]), []).append(p)
    all_norms = list(by_norm.keys())
    fuzzy_notes = []

    def find(raw):
        n = _norm_name(raw)
        if not n:
            return None
        cands = by_norm.get(n)
        if cands and len(cands) == 1:
            return cands[0]
        toks = n.split()
        cands = by_first_last.get((toks[0], toks[-1]))
        if cands and len(cands) == 1:
            fuzzy_notes.append(f'"{_clean_person_name(raw)}" matched to {cands[0].name}')
            return cands[0]
        close = difflib.get_close_matches(n, all_norms, n=2, cutoff=0.85)
        if close and len(by_norm[close[0]]) == 1:
            r1 = difflib.SequenceMatcher(None, n, close[0]).ratio()
            r2 = difflib.SequenceMatcher(None, n, close[1]).ratio() if len(close) > 1 else 0.0
            first_sim = difflib.SequenceMatcher(None, toks[0], close[0].split()[0]).ratio()
            if r1 >= 0.90 and (r1 - r2) >= 0.04 and first_sim >= 0.8:
                p = by_norm[close[0]][0]
                fuzzy_notes.append(f'"{_clean_person_name(raw)}" matched to {p.name}')
                return p
        return None

    return find, fuzzy_notes


def _email_configured():
    return (Setting.get('email_sending_enabled', '0') == '1'
            and bool(Setting.get('smtp_username', ''))
            and bool(Setting.get('smtp_password', ''))
            and bool(Setting.get('email_from', '')))


def _recent_player_emails(months, session_id=None):
    """Players who attended in the last `months` months (optionally only a
    specific session) → best contact email. Juniors use guardian email first;
    Seniors their own email first. Returns (email_map: email → [player names],
    missing: [player names with no email])."""
    cutoff = date.today() - timedelta(days=months * 30)
    q = (db.session.query(Attendance.player_id)
         .join(SessionDate, Attendance.session_date_id == SessionDate.id)
         .filter(SessionDate.date >= cutoff))
    if session_id:
        q = q.filter(SessionDate.session_id == session_id)
    pids = {pid for (pid,) in q.distinct()}
    email_map, missing = OrderedDict(), []
    for p in (Player.query.filter(Player.id.in_(pids), Player.active == True)
              .order_by(Player.name).all() if pids else []):
        if p.category == 'Senior':
            email = (p.own_email or '').strip() or (p.guardian_email or '').strip()
        else:
            email = (p.guardian_email or '').strip() or (p.own_email or '').strip()
        if email:
            email_map.setdefault(email.lower(), []).append(p.name)
        else:
            missing.append(p.name)
    return email_map, missing


def _send_bulk_email(subject, body, addresses):
    """Send one individual email per address (no shared To/CC — keeps parents'
    addresses private from each other). Returns (sent_count, failures)."""
    host      = Setting.get('smtp_host', 'mail.smtp2go.com') or 'mail.smtp2go.com'
    port      = int(Setting.get('smtp_port', '2525') or 2525)
    user      = Setting.get('smtp_username', '')
    password  = Setting.get('smtp_password', '')
    from_addr = Setting.get('email_from', '')
    from_name = Setting.get('email_from_name', '') or Setting.get('club_name', '')

    sent, failures = 0, []
    with smtplib.SMTP(host, port, timeout=30) as server:
        server.starttls()
        server.login(user, password)
        for addr in addresses:
            try:
                msg = MIMEText(body, 'plain', 'utf-8')
                msg['Subject'] = subject
                msg['From']    = f'{from_name} <{from_addr}>' if from_name else from_addr
                msg['To']      = addr
                server.send_message(msg)
                sent += 1
            except smtplib.SMTPException as e:
                failures.append(f'{addr} ({e.__class__.__name__})')
    return sent, failures


def _reports_data(months, session_filter):
    """Shared attendance-trend data for the Reports page and its Excel export.
    Player counts only — no money. `months` <= 0 means all time."""
    start = date.today() - timedelta(days=months * 30) if months and months > 0 else date(2000, 1, 1)

    q = (SessionDate.query.join(SessionTemplate)
         .filter(SessionDate.date >= start).order_by(SessionDate.date))
    if session_filter:
        try:
            q = q.filter(SessionDate.session_id == int(session_filter))
        except ValueError:
            pass
    dates = q.all()

    monthly = OrderedDict()
    for sd in dates:
        key = (sd.date.year, sd.date.month)
        if key not in monthly:
            monthly[key] = {'label': sd.date.strftime('%b %Y'), 'total': 0, 'sessions': 0}
        monthly[key]['total']    += sd.total_attending
        monthly[key]['sessions'] += 1
    monthly_summary = []
    for key in sorted(monthly.keys()):
        row = monthly[key]
        row['avg'] = round(row['total'] / row['sessions'], 1) if row['sessions'] else 0
        monthly_summary.append(row)

    session_summary = {}
    for sd in dates:
        sid = sd.session_id
        if sid not in session_summary:
            session_summary[sid] = {'name': sd.template.name, 'count': 0, 'total_att': 0}
        session_summary[sid]['count']     += 1
        session_summary[sid]['total_att'] += sd.total_attending
    for v in session_summary.values():
        v['avg'] = round(v['total_att'] / v['count'], 1) if v['count'] else 0

    return {
        'monthly_summary': monthly_summary,
        'session_summary': session_summary,
        'total_sessions':  len(dates),
        'total_att':       sum(sd.total_attending for sd in dates),
    }


def _session_duration_hours(template):
    """Scheduled length of a session in hours, from its HH:MM start/end."""
    try:
        sh, sm = (int(x) for x in template.start_time.split(':'))
        eh, em = (int(x) for x in template.end_time.split(':'))
        mins = (eh * 60 + em) - (sh * 60 + sm)
        return round(max(mins, 0) / 60, 2)
    except (ValueError, AttributeError):
        return 0.0


def _coach_pay_amount(coach, template, hours=None):
    """(amount, hours) for a coach working one occurrence of `template`.
    Session basis: flat rate, hours None. Hour basis: rate × hours, defaulting
    hours to the session's scheduled duration."""
    rate = float(coach.pay_rate or 0)
    if coach.pay_basis == 'hour':
        h = float(hours) if hours is not None else _session_duration_hours(template)
        return round(rate * h, 2), h
    return round(rate, 2), None


def _coach_month_finalised(year, month):
    return Setting.get(f'coach_month_final_{year:04d}-{month:02d}', '0') == '1'


def _voucher_defaults():
    """Voucher rules, configurable in Settings → Vouchers (falling back to the
    original hardcoded Sports Voucher defaults)."""
    def _int_setting(key, fallback):
        try:
            return max(1, int(Setting.get(key, '') or fallback))
        except ValueError:
            return fallback
    return {
        'amount':       _int_setting('voucher_amount', DEFAULT_VOUCHER_AMOUNT),
        'sessions':     _int_setting('voucher_sessions', DEFAULT_VOUCHER_SESSIONS),
        'max_active':   _int_setting('voucher_max_active', 2),
        'max_per_year': _int_setting('voucher_max_per_year', 2),
    }


def _voucher_limit_error(player_id, issued_date):
    """Returns an error message if creating a voucher for this player/date would
    breach the max-active / max-per-calendar-year voucher limits, else None."""
    vd = _voucher_defaults()
    vouchers = Voucher.query.filter_by(player_id=player_id).all()
    active_count = sum(1 for v in vouchers if v.sessions_remaining > 0)
    if active_count >= vd['max_active']:
        return (f'This child already has {vd["max_active"]} active '
                'vouchers. Use one up before creating another.')
    year_count = sum(1 for v in vouchers if v.date_issued.year == issued_date.year)
    if year_count >= vd['max_per_year']:
        return (f'This child has already been issued {vd["max_per_year"]} '
                f'vouchers in {issued_date.year} (the yearly maximum).')
    return None


def _save_siblings(player_id, sibling_ids):
    for sid in sibling_ids:
        try:
            sid = int(sid)
        except (ValueError, TypeError):
            continue
        if sid == player_id:
            continue
        a, b = min(player_id, sid), max(player_id, sid)
        exists = db.session.execute(
            sibling_links.select().where(
                sibling_links.c.player_a_id == a,
                sibling_links.c.player_b_id == b,
            )
        ).fetchone()
        if not exists:
            db.session.execute(sibling_links.insert().values(player_a_id=a, player_b_id=b))


def _totals(sd):
    return {
        'total':    sd.total_attending,
        'cash':     round(sd.total_cash, 2),
        'card':     round(sd.total_card, 2),
        'by_type':  sd.payment_summary,
        'by_group': sd.group_summary,
    }


# ─── Entry point ────────────────────────────────────────────────────

def _free_port(start=7433):
    for p in range(start, start + 20):
        with socket.socket() as s:
            if s.connect_ex(('127.0.0.1', p)) != 0:
                return p
    return start


def _wait_for_server(port, timeout=5):
    """Poll until the local Flask server accepts connections (or give up after timeout)."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection(('127.0.0.1', port), timeout=0.3):
                return True
        except OSError:
            time.sleep(0.1)
    return False


def _unblock_bundle():
    """Strip Windows 'downloaded from the internet' marks (Zone.Identifier
    streams) from every bundled file. When the app is distributed as a zip
    (e.g. GitHub Releases), Windows tags the extracted files as untrusted and
    .NET then refuses to load our bundled DLLs — crashing the native window
    with 'Failed to resolve Python.Runtime.Loader.Initialize'. Clearing the
    marks up front makes a downloaded copy behave like a locally built one."""
    if not getattr(sys, 'frozen', False):
        return
    base = os.path.dirname(sys.executable)
    for root, _dirs, files in os.walk(base):
        for fn in files:
            try:
                os.remove(os.path.join(root, fn) + ':Zone.Identifier')
            except OSError:
                pass  # no mark on this file — the normal case


if __name__ == '__main__':
    _unblock_bundle()
    _tested_versions = ((3, 9), (3, 14))  # inclusive range this app has been tested against
    if not (_tested_versions[0] <= sys.version_info[:2] <= _tested_versions[1]):
        print(f'  Note: this app was built and tested on Python 3.12. You are running '
              f'{sys.version_info[0]}.{sys.version_info[1]}, which is outside the tested range '
              f'({_tested_versions[0][0]}.{_tested_versions[0][1]}–{_tested_versions[1][0]}.{_tested_versions[1][1]}).')
        print('  The app will still try to start, but if something looks wrong, installing '
              'Python 3.12 is the known-good fix.\n')

    app  = create_app()
    port = _free_port()

    server_thread = threading.Thread(
        target=lambda: app.run(host='127.0.0.1', port=port, debug=False, use_reloader=False),
        daemon=True,
    )
    server_thread.start()
    _wait_for_server(port)

    with app.app_context():
        club_name = Setting.get('club_name', 'Club Training')
    window_title = (f'Club Training — {club_name}'
                    if club_name and club_name != 'Club Training'
                    else 'Club Training')

    try:
        import webview
        webview.create_window(window_title, f'http://127.0.0.1:{port}',
                              width=1280, height=850, min_size=(1000, 650))
        webview.start()
    except Exception as e:
        # Never die with an error dialog just because the native window
        # couldn't start — the app itself is fine, so serve it in the
        # default browser instead.
        print(f'  Desktop window unavailable ({e.__class__.__name__}: {e}).')
        print('  Falling back to your default browser.\n')
        webbrowser.open(f'http://localhost:{port}')
        print(f'  Club Training running at http://localhost:{port}')
        server_thread.join()
