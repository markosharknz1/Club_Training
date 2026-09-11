"""
Scan a release file with VirusTotal and print the public analysis link.

Usage:
    set VT_API_KEY=<your key>          (once per machine, or a user env var)
    python scripts/vt_scan.py dist/Club_Training_v1.7.0.zip

- Reuses an existing VirusTotal report when the file has been scanned before
  (lookup by SHA-256), otherwise uploads it (handles files over 32 MB via the
  large-file upload URL) and waits for the analysis to finish.
- Prints the SHA-256, the permalink, and a per-engine summary suitable for
  pasting into GitHub release notes.
- The API key is read from the VT_API_KEY environment variable only — never
  hard-code it and never commit it.
"""
import hashlib
import os
import sys
import time

import requests

API = 'https://www.virustotal.com/api/v3'


def sha256_of(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def main():
    if len(sys.argv) != 2:
        sys.exit('usage: python scripts/vt_scan.py <file>')
    path = sys.argv[1]
    key = os.environ.get('VT_API_KEY', '').strip()
    if not key:
        sys.exit('Set the VT_API_KEY environment variable first '
                 '(VirusTotal → profile → API key).')
    headers = {'x-apikey': key}
    digest = sha256_of(path)
    size_mb = os.path.getsize(path) / 1048576
    print(f'file:    {os.path.basename(path)} ({size_mb:.1f} MB)')
    print(f'sha256:  {digest}')

    # Already known to VirusTotal?
    r = requests.get(f'{API}/files/{digest}', headers=headers, timeout=60)
    if r.status_code == 404:
        print('not seen before — uploading…')
        if size_mb > 30:
            up = requests.get(f'{API}/files/upload_url', headers=headers,
                              timeout=60).json()['data']
        else:
            up = f'{API}/files'
        with open(path, 'rb') as f:
            r2 = requests.post(up, headers=headers,
                               files={'file': (os.path.basename(path), f)},
                               timeout=600)
        r2.raise_for_status()
        analysis_id = r2.json()['data']['id']
        print('uploaded — waiting for analysis', end='', flush=True)
        while True:
            time.sleep(20)
            a = requests.get(f'{API}/analyses/{analysis_id}', headers=headers,
                             timeout=60).json()
            status = a['data']['attributes']['status']
            print('.', end='', flush=True)
            if status == 'completed':
                print()
                break
        r = requests.get(f'{API}/files/{digest}', headers=headers, timeout=60)
    r.raise_for_status()

    stats = r.json()['data']['attributes']['last_analysis_stats']
    results = r.json()['data']['attributes']['last_analysis_results']
    flagged = [(eng, res['result']) for eng, res in results.items()
               if res['category'] in ('malicious', 'suspicious')]
    total = sum(stats.get(k, 0) for k in
                ('malicious', 'suspicious', 'undetected', 'harmless'))
    link = f'https://www.virustotal.com/gui/file/{digest}'
    print(f'\nresult:  {stats.get("malicious", 0) + stats.get("suspicious", 0)}'
          f'/{total} engines flagged it')
    for eng, what in flagged:
        print(f'         - {eng}: {what}')
    print(f'link:    {link}')

    print('\n--- paste into release notes ---')
    print(f'**Verify your download**')
    print(f'- SHA-256: `{digest}`')
    print(f'- VirusTotal: {link} '
          f'({stats.get("malicious", 0) + stats.get("suspicious", 0)}/{total} '
          'engines flagged at publish time)')


if __name__ == '__main__':
    main()
