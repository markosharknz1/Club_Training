"""
Entry point for the packaged (zip) copy of Club Training.

Started by "Club Training.cmd" (or the desktop shortcut) via the bundled,
python.org-signed pythonw.exe — no compiled program of our own is shipped
at all, which is what keeps SmartScreen and Smart App Control quiet.

What it does, in order:
  1. Strip Windows "downloaded from the internet" marks from the app files.
  2. If this folder is only the download that setup already installed from,
     start the installed copy instead and exit (the `installed-to=` marker).
  3. First run (no `.setup-complete` marker): show the setup window and,
     once the user installs, start the installed copy.
  4. Otherwise run the app: Flask on 127.0.0.1, shown in an Edge app
     window; the server stops when the window is closed. If the app is
     already running, just open a window on the running copy.

Running from source (run.bat / `python app.py`) never comes through here.

Environment hooks (used by CI and tests):
  CLUB_TRAINING_PORT       fixed port instead of the first free one
  CLUB_TRAINING_NO_WINDOW  serve only; never open a window (CI probe)
  CLUB_TRAINING_EDGE       explicit path to msedge.exe
"""
import json
import os
import sys
import threading
import time
import urllib.request
import webbrowser

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)   # belt and braces beside python\*._pth

import config
import native_window
import setup_wizard

PORT_FILE = os.path.join(BASE_DIR, 'logs', 'app.port')


def _strip_motw():
    """Remove Zone.Identifier ("downloaded from the internet") marks from
    every app file, so a downloaded zip behaves like a local install."""
    for root, _dirs, files in os.walk(BASE_DIR):
        for fn in files:
            try:
                os.remove(os.path.join(root, fn) + ':Zone.Identifier')
            except OSError:
                pass  # no mark on this file — the normal case


def _running_instance_port():
    """Port of an already-running instance in this folder, or None."""
    try:
        with open(PORT_FILE, 'r', encoding='utf-8') as f:
            port = int(f.read().strip())
    except (OSError, ValueError):
        return None
    try:
        with urllib.request.urlopen(
                f'http://127.0.0.1:{port}/__alive', timeout=1.5) as r:
            if json.load(r).get('app') == 'club-training':
                return port
    except Exception:
        pass
    return None


def _write_port_file(port):
    os.makedirs(os.path.dirname(PORT_FILE), exist_ok=True)
    with open(PORT_FILE, 'w', encoding='utf-8') as f:
        f.write(f'{port}\n')


def _close_window(proc):
    if proc.poll() is None:
        try:
            proc.terminate()
            proc.wait(timeout=5)
        except Exception:
            pass


def run_setup():
    """Show the first-run setup window; on install, start the installed
    copy and close the window."""
    from app import _free_port, _wait_for_server

    setup_flask = setup_wizard.build_setup_app(
        os.path.join(BASE_DIR, 'templates'), os.path.join(BASE_DIR, 'static'))
    state = setup_flask.setup_state
    port = _free_port()
    threading.Thread(
        target=lambda: setup_flask.run(host='127.0.0.1', port=port,
                                       debug=False, use_reloader=False),
        daemon=True,
    ).start()
    _wait_for_server(port)
    url = f'http://127.0.0.1:{port}/setup'

    proc = None
    if native_window.find_edge():
        proc = native_window.open_app_window(
            url, os.path.join(BASE_DIR, '.edge-setup-profile'))
        # wait for install/cancel — or the user just closing the window
        while proc.poll() is None and not state['event'].wait(0.3):
            pass
    else:
        webbrowser.open(url)
        state['event'].wait()

    if state['result'] == 'installed':
        setup_wizard.launch_installed(state['dest'])
        time.sleep(1.5)   # let the installed copy's window appear first
    if proc is not None:
        _close_window(proc)


def run_app():
    # already running here? just show it — never start a second server
    if 'CLUB_TRAINING_PORT' not in os.environ:
        existing = _running_instance_port()
        if existing and native_window.find_edge():
            native_window.open_app_window(
                f'http://127.0.0.1:{existing}',
                os.path.join(BASE_DIR, '.edge-app-profile'))
            return

    from app import create_app, _free_port, _wait_for_server

    app = create_app()
    port = (int(os.environ['CLUB_TRAINING_PORT'])
            if 'CLUB_TRAINING_PORT' in os.environ else _free_port())
    server_thread = threading.Thread(
        target=lambda: app.run(host='127.0.0.1', port=port,
                               debug=False, use_reloader=False),
        daemon=True,
    )
    server_thread.start()
    _wait_for_server(port)
    _write_port_file(port)
    url = f'http://127.0.0.1:{port}'

    try:
        if os.environ.get('CLUB_TRAINING_NO_WINDOW'):
            server_thread.join()   # CI probe: serve until killed
        elif native_window.find_edge():
            proc = native_window.open_app_window(
                url, os.path.join(BASE_DIR, '.edge-app-profile'))
            proc.wait()            # window closed -> stop the server
        else:
            webbrowser.open(url)
            server_thread.join()
    finally:
        try:
            os.remove(PORT_FILE)
        except OSError:
            pass


if __name__ == '__main__':
    _strip_motw()
    installed = setup_wizard.installed_elsewhere()
    if installed:
        setup_wizard.launch_installed(installed)
        sys.exit(0)
    if setup_wizard.first_run():
        run_setup()
        sys.exit(0)
    run_app()
    sys.exit(0)
