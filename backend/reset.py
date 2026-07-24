import hashlib
import json
import os
import sqlite3
import subprocess
import threading
import time
import sys

DB_FILE = "tarkov.db"

# Written by the background dev sync when it detects that data actually
# changed. Consumed (and deleted) by GET /dev/sync-notice in main.py, which
# only ever runs when reset.py's dev branch has produced one - production
# never calls reset.py, so this file never appears there.
NOTICE_FILE = "dev_sync_notice.json"


def delete_db():
    if os.path.exists(DB_FILE):
        print("Deleting old database...")
        os.remove(DB_FILE)
    else:
        print("No existing database found.")


def sync_tarkov():
    print("Syncing tarkov.dev data...")
    subprocess.run([sys.executable, "sync_tarkov_dev.py"], check=True)


# Isolated DB used by the dev background sync so the live tarkov.db (and any
# connections uvicorn already has open against it) are never touched until a
# full, fresh copy of the data is ready to go.
SCRATCH_DB = "tarkov_dev_sync_scratch.db"

# Tables sync_tarkov_dev.py rewrites on every run. Order matters for the copy
# below: children deleted before parents, parents inserted before children.
_SYNC_TABLES = ("slot_allowed_items", "slots", "items", "traders")


def _items_fingerprint(db_path):
    """Hash of the items table, used to tell whether a resync actually changed anything."""
    if not os.path.exists(db_path):
        return None
    conn = sqlite3.connect(db_path)
    try:
        h = hashlib.sha256()
        for row in conn.execute("SELECT * FROM items ORDER BY id"):
            h.update(repr(row).encode("utf-8", "ignore"))
        return h.hexdigest()
    except sqlite3.OperationalError:
        return None
    finally:
        conn.close()


def _sync_to_scratch():
    """Runs the normal sync script against a throwaway DB file, completely
    isolated from the live tarkov.db - no shared connections, no visible
    half-written state, regardless of how long the network fetch takes."""
    if os.path.exists(SCRATCH_DB):
        os.remove(SCRATCH_DB)
    print("Syncing tarkov.dev data into scratch DB...")
    env = {**os.environ, "DATABASE_URL": f"sqlite:///{SCRATCH_DB}"}
    subprocess.run([sys.executable, "sync_tarkov_dev.py"], check=True, env=env)


def _copy_scratch_into_live():
    """Replaces the live tables' rows with the scratch DB's in one transaction,
    so any query running against tarkov.db sees either the full old data or
    the full new data - never a table that's been cleared but not yet refilled."""
    conn = sqlite3.connect(DB_FILE, timeout=10)
    try:
        conn.execute("ATTACH DATABASE ? AS scratch", (SCRATCH_DB,))
        conn.execute("BEGIN IMMEDIATE")
        for table in _SYNC_TABLES:
            conn.execute(f"DELETE FROM {table}")
        for table in reversed(_SYNC_TABLES):
            conn.execute(f"INSERT INTO {table} SELECT * FROM scratch.{table}")
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.execute("DETACH DATABASE scratch")
        conn.close()


def _sync_in_background():
    """Sync into scratch, and only touch the live DB (atomically) if the data
    actually changed - writes NOTICE_FILE so the frontend can prompt a refresh."""
    try:
        _sync_to_scratch()
        before = _items_fingerprint(DB_FILE)
        after = _items_fingerprint(SCRATCH_DB)
        if after is not None and after != before:
            _copy_scratch_into_live()
            with open(NOTICE_FILE, "w", encoding="utf-8") as f:
                json.dump({"changed": True, "at": time.time()}, f)
            print("Background sync found new data - live DB updated, frontend will be notified.")
        else:
            print("Background sync complete - no data changes detected.")
    except Exception as e:
        print(f"Background sync failed (server keeps running on existing data): {e}")
    finally:
        if os.path.exists(SCRATCH_DB):
            os.remove(SCRATCH_DB)


def seed_other():
    # Add any additional seed scripts here
    # subprocess.run(["python", "other_seed_script.py"], check=True)
    print("No additional seeds configured.")


def start_server_dev():
    print("Starting server (dev mode with --reload)...")
    subprocess.run([sys.executable, "-m", "uvicorn", "main:app", "--reload"])


def start_server_prod():
    """Production server: no --reload, multi-worker via Gunicorn + Uvicorn workers."""
    print("Starting server (production)...")
    workers = str(os.cpu_count() or 2)
    subprocess.run([
        sys.executable, "-m", "gunicorn", "main:app",
        "-w", workers,
        "-k", "uvicorn.workers.UvicornWorker",
        "--bind", "0.0.0.0:8000",
    ])


if __name__ == "__main__":
    prod = "--prod" in sys.argv

    if prod:
        delete_db()
        sync_tarkov()
        seed_other()
        start_server_prod()
    else:
        if os.path.exists(NOTICE_FILE):
            os.remove(NOTICE_FILE)

        if os.path.exists(DB_FILE):
            print(f"Using existing {DB_FILE} - starting immediately, syncing in the background...")
            threading.Thread(target=_sync_in_background, daemon=True).start()
        else:
            print("No existing database found - syncing before first start...")
            sync_tarkov()
            seed_other()

        start_server_dev()
