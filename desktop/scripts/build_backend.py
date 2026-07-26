"""Build the backend sidecar exe and stage everything the Tauri build needs.

Usage (from anywhere, with the backend venv's python):
    python desktop/scripts/build_backend.py [--fresh-snapshot]

Steps:
  1. PyInstaller-freeze backend/desktop_main.py -> eftforge-backend.exe
  2. Copy the exe to desktop/src-tauri/binaries/eftforge-backend-<target-triple>.exe
     (the name format tauri's externalBin expects)
  3. Stage the tarkov.db snapshot into desktop/src-tauri/resources/tarkov.db
     (--fresh-snapshot syncs a brand-new one from tarkov.dev first; otherwise
     the dev DB at backend/tarkov.db is used)
"""

import argparse
import os
import platform
import shutil
import subprocess
import sys
import tempfile

REPO_ROOT   = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
BACKEND_DIR = os.path.join(REPO_ROOT, "backend")
DESKTOP_DIR = os.path.join(REPO_ROOT, "desktop")
SPEC_FILE   = os.path.join(DESKTOP_DIR, "pyinstaller", "eftforge-backend.spec")
TAURI_DIR   = os.path.join(DESKTOP_DIR, "src-tauri")


def target_triple() -> str:
    machine = platform.machine().lower()
    arch = {"amd64": "x86_64", "x86_64": "x86_64", "arm64": "aarch64"}.get(machine, machine)
    if sys.platform == "win32":
        return f"{arch}-pc-windows-msvc"
    if sys.platform == "darwin":
        return f"{arch}-apple-darwin"
    return f"{arch}-unknown-linux-gnu"


def fresh_snapshot(dest: str) -> None:
    """Sync a brand-new tarkov.db from tarkov.dev into dest."""
    print("Syncing a fresh tarkov.db snapshot from tarkov.dev...")
    with tempfile.TemporaryDirectory() as tmp:
        db_path = os.path.join(tmp, "snapshot.db")
        env = {
            **os.environ,
            "EFTFORGE_DESKTOP": "1",
            "EFTFORGE_DATA_DIR": tmp,
            "DATABASE_URL": "sqlite:///" + db_path.replace("\\", "/"),
        }
        subprocess.run(
            [sys.executable, os.path.join(BACKEND_DIR, "desktop_main.py"), "--sync-worker"],
            env=env, check=True, timeout=600,
        )
        shutil.copyfile(db_path, dest)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fresh-snapshot", action="store_true",
                        help="sync a new tarkov.db from tarkov.dev instead of using backend/tarkov.db")
    args = parser.parse_args()

    # 1. freeze
    dist_dir = os.path.join(DESKTOP_DIR, "pyinstaller", "dist")
    subprocess.run(
        [sys.executable, "-m", "PyInstaller", SPEC_FILE, "--noconfirm",
         "--distpath", dist_dir,
         "--workpath", os.path.join(DESKTOP_DIR, "pyinstaller", "build")],
        check=True,
    )

    exe_name = "eftforge-backend.exe" if sys.platform == "win32" else "eftforge-backend"
    built = os.path.join(dist_dir, exe_name)
    if not os.path.exists(built):
        sys.exit(f"PyInstaller output not found: {built}")

    # 2. stage sidecar binary where tauri.conf.json's externalBin expects it
    binaries_dir = os.path.join(TAURI_DIR, "binaries")
    os.makedirs(binaries_dir, exist_ok=True)
    suffix = ".exe" if sys.platform == "win32" else ""
    sidecar = os.path.join(binaries_dir, f"eftforge-backend-{target_triple()}{suffix}")
    shutil.copyfile(built, sidecar)
    print(f"Sidecar staged: {sidecar}")

    # 3. stage the tarkov.db snapshot resource
    resources_dir = os.path.join(TAURI_DIR, "resources")
    os.makedirs(resources_dir, exist_ok=True)
    snapshot_dest = os.path.join(resources_dir, "tarkov.db")
    if args.fresh_snapshot:
        fresh_snapshot(snapshot_dest)
    else:
        dev_db = os.path.join(BACKEND_DIR, "tarkov.db")
        if not os.path.exists(dev_db):
            sys.exit("backend/tarkov.db not found - run with --fresh-snapshot or start the dev backend once")
        shutil.copyfile(dev_db, snapshot_dest)
    print(f"Snapshot staged: {snapshot_dest}")
    print("Done. Next: npm run tauri build (from desktop/)")


if __name__ == "__main__":
    main()
