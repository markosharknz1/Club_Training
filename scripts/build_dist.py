#!/usr/bin/env python3
r"""
Assemble the distributable Club_Training folder — no compiled code of ours.

The result is: the app's own Python source + templates/static, its
dependencies as pure Python in lib\, and the official python.org embeddable
runtime (every binary signed by the Python Software Foundation) in python\.
The only script is "Club Training.cmd". Nothing here needs code signing by
us, which is what keeps SmartScreen / Smart App Control quiet.

Used by .github/workflows/release.yml, and runnable locally:

    python scripts/build_dist.py [--out dist/Club_Training]
"""
import argparse
import glob
import hashlib
import os
import re
import shutil
import subprocess
import sys
import urllib.request
import zipfile

PY_EMBED_VERSION = '3.12.10'
PY_EMBED_SHA256 = '4acbed6dd1c744b0376e3b1cf57ce906f9dc9e95e68824584c8099a63025a3c3'
PY_EMBED_URL = (f'https://www.python.org/ftp/python/{PY_EMBED_VERSION}/'
                f'python-{PY_EMBED_VERSION}-embed-amd64.zip')

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

APP_FILES = ['app.py', 'models.py', 'config.py', 'setup_wizard.py',
             'native_window.py', 'launch.py', 'Club Training.cmd',
             'README.md', 'SECURITY.md']
APP_DIRS = ['templates', 'static']

# Optional native accelerators whose packages fall back to pure Python
# (markupsafe, sqlalchemy's cyextension), pip's script shims, and packages
# we deliberately don't ship: greenlet (only needed for SQLAlchemy asyncio,
# which this app never uses) and Pillow (reportlab optional dep — our PDFs
# are text/tables only).
PRUNE_DIR_NAMES = {'__pycache__', 'bin', 'Scripts', 'include'}
PRUNE_PACKAGES = ('greenlet', 'PIL', 'pillow')
BINARY_EXTS = {'.pyd', '.dll', '.exe', '.so'}
FORBIDDEN_SCRIPT_EXTS = {'.ps1', '.vbs', '.wsf', '.bat'}


def log(msg):
    print(f'  {msg}', flush=True)


def fetch_embeddable(cache_dir):
    os.makedirs(cache_dir, exist_ok=True)
    path = os.path.join(cache_dir, os.path.basename(PY_EMBED_URL))
    if not os.path.exists(path) or _sha256(path) != PY_EMBED_SHA256:
        log(f'downloading {PY_EMBED_URL}')
        urllib.request.urlretrieve(PY_EMBED_URL, path)
    digest = _sha256(path)
    if digest != PY_EMBED_SHA256:
        raise SystemExit(f'embeddable Python checksum mismatch: {digest}')
    log(f'embeddable Python {PY_EMBED_VERSION} verified ({digest[:16]}…)')
    return path


def _sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def install_runtime(zip_path, out):
    py_dir = os.path.join(out, 'python')
    with zipfile.ZipFile(zip_path) as z:
        z.extractall(py_dir)
    # Point sys.path at the app root and lib\ (paths are relative to the
    # exe's folder). Site is deliberately left off — nothing else may
    # sneak onto the path.
    pth = glob.glob(os.path.join(py_dir, 'python3*._pth'))
    if len(pth) != 1:
        raise SystemExit(f'expected one ._pth file, found {pth}')
    zip_line = f'python{"".join(PY_EMBED_VERSION.split(".")[:2])}.zip'
    with open(pth[0], 'w', encoding='ascii') as f:
        f.write(f'{zip_line}\n.\n..\n..\\lib\n')
    log(f'runtime installed to python\\ ({zip_line} + app root + lib on path)')


def install_deps(out):
    lib = os.path.join(out, 'lib')
    req = os.path.join(ROOT, 'requirements.txt')
    log('pip install --target lib\\ (this takes a minute)…')
    subprocess.run(
        [sys.executable, '-m', 'pip', 'install', '--quiet',
         '--target', lib, '-r', req, '--no-warn-script-location'],
        check=True)
    _force_pure_charset_normalizer(lib)
    _prune(lib)
    log('dependencies installed (pure Python)')


def _force_pure_charset_normalizer(lib):
    """charset_normalizer's Windows wheel is mypyc-COMPILED (its .pyd
    replaces the .py, so deleting it would break the package). Reinstall
    from source, which builds pure Python when mypyc isn't requested."""
    if not glob.glob(os.path.join(lib, 'charset_normalizer', '*.pyd')):
        return
    info = glob.glob(os.path.join(lib, 'charset_normalizer-*.dist-info'))
    version = re.search(r'charset_normalizer-([\d.]+)\.dist-info',
                        info[0]).group(1)
    for path in glob.glob(os.path.join(lib, 'charset_normalizer*')):
        shutil.rmtree(path) if os.path.isdir(path) else os.remove(path)
    env = dict(os.environ, CHARSET_NORMALIZER_USE_MYPYC='0')
    log(f'rebuilding charset_normalizer=={version} as pure Python…')
    subprocess.run(
        [sys.executable, '-m', 'pip', 'install', '--quiet', '--no-deps',
         '--no-binary', 'charset_normalizer', '--target', lib,
         f'charset_normalizer=={version}'],
        check=True, env=env)


def _prune(lib):
    for name in os.listdir(lib):
        base = name.split('-')[0].split('.')[0].lower()
        if name in PRUNE_DIR_NAMES or base in [p.lower() for p in PRUNE_PACKAGES]:
            path = os.path.join(lib, name)
            shutil.rmtree(path) if os.path.isdir(path) else os.remove(path)
    removed = 0
    for root, dirs, files in os.walk(lib):
        dirs[:] = [d for d in dirs if d not in PRUNE_DIR_NAMES]
        for fn in files:
            if os.path.splitext(fn)[1].lower() in BINARY_EXTS:
                os.remove(os.path.join(root, fn))
                removed += 1
    log(f'pruned optional native accelerators ({removed} binary files)')


def copy_app(out):
    for fn in APP_FILES:
        shutil.copy2(os.path.join(ROOT, fn), os.path.join(out, fn))
    for d in APP_DIRS:
        shutil.copytree(os.path.join(ROOT, d), os.path.join(out, d),
                        ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    log('app files copied')


def verify(out):
    """The whole trust story in one check: every executable binary lives in
    python\\ (signed by the PSF), and the only Windows script anywhere is
    Club Training.cmd at the root."""
    problems = []
    for root, dirs, files in os.walk(out):
        rel_root = os.path.relpath(root, out)
        in_python = rel_root == 'python' or rel_root.startswith('python' + os.sep)
        for fn in files:
            ext = os.path.splitext(fn)[1].lower()
            rel = os.path.join(rel_root, fn)
            if ext in BINARY_EXTS and not in_python:
                problems.append(f'binary outside python\\: {rel}')
            if ext in FORBIDDEN_SCRIPT_EXTS:
                problems.append(f'forbidden script type: {rel}')
            if ext == '.cmd' and rel != os.path.join('.', 'Club Training.cmd'):
                problems.append(f'unexpected .cmd: {rel}')
    if problems:
        raise SystemExit('DIST VERIFY FAILED:\n  ' + '\n  '.join(problems))
    total = sum(os.path.getsize(os.path.join(r, f))
                for r, _, fs in os.walk(out) for f in fs)
    log(f'verified: no binaries outside python\\, no stray scripts '
        f'({total / 1e6:.1f} MB total)')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', default=os.path.join(ROOT, 'dist', 'Club_Training'))
    ap.add_argument('--cache', default=os.path.join(ROOT, 'build', 'cache'))
    args = ap.parse_args()

    out = os.path.abspath(args.out)
    if os.path.exists(out):
        shutil.rmtree(out)
    os.makedirs(out)

    copy_app(out)
    install_deps(out)
    install_runtime(fetch_embeddable(os.path.abspath(args.cache)), out)
    verify(out)
    print(f'\nDone: {out}')


if __name__ == '__main__':
    main()
