"""
First-run installer for the standalone Club_Training.exe.

The zip can be extracted anywhere — including places the live database must
never live (Documents / OneDrive, where sync corrupts SQLite). So the first
run of the exe shows a small setup window in the app's own native window:
where to install (default C:\\Apps\\Club_Training; Documents/OneDrive/Temp
are refused with an explanation), a desktop-shortcut tickbox, then it copies
the app there, and starts the installed copy.

Markers (`.setup-complete` beside the exe):
  - installed copy:  "setup completed <timestamp>"
  - the folder setup was RUN from (the download): "installed-to=<path>", so
    double-clicking the downloaded copy again just opens the installed app.

Installing into a folder that already holds an install is an upgrade: app
files are refreshed, `badminton.db` and `backups` there are never touched.

Only the frozen exe ever sees this — running from source (run.bat / dev)
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
    'badminton.db*', 'backups', MARKER_NAME, 'logs', '*.log')


def _marker_path(base=None):
    return os.path.join(base or config.BASE_DIR, MARKER_NAME)


def first_run():
    return not os.path.exists(_marker_path())


def installed_elsewhere():
    """The exe path to hand over to when THIS folder was only the download
    that setup installed from — else None."""
    try:
        with open(_marker_path(), 'r', encoding='utf-8', errors='replace') as f:
            content = f.read()
    except OSError:
        return None
    m = re.match(r'installed-to=(.+)', content.strip())
    if not m:
        return None
    dest = os.path.normpath(m.group(1).strip())
    exe = os.path.join(dest, 'Club_Training.exe')
    if dest.lower() != os.path.normpath(config.BASE_DIR).lower() and os.path.exists(exe):
        return exe
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
    desktop shortcut. Returns the destination exe path (may be this very
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
    return os.path.join(dest, 'Club_Training.exe')


def _create_desktop_shortcut(dest):
    """Best-effort — never blocks the install over a shortcut."""
    exe = os.path.join(dest, 'Club_Training.exe')
    script = (
        "$s = (New-Object -ComObject WScript.Shell)."
        "CreateShortcut([System.IO.Path]::Combine("
        "[Environment]::GetFolderPath('Desktop'), 'Club Training.lnk')); "
        f"$s.TargetPath = '{exe}'; "
        f"$s.WorkingDirectory = '{dest}'; "
        f"$s.IconLocation = '{exe}'; "
        "$s.Description = 'Club Training'; $s.Save()")
    try:
        subprocess.run(['powershell', '-NoProfile', '-Command', script],
                       capture_output=True, timeout=30,
                       creationflags=subprocess.CREATE_NO_WINDOW)
    except Exception:
        pass


def launch_detached(exe):
    # In a windowed (no-console) exe the std handles are invalid — Popen must
    # be given explicit DEVNULL handles or it can fail to spawn at all.
    subprocess.Popen(
        [exe], cwd=os.path.dirname(exe), close_fds=True,
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP)


def build_setup_app(template_folder, static_folder):
    """A tiny standalone Flask app for the setup window — deliberately does
    NOT touch the club database at all."""
    from flask import Flask, jsonify, render_template, request

    setup_app = Flask('club_training_setup',
                      template_folder=template_folder,
                      static_folder=static_folder)
    state = {'result': None}   # 'launched' once the installed copy is started

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
            exe = perform_install(dest, bool(data.get('shortcut')))
        except (RuntimeError, OSError) as e:
            return jsonify(ok=False, error=str(e))

        def _finish():
            state['result'] = 'launched'
            # Outside the frozen exe (tests, dev) just record the outcome —
            # never kill the calling process.
            if getattr(sys, 'frozen', False):
                try:
                    launch_detached(exe)
                finally:
                    os._exit(0)

        # reply first, then start the installed copy and bow out
        threading.Timer(1.2, _finish).start()
        return jsonify(ok=True, dest=os.path.dirname(exe))

    @setup_app.route('/api/cancel', methods=['POST'])
    def api_cancel():
        state['result'] = 'cancelled'
        if getattr(sys, 'frozen', False):
            threading.Timer(0.3, lambda: os._exit(0)).start()
        return jsonify(ok=True)

    setup_app.setup_state = state

    return setup_app


class SetupWindowApi:
    """js_api for the pywebview setup window — native folder Browse."""

    def browse(self):
        try:
            import webview
            win = webview.windows[0]
            picked = win.create_file_dialog(webview.FOLDER_DIALOG)
            if picked:
                folder = picked[0] if isinstance(picked, (list, tuple)) else picked
                # picking e.g. C:\Apps means "put the app folder in there"
                if os.path.basename(folder).lower() not in ('club_training', 'club training'):
                    folder = os.path.join(folder, 'Club_Training')
                return folder
        except Exception:
            pass
        return None
