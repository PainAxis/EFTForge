import json
import os
from pathlib import Path

import requests
from playwright.sync_api import sync_playwright


BASE_URL = os.environ["BASE_URL"].rstrip("/")
ARTIFACT_DIR = Path(os.environ["RUNNER_TEMP"]) / "smoke-artifacts"
ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)

VIEWPORTS = (1920, 901, 900, 767, 480)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


guns = requests.get(f"{BASE_URL}/guns", timeout=30).json()
gun = next(
    item
    for item in guns
    if item.get("caliber") != "Caliber20x1mm" and item.get("factory_attachment_ids")
)

results = []
with sync_playwright() as playwright:
    browser = playwright.chromium.launch()
    for width in VIEWPORTS:
        context = browser.new_context(viewport={"width": width, "height": 1000})
        page = context.new_page()
        page_errors = []
        page.on("pageerror", lambda error: page_errors.append(str(error)))

        response = page.goto(BASE_URL, wait_until="domcontentloaded", timeout=120_000)
        require(response is not None and response.ok, f"{width}px: page load failed")
        page.locator(f'.gun-card[data-gun-id="{gun["id"]}"]').wait_for(
            state="visible", timeout=120_000
        )
        news_backdrop = page.locator("#news-backdrop.visible")
        if news_backdrop.is_visible():
            news_backdrop.click()
            news_backdrop.wait_for(state="hidden", timeout=30_000)
        page.locator(f'.gun-card[data-gun-id="{gun["id"]}"]').click()
        page.wait_for_function(
            "() => Boolean(window.EFTForge?.state?.currentGun)", timeout=120_000
        )
        page.locator("#optimizer-edge-tab").click()
        page.locator("#optimizer-overlay.visible").wait_for(state="visible", timeout=30_000)
        page.wait_for_function(
            """() => {
              const rect = document.querySelector('#optimizer-overlay').getBoundingClientRect();
              return rect.left >= -1 && rect.right <= window.innerWidth + 1;
            }""",
            timeout=30_000,
        )
        page.locator(".optimizer-two-pane").wait_for(state="attached", timeout=30_000)

        metrics = page.evaluate(
            """
            (width) => {
              const overlay = document.querySelector('#optimizer-overlay');
              const twoPane = document.querySelector('.optimizer-two-pane');
              const ternary = document.querySelector('.optimizer-ternary-svg');
              const presets = document.querySelector('.optimizer-preset-row');
              const fieldRow = document.querySelector('.optimizer-field-row');

              const syntheticSplit = document.createElement('div');
              syntheticSplit.className = 'optimizer-results-split';
              syntheticSplit.innerHTML = '<div></div><div></div>';
              overlay.appendChild(syntheticSplit);

              const overlayRect = overlay.getBoundingClientRect();
              const ternaryRect = ternary.getBoundingClientRect();
              const presetStyle = getComputedStyle(presets);
              const result = {
                width,
                documentScrollWidth: document.documentElement.scrollWidth,
                overlayLeft: overlayRect.left,
                overlayRight: overlayRect.right,
                overlayWidth: overlayRect.width,
                overlayMaxWidth: getComputedStyle(overlay).maxWidth,
                twoPaneDirection: getComputedStyle(twoPane).flexDirection,
                ternaryWidth: ternaryRect.width,
                presetDisplay: presetStyle.display,
                presetColumns: presetStyle.gridTemplateColumns,
                resultDirection: getComputedStyle(syntheticSplit).flexDirection,
                fieldDirection: fieldRow ? getComputedStyle(fieldRow).flexDirection : null,
                bodyMobile: document.body.dataset.mobile || null,
              };
              syntheticSplit.remove();
              return result;
            }
            """,
            width,
        )

        require(
            metrics["documentScrollWidth"] <= width + 1,
            f"{width}px: horizontal document overflow {metrics}",
        )
        require(
            metrics["overlayLeft"] >= -1 and metrics["overlayRight"] <= width + 1,
            f"{width}px: optimizer escaped viewport {metrics}",
        )
        if width <= 900:
            require(metrics["twoPaneDirection"] == "column", f"{width}px: panes not stacked")
            require(metrics["presetDisplay"] == "grid", f"{width}px: presets not a grid")
            require(metrics["resultDirection"] == "column", f"{width}px: results not stacked")
            require(metrics["ternaryWidth"] <= width + 1, f"{width}px: ternary SVG overflow")
        if width == 480:
            require(
                len(metrics["presetColumns"].split()) == 3,
                f"480px: expected three preset columns: {metrics}",
            )
            require(metrics["fieldDirection"] == "column", "480px: fields not stacked")
        if width == 1920:
            require(metrics["overlayWidth"] <= 1401, f"1920px: upstream width cap changed")

        require(not page_errors, f"{width}px: uncaught browser errors: {page_errors}")
        page.screenshot(
            path=str(ARTIFACT_DIR / f"optimizer-{width}px.png"), full_page=True
        )
        results.append({"metrics": metrics, "pageErrors": page_errors})
        context.close()
    browser.close()

(ARTIFACT_DIR / "viewport-results.json").write_text(
    json.dumps(results, indent=2), encoding="utf-8"
)
print(json.dumps(results, indent=2))
