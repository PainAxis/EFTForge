import json
import os
from pathlib import Path

import requests
from playwright.sync_api import sync_playwright

BASE_URL = os.environ["BASE_URL"].rstrip("/")
ARTIFACT_DIR = Path(os.environ["RUNNER_TEMP"]) / "smoke-artifacts"
ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)

VIEWPORTS = (1920, 901, 900, 767, 543, 480)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


guns = requests.get(f"{BASE_URL}/guns", timeout=30).json()
gun = next(
    (item for item in guns if "M4A1" in item.get("name", "") and item.get("factory_attachment_ids")),
    next(item for item in guns if item.get("caliber") != "Caliber20x1mm" and item.get("factory_attachment_ids")),
)

results = []
with sync_playwright() as playwright:
    browser = playwright.chromium.launch()
    for width in VIEWPORTS:
        context = browser.new_context(viewport={"width": width, "height": 1000})
        context.add_init_script("localStorage.setItem('eftforge_news_seen', '2026-07-26-desktop-app-launch')")
        page = context.new_page()
        page_errors = []
        page.on("pageerror", lambda error: page_errors.append(str(error)))

        response = page.goto(BASE_URL, wait_until="domcontentloaded", timeout=120_000)
        require(response is not None and response.ok, f"{width}px: page load failed")
        gun_card = page.locator(f'.gun-card[data-gun-id="{gun["id"]}"]')
        gun_card.wait_for(state="visible", timeout=120_000)
        news_backdrop = page.locator("#news-backdrop.visible")
        if news_backdrop.is_visible():
            news_backdrop.click()
            news_backdrop.wait_for(state="hidden", timeout=30_000)
        gun_card.click()
        page.wait_for_function("() => Boolean(window.EFTForge?.state?.currentGun)", timeout=120_000)
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

        # Exercise the real solver and real manifest DOM: the regression only
        # appears once the table has populated rows at its intrinsic width.
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

        metrics = page.evaluate(
            """
            (width) => {
              const overlay = document.querySelector('#optimizer-overlay');
              const twoPane = document.querySelector('.optimizer-two-pane');
              const ternary = document.querySelector('.optimizer-ternary-svg');
              const presets = document.querySelector('.optimizer-preset-row');
              const currentBuild = document.querySelector('.optimizer-results-split');
              const resultsPane = document.querySelector('#optimizer-results-pane');
              const manifest = document.querySelector('.optimizer-manifest');
              const wrap = document.querySelector('.optimizer-manifest-table-wrap');
              const table = document.querySelector('.optimizer-manifest-table');
              const visibleHeaders = [...table.querySelectorAll('th')]
                .filter(header => getComputedStyle(header).display !== 'none');
              const lastHeader = visibleHeaders.at(-1);

              const overlayRect = overlay.getBoundingClientRect();
              const ternaryRect = ternary.getBoundingClientRect();
              const presetStyle = getComputedStyle(presets);
              const currentBuildRect = currentBuild.getBoundingClientRect();
              const manifestRect = manifest.getBoundingClientRect();
              const wrapRect = wrap.getBoundingClientRect();
              const lastHeaderBefore = lastHeader.getBoundingClientRect();
              const beforeScroll = {
                scrollLeft: wrap.scrollLeft,
                lastHeaderLeft: lastHeaderBefore.left,
                lastHeaderRight: lastHeaderBefore.right,
              };

              const horizontalScroller = width <= 900 ? wrap : resultsPane;
              horizontalScroller.scrollLeft = horizontalScroller.scrollWidth;
              const lastHeaderAfter = lastHeader.getBoundingClientRect();
              const horizontalScrollerRect = horizontalScroller.getBoundingClientRect();
              const maxScrollLeft =
                horizontalScroller.scrollWidth - horizontalScroller.clientWidth;
              const result = {
                width,
                documentScrollWidth: document.documentElement.scrollWidth,
                overlayLeft: overlayRect.left,
                overlayRight: overlayRect.right,
                overlayWidth: overlayRect.width,
                overlayMaxWidth: getComputedStyle(overlay).maxWidth,
                overlayClientHeight: overlay.clientHeight,
                overlayScrollHeight: overlay.scrollHeight,
                twoPaneDirection: getComputedStyle(twoPane).flexDirection,
                ternaryWidth: ternaryRect.width,
                presetDisplay: presetStyle.display,
                presetColumns: presetStyle.gridTemplateColumns,
                resultDirection: getComputedStyle(currentBuild).flexDirection,
                resultLeft: currentBuildRect.left,
                resultRight: currentBuildRect.right,
                manifestLeft: manifestRect.left,
                manifestRight: manifestRect.right,
                manifestWidth: manifestRect.width,
                wrapLeft: wrapRect.left,
                wrapRight: wrapRect.right,
                wrapClientWidth: wrap.clientWidth,
                wrapScrollWidth: wrap.scrollWidth,
                wrapScrollLeft: wrap.scrollLeft,
                wrapMaxScrollLeft: wrap.scrollWidth - wrap.clientWidth,
                wrapOverflowX: getComputedStyle(wrap).overflowX,
                resultsOverflow: getComputedStyle(resultsPane).overflow,
                resultsClientWidth: resultsPane.clientWidth,
                resultsScrollWidth: resultsPane.scrollWidth,
                resultsScrollLeft: resultsPane.scrollLeft,
                resultsMaxScrollLeft:
                  resultsPane.scrollWidth - resultsPane.clientWidth,
                horizontalScroller:
                  horizontalScroller === wrap ? 'manifest-wrap' : 'results-pane',
                horizontalScrollerLeft: horizontalScrollerRect.left,
                horizontalScrollerRight: horizontalScrollerRect.right,
                horizontalScrollLeft: horizontalScroller.scrollLeft,
                horizontalMaxScrollLeft: maxScrollLeft,
                tableWidth: table.getBoundingClientRect().width,
                visibleHeaderCount: visibleHeaders.length,
                lastHeaderText: lastHeader.textContent.trim(),
                lastHeaderLeft: lastHeaderAfter.left,
                lastHeaderRight: lastHeaderAfter.right,
                beforeScroll,
                bodyMobile: document.body.dataset.mobile || null,
              };
              overlay.scrollTop = overlay.scrollHeight;
              result.overlayScrollTop = overlay.scrollTop;
              result.overlayMaxScrollTop = overlay.scrollHeight - overlay.clientHeight;
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
        require(
            metrics["resultLeft"] >= metrics["overlayLeft"] - 1
            and metrics["resultRight"] <= metrics["overlayRight"] + 1,
            f"{width}px: current-build panel escaped drawer {metrics}",
        )
        require(
            abs(metrics["overlayScrollTop"] - metrics["overlayMaxScrollTop"]) <= 1,
            f"{width}px: outer drawer cannot reach its vertical end {metrics}",
        )

        if width <= 900:
            require(
                metrics["manifestLeft"] >= metrics["overlayLeft"] - 1
                and metrics["manifestRight"] <= metrics["overlayRight"] + 1,
                f"{width}px: manifest panel escaped drawer {metrics}",
            )
            require(metrics["twoPaneDirection"] == "column", f"{width}px: panes not stacked")
            require(metrics["presetDisplay"] == "grid", f"{width}px: presets not a grid")
            require(metrics["resultDirection"] == "column", f"{width}px: results not stacked")
            require(metrics["ternaryWidth"] <= width + 1, f"{width}px: ternary SVG overflow")
            require(
                metrics["wrapOverflowX"] == "auto",
                f"{width}px: manifest wrapper is not scrollable {metrics}",
            )
            if metrics["wrapScrollWidth"] > metrics["wrapClientWidth"] + 1:
                require(
                    abs(metrics["wrapScrollLeft"] - metrics["wrapMaxScrollLeft"]) <= 1,
                    f"{width}px: cannot reach manifest's horizontal end {metrics}",
                )
                require(
                    metrics["lastHeaderLeft"] >= metrics["wrapLeft"] - 1
                    and metrics["lastHeaderRight"] <= metrics["wrapRight"] + 1,
                    f"{width}px: final manifest column remains inaccessible {metrics}",
                )
        else:
            require(
                metrics["wrapOverflowX"] == "visible",
                f"{width}px: desktop manifest overflow behavior changed {metrics}",
            )
            if metrics["resultsScrollWidth"] > metrics["resultsClientWidth"] + 1:
                require(
                    abs(metrics["resultsScrollLeft"] - metrics["resultsMaxScrollLeft"]) <= 1,
                    f"{width}px: desktop results pane cannot reach its horizontal end {metrics}",
                )
                require(
                    metrics["lastHeaderLeft"] >= metrics["horizontalScrollerLeft"] - 1
                    and metrics["lastHeaderRight"] <= metrics["horizontalScrollerRight"] + 1,
                    f"{width}px: desktop final manifest column inaccessible {metrics}",
                )

        if width in (543, 480):
            require(
                metrics["wrapScrollWidth"] > metrics["wrapClientWidth"] + 1,
                f"{width}px: regression fixture did not overflow {metrics}",
            )
        if width == 480:
            require(
                len(metrics["presetColumns"].split()) == 3,
                f"480px: expected three preset columns: {metrics}",
            )
        if width == 1920:
            require(metrics["overlayWidth"] <= 1401, f"1920px: upstream width cap changed")

        require(not page_errors, f"{width}px: uncaught browser errors: {page_errors}")
        page.screenshot(
            path=str(ARTIFACT_DIR / f"optimizer-manifest-{width}px.png"),
            full_page=True,
        )
        results.append({"metrics": metrics, "pageErrors": page_errors})
        context.close()
    browser.close()

(ARTIFACT_DIR / "viewport-results.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
print(json.dumps(results, indent=2))
