"""Temporary runner app: public game data, read/calculation routes only."""
import os
import sys
from pathlib import Path

os.environ["EFTFORGE_DESKTOP"] = "1"
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))
import main
import uvicorn
from starlette.responses import PlainTextResponse


async def app(scope, receive, send):
    if scope["type"] == "http":
        path, method = scope["path"], scope["method"]
        if path.startswith("/admin") or (
            method not in ("GET", "HEAD") and not (method == "POST" and (path.startswith("/build/") or path in ("/slots/allowed-items/batch", "/items/slots/batch")))
        ):
            return await PlainTextResponse("Read/calculation test only", status_code=405)(scope, receive, send)
    return await main.app(scope, receive, send)


uvicorn.run(app, host="127.0.0.1", port=int(os.environ.get("EFTFORGE_PORT", "47651")), log_level="warning")
