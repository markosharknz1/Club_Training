from flask_sqlalchemy import SQLAlchemy
from datetime import date as date_t, datetime

db = SQLAlchemy()

PAYMENT_TYPES  = ['Cash', 'Card', 'Sports Voucher', 'Visitor', 'Other']
AMOUNT_TYPES   = {'Cash', 'Card'}       # these record a dollar amount
DAY_NAMES      = ['Monday', 'Tuesday', 'Wednesday', 'Thursday',
                  'Friday', 'Saturday', 'Sunday']
PAYMENT_COLORS = {
    'Cash':           'success',
    'Card':           'primary',
    'Sports Voucher': 'warning',
    'Visitor':        'info',
    'Other':          'secondary',
}

# A family may split a Sports Voucher's value across multiple activities
# (e.g. part on badminton, part on footy), so each voucher a family brings
# to the club must be registered here before it can be redeemed for sessions.
# Standard voucher: $100, redeemable for 10 sessions at this club.
DEFAULT_VOUCHER_AMOUNT   = 100
DEFAULT_VOUCHER_SESSIONS = 10


class Setting(db.Model):
    __tablename__ = 'settings'
    key   = db.Column(db.String(100), primary_key=True)
    value = db.Column(db.Text)

    @staticmethod
    def get(key, default=''):
        row = Setting.query.get(key)
        return row.value if row else default

    @staticmethod
    def set(key, value):
        row = Setting.query.get(key)
        if row:
            row.value = str(value)
        else:
            db.session.add(Setting(key=key, value=str(value)))
        db.session.commit()


class SessionTemplate(db.Model):
    """A recurring training session definition (e.g. 'Tuesday Juniors 6–8 pm')."""
    __tablename__ = 'session_templates'
    id           = db.Column(db.Integer, primary_key=True)
    name         = db.Column(db.String(100), nullable=False)
    day_of_week  = db.Column(db.Integer, nullable=False)   # 0=Mon … 6=Sun
    start_time   = db.Column(db.String(5),  nullable=False) # HH:MM
    end_time     = db.Column(db.String(5),  nullable=False)
    price_cash   = db.Column(db.Numeric(8, 2), default=0)
    price_card   = db.Column(db.Numeric(8, 2), default=0)
    category     = db.Column(db.String(10), default='Mixed', nullable=False)  # Junior | Senior | Mixed
    active       = db.Column(db.Boolean, default=True, nullable=False)

    groups = db.relationship('Group', backref='session', lazy=True,
                              order_by='Group.sort_order',
                              cascade='all, delete-orphan')
    dates  = db.relationship('SessionDate', backref='template', lazy=True)

    @property
    def day_name(self):
        return DAY_NAMES[self.day_of_week]

    @property
    def display(self):
        return f'{self.name} ({self.day_name} {self.start_time}–{self.end_time})'

    @property
    def active_groups(self):
        return [g for g in self.groups if g.active]

    @property
    def total_checkins(self):
        """Total kid-visits ever recorded for this session (all occurrences)."""
        return sum(sd.total_attending for sd in self.dates)

    @property
    def total_collected(self):
        """Total Cash + Card money ever collected for this session (all occurrences)."""
        return sum(sd.total_cash + sd.total_card for sd in self.dates)


class Group(db.Model):
    __tablename__ = 'groups'
    id         = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.Integer, db.ForeignKey('session_templates.id'), nullable=False)
    name       = db.Column(db.String(100), nullable=False)
    sort_order = db.Column(db.Integer, default=0)
    active     = db.Column(db.Boolean, default=True, nullable=False)


class Coach(db.Model):
    __tablename__ = 'coaches'
    id        = db.Column(db.Integer, primary_key=True)
    name      = db.Column(db.String(150), nullable=False)
    phone     = db.Column(db.String(30))
    email     = db.Column(db.String(150))
    pay_rate  = db.Column(db.Numeric(8, 2), nullable=False, default=0)  # whole dollars; 0 = volunteer
    pay_basis = db.Column(db.String(10), nullable=False, default='session')  # 'session' | 'hour'
    notes     = db.Column(db.String(200))
    active    = db.Column(db.Boolean, default=True, nullable=False)

    @property
    def is_volunteer(self):
        return float(self.pay_rate or 0) == 0


class CoachAttendance(db.Model):
    """One row per coach per session occurrence, carrying a SNAPSHOT of the
    coach's rate and basis at the time of marking — so a later rate change
    never silently rewrites an already-generated month's pay report.
    `amount` is likewise stored, not recomputed on read."""
    __tablename__ = 'coach_attendance'
    id                = db.Column(db.Integer, primary_key=True)
    session_date_id   = db.Column(db.Integer, db.ForeignKey('session_dates.id'), nullable=False)
    coach_id          = db.Column(db.Integer, db.ForeignKey('coaches.id'), nullable=False)
    hours             = db.Column(db.Numeric(5, 2))                      # only for basis 'hour'
    rate_snapshot     = db.Column(db.Numeric(8, 2), nullable=False, default=0)
    basis_snapshot    = db.Column(db.String(10), nullable=False, default='session')
    amount            = db.Column(db.Numeric(8, 2), nullable=False, default=0)
    adjustment        = db.Column(db.Numeric(8, 2), nullable=False, default=0)  # manual +/- (travel, cover…)
    adjustment_reason = db.Column(db.String(200))
    marked_at         = db.Column(db.DateTime, default=datetime.utcnow)
    paid              = db.Column(db.Boolean, nullable=False, default=False)
    paid_date         = db.Column(db.Date)
    payment_reference = db.Column(db.String(100))   # e.g. bank transfer ref

    coach        = db.relationship('Coach')
    session_date = db.relationship('SessionDate', backref='coach_attendance')

    __table_args__ = (db.UniqueConstraint('session_date_id', 'coach_id'),)

    @property
    def net_amount(self):
        return float(self.amount or 0) + float(self.adjustment or 0)


sibling_links = db.Table('sibling_links',
    db.Column('player_a_id', db.Integer, db.ForeignKey('players.id'), primary_key=True),
    db.Column('player_b_id', db.Integer, db.ForeignKey('players.id'), primary_key=True),
)


class Player(db.Model):
    __tablename__ = 'players'
    id                 = db.Column(db.Integer, primary_key=True)
    name               = db.Column(db.String(150), nullable=False)
    date_of_birth      = db.Column(db.Date)
    guardian_name      = db.Column(db.String(150))
    guardian_phone     = db.Column(db.String(30))
    guardian_email     = db.Column(db.String(150))
    medicare_number    = db.Column(db.String(30))
    category           = db.Column(db.String(10), default='Junior', nullable=False)  # Junior | Senior
    rego_number        = db.Column(db.String(20))   # club registration number, from the member register
    membership_type    = db.Column(db.String(30))   # e.g. Junior / Social / Comp A-C
    membership_status  = db.Column(db.String(30))   # e.g. Paid
    address            = db.Column(db.String(250))
    own_email          = db.Column(db.String(150))
    own_phone          = db.Column(db.String(30))
    default_session_id = db.Column(db.Integer, db.ForeignKey('session_templates.id'))
    default_group_id   = db.Column(db.Integer, db.ForeignKey('groups.id'))
    active             = db.Column(db.Boolean, default=True, nullable=False)
    notes              = db.Column(db.Text)
    created_at         = db.Column(db.DateTime, default=datetime.utcnow)

    default_session = db.relationship('SessionTemplate', foreign_keys=[default_session_id])
    default_group   = db.relationship('Group',           foreign_keys=[default_group_id])
    attendance_records = db.relationship('Attendance', backref='player', lazy=True,
                                          cascade='all, delete-orphan')

    siblings_a = db.relationship('Player', secondary=sibling_links,
                                  primaryjoin=sibling_links.c.player_a_id == id,
                                  secondaryjoin=sibling_links.c.player_b_id == id,
                                  lazy='dynamic')
    siblings_b = db.relationship('Player', secondary=sibling_links,
                                  primaryjoin=sibling_links.c.player_b_id == id,
                                  secondaryjoin=sibling_links.c.player_a_id == id,
                                  lazy='dynamic', overlaps='siblings_a')

    @property
    def siblings(self):
        return list(self.siblings_a) + list(self.siblings_b)

    @property
    def age(self):
        if not self.date_of_birth:
            return None
        today = date_t.today()
        return (today.year - self.date_of_birth.year
                - ((today.month, today.day) < (self.date_of_birth.month,
                                                self.date_of_birth.day)))

    @property
    def total_attended(self):
        return sum(1 for a in self.attendance_records)


_sd_coaches = db.Table('session_date_coaches',
    db.Column('session_date_id', db.Integer, db.ForeignKey('session_dates.id'), primary_key=True),
    db.Column('coach_id',        db.Integer, db.ForeignKey('coaches.id'),        primary_key=True),
)


class SessionDate(db.Model):
    """A specific date on which a SessionTemplate was run."""
    __tablename__ = 'session_dates'
    id               = db.Column(db.Integer, primary_key=True)
    session_id       = db.Column(db.Integer, db.ForeignKey('session_templates.id'), nullable=False)
    date             = db.Column(db.Date, nullable=False)
    status           = db.Column(db.String(20), default='open', nullable=False)  # open | closed
    notes            = db.Column(db.Text)
    closed_at        = db.Column(db.DateTime)
    created_at       = db.Column(db.DateTime, default=datetime.utcnow)
    active_group_ids = db.Column(db.Text)  # JSON list of Group IDs; null = all groups

    attendance = db.relationship('Attendance', backref='session_date', lazy=True,
                                  cascade='all, delete-orphan')
    coaches    = db.relationship('Coach', secondary=_sd_coaches, lazy='subquery')

    @property
    def total_attending(self):
        return len(self.attendance)

    @property
    def total_cash(self):
        return sum(float(a.amount or 0) for a in self.attendance if a.payment_type == 'Cash')

    @property
    def total_card(self):
        return sum(float(a.amount or 0) for a in self.attendance if a.payment_type == 'Card')

    @property
    def payment_summary(self):
        counts = {}
        for a in self.attendance:
            counts[a.payment_type] = counts.get(a.payment_type, 0) + 1
        return counts

    @property
    def day_active_groups(self):
        """Groups running for this specific session date (subset of template groups)."""
        import json as _j
        if not self.active_group_ids:
            return self.template.active_groups
        try:
            ids = set(_j.loads(self.active_group_ids))
        except Exception:
            return self.template.active_groups
        return [g for g in self.template.active_groups if g.id in ids]

    @property
    def group_summary(self):
        counts = {}
        for a in self.attendance:
            g = a.group.name if a.group else 'No group'
            counts[g] = counts.get(g, 0) + 1
        return counts


class Voucher(db.Model):
    """A Sports Voucher a family has brought to the club to redeem for sessions.

    Vouchers are issued externally (e.g. by a council/community scheme) and a
    family may split one across multiple activities — so each voucher must be
    registered here before attendance can be paid for with it.
    """
    __tablename__ = 'vouchers'
    id             = db.Column(db.Integer, primary_key=True)
    player_id      = db.Column(db.Integer, db.ForeignKey('players.id'), nullable=False)
    voucher_number = db.Column(db.String(50))
    amount         = db.Column(db.Numeric(8, 2), nullable=False, default=DEFAULT_VOUCHER_AMOUNT)
    sessions_total = db.Column(db.Integer, nullable=False, default=DEFAULT_VOUCHER_SESSIONS)
    date_issued    = db.Column(db.Date, nullable=False, default=date_t.today)
    notes          = db.Column(db.String(200))
    created_at     = db.Column(db.DateTime, default=datetime.utcnow)

    player = db.relationship('Player', backref='vouchers')

    @property
    def sessions_used(self):
        return len(self.attendance_records)

    @property
    def sessions_remaining(self):
        return max(self.sessions_total - self.sessions_used, 0)

    @property
    def year(self):
        return self.date_issued.year


class Attendance(db.Model):
    __tablename__ = 'attendance'
    id              = db.Column(db.Integer, primary_key=True)
    session_date_id = db.Column(db.Integer, db.ForeignKey('session_dates.id'), nullable=False)
    player_id       = db.Column(db.Integer, db.ForeignKey('players.id'),       nullable=False)
    group_id        = db.Column(db.Integer, db.ForeignKey('groups.id'))
    payment_type    = db.Column(db.String(30), nullable=False, default='Cash')
    amount          = db.Column(db.Numeric(8, 2), default=0)
    voucher_id      = db.Column(db.Integer, db.ForeignKey('vouchers.id'))
    notes           = db.Column(db.Text)
    marked_at       = db.Column(db.DateTime, default=datetime.utcnow)

    group   = db.relationship('Group')
    voucher = db.relationship('Voucher', backref='attendance_records')

    __table_args__ = (db.UniqueConstraint('session_date_id', 'player_id'),)
