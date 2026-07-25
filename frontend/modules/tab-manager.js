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

    const activeId = EFTForge.state.tabs.some(t => t.id === data.activeTabId)
        ? data.activeTabId
        : EFTForge.state.tabs[0].id;

    EFTForge.state.activeTabId = null;
    await switchToTab(activeId);
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

// A fresh gun pick from gunSelect - always opens a brand new tab with the
// gun's factory attachment set (selectGun applies it exactly as today).
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
        _persistTabs();
        renderTabBar();
    } finally {
        _tabSwitchInFlight = false;
    }
}

// A saved build / community build / shared-URL build - opens as a new tab
// carrying that build's name (and community attribution, if any).
async function createTabFromPayload(payload, buildName = null, communityBuild = null, silent = true) {
    if (_tabSwitchInFlight) return;
    const gun = EFTForge.state.allGuns.find(g => g.id === payload.g);
    if (!gun) {
        showToast(t("toast.loadFailed"), t("toast.unknownWeapon"), 3500);
        return;
    }
    _tabSwitchInFlight = true;
    try {
        _serializeActiveTab();

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
    } finally {
        _tabSwitchInFlight = false;
    }
}

async function switchToTab(tabId) {
    if (tabId === EFTForge.state.activeTabId) return;
    if (_tabSwitchInFlight) return; // ignore rapid re-clicks while a switch is already in progress
    const target = EFTForge.state.tabs.find(t => t.id === tabId);
    if (!target) return;

    const gun = EFTForge.state.allGuns.find(g => g.id === target.gunId);
    if (!gun) {
        showToast(t("toast.loadFailed"), t("toast.unknownWeapon"), 3500);
        return;
    }

    _tabSwitchInFlight = true;
    try {
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
    } finally {
        _tabSwitchInFlight = false;
    }
}

async function closeTab(tabId) {
    const idx = EFTForge.state.tabs.findIndex(t => t.id === tabId);
    if (idx === -1) return;
    const wasActive = EFTForge.state.activeTabId === tabId;

    EFTForge.state.tabs.splice(idx, 1);
    _tabHistory.delete(tabId);

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
        pairs: [...source.pairs],
        collapsedSlots: { ...source.collapsedSlots },
    };
    EFTForge.state.tabs.splice(idx + 1, 0, clone);
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
   RENDER
=========================== */

let _dragTabId = null;

function _syncTabBarSpacer() {
    const spacer = document.querySelector(".header-spacer");
    if (spacer) spacer.classList.toggle("with-tab-bar", EFTForge.state.tabs.length > 0);
}

function renderTabBar() {
    if (!_isDesktopTabs()) return;
    const bar = document.getElementById("tab-bar");
    if (!bar) return;

    bar.classList.toggle("has-tabs", EFTForge.state.tabs.length > 0);
    _syncTabBarSpacer();
    bar.innerHTML = "";

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
        chip.title = label;
        chip.innerHTML = `
            <span class="tab-chip-label">${escapeHtml(label)}</span>
            ${tab.pinned ? "" : `<button class="tab-chip-close" type="button" aria-label="${escapeHtml(t("tab.close"))}">&times;</button>`}
        `;

        chip.addEventListener("click", (e) => {
            if (e.target.closest(".tab-chip-close")) return;
            switchToTab(tab.id);
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

        chip.addEventListener("dragstart", () => {
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

        bar.appendChild(chip);
    });
}

window.EFTForge.tabs = {
    createTabForGun,
    createTabFromPayload,
    switchToTab,
    closeTab,
    duplicateTab,
    togglePin,
    renderTabBar,
    syncActiveTab,
    restoreTabsFromStorage,
};
