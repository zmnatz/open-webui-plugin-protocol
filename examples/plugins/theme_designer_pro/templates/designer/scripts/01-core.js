    const STORAGE_KEY = 'owui_dev_theme_v1';
    const steps = [50, 100, 200, 300, 400, 500, 600, 700, 800, 850, 900, 950];
    const MODES = ['dark', 'light', 'oled', 'her'];
    // This tab, on every save, so the server's broadcast of it reaches every
    // other open designer but doesn't make this one reload.
    const TAB_ORIGIN = Math.random().toString(36).slice(2, 10) + Date.now().toString(36);
    // The saved theme and library this page holds, by tag: from the server at
    // load, then from every update it hears of and every answer to its own
    // saves. A resync, sent when the server's Redis link comes back, names
    // what is saved now: a difference is a save this page missed.
    const _held = window.__THEME_PRO_HELD__ || {};
    function eventData(e) {
        try { return JSON.parse(e.data || '{}') || {}; } catch (x) { return {}; }
    }
    function missedSave(kind, d) {
        if (kind === 'library' ? !('tag' in d) : (kind === 'personal' && !('cssTag' in d))) return false;
        const tags = kind === 'library' ? [d.tag || null, null] : [d.cssTag || null, d.stateTag || null];
        if (!d.resync) { _held[kind] = tags; return false; }
        return !!_held[kind] && (_held[kind][0] !== tags[0] || _held[kind][1] !== tags[1]);
    }

    // Each part's 'Only on Auth Pages' flag, beside its 'Show on Auth Pages'
    // one: [flag, its show flag, its enabled flag, switch id]
    const AUTH_ONLY = [
        ['themeAuthOnly', 'themeShowAuth', 'paletteEnabled', 'toggle-theme-authonly'],
        ['customCssAuthOnly', 'customCssShowAuth', 'customCssEnabled', 'toggle-custom-authonly'],
        ['canvasAuthOnly', 'canvasShowAuth', 'canvasEnabled', 'toggle-canvas-authonly'],
        ['gradientAuthOnly', 'gradientShowAuth', 'gradientEnabled', 'toggle-gradient-authonly']
    ];
    const AUTH_ONLY_KEYS = AUTH_ONLY.map(a => a[0]);
    let _lastLocalSave = 0;
    // Saves this page makes on its own as it opens, before anyone touches it,
    // only settle what it loaded; other designers ignore them (settle: true).
    let _userActed = false;
    ['pointerdown', 'keydown', 'drop', 'paste'].forEach(t => document.addEventListener(t, () => { _userActed = true; }, { capture: true, once: true }));
    const $ = (id) => document.getElementById(id);

    // --- Icons ---
    const ICONS = {
        chevron: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="6 9 12 15 18 9"></polyline></svg>',
        search: '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="8"></circle><line x1="21" y1="21" x2="16.65" y2="16.65"></line></svg>',
        searchLg: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="8"></circle><line x1="21" y1="21" x2="16.65" y2="16.65"></line></svg>',
        sortDefault: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M7 15l5 5 5-5"/><path d="M7 9l5-5 5 5"/></svg>',
        sortAsc: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M18 15l-6-6-6 6"/></svg>',
        sortDesc: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M6 9l6 6 6-6"/></svg>',
        upload: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M17 8l-5-5-5 5M12 3v12"/></svg>',
        download: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M7 10l5 5 5-5M12 15V3"/></svg>',
        trash: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 6 5 6 21 6"></polyline><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path></svg>',
        filter: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="22 3 2 3 10 12.46 10 19 14 21 14 12.46 22 3"></polygon></svg>',
        plusAccent: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="var(--accent)" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><line x1="12" y1="5" x2="12" y2="19"></line><line x1="5" y1="12" x2="19" y2="12"></line></svg>',
        plus: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><line x1="12" y1="5" x2="12" y2="19"></line><line x1="5" y1="12" x2="19" y2="12"></line></svg>',
        file: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>',
        dragHandle: '<svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><circle cx="9" cy="6" r="1.5"/><circle cx="15" cy="6" r="1.5"/><circle cx="9" cy="12" r="1.5"/><circle cx="15" cy="12" r="1.5"/><circle cx="9" cy="18" r="1.5"/><circle cx="15" cy="18" r="1.5"/></svg>',
        lockClosed: '<svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor" stroke="none" style="vertical-align:-2px"><rect x="3" y="11" width="18" height="11" rx="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4" fill="none" stroke="currentColor" stroke-width="2.5"/></svg>',
        lockOpen: '<svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor" stroke="none" style="opacity:0.5; vertical-align:-2px"><rect x="3" y="11" width="18" height="11" rx="2"/><path d="M7 11V7a5 5 0 0 1 10 0" fill="none" stroke="currentColor" stroke-width="2.5"/></svg>',
    };
    function hydrateIcons() { document.querySelectorAll('[data-icon]').forEach(el => { const k = el.dataset.icon; if (ICONS[k]) el.innerHTML = ICONS[k]; }); }

    // --- Gallery toolbars ---
    const GALLERY_TOOLBARS = [
        {
            mountId: 'gallery-toolbar-theme', title: 'Theme Gallery',
            countId: 'library-count', countWrapId: 'library-count-wrap',
            searchId: 'theme-search-input', searchToggleId: 'theme-search-toggle-btn', searchPlaceholder: 'Search themes...', searchTooltip: 'Search Themes',
            sortId: 'theme-sort-btn',
            filter: { btnId: 'tag-filter-toggle-btn', dropdownId: 'tag-filter-dropdown', tooltip: 'Filter by Tag', options: [
                { value: 'all', label: 'All Themes' }, { value: 'css', label: 'Custom CSS' }, { value: 'canvas', label: 'Canvas FX' }, { value: 'gradient', label: 'Gradient' }, { value: 'overrides', label: 'Overrides' }, { value: 'linked', label: 'Linked' }
            ]},
            importId: 'import-json-btn', importTooltip: 'Import JSON',
            exportId: 'export-all-btn', exportTooltip: 'Export All (Backup)',
            save: { id: 'save-snapshot-btn', tooltip: 'Save as New Theme' },
            deleteId: 'delete-all-themes-btn', deleteTooltip: 'Delete All Themes',
            scrollId: 'snapshot-scroll', scrollStyle: 'max-height: 35vh; overflow-y: auto; overflow-x: hidden; padding: 12px 8px; margin: -12px -8px 12px -8px; width: calc(100% + 16px); display: none;',
            galleryId: 'snapshot-list', galleryClass: 'preset-grid',
        },
        {
            mountId: 'gallery-toolbar-css', title: 'Preset Gallery',
            countId: 'css-count', countWrapId: 'css-count-wrap',
            searchId: 'css-search-input', searchToggleId: 'css-search-toggle-btn', searchPlaceholder: 'Search snippets...', searchTooltip: 'Search Snippets',
            sortId: 'css-sort-btn',
            importId: 'import-css-btn', importTooltip: 'Import CSS or JSON',
            exportId: 'export-all-css-btn', exportTooltip: 'Export All (Backup)',
            deleteId: 'delete-all-css-btn', deleteTooltip: 'Delete All Snippets',
            scrollId: 'css-preset-scroll', scrollStyle: 'max-height: 600px; overflow-y: auto; overflow-x: hidden; padding: 12px 8px; margin: -12px -8px 16px -8px; width: calc(100% + 16px); display: none;',
            galleryId: 'css-preset-gallery', galleryClass: 'preset-grid',
        },
        {
            mountId: 'gallery-toolbar-canvas', title: 'Preset Gallery',
            countId: 'canvas-count', countWrapId: 'canvas-count-wrap',
            searchId: 'canvas-search-input', searchToggleId: 'canvas-search-toggle-btn', searchPlaceholder: 'Search scripts...', searchTooltip: 'Search Scripts',
            sortId: 'canvas-sort-btn',
            filter: { btnId: 'canvas-filter-toggle-btn', dropdownId: 'canvas-filter-dropdown', tooltip: 'Filter by Type', options: [
                { value: 'all', label: 'All Scripts' }, { value: 'webgl', label: 'WebGL' }, { value: 'context', label: 'Context' }, { value: 'theme', label: 'Follows Theme' }, { value: 'dom', label: 'DOM Access' }
            ]},
            importId: 'import-canvas-btn', importTooltip: 'Import JS or JSON',
            exportId: 'export-all-canvas-btn', exportTooltip: 'Export All (Backup)',
            deleteId: 'delete-all-canvas-btn', deleteTooltip: 'Delete All Presets',
            scrollId: 'canvas-preset-scroll', scrollStyle: 'max-height: 600px; overflow-y: auto; overflow-x: hidden; padding: 12px 8px; margin: -12px -8px 16px -8px; width: calc(100% + 16px); display: none;',
            galleryId: 'canvas-preset-gallery', galleryClass: 'preset-grid',
        },
        {
            mountId: 'gallery-toolbar-gradient', title: 'Preset Gallery',
            countId: 'gradient-quick-count', countWrapId: 'gradient-quick-count-wrap', countWrapStyle: 'opacity: 0.5;',
            searchId: 'gradient-search-input', searchToggleId: 'gradient-search-toggle-btn', searchPlaceholder: 'Search presets...', searchTooltip: 'Search Presets',
            sortId: 'gradient-sort-btn',
            filter: { btnId: 'gradient-filter-toggle-btn', dropdownId: 'gradient-filter-dropdown', tooltip: 'Filter by Type', options: [
                { value: 'all', label: 'All Types' }, { value: 'linear', label: 'Linear' }, { value: 'radial', label: 'Radial' }, { value: 'mesh', label: 'Mesh' }
            ]},
            importId: 'import-gradient-btn', importTooltip: 'Import JSON',
            exportId: 'export-all-gradient-btn', exportTooltip: 'Export All (Backup)',
            save: { id: 'save-gradient-preset-btn', tooltip: 'Save Current Gradient', onclick: 'window.saveGradientPreset()' },
            deleteId: 'delete-all-gradient-btn', deleteTooltip: 'Delete All Presets',
            scrollId: 'gradient-preset-scroll', scrollStyle: 'max-height: 210px; overflow-y: auto; overflow-x: hidden; padding: 12px 8px; margin: -12px -8px 0 -8px; width: calc(100% + 16px);',
            galleryId: 'gradient-preset-gallery', galleryClass: 'gradient-preset-grid',
        },
    ];

    function buildGalleryToolbar(cfg) {
        const countWrapStyle = cfg.countWrapStyle || 'display:none; opacity: 0.5;';
        let filterHtml = '';
        if (cfg.filter) {
            const opts = cfg.filter.options.map((o, i) =>
                `<button class="tag-filter-option${i === 0 ? ' active' : ''}" data-filter="${o.value}"><span class="tag-filter-dot tag-filter-dot-${o.value}"></span>${o.label}</button>`
            ).join('');
            filterHtml = `<div class="tag-filter-wrap"><button class="btn btn-icon tag-filter-btn" id="${cfg.filter.btnId}" data-tooltip="${cfg.filter.tooltip}" aria-label="${cfg.filter.tooltip}">${ICONS.filter}</button><div class="tag-filter-dropdown" id="${cfg.filter.dropdownId}">${opts}</div></div>`;
        }
        let saveHtml = '';
        if (cfg.save) {
            const oc = cfg.save.onclick ? ` onclick="${cfg.save.onclick}"` : '';
            saveHtml = `<button class="btn btn-icon" id="${cfg.save.id}"${oc} data-tooltip="${cfg.save.tooltip}" aria-label="${cfg.save.tooltip}">${ICONS.plusAccent}</button>`;
        }
        return `<div class="section-title" style="margin-top: 8px; display: flex; align-items: center; gap: 8px;">` +
            `<div style="flex:1;">${cfg.title} <span id="${cfg.countWrapId}" style="${countWrapStyle}">| <span id="${cfg.countId}">0</span></span></div>` +
            `<div class="flex-center-gap6">` +
                `<div class="search-wrap"><i class="search-icon-overlay">${ICONS.search}</i><input type="text" id="${cfg.searchId}" placeholder="${cfg.searchPlaceholder}" class="search-input-expand" tabindex="-1" /><button type="button" class="search-clear-btn" id="${cfg.searchId}-clear" aria-label="Clear search">&times;</button></div>` +
                `<button class="btn btn-icon" id="${cfg.searchToggleId}" data-tooltip="${cfg.searchTooltip}" aria-label="${cfg.searchTooltip}">${ICONS.searchLg}</button>` +
                `<button class="btn btn-icon sort-btn" id="${cfg.sortId}" data-sort="default" data-tooltip="Default Sort" aria-label="Default Sort">` +
                    `<i class="sort-icon sort-icon-default">${ICONS.sortDefault}</i>` +
                    `<i class="sort-icon sort-icon-asc">${ICONS.sortAsc}</i>` +
                    `<i class="sort-icon sort-icon-desc">${ICONS.sortDesc}</i></button>` +
                filterHtml +
                `<button class="btn btn-icon" id="${cfg.importId}" data-tooltip="${cfg.importTooltip}" aria-label="${cfg.importTooltip}">${ICONS.upload}</button>` +
                `<button class="btn btn-icon" id="${cfg.exportId}" data-tooltip="${cfg.exportTooltip}" aria-label="${cfg.exportTooltip}">${ICONS.download}</button>` +
                saveHtml +
                `<button class="btn btn-icon btn-danger" id="${cfg.deleteId}" data-tooltip="${cfg.deleteTooltip}" aria-label="${cfg.deleteTooltip}">${ICONS.trash}</button>` +
            `</div></div>` +
            `<div id="${cfg.scrollId}" style="${cfg.scrollStyle}"><div id="${cfg.galleryId}" class="${cfg.galleryClass}"></div></div>`;
    }

    function hydrateToolbars() {
        GALLERY_TOOLBARS.forEach(cfg => {
            const mount = document.getElementById(cfg.mountId);
            if (mount) mount.innerHTML = buildGalleryToolbar(cfg);
        });
    }

    // --- Event delegation ---
    const ACTION_MAP = {
        'reverse-gradient':      () => window.reverseGradientStops(),
        'distribute-gradient':   () => window.distributeGradientStops(),
        'reset-gradient':        () => window.resetGradient(),
        'random-gradient':       () => window.randomGradient(),
        'toggle-transfer':       () => window.toggleTransferPanel(),
        'execute-transfer':      () => window.executeTransferColors(),
        'add-mesh-stop':         () => window.addMeshStop(),
        'add-gradient-stop':     () => window.addGradientStop(),
        'save-css':              () => window.saveCssSnapshot(),
        'save-canvas':           () => window.saveCanvasSnapshot(),
        'apply-all-updates':     () => window.applyAllBatchUpdates(),
    };

    function setupDelegation() {
        const body = document.getElementById('tool-body');
        if (!body) return;

        body.addEventListener('click', (e) => {
            const actionEl = e.target.closest('[data-action]');
            if (actionEl) {
                const fn = ACTION_MAP[actionEl.dataset.action];
                if (fn) { fn(actionEl, e); return; }
            }

            const dismissEl = e.target.closest('[data-dismiss]');
            if (dismissEl) {
                hideModal(dismissEl.dataset.dismiss);
                if (dismissEl.dataset.dismiss === 'sync-modal') collapseAllSyncDiffs();
                return;
            }

            const syncOpt = e.target.closest('.sync-option');
            if (syncOpt && !e.target.closest('input') && !e.target.closest('.sync-diff-chevron')) {
                const cb = syncOpt.querySelector('input');
                if (cb) cb.click();
                return;
            }

            const chevron = e.target.closest('.sync-diff-chevron');
            if (chevron) {
                e.stopPropagation();
                const setting = chevron.dataset.setting;
                if (setting) toggleSyncDiff(setting);
            }
        });

        body.addEventListener('dblclick', (e) => {
            const resetEl = e.target.closest('[data-reset]');
            if (!resetEl) return;
            const field = resetEl.dataset.reset;
            if (field === 'h' || field === 'c' || field === 'l') resetSlider(field);
            else if (field === 'accents') resetAccents();
            else if (field === 'gradient-angle') resetGradientAngle();
            else if (field === 'gradient-intensity') resetGradientIntensity();
            else if (field === 'gradient-speed') resetGradientSpeed();
            else if (SURFACE_FIELDS.includes(field)) resetSurfaceSlider(field);
        });
    }

    // Escape for an HTML attribute value. _esc() goes through textContent, which
    // escapes &<> but NOT quotes, so it is safe for element content and unsafe
    // for attributes: a remote string containing a double quote closes the
    // attribute and everything after it is parsed as markup.
    function _escAttr(s) {
        return String(s == null ? '' : s)
            .replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/'/g, '&#39;')
            .replace(/</g, '&lt;').replace(/>/g, '&gt;');
    }

    // The objects in an array from theme data, for code that reads fields off
    // each one: a remote theme's [null, null] or a string threw in the diff
    function _objArr(a) {
        return Array.isArray(a) ? a.filter(x => x && typeof x === 'object') : [];
    }

    // --- CSS value sanitizers ---
    //
    // Theme data is not all admin-authored: community themes, "Install All"
    // and update checks fetch JSON from whatever updateUrl a theme names. The
    // preset repo's CI schema guards contributions to that repo, not those
    // URLs. The values reach CSS in style="" attributes of the designer's own
    // preview markup, and in the generated theme CSS, which is composed into
    // /static/custom.css for every user of the instance. There an override
    // value of `red } html { background: url(https://evil.tld/x) } .z {`
    // would escape its rule block and inject instance-wide CSS. Admins can
    // write arbitrary CSS in Style Overrides on purpose; a colour swatch
    // silently carrying CSS is a different thing, so colour fields are
    // sanitized.
    //
    // The charset excludes quotes, ; : {} <> \ @ * (rule-block breakout and
    // appended declarations) and passes every colour form, including
    // slash-alpha syntax like `rgb(0 0 0 / 50%)`. Allowing '/' for that
    // re-opens url(https://…) exfiltration, because a custom property accepts
    // almost any token sequence, so url( and image-set( are rejected outright.

    // An unbalanced '(' is the one way a value inside the allowed charset can
    // still escape its declaration: per CSS syntax an open paren consumes
    // tokens until a matching ')' or EOF, swallowing the ';' and the '}' that
    // close the rule and everything after them. Measured: one override of
    // `rgb(` collapsed a three-rule stylesheet to a single parsed rule.
    function _parensBalanced(s) {
        let depth = 0;
        for (let i = 0; i < s.length; i++) {
            const ch = s[i];
            if (ch === '(') depth++;
            else if (ch === ')') { depth--; if (depth < 0) return false; }
        }
        return depth === 0;
    }

    function _cssTok(v, fallback) {
        // Only strings and finite numbers are colour-shaped: anything else
        // coerces to "false", "0" or "[object Object]", which pass the charset
        const t = typeof v;
        if (!(t === 'string' || (t === 'number' && isFinite(v)))) {
            return fallback === undefined ? 'transparent' : fallback;
        }
        const s = String(v);
        const ok = s.length <= 64
            // At least one non-whitespace char: a whitespace-only value is a
            // LEGAL empty custom-property value, which makes every
            // color: var(--x) that reads it resolve to unset and strips colour
            // from the UI for every user.
            && /\S/.test(s)
            && /^[\w#(),.%\s/-]+$/.test(s)
            && !/url\s*\(/i.test(s)
            && !/image-set\s*\(/i.test(s)
            && _parensBalanced(s);
        if (ok) return s;
        return fallback === undefined ? 'transparent' : fallback;
    }

    // Number(null) and Number('') are 0, which is finite, so a plain Number()
    // guard turns "unset" into zero: a 0deg gradient, or a 0 intensity that
    // flattens every stop to grey. Only real numbers and numeric strings count.
    function _toFiniteNumber(v) {
        if (typeof v === 'number') return isFinite(v) ? v : null;
        if (typeof v === 'string' && v.trim() !== '') {
            const n = Number(v);
            return isFinite(n) ? n : null;
        }
        return null;
    }

    function _cssNum(v, fallback) {
        const n = _toFiniteNumber(v);
        if (n !== null) return n;
        return fallback === undefined ? 0 : fallback;
    }

    // getAttribute returns null when the attribute is absent, and Number(null) is
    // 0 — a perfectly finite index that points at the FIRST theme in the library.
    // A missing attribute must read as "no index", never as index zero.
    function _attrIndex(el, name) {
        const raw = el && el.getAttribute(name);
        if (raw === null || raw === undefined || raw === '') return null;
        const n = Number(raw);
        return Number.isInteger(n) && n >= 0 ? n : null;
    }

