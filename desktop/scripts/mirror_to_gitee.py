"""Mirror a desktop release to Gitee for users in China.

Steps:
  1. Create (or reuse) a release with the same tag on the Gitee mirror repo.
  2. Upload the NSIS installer (+ .sig) as release attachments.
  3. Build the Gitee variant of latest.json - identical to the GitHub one but
     pointing at the Gitee attachment URL - and commit it to the assets repo
     at desktop/latest.json (the raw URL the app's updater checks first).

Usage:
    python desktop/scripts/mirror_to_gitee.py --tag app-v0.1.0 [--notes "..."]
Env:
    GITEE_TOKEN          personal access token (required)
    GITEE_OWNER          default: morph1ne
    GITEE_RELEASES_REPO  repo that hosts the release attachments, default: eftforge-gitee-mirror
    GITEE_ASSETS_REPO    repo whose raw files serve latest.json, default: eftforge-assets
"""

import argparse
import base64
import glob
import json
import os
import sys
from datetime import datetime, timezone

import requests

API = "https://gitee.com/api/v5"

DESKTOP_DIR = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
BUNDLE_DIR  = os.path.join(DESKTOP_DIR, "src-tauri", "target", "release", "bundle", "nsis")

TOKEN = os.environ.get("GITEE_TOKEN", "")
OWNER = os.environ.get("GITEE_OWNER", "morph1ne")
RELEASES_REPO = os.environ.get("GITEE_RELEASES_REPO", "eftforge-gitee-mirror")
ASSETS_REPO   = os.environ.get("GITEE_ASSETS_REPO", "eftforge-assets")


def _die(msg: str) -> None:
    sys.exit(f"mirror_to_gitee: {msg}")


def find_bundle() -> tuple[str, str]:
    exes = glob.glob(os.path.join(BUNDLE_DIR, "*-setup.exe"))
    if not exes:
        _die(f"no NSIS setup exe in {BUNDLE_DIR}")
    exe = exes[0]
    sig = exe + ".sig"
    if not os.path.exists(sig):
        _die(f"missing {sig}")
    return exe, sig


def ensure_release(tag: str, notes: str) -> int:
    """Create the release on the mirror repo, or return the existing one."""
    r = requests.get(
        f"{API}/repos/{OWNER}/{RELEASES_REPO}/releases/tags/{tag}",
        params={"access_token": TOKEN}, timeout=30,
    )
    if r.status_code == 200 and r.json():
        return r.json()["id"]
    r = requests.post(
        f"{API}/repos/{OWNER}/{RELEASES_REPO}/releases",
        json={
            "access_token": TOKEN,
            "tag_name": tag,
            "name": f"EFTForge Desktop {tag}",
            "body": notes or f"EFTForge desktop release {tag}",
            "target_commitish": "main",
        },
        timeout=30,
    )
    if r.status_code not in (200, 201):
        _die(f"release create failed ({r.status_code}): {r.text[:500]}")
    return r.json()["id"]


def upload_attachment(release_id: int, path: str) -> str:
    with open(path, "rb") as f:
        r = requests.post(
            f"{API}/repos/{OWNER}/{RELEASES_REPO}/releases/{release_id}/attach_files",
            params={"access_token": TOKEN},
            files={"file": (os.path.basename(path), f)},
            timeout=600,
        )
    if r.status_code not in (200, 201):
        _die(f"attachment upload failed for {path} ({r.status_code}): {r.text[:500]}")
    data = r.json()
    return data.get("browser_download_url") or data.get("download_url") or ""


def upsert_assets_file(repo_path: str, content: bytes, message: str) -> None:
    """Create or update a file in the assets repo via the contents API."""
    url = f"{API}/repos/{OWNER}/{ASSETS_REPO}/contents/{repo_path}"
    b64 = base64.b64encode(content).decode()
    existing = requests.get(url, params={"access_token": TOKEN, "ref": "master"}, timeout=30)
    if existing.status_code == 200 and isinstance(existing.json(), dict) and existing.json().get("sha"):
        r = requests.put(url, json={
            "access_token": TOKEN, "content": b64, "message": message,
            "sha": existing.json()["sha"], "branch": "master",
        }, timeout=60)
    else:
        r = requests.post(url, json={
            "access_token": TOKEN, "content": b64, "message": message, "branch": "master",
        }, timeout=60)
    if r.status_code not in (200, 201):
        _die(f"assets repo update failed ({r.status_code}): {r.text[:500]}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tag", required=True)
    parser.add_argument("--notes", default="")
    args = parser.parse_args()

    if not TOKEN:
        _die("GITEE_TOKEN not set")

    version = args.tag.removeprefix("app-v").removeprefix("v")
    exe, sig = find_bundle()
    with open(sig, "r", encoding="utf-8") as f:
        signature = f.read().strip()

    release_id = ensure_release(args.tag, args.notes)
    print(f"Gitee release id: {release_id}")

    exe_url = upload_attachment(release_id, exe)
    upload_attachment(release_id, sig)
    if not exe_url:
        _die("Gitee did not return a download URL for the installer")
    print(f"Installer mirrored: {exe_url}")

    manifest = {
        "version": version,
        "notes": args.notes or f"EFTForge desktop {version}",
        "pub_date": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "platforms": {
            "windows-x86_64": {"signature": signature, "url": exe_url},
        },
    }
    upsert_assets_file(
        "desktop/latest.json",
        json.dumps(manifest, indent=2).encode("utf-8"),
        f"desktop updater manifest {args.tag}",
    )
    print(f"Updater manifest published: https://gitee.com/{OWNER}/{ASSETS_REPO}/raw/master/desktop/latest.json")


if __name__ == "__main__":
    main()
