window.EFTForge = window.EFTForge || {};

/* ============================================================
   WEAPON OPTIMIZER
   Optimize and Gunsmith tabs. Explore (Pareto curves) is a separate
   follow-up tab, added once its backend solver piece exists - see
   backend/optimizer/solver.py's module docstring.

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

    // Gunsmith tasks are being re-curated for the current wipe - the backend
    // (GET /build/gunsmith-tasks, POST /build/gunsmith-solve) and this tab's
    // UI are fully implemented and tested, just hidden from players until the
    // task data is ready. Flip this back to true to re-expose it.
    const GUNSMITH_ENABLED = false;

    let _activeTab = 'optimize';  // 'optimize' | 'gunsmith'
    let _result = null;   // last successful solve response, or null
    let _solving = false;
    let _error = null;

    let _gunsmithTasks = null;      // cached GET /build/gunsmith-tasks response
    let _gunsmithTasksPromise = null;

    // Lets the user bail out of a slow solve instead of being stuck staring
    // at "Solving...". This only abandons the fetch client-side - a solve
    // already running on the server keeps running (a synchronous HiGHS call
    // can't be interrupted mid-flight from outside), it just stops waiting
    // on it and frees the drawer back up.
    let _abortController = null;

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
        _render();
    }

    function hidePanel() {
        const overlay = document.getElementById('optimizer-overlay');
        const backdrop = document.getElementById('optimizer-backdrop');
        if (overlay) overlay.classList.remove('visible');
        if (backdrop) backdrop.classList.remove('visible');
        document.getElementById('main-container')?.removeAttribute('inert');
        // Otherwise a solve left running behind a closed drawer could still
        // resolve later and pop a stale result into a future, unrelated session.
        _abortController?.abort();
    }

    function onLangChange() {
        const label = document.getElementById('optimizer-edge-tab-label');
        if (label) label.textContent = _t('optimizer.title');

        const overlay = document.getElementById('optimizer-overlay');
        if (!overlay || !overlay.classList.contains('visible')) return;
        _render();
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
       SHARED HELPERS
    =========================== */

    function _creditHtml() {
        const link = `<a href="https://ahaimk01.github.io/tarkov-weapon-optimizer/" target="_blank" rel="noopener noreferrer">${_t('optimizer.creditLinkText')}</a>`;
        return window.tFmt ? window.tFmt('optimizer.creditText', { link }) : '';
    }

    function _escape(str) {
        const div = document.createElement('div');
        div.textContent = str == null ? '' : String(str);
        return div.innerHTML;
    }

    function _numOrNull(id) {
        const el = document.getElementById(id);
        if (!el || el.value === '') return null;
        const n = Number(el.value);
        return Number.isFinite(n) ? n : null;
    }

    function _switchTab(tab) {
        _activeTab = tab;
        _result = null;
        _error = null;
        _render();
    }

    /* ===========================
       ROOT RENDER (tab strip + active tab's form)
    =========================== */

    function _render() {
        const body = document.getElementById('optimizer-panel-body');
        if (!body) return;

        if (!GUNSMITH_ENABLED) _activeTab = 'optimize';

        const tabStripHtml = GUNSMITH_ENABLED ? `
            <div class="modal-row">
                <button class="toggle-btn ${_activeTab === 'optimize' ? 'active' : ''}" id="optimizer-tab-optimize">${_t('optimizer.tabOptimize')}</button>
                <button class="toggle-btn ${_activeTab === 'gunsmith' ? 'active' : ''}" id="optimizer-tab-gunsmith">${_t('optimizer.tabGunsmith')}</button>
            </div>
        ` : '';

        body.innerHTML = `
            ${tabStripHtml}
            <div id="optimizer-tab-content"></div>
            <div class="optimizer-credit">${_creditHtml()}</div>
        `;

        if (GUNSMITH_ENABLED) {
            document.getElementById('optimizer-tab-optimize').addEventListener('click', () => _switchTab('optimize'));
            document.getElementById('optimizer-tab-gunsmith').addEventListener('click', () => _switchTab('gunsmith'));
        }

        if (_activeTab === 'optimize') _renderOptimizeTab();
        else _renderGunsmithTab();
    }

    /* ===========================
       OPTIMIZE TAB
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

    function _renderOptimizeTab() {
        const content = document.getElementById('optimizer-tab-content');
        if (!content) return;

        content.innerHTML = `
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
        `;

        document.getElementById('optimizer-solve-btn').addEventListener('click', _solveOptimize);
        _renderResult();
    }

    async function _solveOptimize() {
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

        await _runSolve(`${EFTForge.config.API_BASE}/build/optimize`, body);
    }

    /* ===========================
       GUNSMITH TAB
    =========================== */

    function _fetchGunsmithTasks() {
        if (_gunsmithTasks) return Promise.resolve(_gunsmithTasks);
        if (_gunsmithTasksPromise) return _gunsmithTasksPromise;

        const lang = (window.EFTForge.state && window.EFTForge.state.lang) || 'en';
        _gunsmithTasksPromise = fetch(`${EFTForge.config.API_BASE}/build/gunsmith-tasks?lang=${lang}`)
            .then(res => { if (!res.ok) throw new Error(`HTTP ${res.status}`); return res.json(); })
            .then(data => { _gunsmithTasks = data.tasks; return _gunsmithTasks; })
            .finally(() => { _gunsmithTasksPromise = null; });
        return _gunsmithTasksPromise;
    }

    async function _renderGunsmithTab() {
        const content = document.getElementById('optimizer-tab-content');
        if (!content) return;

        content.innerHTML = `<div class="optimizer-result">${_t('optimizer.loadingTasks')}</div>`;

        let tasks;
        try {
            tasks = await _fetchGunsmithTasks();
        } catch {
            content.innerHTML = `<div class="optimizer-result"><div class="optimizer-error">${_t('optimizer.tasksLoadFailed')}</div></div>`;
            return;
        }
        if (_activeTab !== 'gunsmith') return; // user switched tabs while this was loading

        const options = tasks.map(t => `<option value="${_escape(t.task_name)}">${_escape(t.task_name)}</option>`).join('');

        content.innerHTML = `
            <div class="optimizer-field">
                <label class="modal-label">${_t('optimizer.task')}</label>
                <select id="optimizer-gunsmith-task" class="optimizer-input">${options}</select>
            </div>
            <div id="optimizer-gunsmith-info"></div>
            <label class="optimizer-checkbox-row">
                <input type="checkbox" id="optimizer-gunsmith-flea-available" checked>
                ${_t('optimizer.fleaAvailable')}
            </label>
            <button class="modal-btn primary full-width" id="optimizer-gunsmith-solve-btn">${_t('optimizer.solve')}</button>
            <div id="optimizer-result-container"></div>
        `;

        const select = document.getElementById('optimizer-gunsmith-task');
        select.addEventListener('change', () => _renderGunsmithTaskInfo(tasks));
        _renderGunsmithTaskInfo(tasks);

        document.getElementById('optimizer-gunsmith-solve-btn').addEventListener('click', _solveGunsmith);
        _renderResult();
    }

    function _renderGunsmithTaskInfo(tasks) {
        const select = document.getElementById('optimizer-gunsmith-task');
        const info = document.getElementById('optimizer-gunsmith-info');
        if (!select || !info) return;
        const task = tasks.find(t => t.task_name === select.value);
        if (!task) { info.innerHTML = ''; return; }

        const c = task.constraints || {};
        const constraintTags = Object.entries({
            [_t('optimizer.minErgo')]: c.min_ergonomics,
            [_t('optimizer.maxRecoilSum')]: c.max_recoil_sum,
            [_t('optimizer.minMagCapacity')]: c.min_mag_capacity,
            [_t('optimizer.minSightingRange')]: c.min_sighting_range,
            [_t('optimizer.maxWeight')]: c.max_weight,
        }).filter(([, v]) => v != null).map(([label, v]) => `<span class="stat-label">${label}: <span class="stat-value" style="display:inline;">${v}</span></span>`).join('');

        const requiredNames = task.required_item_names.length
            ? `<div class="stat-label">${_t('optimizer.requiredItems')}: ${task.required_item_names.map(_escape).join(', ')}</div>`
            : '';

        info.innerHTML = `
            <div class="optimizer-result">
                <div class="modal-label" style="margin:0;">${_escape(task.weapon_name)}</div>
                ${constraintTags}
                ${requiredNames}
            </div>
        `;
    }

    async function _solveGunsmith() {
        const select = document.getElementById('optimizer-gunsmith-task');
        const taskName = select?.value;
        if (!taskName) return;

        _solving = true;
        _error = null;
        _result = null;
        _renderResult();

        const state = window.EFTForge.state || {};
        const body = {
            task_name: taskName,
            flea_available: document.getElementById('optimizer-gunsmith-flea-available').checked,
            trader_levels: state.traderLevels || null,
            strength_level: state.currentStrengthLevel ?? 10,
            equip_ergo_modifier: state.currentEquipErgoModifier ?? 0,
        };

        await _runSolve(`${EFTForge.config.API_BASE}/build/gunsmith-solve`, body);
    }

    /* ===========================
       SOLVE (shared) + RESULT
    =========================== */

    async function _runSolve(url, body) {
        _abortController = new AbortController();
        try {
            const res = await fetch(url, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(body),
                signal: _abortController.signal,
            });
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            const data = await res.json();
            if (data.status === 'optimal') {
                _result = data;
            } else {
                _error = data.reason || _t('optimizer.infeasible');
            }
        } catch (err) {
            _error = err.name === 'AbortError' ? _t('optimizer.cancelled') : _t('optimizer.solveFailed');
        } finally {
            _solving = false;
            _abortController = null;
            _renderResult();
        }
    }

    function _cancelSolve() {
        _abortController?.abort();
    }

    function _renderResult() {
        const container = document.getElementById('optimizer-result-container');
        if (!container) return;

        if (_solving) {
            container.innerHTML = `
                <div class="optimizer-result">
                    <div>${_t('optimizer.solving')}</div>
                    <button class="modal-btn full-width" id="optimizer-cancel-btn">${_t('modal.cancel')}</button>
                </div>
            `;
            document.getElementById('optimizer-cancel-btn').addEventListener('click', _cancelSolve);
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
