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


def _fail(message, exc=None):
    """pythonw has no console, so a startup failure must be SHOWN: write the
    full detail to logs\\startup_error.log and put a plain-English dialog on
    screen saying what happened and where the detail is."""
    detail = ''
    if exc is not None:
        import traceback
        detail = ''.join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    log_path = os.path.join(BASE_DIR, 'logs', 'startup_error.log')
    try:
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        with open(log_path, 'w', encoding='utf-8') as f:
            from datetime import datetime
            f.write(f'{datetime.now():%Y-%m-%d %H:%M:%S}\n{message}\n\n{detail}')
    except OSError:
        pass
    if not os.environ.get('CLUB_TRAINING_NO_DIALOG'):   # tests set this
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(
                0,
                message + '\n\nTrying again usually works. If it keeps happening, '
                'send the club the file:\n' + log_path,
                'Club Training could not start', 0x10)
        except Exception:
            pass
    sys.exit(1)


def _start_server(flask_app, host, port, timeout=30):
    """Run the Flask server in a daemon thread and wait until it accepts
    connections. Cold starts on club PCs are slow (antivirus scanning a
    freshly extracted app can take well over five seconds), so wait
    patiently — but if the server THREAD dies (port taken, bad config),
    fail immediately with the real reason instead of timing out."""
    import socket as _socket
    error = {}

    def _serve():
        try:
            flask_app.run(host=host, port=port, debug=False, use_reloader=False)
        except BaseException as e:          # noqa: BLE001 — must capture to report
            error['exc'] = e

    thread = threading.Thread(target=_serve, daemon=True)
    thread.start()
    deadline = time.time() + timeout
    while time.time() < deadline:
        if 'exc' in error:
            _fail('The app\'s internal server could not start '
                  f'(address {host}, port {port}).', error['exc'])
        try:
            with _socket.create_connection(('127.0.0.1', port), timeout=0.3):
                pass
            # Something answered — but it could be another process squatting
            # on the port while OUR bind just failed. Give that error a
            # moment to surface before declaring victory.
            time.sleep(0.4)
            if 'exc' in error:
                _fail('The app\'s internal server could not start '
                      f'(address {host}, port {port} is already in use).',
                      error['exc'])
            return thread
        except OSError:
            time.sleep(0.2)
    _fail(f'The app\'s internal server did not answer within {timeout} seconds. '
          'The computer may just be very busy — close this and try again.')


def run_setup():
    """Show the first-run setup window; on install, start the installed
    copy and close the window."""
    from app import _free_port

    setup_flask = setup_wizard.build_setup_app(
        os.path.join(BASE_DIR, 'templates'), os.path.join(BASE_DIR, 'static'))
    state = setup_flask.setup_state
    port = _free_port()
    _start_server(setup_flask, '127.0.0.1', port)
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

    from app import create_app, _network_bind

    app = create_app()
    if 'CLUB_TRAINING_PORT' in os.environ:     # CI probe: local-only, fixed
        host, port = '127.0.0.1', int(os.environ['CLUB_TRAINING_PORT'])
    else:
        host, port = _network_bind(app)
    server_thread = _start_server(app, host, port)
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
    # Anything unexpected must surface as a dialog + logs\startup_error.log —
    # under pythonw a bare exception dies in silence and the desk just sees
    # "nothing happened".
    try:
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
    except SystemExit:
        raise
    except BaseException as _e:   # noqa: BLE001 — last-resort reporter
        _fail('Club Training hit an unexpected error while starting.', _e)
