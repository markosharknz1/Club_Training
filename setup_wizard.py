"""
First-run installer for the packaged (zip) copy of Club Training.

The zip can be extracted anywhere — including places the live database must
never live (Documents / OneDrive, where sync corrupts SQLite). So the first
run shows a small setup window: where to install (default
C:\\Apps\\Club_Training; Documents/OneDrive/Temp are refused with an
explanation), a desktop-shortcut tickbox, then it copies the app there and
starts the installed copy. launch.py owns the window and process lifecycle;
this module is the Flask app + install logic only.

Markers (`.setup-complete` beside launch.py):
  - installed copy:  "setup completed <timestamp>"
  - the folder setup was RUN from (the download): "installed-to=<path>", so
    double-clicking the downloaded copy again just opens the installed app.

Installing into a folder that already holds an install is an upgrade: app
files are refreshed, `badminton.db` and `backups` there are never touched
(leftovers from the old .exe-based layout are cleaned up).

Only the packaged copy ever sees this — running from source (run.bat / dev)
skips it entirely.
"""
import os
import re
import shutil
import subprocess
import sys
import threading
from datetime import datetime

import config

DEFAULT_INSTALL_DIR = r'C:\Apps\Club_Training'
MARKER_NAME = '.setup-complete'

# Never copied into the destination: the destination's own club data and
# transient files. badminton.db in the SOURCE is also never copied — a fresh
# install creates its own, and an upgrade must keep the destination's.
COPY_IGNORE = shutil.ignore_patterns(
    'badminton.db*', 'backups', MARKER_NAME, 'logs', '*.log',
    '.edge-app-profile', '.edge-setup-profile', '__pycache__')

# Files/folders from the old PyInstaller-exe layout (v1.8.0 and earlier)
# that an upgrade should clear out of the destination.
OLD_LAYOUT = ('Club_Training.exe', '_internal')


def _marker_path(base=None):
    return os.path.join(base or config.BASE_DIR, MARKER_NAME)


def first_run():
    return not os.path.exists(_marker_path())


def installed_elsewhere():
    """The install folder to hand over to when THIS folder was only the
    download that setup installed from — else None."""
    try:
        with open(_marker_path(), 'r', encoding='utf-8', errors='replace') as f:
            content = f.read()
    except OSError:
        return None
    m = re.match(r'installed-to=(.+)', content.strip())
    if not m:
        return None
    dest = os.path.normpath(m.group(1).strip())
    if (dest.lower() != os.path.normpath(config.BASE_DIR).lower()
            and os.path.exists(os.path.join(dest, 'python', 'pythonw.exe'))
            and os.path.exists(os.path.join(dest, 'launch.py'))):
        return dest
    return None


def _documents_dir():
    """The user's real Documents folder — OneDrive commonly redirects it, so
    resolve from the registry rather than assuming ~/Documents."""
    try:
        import winreg
        with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r'Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders') as key:
            value, _ = winreg.QueryValueEx(key, 'Personal')
        return os.path.expandvars(value)
    except OSError:
        return os.path.join(os.path.expanduser('~'), 'Documents')


def install_dir_problem(path):
    """A plain-English reason the folder can't hold the app, or None if OK."""
    path = (path or '').strip().strip('"')
    if not path:
        return 'Choose a folder to install to.'
    if not re.match(r'^[A-Za-z]:\\', path):
        return 'Use a full folder path, like C:\\Apps\\Club_Training.'
    try:
        full = os.path.normpath(os.path.abspath(path))
    except (OSError, ValueError):
        return 'That is not a valid folder path.'
    docs = os.path.normpath(_documents_dir()).lower().rstrip('\\')
    if docs and (full.lower() + '\\').startswith(docs + '\\'):
        return ("Please don't install in your Documents folder — it's usually "
                "synced by OneDrive, and syncing the app's live database "
                "corrupts it. The app already saves daily backups to "
                "Documents automatically; the app itself just can't live "
                "there. The suggested folder is fine.")
    if re.search(r'\\onedrive', full, re.I):
        return ("Please don't install in a OneDrive folder — syncing the "
                "app's live database while it's in use corrupts it. The "
                "suggested folder is fine.")
    if re.search(r'\\(temp|tmp)(\\|$)', full, re.I):
        return ("That's a temporary folder — Windows may clean it out. "
                "Choose somewhere permanent, like the suggested folder.")
    return None


def perform_install(dest, make_shortcut):
    """Copy the app to `dest`, write both markers, optionally create a
    desktop shortcut. Returns the destination folder (may be this very
    folder when dest == the current folder)."""
    src = os.path.normpath(config.BASE_DIR)
    dest = os.path.normpath(os.path.abspath(dest))
    stamp = f'setup completed {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}'

    if dest.lower() != src.lower():
        os.makedirs(dest, exist_ok=True)
        try:
            shutil.copytree(src, dest, dirs_exist_ok=True, ignore=COPY_IGNORE)
        except PermissionError as e:
            raise RuntimeError(
                'Could not copy the app — if Club Training is already running '
                f'from {dest}, close it first and run setup again. ({e})')
        _remove_old_layout(dest)
        with open(_marker_path(dest), 'w', encoding='utf-8') as f:
            f.write(stamp + '\n')
        # remember where it went, so this downloaded copy hands over next time
        with open(_marker_path(src), 'w', encoding='utf-8') as f:
            f.write(f'installed-to={dest}\n')
    else:
        with open(_marker_path(src), 'w', encoding='utf-8') as f:
            f.write(stamp + '\n')

    if make_shortcut:
        _create_desktop_shortcut(dest)
    return dest


def _remove_old_layout(dest):
    """Upgrading over a v1.8.0-or-earlier install: clear the PyInstaller
    exe and its _internal folder so the old (unsigned) binary doesn't
    linger beside the new layout. Scoped strictly to known names in dest."""
    for name in OLD_LAYOUT:
        target = os.path.join(dest, name)
        try:
            if os.path.isdir(target):
                shutil.rmtree(target)
            elif os.path.exists(target):
                os.remove(target)
        except OSError:
            pass  # a locked leftover is harmless — never fail the install


def _create_desktop_shortcut(dest):
    """Best-effort — never blocks the install over a shortcut. Targets the
    bundled (signed) pythonw.exe running launch.py."""
    pythonw = os.path.join(dest, 'python', 'pythonw.exe')
    launch = os.path.join(dest, 'launch.py')
    icon = os.path.join(dest, 'static', 'icon.ico')
    script = (
        "$s = (New-Object -ComObject WScript.Shell)."
        "CreateShortcut([System.IO.Path]::Combine("
        "[Environment]::GetFolderPath('Desktop'), 'Club Training.lnk')); "
        f"$s.TargetPath = '{pythonw}'; "
        f"$s.Arguments = '\"{launch}\"'; "
        f"$s.WorkingDirectory = '{dest}'; "
        f"$s.IconLocation = '{icon}'; "
        "$s.Description = 'Club Training'; $s.Save()")
    try:
        subprocess.run(['powershell', '-NoProfile', '-Command', script],
                       capture_output=True, timeout=30,
                       creationflags=subprocess.CREATE_NO_WINDOW)
    except Exception:
        pass


def launch_installed(dest):
    """Start the installed copy, fully detached from this process.

    Explicit DEVNULL std handles: under pythonw.exe the standard handles
    are invalid and Popen can fail to spawn at all without them.
    """
    pythonw = os.path.join(dest, 'python', 'pythonw.exe')
    subprocess.Popen(
        [pythonw, os.path.join(dest, 'launch.py')], cwd=dest, close_fds=True,
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP)


def build_setup_app(template_folder, static_folder):
    """A tiny standalone Flask app for the setup window — deliberately does
    NOT touch the club database at all. The caller (launch.py) watches
    `setup_state`: `event` is set once `result` is 'installed' (with `dest`
    filled in) or 'cancelled', and the caller then launches the installed
    copy and closes the window."""
    from flask import Flask, jsonify, render_template, request

    setup_app = Flask('club_training_setup',
                      template_folder=template_folder,
                      static_folder=static_folder)
    state = {'result': None, 'dest': None, 'event': threading.Event()}

    @setup_app.route('/')
    @setup_app.route('/setup')
    def setup_page():
        current_ok = install_dir_problem(config.BASE_DIR) is None
        return render_template(
            'setup.html',
            default_dir=DEFAULT_INSTALL_DIR,
            current_dir=os.path.normpath(config.BASE_DIR),
            current_ok=current_ok)

    @setup_app.route('/api/check', methods=['POST'])
    def api_check():
        problem = install_dir_problem((request.get_json() or {}).get('dir', ''))
        return jsonify(ok=problem is None, problem=problem)

    @setup_app.route('/api/install', methods=['POST'])
    def api_install():
        data = request.get_json() or {}
        dest = (data.get('dir') or '').strip().strip('"')
        problem = install_dir_problem(dest)
        if problem:
            return jsonify(ok=False, error=problem)
        try:
            installed = perform_install(dest, bool(data.get('shortcut')))
        except (RuntimeError, OSError) as e:
            return jsonify(ok=False, error=str(e))

        def _finish():
            state['dest'] = installed
            state['result'] = 'installed'
            state['event'].set()

        # reply first (so the page can show "setup complete"), then signal
        threading.Timer(1.2, _finish).start()
        return jsonify(ok=True, dest=installed)

    @setup_app.route('/api/cancel', methods=['POST'])
    def api_cancel():
        state['result'] = 'cancelled'
        state['event'].set()
        return jsonify(ok=True)

    setup_app.setup_state = state

    return setup_app
