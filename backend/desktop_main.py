"""Entrypoint for the desktop app's backend sidecar.

Run modes:
  desktop_main.py                 start the local server (prints EFTFORGE_PORT=<n>
                                  on stdout for the Tauri launcher to read)
  desktop_main.py --sync-worker   run one tarkov.dev sync against whatever
                                  DATABASE_URL is set in the environment, then
                                  exit (spawned by desktop.py's sync manager)

The PyInstaller build uses this as its entry script; the frozen exe supports
both modes the same way (desktop.py re-invokes the exe with --sync-worker).
"""

import os
import socket
import sys

# Everything this process does is desktop mode, regardless of how it's launched.
os.environ["EFTFORGE_DESKTOP"] = "1"

# Preferred fixed port: the frontend origin is http://127.0.0.1:<port>, and
# localStorage (saved builds, settings, language) is scoped to that origin -
# so the port must stay stable across launches or users would "lose" their
# data. Falls back to nearby ports, then an ephemeral one, if taken.
_PREFERRED_PORT = 47651


def _run_sync_worker() -> None:
    import sync_tarkov_dev
    sync_tarkov_dev.sync_items()


def _pick_port() -> int:
    override = os.environ.get("EFTFORGE_PORT", "").strip()
    if override:
        return int(override)
    for candidate in range(_PREFERRED_PORT, _PREFERRED_PORT + 10):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(("127.0.0.1", candidate))
            return candidate
        except OSError:
            continue
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _resource_dir() -> str:
    """Where read-only bundled resources (tarkov.db snapshot) live."""
    override = os.environ.get("EFTFORGE_RESOURCE_DIR", "").strip()
    if override:
        return override
    if getattr(sys, "frozen", False):
        return getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def _seed_data_dir(data_dir: str) -> None:
    """First run: copy the bundled tarkov.db snapshot into the data dir so the
    app works immediately without waiting on a tarkov.dev sync."""
    live_db = os.path.join(data_dir, "tarkov.db")
    if os.path.exists(live_db):
        return
    snapshot = os.path.join(_resource_dir(), "tarkov.db")
    if os.path.exists(snapshot):
        import shutil
        print(f"First run - seeding item database into {data_dir}", flush=True)
        shutil.copyfile(snapshot, live_db)
    else:
        # No snapshot bundled: the automatic startup sync in desktop.py will
        # fetch everything from tarkov.dev instead.
        print("No bundled item database snapshot - will sync from tarkov.dev.", flush=True)


def main() -> None:
    if "--sync-worker" in sys.argv:
        _run_sync_worker()
        return

    import config  # resolves DATA_DIR (portable dir next to exe, or fallback)

    _seed_data_dir(config.DATA_DIR)
    os.chdir(config.DATA_DIR)

    port = _pick_port()
    # The Tauri launcher blocks on this line to learn where to point the window.
    print(f"EFTFORGE_PORT={port}", flush=True)

    import uvicorn
    import main as app_module

    uvicorn.run(app_module.app, host="127.0.0.1", port=port, log_level="info")


if __name__ == "__main__":
    main()
