"""
The app's native-looking window, without shipping any executable of our own.

Microsoft Edge is on every Windows 10/11 machine and is signed by Microsoft,
so `msedge --app=<url>` gives us a chromeless desktop window for the local
Flask server — the same approach as the Game Scheduler's launcher. Each use
gets its own profile folder beside the app so it never touches the user's
real browsing profile (and a fresh profile on an MS-account PC would
otherwise pop sign-in/sync prompts — the flags below suppress those).
"""
import os
import subprocess


def find_edge():
    """Full path to msedge.exe, or None if Edge isn't installed."""
    override = os.environ.get('CLUB_TRAINING_EDGE')
    candidates = [override] if override else []
    for root in (os.environ.get('ProgramFiles(x86)'),
                 os.environ.get('ProgramFiles'),
                 os.environ.get('LocalAppData')):
        if root:
            candidates.append(os.path.join(
                root, 'Microsoft', 'Edge', 'Application', 'msedge.exe'))
    for c in candidates:
        if c and os.path.exists(c):
            return c
    return None


def open_app_window(url, profile_dir):
    """Open `url` in an Edge app window. Returns the Popen handle — when the
    profile isn't already in use, that process IS the window, so .wait()
    returns when the user closes it. (If the profile is already running,
    Edge hands the URL to the existing process and this handle exits at
    once — callers that care check for a running instance first.)

    Explicit DEVNULL std handles: under pythonw.exe the standard handles are
    invalid and Popen can fail to spawn at all without them.
    """
    edge = find_edge()
    if not edge:
        raise OSError('Microsoft Edge not found')
    os.makedirs(profile_dir, exist_ok=True)
    return subprocess.Popen(
        [edge, f'--app={url}', f'--user-data-dir={profile_dir}',
         '--no-first-run', '--disable-sync',
         '--disable-features=msImplicitSignin,msSyncPromo'],
        cwd=profile_dir, close_fds=True,
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL)
