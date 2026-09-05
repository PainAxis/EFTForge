import json
import os
import time
from pathlib import Path

import requests
from playwright.sync_api import sync_playwright

base = os.environ["BASE_URL"].rstrip("/")
out = Path(os.environ["RUNNER_TEMP"]) / "smoke-artifacts"
out.mkdir(exist_ok=True)
report = {"api": [], "ui": []}
guns = ["5447a9cd4bdc2dbd208b4567", "5ea03f7400685063ec28bfa8"]
slots = ["55d5a3074bdc2d61338b4574", "5ea03f7400685063ec28bfad"]


def post(path, body):
    response = requests.post(base + path, json=body, timeout=60)
    if response.status_code == 429:
        time.sleep(2)
        response = requests.post(base + path, json=body, timeout=60)
    response.raise_for_status()
    return response


for gun, slot in zip(guns, slots):
    for params in [{}, {"flea_available": False}, {"max_weight": 0.001}]:
        result = post("/build/optimize", {"weapon_id": gun, **params}).json()
        expected = "infeasible" if "max_weight" in params else "optimal"
        assert result["status"] == expected, result
        assert "pruned_candidate_count" in result["metrics"], result
        report["api"].append({"gun": gun, "params": params, "status": result["status"], "metrics": result["metrics"]})
        time.sleep(1.1)
    response = post("/build/combo-full", {"base_item_id": gun, "installed_ids": [], "root_slot_id": slot})
    results = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]
    result = next(r["data"] for r in results if r["type"] == "result")
    assert result["combos"] and isinstance(result["truncated"], bool)
    assert "pruning_ms" in result["metrics"]
    report["api"].append({"gun": gun, "combo_count": len(result["combos"]), "metrics": result["metrics"]})

with sync_playwright() as p:
    browser = p.chromium.launch()
    for width in (1280, 480):
        for gun in guns:
            context = browser.new_context(viewport={"width": width, "height": 1000})
            context.add_init_script("localStorage.setItem('eftforge_news_seen', '2026-09-04-v150-release');")
            page = context.new_page()
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(base, wait_until="domcontentloaded", timeout=120000)
            page.locator(f'.gun-card[data-gun-id="{gun}"]').wait_for(state="visible", timeout=120000)
            if page.locator("#news-backdrop.visible").is_visible():
                page.locator("#news-backdrop.visible").click()
            page.locator(f'.gun-card[data-gun-id="{gun}"]').click()
            page.locator("#optimizer-edge-tab").wait_for(state="visible", timeout=30000)
            page.locator("#optimizer-edge-tab").click()
            page.locator("#optimizer-solve-btn").wait_for(state="visible", timeout=30000)
            with page.expect_response(lambda r: r.url.endswith("/build/optimize") and r.request.method == "POST", timeout=60000) as solved:
                page.locator("#optimizer-solve-btn").click()
            payload = solved.value.json()
            assert payload["status"] in ("optimal", "feasible"), payload
            page.locator("#optimizer-use-build-btn").wait_for(state="visible", timeout=45000)
            page.locator(".optimizer-manifest-loading").wait_for(state="hidden", timeout=45000)
            bounds = page.locator("#optimizer-overlay").bounding_box()
            assert bounds and bounds["x"] >= -1 and bounds["x"] + bounds["width"] <= width + 1
            page.screenshot(path=str(out / f"optimizer-{gun}-{width}.png"), full_page=True)
            page.locator("#optimizer-use-build-btn").click()
            page.locator("#optimizer-overlay.visible").wait_for(state="hidden", timeout=30000)
            page.screenshot(path=str(out / f"applied-{gun}-{width}.png"), full_page=True)
            assert not errors, errors
            report["ui"].append({"width": width, "gun": gun, "status": payload["status"], "applied": True, "page_errors": errors})
            context.close()
    browser.close()

(out / "results.json").write_text(json.dumps(report, indent=2))
print(json.dumps(report, indent=2))
