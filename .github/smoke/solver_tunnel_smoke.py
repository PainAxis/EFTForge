"""Ephemeral Cloudflare Tunnel smoke test for the solver baseline branch."""

from __future__ import annotations

import hmac
import json
import os
from pathlib import Path
import sys

M4A1_ID = "5447a9cd4bdc2dbd208b4567"
M4A1_STOCK_SLOT_ID = "55d5a3074bdc2d61338b4574"
PPSH41_ID = "5ea03f7400685063ec28bfa8"
ROOT_DIR = Path(__file__).resolve().parents[2]
BACKEND_DIR = ROOT_DIR / "backend"
FRONTEND_DIR = ROOT_DIR / "frontend"


def _serve() -> None:
    token = os.environ["SMOKE_TOKEN"]
    os.chdir(BACKEND_DIR)
    sys.path.insert(0, str(BACKEND_DIR))

    import uvicorn
    from fastapi import Request
    from fastapi.responses import Response
    from fastapi.staticfiles import StaticFiles
    from main import app

    @app.middleware("http")
    async def smoke_token_gate(request: Request, call_next):
        supplied_header = request.headers.get("x-eftforge-smoke-token", "")
        supplied_cookie = request.cookies.get("eftforge_smoke", "")
        if hmac.compare_digest(supplied_header, token) or hmac.compare_digest(supplied_cookie, token):
            return await call_next(request)
        return Response(status_code=404)

    @app.post("/__smoke_auth", include_in_schema=False)
    def smoke_auth() -> Response:
        response = Response(status_code=204)
        response.set_cookie(
            "eftforge_smoke",
            token,
            httponly=True,
            secure=True,
            samesite="strict",
            max_age=1800,
        )
        return response

    app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="smoke-frontend")
    uvicorn.run(app, host="127.0.0.1", port=int(os.environ.get("EFTFORGE_PORT", "47651")))


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _smoke() -> None:
    from playwright.sync_api import sync_playwright

    base_url = os.environ["BASE_URL"].rstrip("/")
    token = os.environ["SMOKE_TOKEN"]
    artifact_dir = Path(os.environ["RUNNER_TEMP"]) / "smoke-artifacts"
    artifact_dir.mkdir(parents=True, exist_ok=True)

    api_results = None
    ui_results = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        for index, width in enumerate((1440, 480)):
            mobile = width < 768
            context = browser.new_context(
                viewport={"width": width, "height": 1000},
                is_mobile=mobile,
                has_touch=mobile,
            )
            context.add_init_script("localStorage.setItem('eftforge_news_seen', '2026-07-26-desktop-app-launch')")
            auth = context.request.post(
                f"{base_url}/__smoke_auth",
                headers={"X-EFTForge-Smoke-Token": token},
            )
            _require(auth.ok, f"{width}px: smoke authentication failed: {auth.status}")

            page = context.new_page()
            page_errors: list[str] = []
            page.on("pageerror", lambda error: page_errors.append(str(error)))
            response = page.goto(base_url, wait_until="domcontentloaded", timeout=120_000)
            _require(response is not None and response.ok, f"{width}px: page load failed")

            gun_card = page.locator(f'.gun-card[data-gun-id="{M4A1_ID}"]')
            gun_card.wait_for(state="visible", timeout=120_000)

            if index == 0:
                api_results = page.evaluate(
                    """
                    async ({m4a1, ppsh41, stockSlot}) => {
                      async function postJson(path, body) {
                        const response = await fetch(path, {
                          method: 'POST',
                          headers: {'Content-Type': 'application/json'},
                          body: JSON.stringify(body),
                        });
                        if (!response.ok) throw new Error(`${path}: HTTP ${response.status}`);
                        return response.json();
                      }
                      async function combo(body) {
                        const response = await fetch('/build/combo-full', {
                          method: 'POST',
                          headers: {'Content-Type': 'application/json'},
                          body: JSON.stringify(body),
                        });
                        if (!response.ok) throw new Error(`combo: HTTP ${response.status}`);
                        const text = await response.text();
                        for (const part of text.split('\\n\\n')) {
                          if (!part.startsWith('data: ')) continue;
                          const event = JSON.parse(part.slice(6));
                          if (event.type === 'result') return event.data;
                        }
                        throw new Error('combo stream ended without a result');
                      }

                      const optimizerCold = await postJson('/build/optimize', {weapon_id: ppsh41});
                      await new Promise(resolve => setTimeout(resolve, 1100));
                      const optimizerHot = await postJson('/build/optimize', {weapon_id: ppsh41});
                      await new Promise(resolve => setTimeout(resolve, 1100));
                      const infeasible = await postJson('/build/optimize', {
                        weapon_id: m4a1,
                        min_ergonomics: 999,
                      });
                      const comboBody = {
                        base_item_id: m4a1,
                        installed_ids: [],
                        root_slot_id: stockSlot,
                        lang: 'en',
                        strength_level: 10,
                        equip_ergo_modifier: 0,
                        exclude_child_slot_names: [],
                        exclude_item_ids: [],
                      };
                      const comboCold = await combo(comboBody);
                      const comboHot = await combo(comboBody);
                      return {
                        optimizer: {
                          status: optimizerCold.status,
                          cache: [optimizerCold.metrics.cache_hit, optimizerHot.metrics.cache_hit],
                          metrics: optimizerCold.metrics,
                        },
                        infeasibleStatus: infeasible.status,
                        combo: {
                          cache: [comboCold.metrics.cache_hit, comboHot.metrics.cache_hit],
                          count: comboCold.combos.length,
                          truncated: comboCold.truncated,
                          truncationReasons: comboCold.truncation_reasons,
                          metrics: comboCold.metrics,
                        },
                      };
                    }
                    """,
                    {"m4a1": M4A1_ID, "ppsh41": PPSH41_ID, "stockSlot": M4A1_STOCK_SLOT_ID},
                )
                _require(
                    api_results["optimizer"]["status"] in ("optimal", "feasible"),
                    f"optimizer status: {api_results}",
                )
                _require(api_results["optimizer"]["cache"] == [False, True], f"optimizer cache: {api_results}")
                _require(api_results["infeasibleStatus"] == "infeasible", f"infeasible status: {api_results}")
                _require(api_results["combo"]["cache"] == [False, True], f"combo cache: {api_results}")
                _require(api_results["combo"]["count"] > 0, f"empty combo result: {api_results}")

            news_backdrop = page.locator("#news-backdrop.visible")
            if news_backdrop.is_visible():
                news_backdrop.click()
                news_backdrop.wait_for(state="hidden", timeout=30_000)
            gun_card.click()
            page.wait_for_function("() => Boolean(window.EFTForge?.state?.currentGun)", timeout=120_000)

            if width >= 768:
                # The abuse guard intentionally rate-limits optimizer requests per IP.
                # Leave a full cooldown after the direct API assertions above.
                page.wait_for_timeout(1100)
                page.locator("#optimizer-edge-tab").click()
                overlay = page.locator("#optimizer-overlay.visible")
                overlay.wait_for(state="visible", timeout=30_000)
                page.locator("#optimizer-solve-btn").click()
                page.locator(".optimizer-manifest").wait_for(state="visible", timeout=120_000)
                page.wait_for_function(
                    """() => {
                      const body = document.querySelector('#optimizer-manifest-body');
                      return body && body.rows.length > 0 &&
                        !body.querySelector('.optimizer-manifest-loading');
                    }""",
                    timeout=120_000,
                )

                status_text = page.locator(".optimizer-status-label").inner_text(timeout=30_000)
                _require(
                    "Optimal" in status_text or "Feasible" in status_text,
                    f"{width}px: unexpected optimizer status label: {status_text}",
                )
                bounds = overlay.evaluate("""element => {
                      const rect = element.getBoundingClientRect();
                      return {left: rect.left, right: rect.right, width: rect.width};
                    }""")
                _require(
                    bounds["left"] >= -1 and bounds["right"] <= width + 1,
                    f"{width}px: overlay escaped viewport",
                )
            else:
                # Latest main intentionally disables the optimizer on mobile.
                _require(
                    not page.locator("#optimizer-edge-tab").is_visible(),
                    f"{width}px: desktop-only optimizer entry point is visible",
                )
                status_text = "Disabled on mobile (expected)"
                bounds = None
            _require(not page_errors, f"{width}px: uncaught browser errors: {page_errors}")

            screenshot = artifact_dir / f"solver-smoke-{width}px.png"
            page.screenshot(path=str(screenshot), full_page=True)
            ui_results.append(
                {
                    "width": width,
                    "status": status_text,
                    "overlay": bounds,
                    "pageErrors": page_errors,
                }
            )
            context.close()
        browser.close()

    (artifact_dir / "api-results.json").write_text(json.dumps(api_results, indent=2), encoding="utf-8")
    (artifact_dir / "ui-results.json").write_text(json.dumps(ui_results, indent=2), encoding="utf-8")
    print(json.dumps({"api": api_results, "ui": ui_results}, indent=2))


if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] not in {"serve", "smoke"}:
        raise SystemExit("usage: solver_tunnel_smoke.py {serve|smoke}")
    _serve() if sys.argv[1] == "serve" else _smoke()
