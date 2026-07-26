# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for the desktop app's backend sidecar.
#
# Deliberately code-only (one ~25 MB exe): the static frontend and the
# tarkov.db snapshot are installed as Tauri resources on disk instead of being
# packed in here, so they aren't re-extracted from the onefile bundle on every
# launch. The Tauri launcher points the exe at them via EFTFORGE_FRONTEND_DIR
# and EFTFORGE_RESOURCE_DIR.
#
# Build via desktop/scripts/build_backend.py (or directly:
#   pyinstaller desktop/pyinstaller/eftforge-backend.spec --noconfirm).

import os

spec_dir    = os.path.dirname(os.path.abspath(SPEC))
repo_root   = os.path.normpath(os.path.join(spec_dir, "..", ".."))
backend_dir = os.path.join(repo_root, "backend")

a = Analysis(
    [os.path.join(backend_dir, "desktop_main.py")],
    pathex=[backend_dir],
    binaries=[],
    datas=[],
    hiddenimports=[
        # Imported lazily by desktop_main / desktop.py.
        "main",
        "desktop",
        "sync_tarkov_dev",
        # uvicorn resolves these via string config at runtime.
        "uvicorn.logging",
        "uvicorn.loops",
        "uvicorn.loops.auto",
        "uvicorn.loops.asyncio",
        "uvicorn.protocols",
        "uvicorn.protocols.http",
        "uvicorn.protocols.http.auto",
        "uvicorn.protocols.http.h11_impl",
        "uvicorn.protocols.websockets",
        "uvicorn.protocols.websockets.auto",
        "uvicorn.lifespan",
        "uvicorn.lifespan.on",
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=[
        # Server-only: build-card image generation (patchright drives a real
        # browser on prod; in connected mode images come from eftforge.com).
        "patchright",
        "PIL",
        # Dev / prod-only tooling that must not bloat the exe.
        "gunicorn",
        "pytest",
        "black",
        "tkinter",
        "unittest",
        "pydoc",
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="eftforge-backend",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,   # stdout carries the EFTFORGE_PORT handshake; the Tauri
                    # launcher spawns it windowless, manual runs show logs.
    disable_windowed_traceback=False,
)
