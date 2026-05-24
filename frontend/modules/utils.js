window.EFTForge = window.EFTForge || {};

window.EFTForge.utils = {};

function proxyAvatarUrl(url) {
    if (!url) return null;
    if (url.startsWith("https://gitee.com/") || url.startsWith("https://raw.giteeusercontent.com/")) {
        const base = (window.EFTForge && EFTForge.config && EFTForge.config.API_BASE) || "";
        return `${base}/proxy-asset?url=${encodeURIComponent(url)}`;
    }
    return url;
}

/* --- Mobile detection --- */

function isMobileLayout() {
    const hasTouch = navigator.maxTouchPoints > 0;
    const hasCoarsePointer = window.matchMedia('(pointer: coarse)').matches;
    const mobileUA = /Android|iPhone|iPad|iPod|Opera Mini|IEMobile|WPDesktop/i.test(navigator.userAgent);
    return (hasTouch && hasCoarsePointer) || (hasTouch && mobileUA);
}

/* --- Cache --- */

const CACHE_MAX = 300;

function cacheSet(cache, key, value) {
    if (Object.keys(cache).length >= CACHE_MAX) {
        // Drop the oldest ~half to avoid thrashing on a full cache
        const keys = Object.keys(cache);
        for (let i = 0; i < Math.floor(CACHE_MAX / 2); i++) delete cache[keys[i]];
    }
    cache[key] = value;
}

function cacheGet(cache, key) {
    if (!(key in cache)) return undefined;
    const val = cache[key];
    delete cache[key];
    cache[key] = val; // re-insert as newest for LRU ordering
    return val;
}

/* --- Number formatting --- */

function _formatPrice(n) {
    if (n == null) return "";
    return Math.round(n).toString().replace(/\B(?=(\d{3})+(?!\d))/g, "\u00a0") + "₽";
}

/**
 * Format a stat value: shows as integer when the fractional part is negligible,
 * otherwise rounds to `decimals` decimal places.
 */
function formatStat(val, decimals = 1) {
    return Math.abs(val - Math.round(val)) < 0.001 ? Math.round(val) : val.toFixed(decimals);
}

/* --- String helpers --- */

function escapeHtml(str) {
    if (!str) return "";
    return String(str)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;");
}

/* --- Panel loading overlay --- */

function startPanelLoading(panelEl, delayMs = 0) {
    const state = { overlay: null, timer: null };
    const show = () => {
        const overlay = document.createElement("div");
        overlay.className = "panel-loading-overlay";
        panelEl.appendChild(overlay);
        state.overlay = overlay;
    };
    if (delayMs > 0) {
        state.timer = setTimeout(show, delayMs);
    } else {
        show();
    }
    return state;
}

function stopPanelLoading(state) {
    if (!state) return;
    if (state.timer) clearTimeout(state.timer);
    if (state.overlay && state.overlay.isConnected) state.overlay.remove();
}

/* --- Toast notifications --- */

// actions: optional array of { label, onClick } - if provided, toast stays until an action is clicked
// pass duration = 0 to keep the toast open indefinitely (requires actions to dismiss it)
function _hexToRgba(hex, alpha) {
    const r = parseInt(hex.slice(1, 3), 16);
    const g = parseInt(hex.slice(3, 5), 16);
    const b = parseInt(hex.slice(5, 7), 16);
    return `rgba(${r}, ${g}, ${b}, ${alpha})`;
}

function _updateBlobColor() {
    const toasts = document.querySelectorAll(".toast.show");
    if (toasts.length > 0) {
        const blobColor = toasts[toasts.length - 1].dataset.blobColor;
        if (blobColor) document.documentElement.style.setProperty("--blob-color", blobColor);
    } else if (EFTForge.state.compareMode || (EFTForge.state.pveMode && EFTForge.state.priceView)) {
        document.documentElement.style.setProperty("--blob-color", "rgba(0, 200, 180, 0.10)");
    } else {
        document.documentElement.style.removeProperty("--blob-color");
    }
}

function showToast(title, message, duration = 3000, color = "#f44336", actions = null, dismissible = true) {
    const container = document.getElementById("toast-container");

    const toast = document.createElement("div");
    toast.className = "toast";
    toast.dataset.blobColor = _hexToRgba(color, 0.12);
    toast.style.borderLeftColor = color;

    const titleEl = document.createElement("div");
    titleEl.className = "toast-title";
    titleEl.style.color = color;
    if (title.endsWith("...")) {
        titleEl.textContent = title.slice(0, -3);
        for (let i = 0; i < 3; i++) {
            const dot = document.createElement("span");
            dot.className = "toast-dot";
            dot.textContent = ".";
            titleEl.appendChild(dot);
        }
    } else {
        titleEl.textContent = title;
    }

    const bodyEl = document.createElement("div");
    bodyEl.className = "toast-body";
    if (message.endsWith("...")) {
        bodyEl.textContent = message.slice(0, -3);
        for (let i = 0; i < 3; i++) {
            const dot = document.createElement("span");
            dot.className = "toast-dot";
            dot.textContent = ".";
            bodyEl.appendChild(dot);
        }
    } else {
        bodyEl.textContent = message;
    }

    toast.appendChild(titleEl);
    toast.appendChild(bodyEl);

    if (actions && actions.length > 0) {
        const actionsEl = document.createElement("div");
        actionsEl.className = "toast-actions";
        actions.forEach(({ label, onClick }) => {
            const btn = document.createElement("button");
            btn.className = "toast-action-btn";
            btn.textContent = label;
            btn.addEventListener("click", () => {
                dismiss();
                onClick();
            });
            actionsEl.appendChild(btn);
        });
        toast.appendChild(actionsEl);
    }

    if (dismissible) {
        toast.classList.add("dismissible");
        const hint = document.createElement("span");
        hint.className = "toast-dismiss-hint";
        hint.textContent = "×";
        toast.appendChild(hint);
        toast.addEventListener("click", (e) => {
            if (!e.target.closest(".toast-action-btn")) dismiss();
        });
    }

    container.appendChild(toast);

    setTimeout(() => { toast.classList.add("show"); _updateBlobColor(); }, 10);

    function dismiss() {
        toast.classList.remove("show");
        setTimeout(() => {
            if (toast.isConnected) container.removeChild(toast);
            _updateBlobColor();
        }, 250);
    }

    if (duration > 0) setTimeout(dismiss, duration);
    return toast;
}

function setToastStatus(toastEl, text) {
    const body = toastEl?.querySelector(".toast-body");
    if (body) body.textContent = text;
}

/* --- Modal factory --- */

function _createModalOverlay(id, title, opts = {}) {
    if (document.getElementById(id)) return null;
    const {
        closeId     = `${id}-close`,
        bodyId      = `${id}-body`,
        maxWidth    = "",
        titleExtra  = "",
        tabs        = null,
        onTabSwitch = null,
    } = opts;

    const overlay = document.createElement("div");
    overlay.id = id;
    overlay.className = "modal-overlay";

    const winStyle = maxWidth ? ` style="max-width:${maxWidth};"` : "";
    const headerHtml = `
        <div class="modal-header">
            <span class="modal-title">${title}</span>
            ${titleExtra}
            <button class="modal-close-btn" id="${closeId}" aria-label="Close dialog">&#x2715;</button>
        </div>`;

    if (tabs && tabs.length > 0) {
        const tabBtns = tabs.map((tab, i) =>
            `<button class="modal-tab${i === 0 ? " active" : ""}" data-target="${tab.id}">${tab.label}</button>`
        ).join("");
        const tabPanels = tabs.map((tab, i) =>
            `<div class="modal-tab-panel${i === 0 ? " active" : ""}" id="${tab.id}"></div>`
        ).join("");
        overlay.innerHTML = `
            <div class="modal-outer">
                <div class="modal-tab-rail">${tabBtns}</div>
                <div class="modal-window"${winStyle}>
                    ${headerHtml}
                    <div class="modal-body" id="${bodyId}">${tabPanels}</div>
                </div>
            </div>`;
    } else {
        overlay.innerHTML = `
            <div class="modal-window"${winStyle}>
                ${headerHtml}
                <div class="modal-body" id="${bodyId}"></div>
            </div>`;
    }

    document.body.appendChild(overlay);
    document.getElementById(closeId).addEventListener("click", () => overlay.remove());
    let _mdOnBackdrop = false;
    overlay.addEventListener("mousedown", e => { _mdOnBackdrop = e.target === overlay; });
    overlay.addEventListener("click", (e) => { if (e.target === overlay && _mdOnBackdrop) overlay.remove(); });

    if (tabs && tabs.length > 0) {
        overlay.querySelectorAll(".modal-tab").forEach(btn => {
            btn.addEventListener("click", () => {
                const targetId = btn.dataset.target;
                overlay.querySelectorAll(".modal-tab").forEach(b => b.classList.remove("active"));
                overlay.querySelectorAll(".modal-tab-panel").forEach(p => p.classList.remove("active"));
                btn.classList.add("active");
                const panel = document.getElementById(targetId);
                if (panel) {
                    panel.style.animation = "none";
                    panel.offsetHeight;
                    panel.style.animation = "";
                    panel.classList.add("active");
                }
                onTabSwitch?.(targetId);
            });
        });
    }

    return overlay;
}

/* --- Promise timeout --- */

/**
 * Race a promise against a timeout. Rejects with an Error if the promise
 * does not settle within `ms` milliseconds.
 */
function withTimeout(promise, ms = 15000) {
    const timeout = new Promise((_, reject) =>
        setTimeout(() => reject(new Error(`Request timed out after ${ms}ms`)), ms)
    );
    return Promise.race([promise, timeout]);
}

/* --- Marquee / sleep --- */

let _marqueeGeneration = 0;
let _marqueeObservers = [];

function _clearMarqueeTimers() {
    _marqueeGeneration++;
    for (const ro of _marqueeObservers) ro.disconnect();
    _marqueeObservers = [];
}

function _sleep(ms) {
    return new Promise(resolve => setTimeout(resolve, ms));
}

function _initMarqueeText(container, { hoverOnly = false, hoverTarget = "tr" } = {}) {
    container.querySelectorAll(".marquee-text").forEach(el => {
        const parent = el.parentElement;
        if (!parent) return;

        let elGen = 0;
        const globalGen = _marqueeGeneration;

        function resetEl() {
            elGen++;
            el.style.transition = "none";
            el.style.transform = "translateX(0)";
            el.style.opacity = "1";
        }

        function startMarquee() {
            elGen++;
            const myElGen = elGen;

            requestAnimationFrame(async () => {
                if (_marqueeGeneration !== globalGen) return;

                const overflow = el.offsetWidth - parent.clientWidth;

                if (overflow <= 2) {
                    // No overflow - reset to natural state
                    el.style.transition = "none";
                    el.style.transform = "translateX(0)";
                    el.style.opacity = "1";
                    return;
                }

                const scrollDuration = Math.max(1200, (overflow / 45) * 1000);

                async function runCycle() {
                    if (_marqueeGeneration !== globalGen || elGen !== myElGen) return;

                    // Pause while document is not visible to save CPU
                    if (document.hidden) {
                        await _sleep(1000);
                        runCycle();
                        return;
                    }

                    // Snap to start
                    el.style.transition = "none";
                    el.style.transform = "translateX(0)";
                    el.style.opacity = "1";

                    // Phase 1 - pause at start (skipped on hover-triggered cycles)
                    if (!hoverOnly) await _sleep(800);
                    if (_marqueeGeneration !== globalGen || elGen !== myElGen) return;

                    // Phase 2 - scroll to end
                    el.style.transition = `transform ${scrollDuration}ms linear`;
                    el.style.transform = `translateX(-${overflow}px)`;
                    await _sleep(scrollDuration);
                    if (_marqueeGeneration !== globalGen || elGen !== myElGen) return;

                    // Phase 3 - pause at end
                    await _sleep(700);
                    if (_marqueeGeneration !== globalGen || elGen !== myElGen) return;

                    // Phase 4 - fade out
                    el.style.transition = "opacity 0.35s ease";
                    el.style.opacity = "0";
                    await _sleep(400);
                    if (_marqueeGeneration !== globalGen || elGen !== myElGen) return;

                    // Phase 5 - snap back while invisible
                    el.style.transition = "none";
                    el.style.transform = "translateX(0)";

                    // Phase 6 - fade in (double rAF ensures the transition
                    // applies after the snap)
                    await new Promise(resolve =>
                        requestAnimationFrame(() => requestAnimationFrame(resolve))
                    );
                    if (_marqueeGeneration !== globalGen || elGen !== myElGen) return;

                    el.style.transition = "opacity 0.35s ease";
                    el.style.opacity = "1";

                    await _sleep(1500);
                    runCycle();
                }

                runCycle();
            });
        }

        if (hoverOnly) {
            // Start scrolling when the row is hovered, reset immediately on leave
            const row = parent.closest(hoverTarget);
            if (row) {
                row.addEventListener("mouseenter", startMarquee);
                row.addEventListener("mouseleave", resetEl);
            }
            // ResizeObserver only resets position - no ambient animation
            const ro = new ResizeObserver(resetEl);
            ro.observe(parent);
            _marqueeObservers.push(ro);
        } else {
            const ro = new ResizeObserver(startMarquee);
            ro.observe(parent);
            _marqueeObservers.push(ro);
        }
    });
}

/* --- Exports --- */

EFTForge.utils.formatStat          = formatStat;
EFTForge.utils.withTimeout         = withTimeout;
EFTForge.utils.cacheSet            = cacheSet;
EFTForge.utils.cacheGet            = cacheGet;
EFTForge.utils.escapeHtml          = escapeHtml;
EFTForge.utils.startPanelLoading   = startPanelLoading;
EFTForge.utils.stopPanelLoading    = stopPanelLoading;
EFTForge.utils.showToast           = showToast;
EFTForge.utils.updateBlobColor     = _updateBlobColor;
EFTForge.utils._createModalOverlay = _createModalOverlay;
EFTForge.utils._clearMarqueeTimers = _clearMarqueeTimers;
EFTForge.utils._sleep              = _sleep;
EFTForge.utils._initMarqueeText    = _initMarqueeText;
