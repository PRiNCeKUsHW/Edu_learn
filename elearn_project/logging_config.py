"""Small helper for settings.py's file-logging setup, kept out of
settings.py itself: Django settings modules are imported exactly once per
process, before any test runs, so logic that lives directly in settings.py
can't be exercised by a normal test the way this can.
"""


def ensure_log_dir(path):
    """Create `path` (and any missing parents) if it doesn't already exist.

    Returns True if the directory exists and is usable afterward, False
    otherwise. Callers use this to fall back to console-only logging
    instead of crashing the whole app at import time the moment the
    filesystem turns out not to be writable where they expected — a
    read-only container root outside a mounted volume, a permissions
    problem, a full disk. Console output is what most hosting platforms
    capture and show in their own dashboard regardless (Railway does),
    so losing the local files here doesn't mean losing visibility.
    """
    try:
        path.mkdir(parents=True, exist_ok=True)
        return True
    except OSError:
        return False
