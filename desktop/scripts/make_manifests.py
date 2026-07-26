"""Generate the Tauri updater manifest (latest.json) for the GitHub release.

Run after `tauri build` with signing enabled. Reads the NSIS bundle + .sig,
writes desktop/dist-manifests/latest.json with the GitHub download URL.
(The Gitee variant is produced by mirror_to_gitee.py, which only knows the
attachment URL after uploading.)

Usage:
    python desktop/scripts/make_manifests.py --tag app-v0.1.0 [--notes "..."]
Env:
    GITHUB_REPOSITORY   owner/repo (set automatically in Actions),
                        default SouthHorizons76/EFTForge
"""

import argparse
import glob
import json
import os
import sys
from datetime import datetime, timezone

DESKTOP_DIR = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
BUNDLE_DIR  = os.path.join(DESKTOP_DIR, "src-tauri", "target", "release", "bundle", "nsis")
OUT_DIR     = os.path.join(DESKTOP_DIR, "dist-manifests")


def find_bundle(version: str) -> tuple[str, str]:
    # Match the exe to the requested version - the bundle dir accumulates
    # exes from previous local builds, and a bare *-setup.exe glob picks the
    # oldest one alphabetically (this once published a "1.4.8" manifest that
    # pointed at the 1.4.7 installer).
    exes = glob.glob(os.path.join(BUNDLE_DIR, f"*_{version}_*-setup.exe"))
    if not exes:
        sys.exit(f"No NSIS setup exe for version {version} in {BUNDLE_DIR} - run tauri build first")
    exe = exes[0]
    sig = exe + ".sig"
    if not os.path.exists(sig):
        sys.exit(f"Missing signature {sig} - was TAURI_SIGNING_PRIVATE_KEY set during the build?")
    return exe, sig


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tag", required=True, help="release tag, e.g. app-v0.1.0")
    parser.add_argument("--notes", default="", help="release notes for the update prompt")
    args = parser.parse_args()

    repo = os.environ.get("GITHUB_REPOSITORY", "SouthHorizons76/EFTForge")
    version = args.tag.removeprefix("app-v").removeprefix("v")

    exe, sig = find_bundle(version)
    with open(sig, "r", encoding="utf-8") as f:
        signature = f.read().strip()

    manifest = {
        "version": version,
        "notes": args.notes or f"EFTForge desktop {version}",
        "pub_date": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "platforms": {
            "windows-x86_64": {
                "signature": signature,
                "url": f"https://github.com/{repo}/releases/download/{args.tag}/{os.path.basename(exe)}",
            }
        },
    }

    os.makedirs(OUT_DIR, exist_ok=True)
    out = os.path.join(OUT_DIR, "latest.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
    print(f"Wrote {out}")
    print(f"Bundle: {exe}")


if __name__ == "__main__":
    main()
