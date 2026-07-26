/* ============================================================
   DESKTOP APP SETTINGS
   Only active inside the packaged desktop app (the local backend
   injects window.__EFTFORGE_DESKTOP__ into index.html). Self-exits
   on the website and in normal local dev, like the devtool modules.

   Uses the site's own modal factory (_createModalOverlay), t() and
   modal-* classes. Provides:
     - header "Settings" nav button (cog icon)
     - settings modal: community mode / update source / item data sync
     - EFTForge.desktopSettings.goOnline() - used by the local-mode
       prompts in build-manager to switch to connected mode
     - local mode: hides the community-only header buttons
       (leaderboards, profile)
============================================================ */
(function () {
    if (!window.__EFTFORGE_DESKTOP__) return;

    window.EFTForge = window.EFTForge || {};

    const _base = () => (EFTForge.config ? EFTForge.config.API_BASE : "");
    let _syncPollTimer = null;

    async function _postSetting(patch) {
        const res = await fetch(`${_base()}/desktop/settings`, {
            method:  "POST",
            headers: { "Content-Type": "application/json" },
            body:    JSON.stringify(patch),
        });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return res.json();
    }

    /* Switch to connected mode and reload - the entry point from the
       "connect to EFTForge.com" prompts shown in local mode. */
    async function goOnline(btnEl) {
        if (btnEl) { btnEl.disabled = true; btnEl.textContent = "..."; }
        try {
            await _postSetting({ community_mode: "connected" });
            window.location.reload();
        } catch (e) {
            if (btnEl) { btnEl.disabled = false; btnEl.textContent = t("cb.goOnlineBtn"); }
            showToast(t("toast.connectionError"), String(e), 4000);
        }
    }

    function _fmtSyncTime(iso) {
        if (!iso) return t("dt.never");
        try {
            return new Date(iso).toLocaleString(EFTForge.state?.lang === "zh" ? "zh-CN" : "en-US");
        } catch { return iso; }
    }

    /* ---------------- modal ---------------- */

    async function showPanel() {
        const overlay = _createModalOverlay("desktop-settings-modal", t("dt.title"), { maxWidth: "500px" });
        if (!overlay) return;
        if (_syncPollTimer) { clearInterval(_syncPollTimer); _syncPollTimer = null; }

        const body = document.getElementById("desktop-settings-modal-body");
        body.innerHTML = `<div style="color:#555; font-size:13px; font-style:italic;">...</div>`;
        try {
            const [infoRes, syncRes] = await Promise.all([
                fetch(`${_base()}/desktop/settings`,    { cache: "no-store" }),
                fetch(`${_base()}/desktop/sync-status`, { cache: "no-store" }),
            ]);
            _renderBody(body, await infoRes.json(), await syncRes.json());
        } catch (e) {
            body.innerHTML = `<div style="color:#f44336; font-size:13px;">${escapeHtml(String(e))}</div>`;
        }
    }

    function _modeOptionHtml(value, current) {
        const name = value === "connected" ? t("dt.modeConnected") : t("dt.modeLocal");
        const desc = value === "connected" ? t("dt.modeConnectedDesc") : t("dt.modeLocalDesc");
        return `
            <label style="display:flex; gap:10px; align-items:flex-start; padding:6px 0; cursor:pointer;">
                <input type="radio" name="dt-mode" value="${value}" ${current === value ? "checked" : ""}
                       style="margin-top:3px; accent-color:#9a8866; cursor:pointer;" />
                <span style="min-width:0;">
                    <span style="display:block; font-size:13px; font-weight:700; color:#ddd;">${name}</span>
                    <span style="display:block; font-size:12px; color:#888; margin-top:2px; line-height:1.45;">${desc}</span>
                </span>
            </label>`;
    }

    function _renderBody(body, info, syncStatus) {
        const settings = info.settings || {};

        body.innerHTML = `
            <div class="modal-section" style="gap:2px;">
                <div class="modal-label">${t("dt.sectionCommunity")}</div>
                ${_modeOptionHtml("connected", settings.community_mode)}
                ${_modeOptionHtml("local",     settings.community_mode)}
                <div id="dt-mode-status" style="display:none; font-size:12px; color:#c9a53c; align-items:center; gap:8px; margin-top:4px;">
                    <span>${t("dt.modeChanged")}</span>
                    <button class="modal-btn primary" style="font-size:11px;" onclick="window.location.reload()">${t("dt.reloadNow")}</button>
                </div>
            </div>

            <hr class="modal-divider">

            <div class="modal-section" style="gap:6px;">
                <div class="modal-label">${t("dt.sectionUpdates")}</div>
                <select id="dt-src-select">
                    <option value="auto">${escapeHtml(t("dt.srcAuto"))}</option>
                    <option value="gitee">Gitee</option>
                    <option value="github">GitHub</option>
                </select>
                <div style="font-size:11px; color:#666;">${t("dt.updateSourceHint")} <span id="dt-src-status" style="color:#7ba05b;"></span></div>
            </div>

            <hr class="modal-divider">

            <div class="modal-section" style="gap:6px;">
                <div class="modal-label">${t("dt.sectionData")}</div>
                <div id="dt-sync-line" style="font-size:12px; color:#888;">${t("dt.lastSynced")}${escapeHtml(_fmtSyncTime(syncStatus && syncStatus.last_synced_at))}</div>
                <button id="dt-sync-btn" class="modal-btn full-width">${t("dt.syncNow")}</button>
                <div id="dt-sync-status" style="font-size:12px; display:none;"></div>
            </div>

            <hr class="modal-divider">

            <div style="font-size:11px; color:#555; line-height:1.7; word-break:break-all;">
                ${t("dt.appVersion")}${escapeHtml(EFTForge.config.APP_VERSION)}<br>
                ${t("dt.dataDir")}${escapeHtml(info.data_dir || "?")}
            </div>
        `;

        // --- community mode ---
        const modeStatus = body.querySelector("#dt-mode-status");
        body.querySelectorAll('input[name="dt-mode"]').forEach(input => {
            input.addEventListener("change", async () => {
                try {
                    await _postSetting({ community_mode: input.value });
                    modeStatus.style.display = "flex";
                } catch (e) {
                    modeStatus.style.display = "flex";
                    modeStatus.style.color = "#f44336";
                    modeStatus.textContent = String(e);
                }
            });
        });

        // --- update source ---
        const srcSelect = body.querySelector("#dt-src-select");
        const srcStatus = body.querySelector("#dt-src-status");
        srcSelect.value = settings.update_source || "auto";
        // Site-wide custom dropdown UI (app.js); hides the native select.
        if (typeof setupCustomSelect === "function") setupCustomSelect("dt-src-select");
        srcSelect.addEventListener("change", async () => {
            try {
                await _postSetting({ update_source: srcSelect.value });
                srcStatus.textContent = "✓";
                setTimeout(() => { srcStatus.textContent = ""; }, 1500);
            } catch (e) {
                srcStatus.style.color = "#f44336";
                srcStatus.textContent = String(e);
            }
        });

        // --- item data sync ---
        const syncLine   = body.querySelector("#dt-sync-line");
        const syncBtn    = body.querySelector("#dt-sync-btn");
        const syncStatEl = body.querySelector("#dt-sync-status");

        const _pollSync = () => {
            if (_syncPollTimer) clearInterval(_syncPollTimer);
            _syncPollTimer = setInterval(async () => {
                try {
                    const res = await fetch(`${_base()}/desktop/sync-status`, { cache: "no-store" });
                    const status = await res.json();
                    if (status.running) return;
                    clearInterval(_syncPollTimer);
                    _syncPollTimer = null;
                    syncBtn.disabled = false;
                    syncLine.textContent = t("dt.lastSynced") + _fmtSyncTime(status.last_synced_at);
                    syncStatEl.style.display = "";
                    if (status.error) {
                        syncStatEl.style.color = "#f44336";
                        syncStatEl.textContent = t("dt.syncError") + status.error;
                    } else if (status.changed) {
                        syncStatEl.style.color = "#c9a53c";
                        syncStatEl.innerHTML = `${t("dt.syncChanged")} <button class="modal-btn primary" style="font-size:11px;" onclick="window.location.reload()">${t("dt.reloadNow")}</button>`;
                    } else {
                        syncStatEl.style.color = "#7ba05b";
                        syncStatEl.textContent = t("dt.syncUnchanged");
                    }
                } catch { /* backend briefly busy - keep polling */ }
            }, 2000);
        };

        syncBtn.addEventListener("click", async () => {
            syncBtn.disabled = true;
            syncStatEl.style.display = "";
            syncStatEl.style.color = "#888";
            syncStatEl.textContent = t("dt.syncRunning");
            try {
                await fetch(`${_base()}/desktop/sync`, { method: "POST" });
                _pollSync();
            } catch (e) {
                syncBtn.disabled = false;
                syncStatEl.style.color = "#f44336";
                syncStatEl.textContent = t("dt.syncError") + String(e);
            }
        });

        if (syncStatus && syncStatus.running) {
            syncBtn.disabled = true;
            syncStatEl.style.display = "";
            syncStatEl.style.color = "#888";
            syncStatEl.textContent = t("dt.syncRunning");
            _pollSync();
        }
    }

    /* ---------------- bootstrap ---------------- */

    function _init() {
        // Local mode: leaderboards and the community profile are community
        // features - remove their header entry points entirely.
        if (EFTForge.config && EFTForge.config.COMMUNITY_DISABLED) {
            ["leaderboard-btn", "profile-nav-btn"].forEach(id => {
                const el = document.getElementById(id);
                if (el) el.style.display = "none";
            });
        }

        const nav = document.querySelector(".header-nav");
        if (!nav) return;
        const btn = document.createElement("button");
        btn.id = "desktop-settings-btn";
        btn.className = "header-nav-btn";
        btn.addEventListener("click", showPanel);
        btn.innerHTML =
            '<span class="header-nav-btn-icon"><svg width="18" height="18" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">' +
            '<circle cx="12" cy="12" r="3" stroke="currentColor" stroke-width="2"/>' +
            '<path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>' +
            '</svg></span>' +
            '<span class="header-nav-btn-label"></span>';
        btn.querySelector(".header-nav-btn-label").textContent = t("dt.navLabel");

        const profileBtn = document.getElementById("profile-nav-btn");
        if (profileBtn) nav.insertBefore(btn, profileBtn);
        else nav.appendChild(btn);
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", _init);
    } else {
        _init();
    }

    window.EFTForge.desktopSettings = { showPanel, goOnline };
})();
