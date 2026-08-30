window.EFTForge = window.EFTForge || {};

/* ============================================================
   WEAPON OPTIMIZER
   MVP: single "Optimize" mode only (weighted ergo/recoil/price MILP
   solve). Explore (Pareto curves) and Gunsmith (task-specific builds)
   are separate follow-up tabs, added once their backend solver pieces
   exist - see backend/optimizer/solver.py's module docstring.

   Entry point is the gradient edge-tab on the attachment placeholder
   panel (see #optimizer-edge-tab in index.html), not a header nav
   button. Opens this drawer, same show/hide pattern as Ammo Ballistics
   and the Leaderboard (#optimizer-overlay / #optimizer-backdrop).

   "Use this build" applies the result to the CURRENT tab in place via
   loadBuildFromPayload() and closes the drawer - it does not open a
   new tab. That's a deliberate difference from the external ?build=
   URL import flow (importBuildFromCode -> createTabFromPayload), which
   is a separate, unrelated hand-off path.
============================================================ */

window.EFTForge.optimizer = (function () {

    let _result = null;   // last successful /build/optimize response, or null
    let _solving = false;
    let _error = null;

    function _t(key) { return window.t ? window.t(key) : key; }

    /* ===========================
       PUBLIC API
    =========================== */

    function showPanel() {
        const overlay = document.getElementById('optimizer-overlay');
        const backdrop = document.getElementById('optimizer-backdrop');
        if (!overlay) return;

        overlay.classList.add('visible');
        if (backdrop) backdrop.classList.add('visible');
        document.getElementById('main-container')?.setAttribute('inert', '');
        if (document.activeElement) document.activeElement.blur();

        _result = null;
        _error = null;
        _renderForm();
    }

    function hidePanel() {
        const overlay = document.getElementById('optimizer-overlay');
        const backdrop = document.getElementById('optimizer-backdrop');
        if (overlay) overlay.classList.remove('visible');
        if (backdrop) backdrop.classList.remove('visible');
        document.getElementById('main-container')?.removeAttribute('inert');
    }

    function onLangChange() {
        const label = document.getElementById('optimizer-edge-tab-label');
        if (label) label.textContent = _t('optimizer.title');

        const overlay = document.getElementById('optimizer-overlay');
        if (!overlay || !overlay.classList.contains('visible')) return;
        _renderForm();
    }

    function init() {
        const closeBtn = document.getElementById('optimizer-close-btn');
        if (closeBtn) closeBtn.addEventListener('click', hidePanel);
        const backdrop = document.getElementById('optimizer-backdrop');
        if (backdrop) backdrop.addEventListener('click', hidePanel);

        // A few flows (build-manager.js's publish-confirm screen and
        // _restoreNormalPlaceholder) rebuild #attachment-placeholder's
        // innerHTML wholesale and don't know about the edge-tab, so it would
        // otherwise get wiped out the first time either of those runs.
        // Watching and re-appending here keeps this self-contained instead of
        // patching every current (and future) place that rebuilds the panel.
        const placeholder = document.getElementById('attachment-placeholder');
        if (placeholder) {
            _ensureEdgeTab(placeholder);
            new MutationObserver(() => _ensureEdgeTab(placeholder)).observe(placeholder, { childList: true });
        }
        onLangChange(); // sync the edge-tab label with the saved language preference on first paint
    }

    function _ensureEdgeTab(placeholder) {
        if (document.getElementById('optimizer-edge-tab')) return;
        const tab = document.createElement('div');
        tab.id = 'optimizer-edge-tab';
        tab.className = 'optimizer-edge-tab';
        tab.addEventListener('click', showPanel);
        tab.innerHTML = `<span class="optimizer-edge-tab-label" id="optimizer-edge-tab-label">${_t('optimizer.title')}</span>`;
        placeholder.appendChild(tab);
    }

    /* ===========================
       FORM
    =========================== */

    function _weaponOptionsHtml() {
        const guns = (window.EFTForge.state && window.EFTForge.state.allGuns) || [];
        const currentId = window.EFTForge.state.currentGun ? window.EFTForge.state.currentGun.id : null;

        const byCategory = {};
        for (const gun of guns) {
            const cat = gun.weapon_category || 'Primary';
            (byCategory[cat] = byCategory[cat] || []).push(gun);
        }
        const order = (window.EFTForge.config && window.EFTForge.config.CLASS_ORDER) || Object.keys(byCategory);
        const categories = [...new Set([...order, ...Object.keys(byCategory)])].filter(c => byCategory[c]);

        return categories.map(cat => {
            const options = byCategory[cat]
                .slice()
                .sort((a, b) => a.name.localeCompare(b.name))
                .map(g => `<option value="${g.id}" ${g.id === currentId ? 'selected' : ''}>${_escape(g.name)}</option>`)
                .join('');
            const label = (window.EFTForge.config && window.EFTForge.config.CLASS_DISPLAY_NAMES[cat]) || cat;
            return `<optgroup label="${_escape(label)}">${options}</optgroup>`;
        }).join('');
    }

    function _creditHtml() {
        const link = `<a href="https://ahaimk01.github.io/tarkov-weapon-optimizer/" target="_blank" rel="noopener noreferrer">${_t('optimizer.creditLinkText')}</a>`;
        return window.tFmt ? window.tFmt('optimizer.creditText', { link }) : '';
    }

    function _escape(str) {
        const div = document.createElement('div');
        div.textContent = str == null ? '' : String(str);
        return div.innerHTML;
    }

    function _renderForm() {
        const body = document.getElementById('optimizer-panel-body');
        if (!body) return;

        body.innerHTML = `
            <div class="optimizer-field">
                <label class="modal-label">${_t('optimizer.weapon')}</label>
                <select id="optimizer-weapon" class="optimizer-input">${_weaponOptionsHtml()}</select>
            </div>

            <div class="optimizer-field">
                <label class="modal-label">${_t('optimizer.priorities')}</label>
                <label class="optimizer-checkbox-row">
                    <input type="checkbox" id="optimizer-use-evo-ergo">
                    ${_t('optimizer.useEvoErgo')}
                </label>
                ${_sliderRow('optimizer-ergo-weight', _t('optimizer.ergonomics'), 1)}
                ${_sliderRow('optimizer-recoil-weight', _t('optimizer.recoil'), 1)}
                ${_sliderRow('optimizer-price-weight', _t('optimizer.price'), 0.3)}
            </div>

            <div class="optimizer-field">
                <label class="modal-label">${_t('optimizer.constraints')}</label>
                <div class="optimizer-field-row">
                    <div class="optimizer-field">
                        <span class="stat-label">${_t('optimizer.budget')}</span>
                        <input id="optimizer-max-price" type="number" min="0" class="optimizer-input" placeholder="${_t('optimizer.noLimit')}">
                    </div>
                    <div class="optimizer-field">
                        <span class="stat-label">${_t('optimizer.minErgo')}</span>
                        <input id="optimizer-min-ergo" type="number" class="optimizer-input" placeholder="${_t('optimizer.noLimit')}">
                    </div>
                </div>
                <div class="optimizer-field-row">
                    <div class="optimizer-field">
                        <span class="stat-label">${_t('optimizer.maxRecoil')}</span>
                        <input id="optimizer-max-recoil" type="number" min="0" class="optimizer-input" placeholder="${_t('optimizer.noLimit')}">
                    </div>
                    <div class="optimizer-field">
                        <span class="stat-label">${_t('optimizer.maxWeight')}</span>
                        <input id="optimizer-max-weight" type="number" min="0" step="0.1" class="optimizer-input" placeholder="${_t('optimizer.noLimit')}">
                    </div>
                </div>
                <div class="optimizer-field-row">
                    <div class="optimizer-field">
                        <span class="stat-label">${_t('optimizer.minMagCapacity')}</span>
                        <input id="optimizer-min-mag" type="number" min="0" class="optimizer-input" placeholder="${_t('optimizer.noLimit')}">
                    </div>
                    <div class="optimizer-field">
                        <span class="stat-label">${_t('optimizer.minSightingRange')}</span>
                        <input id="optimizer-min-sight" type="number" min="0" class="optimizer-input" placeholder="${_t('optimizer.noLimit')}">
                    </div>
                </div>
                <label class="optimizer-checkbox-row">
                    <input type="checkbox" id="optimizer-flea-available" checked>
                    ${_t('optimizer.fleaAvailable')}
                </label>
            </div>

            <button class="modal-btn primary full-width" id="optimizer-solve-btn">${_t('optimizer.solve')}</button>

            <div id="optimizer-result-container"></div>

            <div class="optimizer-credit">${_creditHtml()}</div>
        `;

        document.getElementById('optimizer-solve-btn').addEventListener('click', _solve);
        _renderResult();
    }

    function _sliderRow(id, label, defaultValue) {
        return `
            <div class="optimizer-slider-row">
                <span class="stat-label" style="width:90px;">${label}</span>
                <input type="range" id="${id}" min="0" max="1" step="0.05" value="${defaultValue}"
                    oninput="document.getElementById('${id}-val').textContent = this.value">
                <span class="optimizer-slider-value" id="${id}-val">${defaultValue}</span>
            </div>
        `;
    }

    function _numOrNull(id) {
        const el = document.getElementById(id);
        if (!el || el.value === '') return null;
        const n = Number(el.value);
        return Number.isFinite(n) ? n : null;
    }

    /* ===========================
       SOLVE
    =========================== */

    async function _solve() {
        const weaponId = document.getElementById('optimizer-weapon').value;
        if (!weaponId) return;

        _solving = true;
        _error = null;
        _result = null;
        _renderResult();

        const state = window.EFTForge.state || {};
        const body = {
            weapon_id: weaponId,
            use_evo_ergo: document.getElementById('optimizer-use-evo-ergo').checked,
            ergo_weight: Number(document.getElementById('optimizer-ergo-weight').value),
            recoil_weight: Number(document.getElementById('optimizer-recoil-weight').value),
            price_weight: Number(document.getElementById('optimizer-price-weight').value),
            max_price: _numOrNull('optimizer-max-price'),
            min_ergonomics: _numOrNull('optimizer-min-ergo'),
            max_recoil_v: _numOrNull('optimizer-max-recoil'),
            max_weight: _numOrNull('optimizer-max-weight'),
            min_mag_capacity: _numOrNull('optimizer-min-mag'),
            min_sighting_range: _numOrNull('optimizer-min-sight'),
            flea_available: document.getElementById('optimizer-flea-available').checked,
            trader_levels: state.traderLevels || null,
            strength_level: state.currentStrengthLevel ?? 10,
            equip_ergo_modifier: state.currentEquipErgoModifier ?? 0,
        };

        try {
            const res = await fetch(`${EFTForge.config.API_BASE}/build/optimize`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(body),
            });
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            const data = await res.json();
            if (data.status === 'optimal') {
                _result = data;
            } else {
                _error = data.reason || _t('optimizer.infeasible');
            }
        } catch {
            _error = _t('optimizer.solveFailed');
        } finally {
            _solving = false;
            _renderResult();
        }
    }

    function _renderResult() {
        const container = document.getElementById('optimizer-result-container');
        if (!container) return;

        if (_solving) {
            container.innerHTML = `<div class="optimizer-result">${_t('optimizer.solving')}</div>`;
            return;
        }
        if (_error) {
            container.innerHTML = `<div class="optimizer-result"><div class="optimizer-error">${_escape(_error)}</div></div>`;
            return;
        }
        if (!_result) {
            container.innerHTML = '';
            return;
        }

        const s = _result.final_stats;
        container.innerHTML = `
            <div class="optimizer-result">
                <div class="optimizer-stat-grid">
                    <span class="stat-label">${_t('modal.ergo')}</span><span class="stat-value">${s.total_ergo}</span>
                    <span class="stat-label">${_t('modal.recoil')}</span><span class="stat-value">${s.recoil_vertical}</span>
                    <span class="stat-label">${_t('modal.weight')}</span><span class="stat-value">${s.total_weight.toFixed(2)}kg</span>
                    <span class="stat-label">${_t('modal.evoErgo')}</span><span class="stat-value">${s.evo_ergo_delta}</span>
                    <span class="stat-label">${_t('optimizer.itemCount')}</span><span class="stat-value">${_result.selected_items.length}</span>
                    <span class="stat-label">${_t('optimizer.totalCost')}</span><span class="stat-value">${_result.total_price_rub.toLocaleString()}₽</span>
                </div>
                <button class="modal-btn primary full-width" id="optimizer-use-build-btn">${_t('optimizer.useThisBuild')}</button>
            </div>
        `;
        document.getElementById('optimizer-use-build-btn').addEventListener('click', _useBuild);
    }

    async function _useBuild() {
        if (!_result) return;
        await loadBuildFromPayload({ v: 1, g: _result.gun_id, p: _result.slot_pairs });
        hidePanel();
    }

    // Scripts are loaded at the end of <body> so DOM is ready; init immediately.
    init();

    return { showPanel, hidePanel, onLangChange };

}());
