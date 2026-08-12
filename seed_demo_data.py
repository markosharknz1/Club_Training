"""
Seed the database with realistic FAKE demo data — for remote/cloud sessions
and testing only. Every name in here is fictional; no real club data.

Usage:  python seed_demo_data.py

Safety: refuses to run if the database already contains any players or
sessions, so it can never pollute a real club database. To re-seed a
sandbox, delete badminton.db first and run again.
"""
import random
import sys
from datetime import date, timedelta

from app import create_app
from models import (db, Player, SessionTemplate, Group, Coach, SessionDate,
                    Attendance, Voucher, sibling_links)

JUNIOR_NAMES = [
    'Ava Thompson', 'Liam Chen', 'Mia Patel', 'Noah Williams', 'Olivia Brown',
    'Ethan Davis', 'Sophie Wilson', 'Jack Taylor', 'Isla Martin', 'Lucas Anderson',
    'Ruby White', 'Oscar Harris', 'Grace Lewis', 'Charlie Walker', 'Zoe Hall',
    'Max Young', 'Lily King', 'Leo Wright',
]
SENIOR_NAMES = [
    'Sarah Mitchell', 'David Kumar', 'Emma Robertson', 'James Connor',
    'Priya Sharma', 'Tom Baker',
]
COACH_NAMES = ['Ana Silva', 'Ben Foster', 'Chris Ngata']

WEEKS_OF_HISTORY = 26


def _dates_for_weekday(weekday, weeks):
    """Past `weeks` occurrences of the given weekday, oldest first, up to today."""
    today = date.today()
    last = today - timedelta(days=(today.weekday() - weekday) % 7)
    return [last - timedelta(weeks=w) for w in range(weeks - 1, -1, -1)]


def seed():
    random.seed(42)

    if Player.query.count() or SessionTemplate.query.count():
        print('Refusing to seed: this database already contains data.')
        print('Seeding is only for fresh/empty databases (e.g. a cloud sandbox).')
        print('To re-seed a sandbox, delete badminton.db and run this again.')
        return False

    # ── Sessions & groups ────────────────────────────────────────────
    adv = SessionTemplate(name='Sunday Advanced', day_of_week=6,
                          start_time='09:00', end_time='10:30',
                          price_cash=10, price_card=10, category='Junior')
    beg = SessionTemplate(name='Sunday Beginner', day_of_week=6,
                          start_time='10:30', end_time='12:00',
                          price_cash=10, price_card=10, category='Junior')
    soc = SessionTemplate(name='Wednesday Social', day_of_week=2,
                          start_time='19:00', end_time='21:00',
                          price_cash=8, price_card=8, category='Senior')
    db.session.add_all([adv, beg, soc])
    db.session.flush()

    groups = {
        adv.id: [Group(session_id=adv.id, name=n, sort_order=i)
                 for i, n in enumerate(['Red Group', 'Blue Group'])],
        beg.id: [Group(session_id=beg.id, name=n, sort_order=i)
                 for i, n in enumerate(['Starters', 'Improvers'])],
        soc.id: [Group(session_id=soc.id, name='Social', sort_order=0)],
    }
    for gs in groups.values():
        db.session.add_all(gs)
    db.session.flush()

    # ── Coaches ──────────────────────────────────────────────────────
    coaches = [Coach(name=n, phone=f'02100000{i:02d}') for i, n in enumerate(COACH_NAMES)]
    db.session.add_all(coaches)
    db.session.flush()

    # ── Players ──────────────────────────────────────────────────────
    today = date.today()
    juniors, seniors = [], []
    for i, name in enumerate(JUNIOR_NAMES):
        tmpl = adv if i % 2 == 0 else beg
        grp  = random.choice(groups[tmpl.id])
        surname = name.split()[-1]
        juniors.append(Player(
            name=name, category='Junior',
            date_of_birth=today.replace(year=today.year - random.randint(7, 16)),
            guardian_name=f'{random.choice(["Sam", "Alex", "Jo", "Pat"])} {surname}',
            guardian_phone=f'0211{i:03d}999',
            default_session_id=tmpl.id, default_group_id=grp.id,
        ))
    for i, name in enumerate(SENIOR_NAMES):
        seniors.append(Player(
            name=name, category='Senior',
            date_of_birth=today.replace(year=today.year - random.randint(22, 55)),
            own_phone=f'0272{i:03d}888',
            own_email=f'{name.split()[0].lower()}@example.com',
            address=f'{10 + i} Example Street',
            default_session_id=soc.id, default_group_id=groups[soc.id][0].id,
        ))
    db.session.add_all(juniors + seniors)
    db.session.flush()

    # A sibling pair
    db.session.execute(sibling_links.insert().values(
        player_a_id=juniors[0].id, player_b_id=juniors[1].id))

    # ── Vouchers for a few juniors ───────────────────────────────────
    voucher_map = {}
    for p in juniors[:3]:
        v = Voucher(player_id=p.id, amount=100, sessions_total=10,
                    date_issued=today - timedelta(days=120),
                    notes='Demo voucher')
        db.session.add(v)
        db.session.flush()
        voucher_map[p.id] = v

    # ── Session history with attendance & coaches ────────────────────
    pools = {
        adv.id: [p for p in juniors if p.default_session_id == adv.id],
        beg.id: [p for p in juniors if p.default_session_id == beg.id],
        soc.id: seniors,
    }
    turnout = {adv.id: (6, 9), beg.id: (4, 7), soc.id: (3, 6)}
    voucher_uses = {pid: 0 for pid in voucher_map}

    for tmpl in (adv, beg, soc):
        for d in _dates_for_weekday(tmpl.day_of_week, WEEKS_OF_HISTORY):
            if d > today:
                continue
            sd = SessionDate(session_id=tmpl.id, date=d,
                             status='closed' if d < today else 'open')
            db.session.add(sd)
            db.session.flush()
            sd.coaches = random.sample(coaches, random.randint(1, 2))

            pool = pools[tmpl.id]
            lo, hi = turnout[tmpl.id]
            for p in random.sample(pool, min(random.randint(lo, hi), len(pool))):
                v = voucher_map.get(p.id)
                if v is not None and voucher_uses[p.id] < v.sessions_total and random.random() < 0.5:
                    pay, amount, vid = 'Sports Voucher', 0, v.id
                    voucher_uses[p.id] += 1
                else:
                    pay = random.choices(['Card', 'Cash', 'Visitor', 'Other'],
                                         weights=[55, 35, 5, 5])[0]
                    amount = float(tmpl.price_card) if pay in ('Card', 'Cash') else 0
                    vid = None
                db.session.add(Attendance(
                    session_date_id=sd.id, player_id=p.id,
                    group_id=p.default_group_id, payment_type=pay,
                    amount=amount, voucher_id=vid,
                ))

    db.session.commit()
    print(f'Seeded: {len(juniors)} juniors, {len(seniors)} seniors, '
          f'{len(coaches)} coaches, 3 sessions, ~{WEEKS_OF_HISTORY} weeks of history, '
          f'{len(voucher_map)} vouchers.')
    return True


if __name__ == '__main__':
    app = create_app()
    with app.app_context():
        ok = seed()
    sys.exit(0 if ok else 1)
