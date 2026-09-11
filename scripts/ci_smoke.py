"""
CI smoke test: boot the app against a fresh temp database and check the key
pages respond. Runs in GitHub Actions before every build, and works locally:
    python scripts/ci_smoke.py
"""
import os
import sys
import tempfile
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config

config.DB_PATH = os.path.join(tempfile.mkdtemp(), 'ci_smoke.db')

from app import create_app, APP_VERSION  # noqa: E402

app = create_app()
client = app.test_client()

failures = []


def check(label, cond):
    print(('PASS' if cond else 'FAIL'), '-', label)
    if not cond:
        failures.append(label)


pages = [
    f'/day/{date.today().isoformat()}',
    '/players',
    '/vouchers',
    '/coaches',
    '/reports',
    '/settings/identity',
    '/settings/email',
    '/settings/about',
    '/api/branding/icon',
]
for url in pages:
    r = client.get(url, follow_redirects=True)
    check(f'GET {url} -> 200', r.status_code == 200)

r = client.get('/settings/about')
check('about page shows APP_VERSION', APP_VERSION.encode() in r.data)

if failures:
    print(f'\n{len(failures)} FAILURES: {failures}')
    sys.exit(1)
print(f'\nALL PASS — Club Training {APP_VERSION} boots clean on a fresh database')
