window.EFTForge = window.EFTForge || {};

/* ============================================================
   TAB MANAGER (desktop only)
   Browser-style tabs over EFTForge.state's build fields. Only one
   build is ever "live" in EFTForge.state at a time - a tab record
   is just that live state serialized to the same {pairs, ammo, ...}
   shape build-manager.js already uses for saved/community/URL builds.
   Switching tabs re-uses loadBuildFromPayload(); gun init data is
   cached per gun id (gun-list.js's _gunInitCache) so revisiting an
   already-open tab never touches the network.
============================================================ */

const TAB_STORAGE_KEY = "eftforge_tabs_v1";

let _tabIdCounter = 0;
let _tabSwitchInFlight = false;
const _tabHistory = new Map(); // tabId -> { buildHistory, buildFuture } (session-only, not persisted)

// _isDesktopTabs() is defined in gun-list.js (loads before this module)

function _newTabId() {
    return "tab_" + Date.now().toString(36) + "_" + (_tabIdCounter++);
}

/* ===========================
   PERSISTENCE
=========================== */

let _persistTimer = null;

function _persistTabs() {
    if (!_isDesktopTabs()) return;
    try {
        const payload = {
            version: 1,
            activeTabId: EFTForge.state.activeTabId,
            tabs: EFTForge.state.tabs.map(t => ({
                id: t.id, gunId: t.gunId, pinned: t.pinned, buildName: t.buildName,
                communityBuild: t.communityBuild, pairs: t.pairs, ammoId: t.ammoId,
                ubglAmmoId: t.ubglAmmoId, collapsedSlots: t.collapsedSlots,
            })),
        };
        localStorage.setItem(TAB_STORAGE_KEY, JSON.stringify(payload));
    } catch (_) {}
}

function _persistTabsDebounced() {
    clearTimeout(_persistTimer);
    _persistTimer = setTimeout(_persistTabs, 250);
}

async function restoreTabsFromStorage() {
    if (!_isDesktopTabs()) return;
    let data;
    try {
        const raw = localStorage.getItem(TAB_STORAGE_KEY);
        if (!raw) return;
        data = JSON.parse(raw);
    } catch (_) { return; }
    if (!data || data.version !== 1 || !Array.isArray(data.tabs) || data.tabs.length === 0) return;

    const restored = data.tabs.filter(t => EFTForge.state.allGuns.some(g => g.id === t.gunId));
    if (restored.length === 0) return;

    EFTForge.state.tabs = restored.map(t => ({
        id: t.id, gunId: t.gunId, pinned: !!t.pinned, buildName: t.buildName || null,
        communityBuild: t.communityBuild || null, pairs: Array.isArray(t.pairs) ? t.pairs : [],
        ammoId: t.ammoId || null, ubglAmmoId: t.ubglAmmoId || null,
        collapsedSlots: t.collapsedSlots || {},
    }));
    EFTForge.state.tabs.forEach(t => _tabHistory.set(t.id, { buildHistory: [], buildFuture: [] }));

    // Tabs are restored but left inactive - a reload always lands on the gun
    // grid, never jumps straight back into whichever tab was last active.
    EFTForge.state.activeTabId = null;
    renderTabBar();
}

/* ===========================
   ACTIVE-TAB SYNC
=========================== */

// Flush the currently-active tab's live EFTForge.state into its record before
// switching focus away from it (or before creating a brand new tab).
function _serializeActiveTab() {
    const activeId = EFTForge.state.activeTabId;
    if (!activeId) return;
    const tab = EFTForge.state.tabs.find(t => t.id === activeId);
    if (!tab || !EFTForge.state.currentGun) return;
    tab.pairs = collectSlotPairs(EFTForge.state.buildTree);
    tab.ammoId = document.getElementById("ammo-select")?.value || null;
    tab.ubglAmmoId = document.getElementById("ubgl-ammo-select")?.value || null;
    tab.collapsedSlots = { ...EFTForge.state.collapsedSlots };
    _tabHistory.set(activeId, {
        buildHistory: [...EFTForge.state.buildHistory],
        buildFuture:  [...EFTForge.state.buildFuture],
    });
}

// Called from syncBuildDisplayName() (build-manager.js) after every meaningful
// build mutation - keeps the active tab's title and stored snapshot current.
function syncActiveTab({ buildName = null, communityBuild = null } = {}) {
    if (!_isDesktopTabs()) return;
    const activeId = EFTForge.state.activeTabId;
    if (!activeId) return;
    const tab = EFTForge.state.tabs.find(t => t.id === activeId);
    if (!tab) return;
    tab.buildName = buildName;
    tab.communityBuild = communityBuild;
    tab.pairs = collectSlotPairs(EFTForge.state.buildTree);
    tab.ammoId = document.getElementById("ammo-select")?.value || null;
    tab.ubglAmmoId = document.getElementById("ubgl-ammo-select")?.value || null;
    tab.collapsedSlots = { ...EFTForge.state.collapsedSlots };
    _persistTabsDebounced();
    renderTabBar();
}

/* ===========================
   CORE ACTIONS
=========================== */

// A tab counts as a duplicate of {gunId, pairs, ammoId, ubglAmmoId} when the
// gun and the full attachment/ammo state match exactly - buildName/pinned/
// collapsedSlots are just labels/UI state and don't factor in. Used to fold
// automatic tab creation (fresh gun pick, saved/community/URL build) into an
// existing tab instead of opening a carbon copy; explicit right-click
// Duplicate deliberately skips this check.
//
// A null incoming ammoId/ubglAmmoId (a saved/community/URL build whose code
// never specified one) is a wildcard, not a "no ammo" requirement - loadAmmoForGun
// (gun-list.js) always auto-selects a default the moment the gun/caliber loads, so
// any already-open tab's ammoId is never actually null. Comparing null against that
// live default would fail every time, so a build with no explicit ammo could never
// be recognized as already open and would spawn a fresh tab on every Load/Publish.
function _findDuplicateTab(gunId, pairs, ammoId, ubglAmmoId, excludeTabId = null) {
    const key = _pairsKey(pairs || []);
    return EFTForge.state.tabs.find(t =>
        t.id !== excludeTabId &&
        t.gunId === gunId &&
        _pairsKey(t.pairs) === key &&
        (ammoId === null || (t.ammoId || null) === ammoId) &&
        (ubglAmmoId === null || (t.ubglAmmoId || null) === ubglAmmoId)
    );
}

// A fresh gun pick from gunSelect - always opens a brand new tab with the
// gun's factory attachment set (selectGun applies it exactly as today),
// unless that exact factory build is already open in another tab.
async function createTabForGun(gun, card = null) {
    if (!gun || _tabSwitchInFlight) return;
    _tabSwitchInFlight = true;
    try {
        _serializeActiveTab();

        const id = _newTabId();
        const tab = { id, gunId: gun.id, pinned: false, buildName: null, communityBuild: null, pairs: [], ammoId: null, ubglAmmoId: null, collapsedSlots: {} };
        EFTForge.state.tabs.push(tab);
        EFTForge.state.activeTabId = id;
        _tabHistory.set(id, { buildHistory: [], buildFuture: [] });

        EFTForge.state.currentGun = null; // bypass selectGun's same-gun guard
        const el = card || { classList: { add() {}, remove() {} } };
        await selectGun(gun, el);

        tab.pairs = collectSlotPairs(EFTForge.state.buildTree);
        tab.ammoId = document.getElementById("ammo-select")?.value || null;
        tab.ubglAmmoId = document.getElementById("ubgl-ammo-select")?.value || null;

        const dup = _findDuplicateTab(gun.id, tab.pairs, tab.ammoId, tab.ubglAmmoId, id);
        if (dup) {
            EFTForge.state.tabs = EFTForge.state.tabs.filter(t => t.id !== id);
            _tabHistory.delete(id);
            await _activateTab(dup.id);
            _persistTabs();
            _scrollTabIntoView(dup.id);
            return;
        }

        _persistTabs();
        renderTabBar();
        _scrollTabIntoView(id);
    } finally {
        _tabSwitchInFlight = false;
    }
}

// A saved build / community build / shared-URL build - opens as a new tab
// carrying that build's name (and community attribution, if any), unless
// that exact build is already open in another tab.
async function createTabFromPayload(payload, buildName = null, communityBuild = null, silent = true) {
    if (_tabSwitchInFlight) return;
    const gun = EFTForge.state.allGuns.find(g => g.id === payload.g);
    if (!gun) {
        showToast(t("toast.loadFailed"), t("toast.unknownWeapon"), 3500);
        return;
    }

    _serializeActiveTab();

    const dup = _findDuplicateTab(gun.id, payload.p || [], payload.a || null, payload.ua || null);
    if (dup) {
        if (dup.id !== EFTForge.state.activeTabId) await switchToTab(dup.id);
        _scrollTabIntoView(dup.id);
        return;
    }

    _tabSwitchInFlight = true;
    try {
        const id = _newTabId();
        const tab = { id, gunId: gun.id, pinned: false, buildName, communityBuild, pairs: payload.p || [], ammoId: payload.a || null, ubglAmmoId: payload.ua || null, collapsedSlots: {} };
        EFTForge.state.tabs.push(tab);
        EFTForge.state.activeTabId = id;
        _tabHistory.set(id, { buildHistory: [], buildFuture: [] });

        await loadBuildFromPayload(payload, buildName, silent);
        EFTForge.state.communityBuild = communityBuild || null;
        syncBuildDisplayName();

        tab.pairs = collectSlotPairs(EFTForge.state.buildTree);
        _persistTabs();
        renderTabBar();
        _scrollTabIntoView(id);
    } finally {
        _tabSwitchInFlight = false;
    }
}

// Actual tab-activation work, shared by switchToTab() and the duplicate-
// collapse paths above (which are already inside a _tabSwitchInFlight
// section and so can't go through the guarded switchToTab()).
async function _activateTab(tabId) {
    if (tabId === EFTForge.state.activeTabId) return;
    const target = EFTForge.state.tabs.find(t => t.id === tabId);
    if (!target) return;

    const gun = EFTForge.state.allGuns.find(g => g.id === target.gunId);
    if (!gun) {
        showToast(t("toast.loadFailed"), t("toast.unknownWeapon"), 3500);
        return;
    }

    _serializeActiveTab();
    EFTForge.state.activeTabId = tabId;

    await loadBuildFromPayload({ g: target.gunId, p: target.pairs, a: target.ammoId, ua: target.ubglAmmoId }, target.buildName, true);
    EFTForge.state.communityBuild = target.communityBuild || null;
    syncBuildDisplayName();

    // loadBuildFromPayload always resets collapsedSlots - reapply this tab's own state
    EFTForge.state.collapsedSlots = target.collapsedSlots || {};
    await renderFullTree(false);

    const hist = _tabHistory.get(tabId);
    EFTForge.state.buildHistory = hist ? [...hist.buildHistory] : [];
    EFTForge.state.buildFuture  = hist ? [...hist.buildFuture]  : [];

    renderTabBar();
}

// Back button / logo click -> gun grid. No tab closes, but nothing should
// read as "active" while the user is browsing the grid; clicking the tab
// again later resumes it exactly where it was left via switchToTab().
function deactivateActiveTab() {
    if (!_isDesktopTabs()) return;
    if (!EFTForge.state.activeTabId) return;
    _serializeActiveTab();
    EFTForge.state.activeTabId = null;
    _persistTabs();
    renderTabBar();
}

async function switchToTab(tabId) {
    if (tabId === EFTForge.state.activeTabId) return;
    if (_tabSwitchInFlight) return; // ignore rapid re-clicks while a switch is already in progress
    _tabSwitchInFlight = true;
    try {
        await _activateTab(tabId);
    } finally {
        _tabSwitchInFlight = false;
    }
}

async function closeTab(tabId) {
    const idx = EFTForge.state.tabs.findIndex(t => t.id === tabId);
    if (idx === -1) return;
    const wasActive = EFTForge.state.activeTabId === tabId;
    const gunId = EFTForge.state.tabs[idx].gunId;

    EFTForge.state.tabs.splice(idx, 1);
    _tabHistory.delete(tabId);
    _evictUnusedGunInitCache(gunId);

    if (!wasActive) {
        _persistTabs();
        renderTabBar();
        return;
    }

    if (EFTForge.state.tabs.length === 0) {
        EFTForge.state.activeTabId = null;
        _persistTabs();
        renderTabBar();
        returnToGunSelection();
        return;
    }

    const nextIdx = Math.min(idx, EFTForge.state.tabs.length - 1);
    await switchToTab(EFTForge.state.tabs[nextIdx].id);
}

async function duplicateTab(tabId) {
    const idx = EFTForge.state.tabs.findIndex(t => t.id === tabId);
    if (idx === -1) return;
    if (tabId === EFTForge.state.activeTabId) _serializeActiveTab();

    const source = EFTForge.state.tabs[idx];
    const clone = {
        ...source,
        id: _newTabId(),
        pinned: false,
        pairs: [...source.pairs],
        collapsedSlots: { ...source.collapsedSlots },
    };
    if (source.pinned) {
        EFTForge.state.tabs.push(clone);
    } else {
        EFTForge.state.tabs.splice(idx + 1, 0, clone);
    }
    _tabHistory.set(clone.id, { buildHistory: [], buildFuture: [] });
    _persistTabs();
    await switchToTab(clone.id);
}

function togglePin(tabId) {
    const idx = EFTForge.state.tabs.findIndex(t => t.id === tabId);
    if (idx === -1) return;
    const tab = EFTForge.state.tabs[idx];
    tab.pinned = !tab.pinned;
    EFTForge.state.tabs.splice(idx, 1);

    let insertAt = 0;
    while (insertAt < EFTForge.state.tabs.length && EFTForge.state.tabs[insertAt].pinned) insertAt++;
    EFTForge.state.tabs.splice(insertAt, 0, tab);

    _persistTabs();
    renderTabBar();
}

/* ===========================
   CONTEXT MENU
=========================== */

let _ctxMenuEl = null;

function _closeTabContextMenu() {
    if (_ctxMenuEl) { _ctxMenuEl.remove(); _ctxMenuEl = null; }
    document.removeEventListener("mousedown", _onCtxMenuOutside, true);
    document.removeEventListener("keydown", _onCtxMenuKey, true);
}

function _onCtxMenuOutside(e) {
    if (_ctxMenuEl && !_ctxMenuEl.contains(e.target)) _closeTabContextMenu();
}

function _onCtxMenuKey(e) {
    if (e.key === "Escape") _closeTabContextMenu();
}

function _showTabContextMenu(e, tab) {
    _closeTabContextMenu();
    _tpHide();
    const menu = document.createElement("div");
    menu.className = "tab-context-menu";
    menu.innerHTML = `
        <button type="button" data-action="duplicate">${escapeHtml(t("tab.duplicate"))}</button>
        <button type="button" data-action="pin">${escapeHtml(tab.pinned ? t("tab.unpin") : t("tab.pin"))}</button>
        <button type="button" data-action="close">${escapeHtml(t("tab.close"))}</button>
    `;
    document.body.appendChild(menu);

    const menuW = menu.offsetWidth, menuH = menu.offsetHeight;
    const left = Math.max(8, Math.min(e.clientX, window.innerWidth - menuW - 8));
    const top  = Math.max(8, Math.min(e.clientY, window.innerHeight - menuH - 8));
    menu.style.left = left + "px";
    menu.style.top  = top + "px";

    menu.addEventListener("click", (ev) => {
        const btn = ev.target.closest("button[data-action]");
        if (!btn) return;
        const action = btn.dataset.action;
        _closeTabContextMenu();
        if (action === "duplicate") duplicateTab(tab.id);
        else if (action === "pin")  togglePin(tab.id);
        else if (action === "close") closeTab(tab.id);
    });

    _ctxMenuEl = menu;
    setTimeout(() => {
        document.addEventListener("mousedown", _onCtxMenuOutside, true);
        document.addEventListener("keydown", _onCtxMenuKey, true);
    }, 0);
}

/* ===========================
   HOVER PREVIEW TOOLTIP

   Rich tooltip shown on tab-chip hover: gun image (static tarkov.dev asset,
   or a live build-preview render if the user has that toggle on) plus a
   minified version of the stats panel. Everything is computed lazily on
   hover, per tab - never eagerly for the whole bar - so opening many tabs
   never fires a burst of build-image generations.
=========================== */

const TAB_PREVIEW_HOVER_DELAY = 150; // ms - lets the cursor pass over several chips without firing requests for each
const TAB_PREVIEW_HIDE_GRACE  = 100; // ms - bridges the gap between adjacent chips so grazing it doesn't hide+reopen the tooltip

let _tpTooltipEl   = null;
let _tpGen         = 0;     // bumped on every hide/hover-away - invalidates in-flight async work
let _tpHoverTimer  = null;
let _tpHideTimer   = null;
let _tpActiveTabId = null;
let _tpImgAbort    = null;  // AbortController for the in-flight tooltip image-gen fetch
let _tpLastX       = 0;     // last known cursor position, used to resume the tooltip once a scroll animation settles
let _tpLastY       = 0;
const _tpImageCache = new Map(); // `${tabId}:${pairsKey}` -> generated image URL, avoids re-generating on repeat hovers

function _tpEnsureTooltipEl() {
    if (_tpTooltipEl) return _tpTooltipEl;
    _tpTooltipEl = document.createElement("div");
    _tpTooltipEl.id = "tab-preview-tooltip";
    document.body.appendChild(_tpTooltipEl);
    return _tpTooltipEl;
}

function _tpPosition(cx, cy) {
    if (!_tpTooltipEl) return;
    const margin = 8, offX = 14, offY = 18;
    const vw = window.innerWidth, vh = window.innerHeight;
    const w = _tpTooltipEl.offsetWidth, h = _tpTooltipEl.offsetHeight;
    let left = cx + offX;
    if (left + w > vw - margin) left = cx - w - offX;
    let top = cy + offY;
    if (top + h > vh - margin) top = cy - h - offY;
    _tpTooltipEl.style.left = Math.max(margin, left) + "px";
    _tpTooltipEl.style.top  = Math.max(margin, top) + "px";
}

function _tpHide() {
    _tpGen++;
    _tpMarqueeGen++;
    clearTimeout(_tpHoverTimer);
    clearTimeout(_tpHideTimer);
    _tpHideTimer = null;
    _tpActiveTabId = null;
    if (_tpImgAbort) { _tpImgAbort.abort(); _tpImgAbort = null; }
    if (_tpTooltipEl) _tpTooltipEl.classList.remove("visible");
}

// Ambient marquee for the tooltip's gun/build name line. Reuses the same
// timing/phases as the site's shared _initMarqueeText (utils.js) for visual
// consistency, but runs standalone rather than going through that utility:
// _initMarqueeText detects overflow via a ResizeObserver on the box, which
// only fires on box resize - it never fires just because the text inside
// changed (e.g. swapping directly between two tab chips whose build names
// differ, see the "connected" in-place-update path in _tpShow), so a
// text-driven restart needs its own explicit trigger. Its global generation
// counter is also unsuitable here since it's shared with the tab chips'
// own hover marquees (_initMarqueeText(..., { hoverTarget: ".tab-chip" })
// below) - clearing it on every tooltip show would freeze whichever chip
// label happens to be mid-scroll at that moment.
let _tpMarqueeGen = 0;

function _tpSetMarqueeName(nameEl, text) {
    // Skip restarting an already-running cycle for unchanged text - renderTabBar()
    // re-connects the tooltip to a freshly rebuilt chip strip on every rename/pin/
    // activate/reorder while the same tab stays hovered (see keepTooltipOpen), and
    // snapping a mid-scroll marquee back to start on each of those would be a
    // needless flicker for text that hasn't actually changed.
    if (nameEl.dataset.tpName === text) return;
    nameEl.dataset.tpName = text;

    let span = nameEl.querySelector(".marquee-text");
    if (!span) {
        nameEl.textContent = "";
        span = document.createElement("span");
        span.className = "marquee-text";
        nameEl.appendChild(span);
    }
    span.textContent = text;

    const myGen = ++_tpMarqueeGen;
    span.style.transition = "none";
    span.style.transform  = "translateX(0)";
    span.style.opacity    = "1";

    requestAnimationFrame(() => {
        if (myGen !== _tpMarqueeGen) return;
        const overflow = span.offsetWidth - nameEl.clientWidth;
        if (overflow <= 2) return;

        const scrollDuration = Math.max(1200, (overflow / 45) * 1000);

        async function runCycle() {
            if (myGen !== _tpMarqueeGen) return;

            if (document.hidden) {
                await _sleep(1000);
                runCycle();
                return;
            }

            span.style.transition = "none";
            span.style.transform  = "translateX(0)";
            span.style.opacity    = "1";

            await _sleep(800);
            if (myGen !== _tpMarqueeGen) return;

            span.style.transition = `transform ${scrollDuration}ms linear`;
            span.style.transform  = `translateX(-${overflow}px)`;
            await _sleep(scrollDuration);
            if (myGen !== _tpMarqueeGen) return;

            await _sleep(700);
            if (myGen !== _tpMarqueeGen) return;

            span.style.transition = "opacity 0.35s ease";
            span.style.opacity    = "0";
            await _sleep(400);
            if (myGen !== _tpMarqueeGen) return;

            span.style.transition = "none";
            span.style.transform  = "translateX(0)";
            await new Promise(resolve =>
                requestAnimationFrame(() => requestAnimationFrame(resolve))
            );
            if (myGen !== _tpMarqueeGen) return;

            span.style.transition = "opacity 0.35s ease";
            span.style.opacity    = "1";

            await _sleep(1500);
            runCycle();
        }

        runCycle();
    });
}

// Used on chip mouseleave instead of hiding instantly - the small gap between
// adjacent chips would otherwise register as a leave, hiding the tooltip only
// to reopen it (after the hover delay) a moment later on the next chip.
function _tpScheduleHide() {
    clearTimeout(_tpHideTimer);
    _tpHideTimer = setTimeout(_tpHide, TAB_PREVIEW_HIDE_GRACE);
}

function _tpScheduleShow(tab, cx, cy) {
    if (_tabBarAnim) return; // bar is mid-scroll - stay hidden until it settles
    clearTimeout(_tpHoverTimer);
    // Tooltip already up for this same tab with no leave in progress: this is a
    // re-fired mouseenter from renderTabBar() replacing the chip DOM under a
    // stationary cursor (the removed chip never fires mouseleave, the new one
    // fires mouseenter). Patch in place instead of scheduling the cold-path
    // rebuild below - that rebuild reseeds the <img> with the factory static
    // image, and for a just-activated tab nothing corrects it afterward because
    // build-preview.js is still mid-generation, so the tooltip visibly reverted
    // to the bare factory gun until the next real re-hover.
    if (!_tpHideTimer && _tpActiveTabId === tab.id && _tpTooltipEl?.classList.contains("visible")) {
        _tpShow(tab, cx, cy, true);
        return;
    }
    if (_tpHideTimer) {
        // Tooltip is still up from the chip we just left - swap straight to
        // the new one instead of hiding and re-running the hover delay.
        clearTimeout(_tpHideTimer);
        _tpHideTimer = null;
        _tpShow(tab, cx, cy, true);
        return;
    }
    // Use the cursor's live position when the timer actually fires, not the
    // one captured at mouseenter - 150ms is enough for the mouse to have kept
    // moving, and showing up at the stale spot made the tooltip visibly jump
    // to the cursor on the next mousemove instead of appearing under it.
    _tpHoverTimer = setTimeout(() => _tpShow(tab, _tpLastX, _tpLastY, false), TAB_PREVIEW_HOVER_DELAY);
}

function _tpStatBarRow(key, labelKey, fillClass, target, valueText) {
    return `
      <div class="stat-bar-row" data-stat="${key}">
        <div class="stat-bar-label">${t(labelKey)}</div>
        <div class="stat-bar-track">
          <div class="stat-bar-fill ${fillClass}" style="width:0%"${target !== null ? ` data-target="${target}"` : ""}></div>
          <div class="stat-bar-value">${valueText}</div>
        </div>
      </div>`;
}

function _tpStatsSkeletonHtml() {
    return _tpStatBarRow("ergo", "stats.ergo", "ergo-bar", null, "-")
         + _tpStatBarRow("verRecoil", "stats.verRecoil", "recoil-bar", null, "-")
         + _tpStatBarRow("horRecoil", "stats.horRecoil", "recoil-bar", null, "-")
         + _tpStatBarRow("accuracy", "stats.accuracy", "accuracy-bar", null, "-");
}

// Shared number-crunching for the minified bars/rows below, used both to
// render fresh markup and to patch an already-visible tooltip in place.
function _tpComputeStatValues(data) {
    const totalErgo   = parseFloat(data.total_ergo ?? 0);
    const totalWeight = parseFloat(data.total_weight ?? 0);
    const eed         = parseFloat(data.evo_ergo_delta ?? 0);
    const armStamina  = parseFloat(data.arm_stamina ?? 0);

    const accuracyMoa    = data.accuracy_moa ?? null;
    const sightingRange  = data.sighting_range ?? null;
    const muzzleVelocity = data.muzzle_velocity ?? null;

    return {
        bars: {
            ergo: {
                target: Math.max(0, Math.min(totalErgo, 100)),
                text: Math.abs(totalErgo - Math.round(totalErgo)) < 0.001 ? Math.round(totalErgo) : totalErgo.toFixed(1),
            },
            verRecoil: {
                target: data.recoil_vertical !== null && data.recoil_vertical !== undefined ? Math.min(Math.round(data.recoil_vertical), 500) / 5 : 0,
                text: data.recoil_vertical !== null && data.recoil_vertical !== undefined ? Math.round(data.recoil_vertical) : "-",
            },
            horRecoil: {
                target: data.recoil_horizontal !== null && data.recoil_horizontal !== undefined ? Math.min(Math.round(data.recoil_horizontal), 500) / 5 : 0,
                text: data.recoil_horizontal !== null && data.recoil_horizontal !== undefined ? Math.round(data.recoil_horizontal) : "-",
            },
            accuracy: {
                target: accuracyMoa !== null ? Math.min(accuracyMoa / 10, 1) * 100 : 0,
                text: accuracyMoa !== null ? accuracyMoa.toFixed(2) + " MOA" : "-",
            },
        },
        weightText:      totalWeight.toFixed(3) + " kg",
        eedText:         (eed > 0 ? "+" : "") + eed.toFixed(1),
        overswingText:   data.overswing ? t("stats.yes") : t("stats.no"),
        armStaminaText:  armStamina.toFixed(1) + "s",
        sightingRange,
        muzzleText:      muzzleVelocity !== null ? muzzleVelocity + " m/s" : t("stats.noAmmo"),
    };
}

// Minified version of updateStatsPanel()'s content.innerHTML (stats-panel.js) -
// same bars/rows, minus the title, the advanced-stats button, the EED/arm-stamina
// config ("i") buttons and their popups, and the "Only Applicable in Arena" note.
function _tpStatsHtml(data) {
    const v = _tpComputeStatValues(data);

    const bars =
        _tpStatBarRow("ergo", "stats.ergo", "ergo-bar", v.bars.ergo.target, v.bars.ergo.text) +
        _tpStatBarRow("verRecoil", "stats.verRecoil", "recoil-bar", v.bars.verRecoil.target, v.bars.verRecoil.text) +
        _tpStatBarRow("horRecoil", "stats.horRecoil", "recoil-bar", v.bars.horRecoil.target, v.bars.horRecoil.text) +
        _tpStatBarRow("accuracy", "stats.accuracy", "accuracy-bar", v.bars.accuracy.target, v.bars.accuracy.text);

    return `
      ${bars}
      <div class="stats-divider"></div>
      <div class="stat-subsection">
      <div class="stat-subsection-cols">
      <div class="stat-col">
        <div class="stat-row stat-row-weight"><span class="stat-label">${t("stats.weight")}</span><span>${v.weightText}</span></div>
        <div class="stat-row stat-row-eed"><span class="stat-label">${t("stats.eedLabelShort")}</span><span>${v.eedText}</span></div>
        <div class="stat-row stat-row-overswing"><span class="stat-label">${t("stats.overswing")}</span><span>${v.overswingText}</span></div>
      </div>
      <div class="stat-col">
        <div class="stat-row stat-row-arm-stamina"><span class="stat-label">${t("stats.armStamina")}</span><span>${v.armStaminaText}</span></div>
        <div class="stat-row stat-row-sighting"${v.sightingRange === null ? ` style="display:none"` : ""}><span class="stat-label">${t("stats.sightingRange")}</span><span>${v.sightingRange !== null ? v.sightingRange + " m" : ""}</span></div>
        <div class="stat-row stat-row-muzzle"><span class="stat-label">${t("stats.muzzleVelocity")}</span><span>${v.muzzleText}</span></div>
      </div>
      </div>
      </div>`;
}

function _tpAnimateBars(statsEl, gen) {
    requestAnimationFrame(() => requestAnimationFrame(() => {
        if (_tpGen !== gen) return;
        statsEl.querySelectorAll(".stat-bar-fill[data-target]").forEach(fillEl => {
            fillEl.style.width = fillEl.dataset.target + "%";
        });
    }));
}

// Used when swapping directly from one still-visible tab preview to another
// (see _tpShow's `connected` param) - patches values/bar widths on the
// existing DOM instead of tearing it down, so bars transition from their
// current width (CSS already animates width changes) instead of restarting
// from 0%, and nothing flashes.
function _tpUpdateStatsInPlace(statsEl, data) {
    const v = _tpComputeStatValues(data);

    for (const key of ["ergo", "verRecoil", "horRecoil", "accuracy"]) {
        const row = statsEl.querySelector(`.stat-bar-row[data-stat="${key}"]`);
        if (!row) continue;
        const fillEl  = row.querySelector(".stat-bar-fill");
        const valueEl = row.querySelector(".stat-bar-value");
        if (fillEl)  fillEl.style.width = v.bars[key].target + "%";
        if (valueEl) valueEl.textContent = v.bars[key].text;
    }

    const weightVal = statsEl.querySelector(".stat-row-weight span:last-child");
    if (weightVal) weightVal.textContent = v.weightText;

    const eedVal = statsEl.querySelector(".stat-row-eed span:last-child");
    if (eedVal) eedVal.textContent = v.eedText;

    const overswingVal = statsEl.querySelector(".stat-row-overswing span:last-child");
    if (overswingVal) overswingVal.textContent = v.overswingText;

    const armStaminaVal = statsEl.querySelector(".stat-row-arm-stamina span:last-child");
    if (armStaminaVal) armStaminaVal.textContent = v.armStaminaText;

    const sightingRow = statsEl.querySelector(".stat-row-sighting");
    if (sightingRow) {
        sightingRow.style.display = v.sightingRange === null ? "none" : "";
        const sightingVal = sightingRow.querySelector("span:last-child");
        if (sightingVal) sightingVal.textContent = v.sightingRange !== null ? v.sightingRange + " m" : "";
    }

    const muzzleVal = statsEl.querySelector(".stat-row-muzzle span:last-child");
    if (muzzleVal) muzzleVal.textContent = v.muzzleText;
}

function _tpSetQueued(wrap, isQueued) {
    let ov = wrap.querySelector(".bp-queue-overlay");
    if (isQueued && !ov) {
        ov = document.createElement("img");
        ov.className = "bp-queue-overlay";
        ov.src = "./assets/images/queue.png";
        ov.alt = "";
        wrap.appendChild(ov);
    } else if (!isQueued && ov) {
        ov.remove();
    }
}

// Swap an already-visible tooltip <img> to a new URL without letting the old
// pixels sit there looking "correct" while the new image is still loading -
// dims immediately and only clears once the new image (this exact URL, not a
// later one that raced past it) has actually finished loading. Matters most
// when hovering several tab chips in a row on a slow connection: without this,
// the previous tab's gun image stays crisp on screen until the new one decodes,
// which reads as "the tooltip is showing the wrong gun."
function _tpSetImg(imgEl, url) {
    if (!imgEl || !url) return;
    imgEl.dataset.tpPendingSrc = url;
    imgEl.style.opacity = "0.35";
    imgEl.style.filter  = "brightness(0.85)";
    const onDone = () => {
        if (imgEl.dataset.tpPendingSrc === url) {
            imgEl.style.opacity = "";
            imgEl.style.filter  = "";
        }
    };
    imgEl.addEventListener("load", onDone, { once: true });
    imgEl.addEventListener("error", onDone, { once: true });
    imgEl.src = url;
}

// Resolve (and, for background tabs, lazily generate) the preview image for a
// tab's chip tooltip. Mirrors build-preview.js's _bpGenerate state machine
// (dimming + queue overlay) but scoped to the tooltip's own <img>, and never
// touches the shared _bp* state that drives the main gun image elsewhere.
async function _tpLoadImage(tab, gun, imgWrap, imgEl, gen) {
    if (!window._bpIsEnabled?.()) return; // static asset already showing

    // Community build with a pre-rendered card image (hosted on Gitee) - use it directly
    // rather than paying for a fresh generation of an image that already exists. tab.communityBuild
    // is kept in sync with tab.pairs by syncActiveTab/loadBuildFromPayload (cleared the moment the
    // build diverges from the loaded community build), so this is safe to trust as-is.
    if (tab.communityBuild?.cardImageUrl) {
        imgEl.referrerPolicy = "no-referrer"; // Gitee-hosted - needs no-referrer or the load can fail
        _tpSetImg(imgEl, tab.communityBuild.cardImageUrl);
        return;
    }

    const key = _pairsKey(tab.pairs || []);

    if (tab.id === EFTForge.state.activeTabId) {
        // Active tab's image is already being managed by build-preview.js - just mirror it.
        // selectGun() always renders the gun's factory tree first and reapplies the tab's
        // real pairs a moment later, so build-preview.js's own generation pipeline briefly
        // settles on the factory image mid-switch before catching up to the real one - only
        // trust its cached URL when it's actually for this tab's current build, not that
        // transient intermediate state (which would otherwise flash the tooltip back to the
        // factory gun right after activating a tab with real attachments).
        if (window._bpGetLastKey?.() === key) {
            const liveUrl = window._bpGetLastImageUrl?.();
            if (liveUrl) _tpSetImg(imgEl, liveUrl);
        }
        if (window._bpIsInflight?.()) {
            imgEl.style.opacity = "0.35";
            imgEl.style.filter  = "brightness(0.85)";
        }
        if (window._bpIsQueued?.()) _tpSetQueued(imgWrap, true);
        return;
    }

    const cacheKey = tab.id + ":" + key;
    const cachedUrl = _tpImageCache.get(cacheKey);
    if (cachedUrl) { _tpSetImg(imgEl, cachedUrl); return; }

    if (key === "") {
        _tpSetImg(imgEl, gun.bare_image_512_link || gun.image_512_link || gun.icon_link || "");
        return;
    }

    const initData = await _ensureGunInitCached(gun);
    if (_tpGen !== gen) return;

    const factoryKey = initData?.factory_tree
        ? _pairsKey(collectSlotPairs({ children: initData.factory_tree }))
        : null;
    if (key === factoryKey) {
        _tpSetImg(imgEl, gun.image_512_link || gun.icon_link || "");
        return;
    }

    // Warm slotCache for any pairs items the gun's own factory data didn't cover.
    const uncachedItemIds = [...new Set(
        (tab.pairs || []).map(([, iid]) => iid).filter(iid => !EFTForge.state.slotCache[iid])
    )];
    if (uncachedItemIds.length) {
        try {
            const batch = await fetchItemSlotsBatch(uncachedItemIds);
            for (const [iid, slots] of Object.entries(batch)) cacheSet(EFTForge.state.slotCache, iid, slots);
        } catch (_) { /* image gen below will just skip unresolved slots */ }
    }
    if (_tpGen !== gen) return;

    const sptData = _bpBuildSptItemsForPairs(gun, tab.pairs || []);
    if (!sptData) return;

    const abort = new AbortController();
    _tpImgAbort = abort;

    // Invalidate any earlier _tpSetImg() call's pending "load" listener (e.g. from
    // the static fallback image swapped in at the top of _tpShow) so it can't fire
    // mid-generation and clear this dim early, briefly revealing the stale image.
    delete imgEl.dataset.tpPendingSrc;
    imgEl.style.opacity = "0.35";
    imgEl.style.filter  = "brightness(0.85)";

    try {
        try {
            const busyResp = await fetch(`${EFTForge.config.API_BASE}/build-image/busy`, { signal: abort.signal });
            if (busyResp.ok) {
                const busyData = await busyResp.json();
                if (_tpGen === gen && busyData.busy) _tpSetQueued(imgWrap, true);
            }
        } catch (_) { /* best-effort queue indicator only */ }

        if (_tpGen !== gen) return;

        const resp = await fetch(`${EFTForge.config.API_BASE}/build-image`, {
            method:  "POST",
            headers: { "Content-Type": "application/json" },
            body:    JSON.stringify(sptData),
            signal:  abort.signal,
        });
        if (resp.ok) {
            const data = await resp.json();
            if (data.image_url) {
                _tpImageCache.set(cacheKey, data.image_url);
                if (_tpGen === gen) imgEl.src = data.image_url;
            }
        }
    } catch (_) {
        // Aborted (hovered away) or network failure - leave the static fallback showing.
    } finally {
        if (_tpGen === gen) {
            imgEl.style.opacity = "";
            imgEl.style.filter  = "";
            _tpSetQueued(imgWrap, false);
        }
        if (_tpImgAbort === abort) _tpImgAbort = null;
    }
}

async function _tpShow(tab, cx, cy, connected = false) {
    const gun = EFTForge.state.allGuns.find(g => g.id === tab.gunId);
    if (!gun) return;

    const gen = ++_tpGen;
    const isSameTab = tab.id === _tpActiveTabId;
    _tpActiveTabId = tab.id;

    const el = _tpEnsureTooltipEl();
    const staticImg = gun.image_512_link || gun.icon_link || "";

    // "Connected" = swapping straight from another chip's still-visible
    // preview (see _tpScheduleShow). Patch the existing DOM instead of
    // rebuilding it so nothing flashes; a plain reveal from hidden still
    // gets the normal skeleton + bars-grow-from-0 treatment.
    const canUpdateInPlace = connected && el.classList.contains("visible") && el.querySelector(".tab-preview-stats");

    if (canUpdateInPlace) {
        const imgEl  = el.querySelector(".tab-preview-img");
        const nameEl = el.querySelector(".tab-preview-gunname");
        // Only reset to the plain factory image when actually swapping to a
        // different tab - the gun/build hasn't changed here (e.g. renderTabBar()
        // re-connecting the tooltip after a click activated this same tab), so
        // the composite image already showing is still correct. Resetting it
        // anyway just replaces it with the factory image and, if the just-
        // activated tab's live build-preview image isn't ready yet (a moment
        // after activation - see _tpLoadImage's active-tab branch below),
        // nothing corrects it back until the next real hover.
        if (imgEl && !isSameTab) _tpSetImg(imgEl, staticImg);
        if (nameEl) _tpSetMarqueeName(nameEl, tab.buildName || gun.name);
    } else {
        el.innerHTML = `
            <div class="tab-preview-img-wrap"><img class="tab-preview-img" src="${escapeHtml(staticImg)}" alt="" /></div>
            <div class="tab-preview-gunname"></div>
            <div class="tab-preview-stats">${_tpStatsSkeletonHtml()}</div>
        `;
        _tpSetMarqueeName(el.querySelector(".tab-preview-gunname"), tab.buildName || gun.name);
    }
    el.classList.add("visible");
    _tpPosition(cx, cy);

    const isActive = tab.id === EFTForge.state.activeTabId;
    let data = null;
    if (isActive) {
        data = {
            total_ergo:        EFTForge.state.lastTotalErgo,
            total_weight:      EFTForge.state.lastTotalWeight,
            recoil_vertical:   EFTForge.state.lastRecoilV,
            recoil_horizontal: EFTForge.state.lastRecoilH,
            accuracy_moa:      EFTForge.state.lastAccuracyMoa,
            sighting_range:    EFTForge.state.lastSightingRange,
            muzzle_velocity:   EFTForge.state.lastMuzzleVelocity,
            evo_ergo_delta:    EFTForge.state.lastEED,
            overswing:         EFTForge.state.lastOverswing,
            arm_stamina:       EFTForge.state.lastArmStamina,
        };
    } else {
        try {
            data = await calculateBuild({
                base_item_id:          tab.gunId,
                attachment_ids:        (tab.pairs || []).map(p => p[1]),
                assume_full_mag:       EFTForge.state.assumeFullMag ?? true,
                selected_ammo_id:      tab.ammoId,
                selected_ubgl_ammo_id: tab.ubglAmmoId,
                strength_level:        EFTForge.state.currentStrengthLevel,
                equip_ergo_modifier:   EFTForge.state.currentEquipErgoModifier,
            });
        } catch (_) {
            data = null;
        }
    }

    if (_tpGen !== gen) return; // hovered away while calculating

    const statsEl = el.querySelector(".tab-preview-stats");
    if (statsEl && data) {
        if (canUpdateInPlace) {
            _tpUpdateStatsInPlace(statsEl, data);
        } else {
            statsEl.innerHTML = _tpStatsHtml(data);
            _tpAnimateBars(statsEl, gen);
        }
    }
    _tpPosition(cx, cy);

    const imgWrap = el.querySelector(".tab-preview-img-wrap");
    const imgEl   = el.querySelector(".tab-preview-img");
    if (imgWrap && imgEl) await _tpLoadImage(tab, gun, imgWrap, imgEl, gen);
}

/* ===========================
   RENDER
=========================== */

let _dragTabId = null;

function _syncTabBarSpacer() {
    const spacer = document.querySelector(".header-spacer");
    if (spacer) spacer.classList.toggle("with-tab-bar", EFTForge.state.tabs.length > 0);
}

// Fade opacity ramps smoothly over this many px of scroll near each edge,
// instead of snapping straight to fully visible.
const TAB_BAR_FADE_DISTANCE = 40;

function _updateTabBarFades() {
    const scroll = document.getElementById("tab-bar-scroll");
    const fadeLeft = document.querySelector(".tab-bar-fade-left");
    const fadeRight = document.querySelector(".tab-bar-fade-right");
    if (!scroll || !fadeLeft || !fadeRight) return;

    const maxScroll = scroll.scrollWidth - scroll.clientWidth;
    if (maxScroll <= 1) {
        fadeLeft.style.opacity = 0;
        fadeRight.style.opacity = 0;
        return;
    }

    const left = scroll.scrollLeft;
    const right = maxScroll - scroll.scrollLeft;
    fadeLeft.style.opacity = Math.max(0, Math.min(1, left / TAB_BAR_FADE_DISTANCE));
    fadeRight.style.opacity = Math.max(0, Math.min(1, right / TAB_BAR_FADE_DISTANCE));
}

function renderTabBar() {
    if (!_isDesktopTabs()) return;
    const bar = document.getElementById("tab-bar");
    const scroll = document.getElementById("tab-bar-scroll");
    if (!bar || !scroll) return;

    bar.classList.toggle("has-tabs", EFTForge.state.tabs.length > 0);
    _syncTabBarSpacer();
    _clearMarqueeTimers();

    // Chips get torn down and rebuilt below (innerHTML reset), which would
    // otherwise force the tooltip closed even when the hovered tab isn't going
    // anywhere - clicking a chip re-renders the whole strip to flip its
    // "active" class, and that alone shouldn't hide the tooltip the user is
    // still sitting on top of, only to have a stray mousemove reopen it a
    // moment later. Only actually hide it when the hovered tab won't exist
    // after this render (e.g. it was just closed).
    const hoveredTabId = _tpActiveTabId;
    const keepTooltipOpen = hoveredTabId && EFTForge.state.tabs.some(t => t.id === hoveredTabId);
    if (!keepTooltipOpen) _tpHide();
    scroll.innerHTML = "";

    EFTForge.state.tabs.forEach(tab => {
        const gun = EFTForge.state.allGuns.find(g => g.id === tab.gunId);
        const shortName = gun ? gun.short_name : "?";
        const label = tab.buildName ? `${shortName} - ${tab.buildName}` : shortName;

        const chip = document.createElement("div");
        chip.className = "tab-chip"
            + (tab.id === EFTForge.state.activeTabId ? " active" : "")
            + (tab.pinned ? " pinned" : "");
        chip.draggable = true;
        chip.dataset.tabId = tab.id;
        chip.innerHTML = `
            ${tab.pinned ? `<img class="tab-chip-pin-icon" src="./assets/images/pin.png" alt="" />` : ""}
            <span class="tab-chip-label"><span class="marquee-text">${escapeHtml(label)}</span></span>
            ${tab.pinned ? "" : `<button class="tab-chip-close" type="button" aria-label="${escapeHtml(t("tab.close"))}">&times;</button>`}
        `;

        chip.addEventListener("click", (e) => {
            if (e.target.closest(".tab-chip-close")) return;
            switchToTab(tab.id);
        });
        chip.addEventListener("mousedown", (e) => {
            // Middle-click's native pan/autoscroll gesture arms on mousedown, before
            // auxclick ever fires (that only fires after mouseup) - preventing default
            // there is too late, the browser has already entered autoscroll mode.
            if (e.button === 1) e.preventDefault();
        });
        chip.addEventListener("auxclick", (e) => {
            if (e.button === 1) { e.preventDefault(); closeTab(tab.id); }
        });
        chip.addEventListener("contextmenu", (e) => {
            e.preventDefault();
            _showTabContextMenu(e, tab);
        });
        chip.querySelector(".tab-chip-close")?.addEventListener("click", (e) => {
            e.stopPropagation();
            closeTab(tab.id);
        });

        chip.addEventListener("mouseenter", (e) => {
            _tpLastX = e.clientX; _tpLastY = e.clientY;
            _tpScheduleShow(tab, e.clientX, e.clientY);
        });
        chip.addEventListener("mousemove", (e) => {
            _tpLastX = e.clientX; _tpLastY = e.clientY;
            if (_tpActiveTabId === tab.id) _tpPosition(e.clientX, e.clientY);
        });
        chip.addEventListener("mouseleave", _tpScheduleHide);

        chip.addEventListener("dragstart", () => {
            _tpHide();
            _dragTabId = tab.id;
            requestAnimationFrame(() => chip.classList.add("dragging"));
        });
        chip.addEventListener("dragover", (e) => {
            if (!_dragTabId || _dragTabId === tab.id) return;
            const dragged = EFTForge.state.tabs.find(t => t.id === _dragTabId);
            if (!dragged || dragged.pinned !== tab.pinned) return;
            e.preventDefault();
            const rect = chip.getBoundingClientRect();
            const before = (e.clientX - rect.left) < rect.width / 2;
            chip.classList.toggle("drag-over-before", before);
            chip.classList.toggle("drag-over-after", !before);
        });
        chip.addEventListener("dragleave", () => {
            chip.classList.remove("drag-over-before", "drag-over-after");
        });
        chip.addEventListener("drop", (e) => {
            e.preventDefault();
            chip.classList.remove("drag-over-before", "drag-over-after");
            if (!_dragTabId || _dragTabId === tab.id) return;
            const fromIdx = EFTForge.state.tabs.findIndex(t => t.id === _dragTabId);
            if (fromIdx === -1) return;
            const dragged = EFTForge.state.tabs[fromIdx];
            if (dragged.pinned !== tab.pinned) return;
            const rect = chip.getBoundingClientRect();
            const before = (e.clientX - rect.left) < rect.width / 2;
            EFTForge.state.tabs.splice(fromIdx, 1);
            let toIdx = EFTForge.state.tabs.findIndex(t => t.id === tab.id);
            if (!before) toIdx += 1;
            EFTForge.state.tabs.splice(toIdx, 0, dragged);
            _persistTabs();
            renderTabBar();
        });
        chip.addEventListener("dragend", () => {
            _dragTabId = null;
            document.querySelectorAll(".tab-chip.dragging, .tab-chip.drag-over-before, .tab-chip.drag-over-after")
                .forEach(c => c.classList.remove("dragging", "drag-over-before", "drag-over-after"));
        });

        scroll.appendChild(chip);
    });

    _initMarqueeText(scroll, { hoverOnly: true, hoverTarget: ".tab-chip" });
    _updateTabBarFades();

    // Chips were just rebuilt from scratch, so the old element the tooltip's
    // hover listeners were attached to is gone - patch it onto the new one in
    // place (same "connected" path used when swapping between adjacent chips)
    // instead of waiting for the next stray mousemove to re-open it from cold.
    if (keepTooltipOpen) {
        const tab = EFTForge.state.tabs.find(t => t.id === hoveredTabId);
        if (tab) _tpShow(tab, _tpLastX, _tpLastY, true);
    }
}

// Manual rAF-eased smooth scroll for the wheel handler below - CSS
// scroll-behavior:smooth is at the mercy of the user's OS/browser smooth-
// scrolling setting (can be force-disabled), so we animate scrollLeft
// ourselves to get consistent behavior everywhere.
//
// Fixed-duration ease-out (not an asymptotic per-frame chase): a chase that
// closes a fraction of the remaining distance every frame slows into
// sub-pixel steps that get rounded away by the renderer, so the bar looked
// visually "stuck" for a stretch before finally snapping to place. Animating
// over a fixed duration guarantees it actually finishes on schedule.
let _tabBarAnim = null; // { fromX, toX, startTs, duration }
let _tabBarScrollRAF = null;

const TAB_BAR_SCROLL_DURATION = 260; // ms

function _easeOutCubic(p) {
    const inv = 1 - p;
    return 1 - inv * inv * inv;
}

function _stepTabBarScroll(scroll, ts) {
    if (!_tabBarAnim) { _tabBarScrollRAF = null; return; }
    const { fromX, toX, startTs, duration, resumeHover } = _tabBarAnim;
    const p = Math.min(1, (ts - startTs) / duration);
    scroll.scrollLeft = Math.round(fromX + (toX - fromX) * _easeOutCubic(p));

    if (p >= 1) {
        _tabBarAnim = null;
        _tabBarScrollRAF = null;
        if (resumeHover) _tpResumeAfterScroll();
        return;
    }
    _tabBarScrollRAF = requestAnimationFrame((t) => _stepTabBarScroll(scroll, t));
}

// Chips slide under a stationary cursor during the scroll animation, so the
// hover preview would otherwise point at a chip that's no longer underneath
// it. Hide it for the duration and re-evaluate what's under the cursor once
// the bar settles. Only meaningful for scrolls the mouse is actually driving
// (wheel) - _tpLastX/_tpLastY are last-known-good coordinates from a real
// hover and go stale the moment the mouse leaves the bar, so a resume here
// after a programmatic scroll (e.g. auto-scrolling a new tab into view from
// a gunSelect click elsewhere on the page) would reopen the tooltip at that
// stale point even though the cursor isn't anywhere near the bar.
function _tpResumeAfterScroll() {
    const chip = document.elementFromPoint(_tpLastX, _tpLastY)?.closest(".tab-chip");
    const tab = chip && EFTForge.state.tabs.find(t => t.id === chip.dataset.tabId);
    if (tab) _tpScheduleShow(tab, _tpLastX, _tpLastY);
}

function _animateTabBarScrollTo(scroll, targetX, { resumeHover = false } = {}) {
    _tpHide();
    const max = scroll.scrollWidth - scroll.clientWidth;
    _tabBarAnim = {
        fromX: scroll.scrollLeft,
        toX: Math.max(0, Math.min(max, targetX)),
        startTs: performance.now(),
        duration: TAB_BAR_SCROLL_DURATION,
        resumeHover,
    };
    if (!_tabBarScrollRAF) _tabBarScrollRAF = requestAnimationFrame((t) => _stepTabBarScroll(scroll, t));
}

function _queueTabBarScroll(scroll, deltaY) {
    const currentTarget = _tabBarAnim ? _tabBarAnim.toX : scroll.scrollLeft;
    _animateTabBarScrollTo(scroll, currentTarget + deltaY, { resumeHover: true });
}

// Bring a tab's chip fully into view when it isn't already - used when a new
// tab is created past the visible edge of an overflowing bar, and when
// clicking a gunSelect grid gun re-activates a tab that's scrolled out of
// view. No-ops if the chip is already fully visible.
function _scrollTabIntoView(tabId) {
    const scroll = document.getElementById("tab-bar-scroll");
    if (!scroll) return;
    const chip = scroll.querySelector(`.tab-chip[data-tab-id="${tabId}"]`);
    if (!chip) return;
    if (scroll.scrollWidth <= scroll.clientWidth) return;

    const chipLeft = chip.offsetLeft;
    const chipRight = chipLeft + chip.offsetWidth;
    const viewLeft = scroll.scrollLeft;
    const viewRight = viewLeft + scroll.clientWidth;
    if (chipLeft >= viewLeft && chipRight <= viewRight) return;

    const targetX = chipRight > viewRight ? chipRight - scroll.clientWidth : chipLeft;
    _animateTabBarScrollTo(scroll, targetX);
}

(function _initTabBarScrollUX() {
    const scroll = document.getElementById("tab-bar-scroll");
    if (!scroll) return;

    scroll.addEventListener("scroll", _updateTabBarFades, { passive: true });
    window.addEventListener("resize", _updateTabBarFades);

    scroll.addEventListener("wheel", (e) => {
        if (scroll.scrollWidth <= scroll.clientWidth) return;
        if (e.deltaY === 0) return;
        e.preventDefault();
        _queueTabBarScroll(scroll, e.deltaY);
    }, { passive: false });
})();

// Failsafe against a stuck-open tooltip. The chip-level mouseenter/mouseleave
// pair (and renderTabBar()'s "keep it open across a re-render" reconnect) covers
// the normal cases, but any path that swaps/removes the hovered chip's DOM
// without a real mouse movement over it first (a re-render landing mid-grace-
// period, a synthetic mouseenter firing for the wrong element, the cursor
// leaving the viewport/window entirely without a trailing mouseleave) can
// leave _tpActiveTabId pointing at a tab the cursor isn't actually over
// anymore, with nothing left to correct it. A document-wide mousemove check
// self-heals on the very next real pointer movement anywhere on the page;
// document mouseleave/blur cover the cursor or focus leaving the window.
document.addEventListener("mousemove", (e) => {
    if (!_tpActiveTabId) return;
    // #tab-bar-scroll itself (not just .tab-chip) is exempt too - small gaps between
    // adjacent chips transiently target the scroll container, not a chip, and forcing
    // a hide there would break the connected-swap bridging (_tpScheduleShow) that
    // avoids a full tooltip redraw when moving directly between two chips.
    if (e.target.closest(".tab-chip, #tab-preview-tooltip, #tab-bar-scroll")) return;
    _tpHide();
}, { passive: true });
document.addEventListener("mouseleave", () => { if (_tpActiveTabId) _tpHide(); });
window.addEventListener("blur", () => { if (_tpActiveTabId) _tpHide(); });

window.EFTForge.tabs = {
    createTabForGun,
    createTabFromPayload,
    switchToTab,
    closeTab,
    duplicateTab,
    togglePin,
    deactivateActiveTab,
    renderTabBar,
    syncActiveTab,
    restoreTabsFromStorage,
};
