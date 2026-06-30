"""
Badminton Club — junior session management
Run:  python app.py
"""
import calendar as _cal_mod
import json, socket, threading, time, webbrowser
from collections import defaultdict, OrderedDict
from datetime import date, datetime, timedelta

from flask import (Flask, jsonify, flash, redirect, render_template,
                   request, url_for)

import config
from models import (db, Setting, SessionTemplate, Group, Coach, Player,
                    sibling_links, SessionDate, Attendance,
                    PAYMENT_TYPES, AMOUNT_TYPES, DAY_NAMES, PAYMENT_COLORS)


# ─── App factory ────────────────────────────────────────────────────

def create_app():
    app = Flask(__name__)
    app.secret_key = 'bc-club-local-2025'
    app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{config.DB_PATH}'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    db.init_app(app)

    with app.app_context():
        db.create_all()
        if not Setting.query.get('club_name'):
            db.session.add(Setting(key='club_name', value='My Badminton Club'))
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
                'sessions' if ep == 'sessions'           else
                'coaches'  if ep == 'coaches'            else
                'settings' if ep == 'settings'           else '')
        return {
            'club_name':   Setting.get('club_name', 'My Badminton Club'),
            'today':       date.today(),
            'active_page': page,
        }

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

        return render_template('day/view.html',
                               d=d, session_dates=session_dates,
                               all_templates=all_templates,
                               used_ids=used_ids,
                               prev_day=prev_day, next_day=next_day,
                               is_today=is_today, is_future=is_future,
                               PAYMENT_COLORS=PAYMENT_COLORS)

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
            # One session opened → go straight to player selection
            if len(new_sds) == 1:
                return redirect(url_for('register_select_players', sd_id=new_sds[0].id))
            # Multiple sessions opened → day view to pick which one
            flash(f'{len(new_sds)} sessions opened for {d.strftime("%A, %d %B %Y")}.', 'success')
        else:
            flash('No new sessions to add.', 'warning')
        return redirect(url_for('day_view', date_iso=date_iso))

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

        return render_template('players/list.html',
                               players=player_list, sessions=sessions, all_groups=all_groups,
                               all_active_players=all_active_players,
                               q=q, session_id=session_id, group_id=group_id,
                               show_inactive=show_inactive)

    @app.route('/players/add', methods=['POST'])
    def players_add():
        dob_str = request.form.get('date_of_birth', '').strip()
        p = Player(
            name=request.form['name'].strip(),
            date_of_birth=date.fromisoformat(dob_str) if dob_str else None,
            guardian_name=request.form.get('guardian_name', '').strip(),
            guardian_phone=request.form.get('guardian_phone', '').strip(),
            guardian_email=request.form.get('guardian_email', '').strip(),
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

    @app.route('/players/<int:pid>')
    def player_detail(pid):
        p      = Player.query.get_or_404(pid)
        recent = (Attendance.query.filter_by(player_id=pid)
                  .join(SessionDate)
                  .order_by(SessionDate.date.desc())
                  .limit(25).all())
        return render_template('players/detail.html', player=p, recent=recent,
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
            p.guardian_name      = request.form.get('guardian_name', '').strip()
            p.guardian_phone     = request.form.get('guardian_phone', '').strip()
            p.guardian_email     = request.form.get('guardian_email', '').strip()
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
                               all_players=all_players, current_sib_ids=current_sib_ids)

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
                }

        # Sessions data for JS modal
        sessions_js = [
            {
                'sd_id':       sd.id,
                'name':        sd.template.name,
                'price_cash':  int(round(float(sd.template.price_cash or 0))),
                'price_card':  int(round(float(sd.template.price_card or 0))),
                'groups':      [{'id': g.id, 'name': g.name}
                                for g in sd.day_active_groups],
            }
            for sd in session_dates
        ]

        return render_template('day/checkin.html',
                               d=d,
                               session_dates=session_dates,
                               all_players=all_players,
                               attendance_map=attendance_map,
                               sessions_js=json.dumps(sessions_js),
                               PAYMENT_TYPES=PAYMENT_TYPES,
                               AMOUNT_TYPES=list(AMOUNT_TYPES),
                               PAYMENT_COLORS=PAYMENT_COLORS)

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
        coach_ids      = {c.id for c in sd.coaches}

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

        rec = Attendance.query.filter_by(session_date_id=sd_id, player_id=player_id).first()
        if rec:
            rec.payment_type = payment_type
            rec.amount       = amount
            rec.group_id     = group_id
        else:
            db.session.add(Attendance(
                session_date_id=sd_id, player_id=player_id,
                group_id=group_id, payment_type=payment_type, amount=amount,
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
        sd.coaches = [Coach.query.get(int(c)) for c in request.form.getlist('coach_ids') if c]
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

    # ── Coaches ──────────────────────────────────────────────────────

    @app.route('/coaches', methods=['GET', 'POST'])
    def coaches():
        if request.method == 'POST':
            action = request.form.get('action')
            if action == 'add':
                db.session.add(Coach(
                    name=request.form['name'].strip(),
                    phone=request.form.get('phone', '').strip(),
                    email=request.form.get('email', '').strip(),
                ))
                db.session.commit()
                flash('Coach added.', 'success')
            elif action == 'edit':
                c = Coach.query.get_or_404(int(request.form['coach_id']))
                c.name  = request.form['name'].strip()
                c.phone = request.form.get('phone', '').strip()
                c.email = request.form.get('email', '').strip()
                db.session.commit()
                flash('Coach updated.', 'success')
            elif action == 'deactivate':
                c = Coach.query.get_or_404(int(request.form['coach_id']))
                c.active = False
                db.session.commit()
                flash('Coach removed.', 'success')
            return redirect(url_for('coaches'))

        all_coaches = Coach.query.filter_by(active=True).order_by(Coach.name).all()
        return render_template('coaches.html', coaches=all_coaches)

    # ── Reports ──────────────────────────────────────────────────────

    @app.route('/reports')
    def reports():
        months         = request.args.get('months', 12, type=int)
        session_filter = request.args.get('session_id', '')
        start          = date.today() - timedelta(days=months * 30)

        q = SessionDate.query.filter(SessionDate.date >= start).order_by(SessionDate.date)
        if session_filter:
            try:
                q = q.filter_by(session_id=int(session_filter))
            except ValueError:
                pass
        dates = q.all()

        # Attendance over time — one point per session date
        palette = ['#1F4E79', '#28a745', '#ffc107', '#dc3545', '#17a2b8', '#6f42c1', '#fd7e14']
        series  = {}
        for sd in dates:
            series.setdefault(sd.template.name, {})[sd.date.isoformat()] = sd.total_attending
        all_chart_dates = sorted({sd.date.isoformat() for sd in dates})
        att_datasets = [
            {
                'label':           name,
                'data':            [dmap.get(d) for d in all_chart_dates],
                'borderColor':     palette[i % len(palette)],
                'backgroundColor': palette[i % len(palette)] + '33',
                'tension': 0.3, 'spanGaps': True,
            }
            for i, (name, dmap) in enumerate(series.items())
        ]

        # Monthly payment breakdown
        monthly     = defaultdict(lambda: defaultdict(int))
        months_list = list(OrderedDict.fromkeys(sd.date.strftime('%b %Y') for sd in dates))
        for sd in dates:
            m = sd.date.strftime('%b %Y')
            for a in sd.attendance:
                monthly[m][a.payment_type] += 1

        pcols = {'Cash': '#28a745', 'Card': '#0d6efd',
                 'Voucher': '#ffc107', 'Visit Pass': '#0dcaf0', 'Free': '#6c757d'}
        pay_datasets = [
            {
                'label':           pt,
                'data':            [monthly[m].get(pt, 0) for m in months_list],
                'backgroundColor': pcols.get(pt, '#999'),
            }
            for pt in PAYMENT_TYPES
        ]

        # Group sizes per session occurrence
        all_groups = sorted({a.group.name for sd in dates for a in sd.attendance if a.group})
        group_dates = [sd.date.isoformat() for sd in dates]
        group_datasets = [
            {
                'label':           g,
                'data':            [sum(1 for a in sd.attendance if a.group and a.group.name == g)
                                    for sd in dates],
                'backgroundColor': palette[i % len(palette)] + 'aa',
                'borderColor':     palette[i % len(palette)],
                'borderWidth': 1,
            }
            for i, g in enumerate(all_groups)
        ]

        # Totals
        total_sessions = len(dates)
        total_att      = sum(sd.total_attending for sd in dates)
        total_cash     = sum(sd.total_cash for sd in dates)
        total_card     = sum(sd.total_card for sd in dates)

        pay_totals = defaultdict(lambda: {'count': 0, 'amount': 0.0})
        for sd in dates:
            for a in sd.attendance:
                pay_totals[a.payment_type]['count']  += 1
                pay_totals[a.payment_type]['amount'] += float(a.amount or 0)

        session_summary = {}
        for sd in dates:
            sid = sd.session_id
            if sid not in session_summary:
                session_summary[sid] = {
                    'name': sd.template.name, 'count': 0,
                    'total_att': 0, 'total_cash': 0.0, 'total_card': 0.0,
                }
            session_summary[sid]['count']      += 1
            session_summary[sid]['total_att']  += sd.total_attending
            session_summary[sid]['total_cash'] += sd.total_cash
            session_summary[sid]['total_card'] += sd.total_card
        for v in session_summary.values():
            v['avg'] = round(v['total_att'] / v['count'], 1) if v['count'] else 0

        all_sessions = SessionTemplate.query.order_by(SessionTemplate.day_of_week).all()

        return render_template('reports.html',
            months=months, session_filter=session_filter, all_sessions=all_sessions,
            all_chart_dates=json.dumps(all_chart_dates),
            att_datasets=json.dumps(att_datasets),
            group_dates=json.dumps(group_dates),
            group_datasets=json.dumps(group_datasets),
            months_list=json.dumps(months_list),
            pay_datasets=json.dumps(pay_datasets),
            total_sessions=total_sessions, total_att=total_att,
            total_cash=total_cash, total_card=total_card,
            pay_totals=dict(pay_totals), session_summary=session_summary,
            PAYMENT_TYPES=PAYMENT_TYPES, PAYMENT_COLORS=PAYMENT_COLORS,
        )

    # ── Settings ─────────────────────────────────────────────────────

    @app.route('/settings', methods=['GET', 'POST'])
    def settings():
        if request.method == 'POST':
            name = request.form.get('club_name', '').strip() or 'My Badminton Club'
            Setting.set('club_name', name)
            flash('Settings saved.', 'success')
            return redirect(url_for('settings'))
        return render_template('settings.html')

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
        club = Setting.get('club_name', 'Badminton Club')
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
        ws4.append(['Coach'] + [sd.date.strftime('%d %b') for sd in sds] + ['Total'])
        for cell in ws4[1]:
            cell.font = hdr_font; cell.fill = hdr_fill
        for i, coach in enumerate(all_coaches):
            coached = {sd.id for sd in sds if coach in sd.coaches}
            ws4.append([coach.name]
                       + ['✓' if sd.id in coached else '' for sd in sds]
                       + [len(coached)])
            if i % 2:
                for cell in ws4[ws4.max_row]: cell.fill = alt_fill

        buf = io.BytesIO()
        wb.save(buf); buf.seek(0)
        fname = f"{club.replace(' ','_')}_{month_label.replace(' ','_')}.xlsx"
        return send_file(buf, as_attachment=True, download_name=fname,
                         mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')

    # ── API ──────────────────────────────────────────────────────────

    @app.route('/api/groups/<int:session_id>')
    def api_groups(session_id):
        groups = (Group.query.filter_by(session_id=session_id, active=True)
                  .order_by(Group.sort_order).all())
        return jsonify([{'id': g.id, 'name': g.name} for g in groups])

    return app


# ─── Helpers ────────────────────────────────────────────────────────

def _int(v):
    try:
        return int(v) if v else None
    except (TypeError, ValueError):
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


if __name__ == '__main__':
    import socket
    app  = create_app()
    port = _free_port()
    threading.Thread(
        target=lambda: (time.sleep(1.2), webbrowser.open(f'http://localhost:{port}')),
        daemon=True,
    ).start()
    print(f'\n  Badminton Club running at http://localhost:{port}')
    print('  Close this window (or press Ctrl+C) to stop.\n')
    app.run(host='127.0.0.1', port=port, debug=False, use_reloader=False)
