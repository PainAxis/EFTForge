/* ============================================================
   DESKTOP APP WINDOW CONTROLS
   Only active inside the packaged desktop app (see desktop-settings.js for
   the same self-exit convention). The window has no native title bar (see
   decorations(false) in desktop/src-tauri/src/main.rs) - the site's own
   header bar plays that role instead:
     - most of the header's empty space becomes a drag region
       (data-tauri-drag-region on <header> and .header-content - it only
       triggers when the click lands on that element's own background, so
       the logo, clock, lang switcher and nav buttons are unaffected)
     - a minimize / maximize / close button group is appended to the right
       of the header, sized/positioned via the "has-window-controls" CSS in
       index.html. Unlike the nav buttons, these never fade or collapse
       with the header's expand/collapse animation.
============================================================ */
(function () {
    if (!window.__EFTFORGE_DESKTOP__ || !window.__TAURI__) return;

    const appWindow = window.__TAURI__.window.getCurrentWindow();

    const MAXIMIZE_ICON =
        '<svg width="10" height="10" viewBox="0 0 10 10"><rect x="1.5" y="1.5" width="7" height="7" fill="none" stroke="currentColor" stroke-width="1.2"/></svg>';
    const RESTORE_ICON =
        '<svg width="10" height="10" viewBox="0 0 10 10"><rect x="1" y="2.5" width="6.5" height="6.5" fill="none" stroke="currentColor" stroke-width="1.1"/><path d="M2.8 2.5V1h6.5v6.5H8" fill="none" stroke="currentColor" stroke-width="1.1"/></svg>';

    function _init() {
        const header = document.querySelector("header");
        if (!header) return;

        header.setAttribute("data-tauri-drag-region", "");
        const content = header.querySelector(".header-content");
        if (content) content.setAttribute("data-tauri-drag-region", "");
        header.classList.add("has-window-controls");

        const controls = document.createElement("div");
        controls.className = "window-controls";
        controls.innerHTML = `
            <button class="window-btn" id="win-minimize-btn" aria-label="${t("dt.winMinimize")}">
                <svg width="10" height="10" viewBox="0 0 10 10"><line x1="1" y1="5" x2="9" y2="5" stroke="currentColor" stroke-width="1.2" stroke-linecap="round"/></svg>
            </button>
            <button class="window-btn" id="win-maximize-btn" aria-label="${t("dt.winMaximize")}">${MAXIMIZE_ICON}</button>
            <button class="window-btn window-btn-close" id="win-close-btn" aria-label="${t("dt.winClose")}">
                <svg width="10" height="10" viewBox="0 0 10 10"><line x1="1" y1="1" x2="9" y2="9" stroke="currentColor" stroke-width="1.2" stroke-linecap="round"/><line x1="9" y1="1" x2="1" y2="9" stroke="currentColor" stroke-width="1.2" stroke-linecap="round"/></svg>
            </button>
        `;
        header.appendChild(controls);

        const maximizeBtn = controls.querySelector("#win-maximize-btn");

        // No title attribute on any of these buttons - deliberate, the icons
        // don't need a hover tooltip on top of them.
        async function syncMaximizeIcon() {
            const maximized = await appWindow.isMaximized();
            maximizeBtn.innerHTML = maximized ? RESTORE_ICON : MAXIMIZE_ICON;
            maximizeBtn.setAttribute("aria-label", maximized ? t("dt.winRestore") : t("dt.winMaximize"));
        }

        controls.querySelector("#win-minimize-btn").addEventListener("click", () => appWindow.minimize());
        maximizeBtn.addEventListener("click", () => appWindow.toggleMaximize());
        controls.querySelector("#win-close-btn").addEventListener("click", () => appWindow.close());

        // Catches every path that changes the maximized state - the button
        // above, double-clicking the drag region, and Windows edge/Win+arrow
        // snapping.
        appWindow.onResized(syncMaximizeIcon);
        syncMaximizeIcon();
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", _init);
    } else {
        _init();
    }
})();
