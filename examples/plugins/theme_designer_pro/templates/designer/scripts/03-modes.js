    // --- Mode data ---
    const DEFAULT_MODE_DATA = {
        h: 250, c: 0, l: 20, overrides: {}, locks: {},
        paletteEnabled: true, accent: "", accent2: "", accent3: "",
        customCSS: "", customCssEnabled: false,
        autoScope: true, canvasEnabled: false, canvasScript: "",
        manualOverrides: "", manualOverridesEnabled: false,
        gradientEnabled: false, gradientType: 'linear', gradientAngle: 135,
        gradientStops: [], gradientIntensity: 85, gradientAnimation: false,
        gradientRadialPosX: 50, gradientRadialPosY: 50, gradientRadialShape: 'ellipse', gradientRadialSize: 'farthest-corner',
        gradientMeshPoints: [], gradientMeshBgColor: '#0a0a12',
        gradientAnimationSpeed: 8, gradientShowAuth: true, themeShowAuth: true,
        customCssShowAuth: true, canvasShowAuth: true,
        themeAuthOnly: false, customCssAuthOnly: false, canvasAuthOnly: false, gradientAuthOnly: false,
        surfacesEnabled: false,
        surfaceSidebarOpacity: 100, surfaceSidebarBlur: 0,
        surfaceComposerOpacity: 5, surfaceComposerBlur: 8,
        surfacePanelOpacity: 100, surfacePanelBlur: 0,
        surfaceCardsOpacity: 100, surfaceCardsBlur: 0,
        surfaceButtonsOpacity: 100, surfaceButtonsBlur: 0,
        surfaceMenuOpacity: 100, surfaceMenuBlur: 0,
        surfaceDialogOpacity: 100, surfaceDialogBlur: 0,
        surfaceBackdropOpacity: 60, surfaceBackdropBlur: 0,
        surfaceFadeOpacity: 100
    };

    function createDefaultModeData(overrides = {}) {
        return { ...DEFAULT_MODE_DATA, overrides: {}, locks: {}, gradientStops: [], gradientMeshPoints: [], ...overrides };
    }

    // The Surfaces tab's layers. Each tints its surface with the color Open
    // WebUI paints it (dark modes first, light second) at the layer's opacity,
    // and blurs what shows through. The backdrop is the page behind an open
    // dialog, tinted black; the top fade has opacity only.
    const SURFACE_LAYERS = [
        { key: 'Sidebar', label: 'Sidebar', hint: 'The open sidebar. The collapsed rail stays clear.', color: ['var(--color-base-950)', 'var(--color-base-50)'] },
        { key: 'Composer', label: 'Message input', hint: 'The box you type in.', color: ['var(--color-base-850)', 'var(--color-base-0)'] },
        { key: 'Panel', label: 'Tabs drawer', hint: 'The drawer tabs open in on a narrow screen. On a wider one each tab looks like the page or chat it shows.', color: ['var(--color-base-900)', 'var(--color-base-0)'] },
        { key: 'Cards', label: 'Cards and panels', hint: 'The rounded panels on a page: note cards, the calendar, workspace and admin cards.', color: ['var(--color-base-900)', 'var(--color-base-0)'] },
        { key: 'Buttons', label: 'Buttons', hint: 'The grey buttons on a page, such as Create, single or split. Switches and the black and white action buttons keep their fill.', color: ['var(--color-base-850)', 'var(--color-base-50)'] },
        { key: 'Menu', label: 'Menus and tooltips', hint: 'Dropdowns, submenus, the model picker, Model controls, tooltips and toasts.', color: ['var(--color-base-850)', 'var(--color-base-0)'] },
        { key: 'Dialog', label: 'Dialogs', hint: 'Settings and the other windows that open over the page.', color: ['var(--color-base-900)', 'var(--color-base-0)'] },
        { key: 'Backdrop', label: 'Behind dialogs', hint: 'The page behind an open dialog: how much it darkens and blurs.', color: null },
        { key: 'Fade', label: 'Top fade', hint: 'The fade at the top of a chat, under the title bar.', color: null, noBlur: true }
    ];
    const SURFACE_FIELDS = ['surfacesEnabled'].concat(...SURFACE_LAYERS.map(l => l.noBlur ? [`surface${l.key}Opacity`] : [`surface${l.key}Opacity`, `surface${l.key}Blur`]));

    // The theme's three accents. A mode field set to '#rrggbb' sets one; ''
    // leaves it generated from the palette's hue, the same color the Canvas
    // FX payload gets (buildCanvasTheme in the bootloader). The theme CSS
    // carries each as its custom property, for theme CSS to use.
    const ACCENT_FIELDS = [
        { key: 'accent', cssVar: '--tdp-accent', shift: 0, label: 'Accent' },
        { key: 'accent2', cssVar: '--tdp-accent-2', shift: 40, label: 'Accent 2' },
        { key: 'accent3', cssVar: '--tdp-accent-3', shift: -40, label: 'Accent 3' }
    ];

    // A set accent, lowercase, or '' for anything that isn't '#' and six hex digits
    function _accentHex(v) {
        return typeof v === 'string' && /^#[0-9a-fA-F]{6}$/.test(v) ? v.toLowerCase() : '';
    }

    // Lighter on dark modes, deeper on light ones, as colorful as the
    // palette, and gray with the palette off
    function generatedAccent(config, mode, shift) {
        const dark = mode === 'dark' || mode === 'oled';
        const hue = _cssNum(config.h, 0);
        const chroma = config.paletteEnabled === false ? 0 : _cssNum(config.c, 0);
        const ac = chroma > 0 ? Math.min(0.18, Math.max(0.06, chroma / 250)) : 0;
        return `oklch(${dark ? 0.74 : 0.56} ${ac.toFixed(3)} ${((hue + shift + 360) % 360).toFixed(1)})`;
    }

    // { '--tdp-accent': color, ... } for a mode, set or generated
    function accentVars(config, mode) {
        const out = {};
        ACCENT_FIELDS.forEach(a => { out[a.cssVar] = _accentHex(config[a.key]) || generatedAccent(config, mode, a.shift); });
        return out;
    }

    // How much of each Open WebUI background shows, 0 to 100, for the ones
    // set below 100, and whether they sit behind the Canvas FX animation. Themes
    // saved before the sliders listed the hidden ones, which read as 0.
    function readHiddenBackgrounds(v) {
        const share = (n) => Math.max(0, Math.min(100, Math.round(Number(n))));
        const isShare = (n) => n !== null && n !== undefined && Number.isFinite(Number(n));
        const out = { models: {}, folders: {}, chat: 100, behind: true, dimming: 100, auth: null, pages: null };
        if (!v || typeof v !== 'object') return out;
        // The picture behind the pages without a chat: the viewer's own Chat
        // Background Image, or an uploaded or https:// one
        const pg = v.pages;
        if (pg && typeof pg === 'object') {
            const pgShare = isShare(pg.share) ? share(pg.share) : 100;
            if (pg.source === 'chat') out.pages = { source: 'chat', share: pgShare };
            else if (pg.source === 'url' && authUrlOk(pg.url)) out.pages = { source: 'url', url: rebaseUpload(pg.url), share: pgShare };
        }
        // The sign-in page's picture: nobody is signed in there, so only the
        // instance theme can show one
        const a = v.auth;
        if ((window.__THEME_PRO_CONFIG__ || {}).scope !== 'me' && a && typeof a === 'object' && authUrlOk(a.url)) {
            out.auth = { url: rebaseUpload(a.url), share: isShare(a.share) ? share(a.share) : 100 };
        }
        out.behind = v.behind !== false;
        if (isShare(v.dimming)) out.dimming = share(v.dimming);
        ['models', 'folders'].forEach(k => {
            const entries = Array.isArray(v[k]) ? v[k].map(id => [id, 0])
                : v[k] && typeof v[k] === 'object' ? Object.entries(v[k]) : [];
            entries.filter(([id, n]) => typeof id === 'string' && id && id.length <= 256 && Number.isFinite(Number(n)) && share(n) < 100)
                .slice(0, 500).forEach(([id, n]) => { out[k][id] = share(n); });
        });
        if (isShare(v.chat)) out.chat = share(v.chat);
        return out;
    }
    // An uploaded picture's address, or an https:// one
    function authUrlOk(u) {
        return typeof u === 'string' && /^(https:\/\/|\/)[^\s"'()\\<>]{1,2048}$/.test(u);
    }
    // An uploaded picture's address carries the Designer Url it was uploaded
    // under, and only the current one serves it. A personal theme's own picture
    // first, then the instance theme's it may have started from, as in
    // _rebase_uploads.
    function rebaseUpload(u) {
        const own = /^\/api\/v1\/[\w.\/-]*?(?=\/me\/page-background\?)/;
        const instance = /^\/api\/v1\/[\w.\/-]*?(?=\/(?:page|auth)-background\?)/;
        const base = (window.__THEME_PRO_CONFIG__ || {}).scope === 'me' && own.test(u) ? own : instance;
        return u.replace(base, '{ROUTE_BASE}');
    }
    function authToken() {
        return (localStorage.getItem('token') || '').replace(/^"|"$/g, '');
    }
    function deleteUpload(url) {
        const headers = {};
        if (authToken()) headers.Authorization = `Bearer ${authToken()}`;
        return fetch(url, { method: 'DELETE', headers }).catch(() => {});
    }
    function isAuthUpload(auth) {
        return (window.__THEME_PRO_CONFIG__ || {}).scope !== 'me' && !!auth && typeof auth.url === 'string' && auth.url.startsWith('{ROUTE_BASE}/auth-background');
    }
    function isPagesUpload(pages) {
        return !!pages && pages.source === 'url' && typeof pages.url === 'string' && pages.url.startsWith(pagesUploadUrl() + '?');
    }
    // Bumped by every choice of picture, so an upload still waiting in the
    // queue knows a later choice replaced it
    const _pictureChoice = { auth: 0, pages: 0 };
    // A reset or a new choice forgets the sign-in picture; an uploaded one
    // goes from the server too, and the result says so. Instance designer
    // only: a personal reset must not touch it. In Draft the published theme
    // still shows it, so Publish deletes it instead.
    function dropAuthUpload(auth) {
        _pictureChoice.auth++;
        if (!isAuthUpload(auth)) return false;
        if (!_draftMode) deleteUpload('{ROUTE_BASE}/auth-background');
        return true;
    }
    // The same for the page picture
    function dropPagesUpload(pages) {
        _pictureChoice.pages++;
        if (!isPagesUpload(pages)) return false;
        if (!_draftMode) deleteUpload(pagesUploadUrl());
        return true;
    }
    // Where this designer keeps its page picture: the instance theme's, or
    // the signed-in user's own for a personal theme
    function pagesUploadUrl() {
        return (window.__THEME_PRO_CONFIG__ || {}).scope === 'me' ? '{ROUTE_BASE}/me/page-background' : '{ROUTE_BASE}/page-background';
    }
    function hasHiddenBackgrounds(h) {
        return Object.keys(h.models).length > 0 || Object.keys(h.folders).length > 0 || h.chat < 100 || !h.behind || h.dimming < 100 || !!h.auth || !!h.pages;
    }
    // Each uploaded picture is one file that only the published theme points
    // at. Worked out from what was published, so a draft that dropped one
    // before a reload still deletes it.
    function deleteUnpublishedUploads(state) {
        let published;
        try { published = readHiddenBackgrounds(JSON.parse(state)._hiddenBackgrounds); } catch (e) { return; }
        if ((window.__THEME_PRO_CONFIG__ || {}).scope !== 'me' && !isAuthUpload(published.auth)) deleteUpload('{ROUTE_BASE}/auth-background');
        if (!isPagesUpload(published.pages)) deleteUpload(pagesUploadUrl());
    }

    // Gallery entries come from storage, the server, imports, community themes
    // and two raw JSON editors. A null entry, or a number where a name or
    // updateUrl belongs, threw in search, sort, export, the duplicate check
    // and Check for Updates. Repaired in place so every index still holds.
    const _THEME_META = ['name', 'description', 'author', 'version', 'targetVersion', 'repositoryUrl', 'updateUrl'];
    function _repairSnapshotEntry(s) {
        if (!s || typeof s !== 'object' || Array.isArray(s)) s = { name: 'Unreadable theme' };
        _THEME_META.forEach(k => {
            const v = s[k];
            if (v !== undefined && v !== null && typeof v !== 'string') s[k] = (typeof v === 'number' && isFinite(v)) ? String(v) : '';
        });
        return s;
    }
    // A mode that isn't an object is no mode
    const _isModeObject = m => !!m && typeof m === 'object';
    // The single-palette format from before modes (top-level h, c and l),
    // which migrateLegacyTheme turns into modes. Every reader asks this, so
    // a backup, a file, a paste and the gallery agree on what one is. One
    // with a mode isn't: migrating it would rebuild that mode from defaults.
    function _isLegacyTheme(t) {
        return !!t && typeof t === 'object' && !Array.isArray(t) &&
            !_isModeObject(t.dark) && !_isModeObject(t.light) && _toFiniteNumber(t.h) !== null;
    }
    // A theme entry the gallery can show: modes for dark and light, or the
    // legacy format
    function _isThemeEntry(t) {
        return !!t && typeof t === 'object' && !Array.isArray(t) &&
            ((_isModeObject(t.dark) && _isModeObject(t.light)) || _isLegacyTheme(t));
    }
    function getSnapshots() {
        const list = Storage.get('snapshots', []);
        return Array.isArray(list) ? list.map(_repairSnapshotEntry) : [];
    }

    // The modes' "applied from gallery theme N" refs are array positions, so
    // every insert or delete moves them, or they name a neighbouring theme
    // (highlighted, synced and updated as if it were the one in use). Undo
    // and redo entries carry their own copies, which move too, or an Undo
    // would restore a position that now names a different theme.
    function _remapSnapshotRefs(fn) {
        const apply = refs => {
            if (!refs) return;
            MODES.forEach(m => {
                if (refs[m] && refs[m].type === 'snapshot') {
                    const id = fn(refs[m].id);
                    if (id === null) refs[m] = null; else refs[m].id = id;
                }
            });
        };
        apply(activeThemeRef);
        historyStack.forEach(h => apply(h && h.activeThemeRef));
        _persistRefsSoon();
    }
    // The saved state carries the refs too, and callers move them without
    // committing, so without this a reload would restore positions that now
    // name a neighbour, and Update and Sync would act on the wrong theme.
    // Saved once, after the caller's own synchronous writes. Not while a
    // personal designer is still holding saves: a ref alone must not turn
    // the instance theme into the user's own.
    let _refsPersistQueued = false;
    function _persistRefsSoon() {
        if (_refsPersistQueued) return;
        _refsPersistQueued = true;
        queueMicrotask(() => {
            _refsPersistQueued = false;
            if (window.__TDP_HOLD_SAVES__ === true) return;
            commitChange({ clearRef: false, push: false });
        });
    }
    function shiftThemeRefs(by) {
        _remapSnapshotRefs(id => id + by);
    }
    function saveSnapshots(s) { Storage.set('snapshots', Array.isArray(s) ? s.map(_repairSnapshotEntry) : s); syncLibrary(); }

    function parseHex(hex) {
        const h = hex.startsWith('#') ? hex.slice(1) : hex;
        return [parseInt(h.slice(0, 2), 16), parseInt(h.slice(2, 4), 16), parseInt(h.slice(4, 6), 16)];
    }

    function getLuminance(hex) {
        const [r, g, b] = parseHex(hex);
        return (0.299 * r + 0.587 * g + 0.114 * b) / 255;
    }

    // WCAG 2.x contrast. getLuminance() above is the cheap Rec.601 perceptual
    // estimate used to pick a swatch's text colour; the AA/AAA thresholds are
    // defined against gamma-correct relative luminance, which is what these
    // compute. Kept separate on purpose — do not fold one into the other.
    function _srgbToLinear(c) {
        c = c / 255;
        return c <= 0.03928 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4);
    }
    function relativeLuminance(hex) {
        const [r, g, b] = parseHex(hex);
        return 0.2126 * _srgbToLinear(r) + 0.7152 * _srgbToLinear(g) + 0.0722 * _srgbToLinear(b);
    }
    function contrastRatio(hexA, hexB) {
        const la = relativeLuminance(hexA), lb = relativeLuminance(hexB);
        if (!isFinite(la) || !isFinite(lb)) return NaN;
        const hi = Math.max(la, lb), lo = Math.min(la, lb);
        return (hi + 0.05) / (lo + 0.05);
    }
    // WCAG 2.1: normal text needs 4.5 (AA) / 7 (AAA); large text (>=18pt, or
    // 14pt bold) needs only 3 (AA) / 4.5 (AAA). The designer's text-on-surface
    // pairs are body copy, so they are rated as normal text, with aaLarge kept
    // so a pair that clears only the large-text bar can say so instead of just
    // "Fail".
    function contrastVerdict(ratio) {
        return { ratio: ratio, aaa: ratio >= 7, aa: ratio >= 4.5, aaLarge: ratio >= 3 };
    }

    function showStatus(el, msg, type = 'error') {
        const colors = {
            error:   { bg: 'rgba(239, 68, 68, 0.1)', color: '#ef4444', border: '1px solid rgba(239, 68, 68, 0.3)' },
            loading: { bg: 'rgba(59, 130, 246, 0.1)', color: 'var(--accent)', border: '1px solid rgba(59, 130, 246, 0.3)' },
            success: { bg: 'rgba(34, 197, 94, 0.1)', color: '#22c55e', border: '1px solid rgba(34, 197, 94, 0.3)' }
        };
        const c = colors[type] || colors.error;
        el.style.display = 'block';
        el.style.background = c.bg;
        el.style.color = c.color;
        el.style.border = c.border;
        el.textContent = msg;
    }

    // Per-field validation on every import path, so a foreign theme cannot
    // carry a wrong type, or a string crafted to break out of the CSS rule it
    // is interpolated into, in any field. The CSS consumers sanitize too, but
    // this stops bad data at the door.
    //
    // customCSS, canvasScript and manualOverrides are only type-checked: they
    // are arbitrary CSS and JS by design, and Canvas FX carries its own
    // security warning.
    //
    // Numeric bounds match the designer's own sliders (h 0-360, c 0-150,
    // l/intensity/positions 0-100), which the 100-theme preset corpus fits
    // inside. Out-of-range or wrong-typed values fall back to the default
    // rather than being dropped, so a partially malformed theme still loads.
    const _MODE_ENUMS = {
        gradientType: ['linear', 'radial', 'conic', 'mesh'],
        gradientRadialShape: ['circle', 'ellipse'],
        gradientRadialSize: ['closest-side', 'closest-corner', 'farthest-side', 'farthest-corner']
    };
    const _MODE_NUM_BOUNDS = {
        h: [0, 360], c: [0, 150], l: [0, 100],
        gradientAngle: [0, 360], gradientIntensity: [0, 100],
        gradientRadialPosX: [0, 100], gradientRadialPosY: [0, 100],
        // Matches the sl-gradient-speed slider (min 2). Zero is not a
        // valid duration here: `animation: 0s` with background-size 300%
        // freezes a 3x-zoomed gradient instead of animating it.
        gradientAnimationSpeed: [2, 30],
        surfaceSidebarOpacity: [0, 100], surfaceSidebarBlur: [0, 40],
        surfaceComposerOpacity: [0, 100], surfaceComposerBlur: [0, 40],
        surfacePanelOpacity: [0, 100], surfacePanelBlur: [0, 40],
        surfaceCardsOpacity: [0, 100], surfaceCardsBlur: [0, 40],
        surfaceButtonsOpacity: [0, 100], surfaceButtonsBlur: [0, 40],
        surfaceMenuOpacity: [0, 100], surfaceMenuBlur: [0, 40],
        surfaceDialogOpacity: [0, 100], surfaceDialogBlur: [0, 40],
        surfaceBackdropOpacity: [0, 100], surfaceBackdropBlur: [0, 40],
        surfaceFadeOpacity: [0, 100]
    };

    // Through _toFiniteNumber, as _cssNum, so a field saved as null takes the
    // default, not 0
    function _num(v, lo, hi, dflt) {
        const n = _toFiniteNumber(v);
        if (n === null) return dflt;
        return Math.max(lo, Math.min(hi, n));
    }

    function validateModeData(d) {
        const def = DEFAULT_MODE_DATA;
        Object.keys(_MODE_NUM_BOUNDS).forEach(k => {
            if (d[k] === undefined) return;
            const [lo, hi] = _MODE_NUM_BOUNDS[k];
            d[k] = _num(d[k], lo, hi, def[k]);
        });
        Object.keys(_MODE_ENUMS).forEach(k => {
            if (d[k] === undefined) return;
            if (!_MODE_ENUMS[k].includes(d[k])) d[k] = def[k];
        });
        ['paletteEnabled', 'customCssEnabled', 'autoScope', 'canvasEnabled',
         'manualOverridesEnabled', 'gradientEnabled', 'gradientAnimation',
         'gradientShowAuth', 'themeShowAuth', 'customCssShowAuth', 'canvasShowAuth',
         'themeAuthOnly', 'customCssAuthOnly', 'canvasAuthOnly', 'gradientAuthOnly', 'surfacesEnabled'
        ].forEach(k => { if (d[k] !== undefined) d[k] = !!d[k]; });
        ['customCSS', 'canvasScript', 'manualOverrides'].forEach(k => {
            if (d[k] !== undefined && typeof d[k] !== 'string') d[k] = def[k];
        });
        // Colour-valued fields: constrained to the CSS colour grammar, unlike
        // the free-form CSS fields above. Accents are stricter still: they
        // also go to Canvas FX, so only '#rrggbb' counts.
        ACCENT_FIELDS.forEach(({ key }) => { if (d[key] !== undefined) d[key] = _accentHex(d[key]); });
        if (d.gradientMeshBgColor !== undefined) {
            d.gradientMeshBgColor = _cssTok(d.gradientMeshBgColor, def.gradientMeshBgColor);
        }
        // Every mode gets both maps, even one saved without them outside the
        // designer: the variable grid writes into them
        if (!d.overrides || typeof d.overrides !== 'object' || Array.isArray(d.overrides)) {
            d.overrides = {};
        } else {
            const clean = {};
            Object.keys(d.overrides).forEach(k => {
                // Only real custom-property names, only colour-shaped values.
                if (!/^--[\w-]{1,64}$/.test(k)) return;
                const v = _cssTok(d.overrides[k], null);
                if (v !== null) clean[k] = v;
            });
            d.overrides = clean;
        }
        if (d.locks === undefined) {
            // Saved before locks existed: its overrides were meant to stay
            // through the next slider move, as locked ones do
            d.locks = {};
            Object.keys(d.overrides).forEach(k => { d.locks[k] = true; });
        } else if (!d.locks || typeof d.locks !== 'object' || Array.isArray(d.locks)) d.locks = {};
        else Object.keys(d.locks).forEach(k => { d.locks[k] = !!d.locks[k]; });
        if (d.gradientStops !== undefined) {
            d.gradientStops = Array.isArray(d.gradientStops) ? d.gradientStops
                .filter(s => s && typeof s === 'object')
                .slice(0, 32)
                .map(s => ({ color: _cssTok(s.color, '#000000'), position: _num(s.position, 0, 100, 0) })) : [];
        }
        if (d.gradientMeshPoints !== undefined) {
            d.gradientMeshPoints = Array.isArray(d.gradientMeshPoints) ? d.gradientMeshPoints
                .filter(pt => pt && typeof pt === 'object')
                .slice(0, 32)
                .map(pt => ({
                    color: _cssTok(pt.color, '#000000'),
                    x: _num(pt.x, 0, 100, 50), y: _num(pt.y, 0, 100, 50),
                    spread: _num(pt.spread, 0, 100, 50)
                })) : [];
        }
        return d;
    }

    // Gradient presets are their own file format, with their own import
    // button and server-side collection, so validateModeData never sees them.
    // Validated here, where they come in, rather than at each render site.
    // i: its place in the file, which names one without a usable name
    function sanitizeGradientPreset(p, i) {
        if (!p || typeof p !== 'object') return null;
        const def = DEFAULT_MODE_DATA;
        const given = typeof p.name === 'string' && p.name.trim() ? p.name
            : p.name !== null && p.name !== undefined && typeof p.name !== 'object' ? String(p.name).trim() : '';
        const clean = {
            name: given ? given.slice(0, 120) : `Gradient ${i + 1}`,
            type: _MODE_ENUMS.gradientType.includes(p.type) ? p.type : def.gradientType,
            angle: _num(p.angle, 0, 360, def.gradientAngle),
            intensity: _num(p.intensity, 0, 100, def.gradientIntensity),
            animation: !!p.animation,
            speed: _num(p.speed, 2, 30, def.gradientAnimationSpeed),
            radialPosX: _num(p.radialPosX, 0, 100, def.gradientRadialPosX),
            radialPosY: _num(p.radialPosY, 0, 100, def.gradientRadialPosY),
            radialShape: _MODE_ENUMS.gradientRadialShape.includes(p.radialShape) ? p.radialShape : def.gradientRadialShape,
            radialSize: _MODE_ENUMS.gradientRadialSize.includes(p.radialSize) ? p.radialSize : def.gradientRadialSize,
            meshBgColor: _cssTok(p.meshBgColor, def.gradientMeshBgColor),
        };
        if (Array.isArray(p.stops)) {
            clean.stops = p.stops.filter(s => s && typeof s === 'object').slice(0, 32)
                .map(s => ({ color: _cssTok(s.color, '#000000'), position: _num(s.position, 0, 100, 0) }));
        }
        if (Array.isArray(p.meshPoints)) {
            clean.meshPoints = p.meshPoints.filter(pt => pt && typeof pt === 'object').slice(0, 32)
                .map(pt => ({
                    color: _cssTok(pt.color, '#000000'),
                    x: _num(pt.x, 0, 100, 50), y: _num(pt.y, 0, 100, 50),
                    spread: _num(pt.spread, 10, 80, 50)
                }));
        }
        if (!clean.stops && !clean.meshPoints) return null;
        return clean;
    }

    function sanitizeGradientPresets(list) {
        return Array.isArray(list) ? list.map(sanitizeGradientPreset).filter(Boolean) : [];
    }

    // A Canvas FX (contentKey 'script') or CSS ('code') preset, or null when
    // it isn't an object or its code isn't text. A preset without a usable
    // name gets one rather than being dropped: older builds stored any name,
    // and the server library is replaced by what this keeps.
    function sanitizeCodePreset(p, contentKey, fallbackName) {
        if (!p || typeof p !== 'object' || Array.isArray(p) || typeof p[contentKey] !== 'string') return null;
        if (typeof p.name === 'string' && p.name.trim()) return p;
        const given = p.name !== null && typeof p.name !== 'object' && p.name !== undefined ? String(p.name).trim() : '';
        return { ...p, name: given || fallbackName };
    }

    function sanitizeCodePresets(list, contentKey, noun) {
        return Array.isArray(list) ? list.map((p, i) => sanitizeCodePreset(p, contentKey, `${noun} ${i + 1}`)).filter(Boolean) : [];
    }

    // Snapshots arriving from the server library are as untrusted as an import:
    // they may have been written by an older build, before the values in them
    // were validated at all.
    function sanitizeSnapshotList(list) {
        if (!Array.isArray(list)) return [];
        list.forEach(s => {
            if (!s || typeof s !== 'object') return;
            MODES.forEach(m => { if (s[m] && typeof s[m] === 'object') s[m] = validateModeData(s[m]); });
        });
        return list;
    }

    function normalizeModeData(d) {
        if (!d) return d;
        // Format normalization (handles JSON Viewer and other non-standard formats)
        if (d.oklch && d.h === undefined) {
            d.h = d.oklch.hue ?? 250;
            d.c = d.oklch.chroma ?? 0;
            d.l = d.oklch.lightness ?? 20;
            delete d.oklch;
        }
        if (Array.isArray(d.locks)) {
            const o = {};
            d.locks.forEach(k => o[k] = true);
            d.locks = o;
        }
        delete d.variables;
        // Themes saved before the switch was kept have none: their overrides
        // were meant to apply, so text means on.
        if (d.manualOverridesEnabled === undefined && typeof d.manualOverrides === 'string' && d.manualOverrides.trim()) {
            d.manualOverridesEnabled = true;
        }
        return validateModeData({ ...createDefaultModeData(), ...d });
    }

    async function loadFromUrl({ urlInputId, statusId, loadBtnId, modalId, fetchMsg, emptyMsg, defaultName, defaultExt, mimeType, importFn }) {
        const urlInput = $(urlInputId);
        const statusEl = $(statusId);
        const loadBtn = $(loadBtnId);
        const url = (urlInput.value || '').trim();

        if (!url) {
            showStatus(statusEl, emptyMsg, 'error');
            return;
        }

        try { new URL(url); } catch {
            showStatus(statusEl, 'Invalid URL format. Please enter a valid URL.', 'error');
            return;
        }

        const origHTML = loadBtn.innerHTML;
        loadBtn.disabled = true;
        loadBtn.innerHTML = '<span class="spin">⟳</span> Loading...';
        showStatus(statusEl, fetchMsg, 'loading');

        try {
            // After the empty and invalid input checks above, so a blank
            // field never reports a disallowed domain. A pasted URL can be a
            // whole gallery bundle, so it gets the bundle ceiling.
            const text = await fetchRemoteText(url, MAX_BUNDLE_BYTES);
            if (linkedImport && linkedImport.inputId === urlInputId && linkedImport.href === url) {
                const problem = linkedImportProblem(text, linkedImport.isCss);
                if (problem) throw new Error(problem);
            }
            const fileName = url.split('/').pop().split('?')[0] || defaultName;

            let isJson = fileName.endsWith('.json');
            if (!isJson) { try { JSON.parse(text); isJson = true; } catch {} }

            const ext = isJson ? '.json' : defaultExt;
            const finalName = fileName.endsWith(ext) ? fileName : fileName + ext;
            const type = isJson ? 'application/json' : mimeType;
            const blob = new Blob([text], { type });
            const file = new File([blob], finalName, { type });

            hideModal(modalId);
            await importFn([file]);
        } catch (err) {
            showStatus(statusEl, `Error: ${err.message}`, 'error');
        } finally {
            loadBtn.disabled = false;
            loadBtn.innerHTML = origHTML;
        }
    }

    function triggerFileImport({ accept, modalId, importFn }) {
        const input = document.createElement('input');
        input.type = 'file';
        input.accept = accept;
        input.multiple = true;
        input.onchange = async (e) => {
            const files = Array.from(e.target.files);
            if (files.length) {
                hideModal(modalId);
                await importFn(files);
            }
        };
        input.click();
    }

    // A missing OLED or Her mode, filled as Selective Sync reads one
    function ensureAllModes(data) {
        ['oled', 'her'].forEach(m => { if (!data[m]) data[m] = snapshotModeData(data, m) || null; });
        return data;
    }

    // The fields each Selective Sync section copies (applySyncToMode, which
    // copies from the source as normalizeModeData leaves it), so the ones
    // that make two modes differ. Locks are not among them: applying a
    // library theme rebuilds them from its overrides.
    const MODE_SECTION_FIELDS = {
        palette: ['h', 'c', 'l', 'paletteEnabled', ...ACCENT_FIELDS.map(a => a.key)],
        overrides: ['overrides', 'manualOverrides', 'manualOverridesEnabled'],
        css: ['customCSS', 'customCssEnabled', 'autoScope'],
        canvas: ['canvasEnabled', 'canvasScript'],
        gradient: [
            'gradientEnabled', 'gradientType', 'gradientAngle', 'gradientStops',
            'gradientIntensity', 'gradientAnimation', 'gradientAnimationSpeed',
            'gradientRadialPosX', 'gradientRadialPosY', 'gradientRadialShape', 'gradientRadialSize',
            'gradientMeshPoints', 'gradientMeshBgColor'
        ],
        surfaces: SURFACE_FIELDS,
        auth: ['themeShowAuth', 'customCssShowAuth', 'canvasShowAuth', 'gradientShowAuth', ...AUTH_ONLY_KEYS]
    };
    const GRADIENT_CLONE_KEYS = new Set(['gradientStops', 'gradientMeshPoints']);
    const DEFAULT_MESH_POINTS = [{color:'#6366f1',x:25,y:25,spread:50},{color:'#ec4899',x:75,y:30,spread:45},{color:'#06b6d4',x:50,y:75,spread:50}];

    function copyGradientProps(target, source) {
        for (const k of MODE_SECTION_FIELDS.gradient) {
            if (source[k] !== undefined) target[k] = GRADIENT_CLONE_KEYS.has(k) ? structuredClone(source[k]) : source[k];
        }
    }

    function copyAuthProps(target, source) {
        for (const k of MODE_SECTION_FIELDS.auth) {
            if (source[k] !== undefined) target[k] = source[k];
        }
    }

    // 'Only on Auth Pages' needs 'Show on Auth Pages': off with it, and
    // dimmed while its part is off, like the switch beside it
    function syncAuthOnlyToggles() {
        const config = themeData[getActiveDataMode()];
        if (!config) return;
        AUTH_ONLY.forEach(([key, showKey, enabledKey, id]) => {
            const el = document.getElementById(id);
            if (!el) return;
            const shown = config[showKey] !== false;
            el.checked = shown && config[key] === true;
            el.disabled = !shown;
            const on = enabledKey === 'customCssEnabled' ? config[enabledKey] !== false : !!config[enabledKey];
            const label = el.closest('label');
            if (label) label.style.opacity = on && shown ? '1' : '0.35';
        });
    }

    function _stableStringify(val) {
        if (val === null || val === undefined) return 'null';
        if (typeof val !== 'object') return JSON.stringify(val);
        if (Array.isArray(val)) return '[' + val.map(_stableStringify).join(',') + ']';
        return '{' + Object.keys(val).sort().map(k => JSON.stringify(k) + ':' + _stableStringify(val[k])).join(',') + '}';
    }

    // The sections in which two modes differ. Both are compared as
    // normalizeModeData leaves them, so a field one side leaves out counts
    // as its default.
    function modeSectionDiffs(a, b) {
        const na = normalizeModeData(structuredClone(a)), nb = normalizeModeData(structuredClone(b));
        return Object.keys(MODE_SECTION_FIELDS).filter(section =>
            MODE_SECTION_FIELDS[section].some(k => _stableStringify(na[k]) !== _stableStringify(nb[k])));
    }

    function resetTooltipStyles(el) {
        el.style.background = '';
        el.style.color = '';
        el.style.borderColor = '';
    }

    const DEFAULT_CANVAS_SCRIPT = `/**
 * Title: Tactical Liquid Grid
 * Description: A field of crosshairs that the cursor shoves aside like elastic fabric, lighting up in your theme's accents as they spring back, faded behind the chat.
 */

/* ────────── CONFIGURABLE VARIABLES ────────── */
const SPACING       = 36;    // distance between crosshairs, in px (20-80)
const CROSS_SIZE    = 4;     // half-length of each crosshair arm, in px (2-8)
const GRID_ALPHA    = 1;     // visibility of the resting grid (0-1)
const ACTIVE_ALPHA  = 0.9;   // visibility of crosshairs while they move (0-1)
const MOUSE_RADIUS  = 150;   // reach of the cursor's shove, in px (60-300)
const MOUSE_FORCE   = 1;     // strength of the shove (0-3)
const SPRING        = 0.1;   // how firmly crosshairs return home (0.02-0.3)
const FRICTION      = 0.85;  // how much motion each step keeps; lower settles faster (0.7-0.95)
const MOTION        = 1;     // speed of the fabric; 0 freezes it (0-2)
const REDUCED_FORCE = 0.25;  // share of the shove kept when the viewer asks to reduce motion (0-1)
const CENTER_CALM   = 0.85;  // how much the grid fades behind the chat column (0-1)
const BAND_WIDTH    = 520;   // half-width of the calm band around the chat column, in px (300-900)
const COLOR_CYCLE   = false; // moving crosshairs drift through all three accents instead of one
const CYCLE_SPEED   = 0.4;   // how fast the accents travel across the moving crosshairs (0-2)
const FOLLOW_THEME  = true;  // take the colors from the theme's palette
const GRID_COLOR    = '#c8ccd8';  // resting crosshair color when not following the theme
const ACTIVE_COLOR  = '#00e5ff';  // moving crosshair color
const ACTIVE_COLOR2 = '#7a6cff';  // second accent for the color cycle
const ACTIVE_COLOR3 = '#ff5fb0';  // third accent for the color cycle
/* ──────────────────────────────────────────── */

// Alpha steps for the resting grid (one path each), and the springs' fixed rate, whatever the display's refresh
const LEVELS = 5;
const STEP = 1 / 60;

let canvas, ctx;
let w = 0, h = 0, dpr = 1;
let last = 0, acc = 0, phase = 0, reduced = false, dark = true, dirty = true;
let count = 0;
let ox, oy, px, py, vx, vy, lvl, calm;
const mouse = { x: -10000, y: -10000, amount: 0, target: 0 };
const palette = { grid: GRID_COLOR, accents: [ACTIVE_COLOR, ACTIVE_COLOR2, ACTIVE_COLOR3] };
const restAlpha = new Float32Array(LEVELS);

function applyTheme(t) {
	if (t) {
		dark = t.dark !== false;
		if (FOLLOW_THEME && t.colors) {
			palette.grid = t.colors.muted;
			palette.accents[0] = t.colors.accent;
			palette.accents[1] = t.colors.accent2;
			palette.accents[2] = t.colors.accent3;
		}
	}
	// Light backgrounds show everything, so the resting grid steps down there
	const top = GRID_ALPHA * (dark ? 0.5 : 0.48);
	for (let i = 0; i < LEVELS; i++) restAlpha[i] = top * (0.25 + 0.75 * i / (LEVELS - 1));
	dirty = true;
}

function band(x) {
	const b = Math.abs(x - w / 2) / BAND_WIDTH;
	const s = Math.min(1, Math.max(0, (b - 0.55) / 0.7));
	return 1 - CENTER_CALM * (1 - s * s * (3 - 2 * s));
}

function resize(width, height, ratio) {
	w = width;
	h = height;
	dpr = Math.min(ratio || 1, 2);
	if (!canvas) return;
	canvas.width = Math.max(1, Math.round(w * dpr));
	canvas.height = Math.max(1, Math.round(h * dpr));
	ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
	const cols = Math.ceil(w / SPACING) + 1, rows = Math.ceil(h / SPACING) + 1;
	count = cols * rows;
	ox = new Float32Array(count); oy = new Float32Array(count);
	px = new Float32Array(count); py = new Float32Array(count);
	vx = new Float32Array(count); vy = new Float32Array(count);
	calm = new Float32Array(count); lvl = new Uint8Array(count);
	// Whole pixels plus a half at dpr 1, so the 1 px arms land crisp on the pixel grid
	const snap = dpr < 1.5 ? 0.5 : 0;
	const offX = Math.round((w - (cols - 1) * SPACING) / 2) + snap, offY = Math.round((h - (rows - 1) * SPACING) / 2) + snap;
	let i = 0;
	for (let c = 0; c < cols; c++) {
		for (let r = 0; r < rows; r++, i++) {
			ox[i] = px[i] = offX + c * SPACING;
			oy[i] = py[i] = offY + r * SPACING;
			calm[i] = band(ox[i]);
			lvl[i] = Math.round(((calm[i] - (1 - CENTER_CALM)) / Math.max(0.001, CENTER_CALM)) * (LEVELS - 1));
		}
	}
	dirty = true;
}

// One fixed spring step; returns whether anything is still moving
function step() {
	const r2 = MOUSE_RADIUS * MOUSE_RADIUS;
	const force = MOUSE_FORCE * 50 * mouse.amount * (reduced ? REDUCED_FORCE : 1);
	let moving = false;
	for (let i = 0; i < count; i++) {
		let ax = vx[i], ay = vy[i];
		const dx = px[i] - mouse.x, dy = py[i] - mouse.y;
		const d2 = dx * dx + dy * dy;
		if (force > 0.01 && d2 < r2 && d2 > 0.01) {
			const d = Math.sqrt(d2);
			const f = ((MOUSE_RADIUS - d) / MOUSE_RADIUS) * force / d;
			ax += dx * f;
			ay += dy * f;
		}
		const hx = ox[i] - px[i], hy = oy[i] - py[i];
		if (ax === 0 && ay === 0 && hx === 0 && hy === 0) continue;
		ax = (ax + hx * SPRING) * FRICTION;
		ay = (ay + hy * SPRING) * FRICTION;
		px[i] += ax;
		py[i] += ay;
		// Settle exactly home once the motion is invisible, so a still grid costs nothing
		if (Math.abs(ax) + Math.abs(ay) < 0.004 && Math.abs(hx) + Math.abs(hy) < 0.02 && force <= 0.01) {
			px[i] = ox[i]; py[i] = oy[i]; ax = 0; ay = 0;
		} else moving = true;
		vx[i] = ax;
		vy[i] = ay;
	}
	return moving;
}

function activity(i) {
	const s = Math.abs(vx[i]) + Math.abs(vy[i]);
	const disp = Math.abs(px[i] - ox[i]) + Math.abs(py[i] - oy[i]);
	return Math.min(1, s * 0.15 + disp * 0.03);
}

function cross(i, s) {
	ctx.moveTo(px[i] - s, py[i]); ctx.lineTo(px[i] + s, py[i]);
	ctx.moveTo(px[i], py[i] - s); ctx.lineTo(px[i], py[i] + s);
}

// The accent a moving crosshair shows: one accent, or a slow wave through all three
function accentOf(i) {
	if (!COLOR_CYCLE) return 0;
	const v = phase + (ox[i] + oy[i]) * 0.004;
	return Math.floor(v - Math.floor(v / 3) * 3);
}

function draw() {
	ctx.clearRect(0, 0, w, h);
	ctx.globalCompositeOperation = 'source-over';
	// Resting crosshairs, one path per alpha step
	ctx.lineWidth = 1;
	ctx.strokeStyle = palette.grid;
	for (let l = 0; l < LEVELS; l++) {
		ctx.globalAlpha = restAlpha[l];
		ctx.beginPath();
		for (let i = 0; i < count; i++) if (lvl[i] === l && activity(i) < 0.08) cross(i, CROSS_SIZE);
		ctx.stroke();
	}
	// Moving crosshairs, bucketed by accent and brightness
	ctx.lineWidth = 1.5;
	const peak = ACTIVE_ALPHA * (dark ? 1 : 0.85);
	for (let a = 0; a < (COLOR_CYCLE ? 3 : 1); a++) {
		ctx.strokeStyle = palette.accents[a];
		for (let b = 0; b < 3; b++) {
			ctx.globalAlpha = peak * (b + 1) / 3;
			ctx.beginPath();
			for (let i = 0; i < count; i++) {
				const act = activity(i);
				if (act < 0.08 || accentOf(i) !== a) continue;
				if (Math.min(2, Math.floor(act * calm[i] * 3)) !== b) continue;
				cross(i, CROSS_SIZE + act * 2);
			}
			ctx.stroke();
		}
	}
	ctx.globalAlpha = 1;
}

function frame(now) {
	requestAnimationFrame(frame);
	if (!ctx) return;
	const dt = last ? Math.min((now - last) / 1000, 0.1) : 0;
	last = now;
	mouse.target = Math.max(0, mouse.target - dt * 0.6);
	mouse.amount += (mouse.target - mouse.amount) * Math.min(1, dt * 6);
	if (COLOR_CYCLE) phase = (phase + dt * CYCLE_SPEED * (reduced ? 0.25 : 1)) % 3;
	acc += dt * MOTION;
	let moving = false, n = 0;
	while (acc >= STEP && n < 8) {
		moving = step() || moving;
		acc -= STEP;
		n++;
	}
	if (n === 8) acc = 0;
	if (moving || dirty) {
		draw();
		dirty = moving;
	}
}

self.onmessage = (e) => {
	const d = e.data;
	switch (d.type) {
		case 'init':
			canvas = d.canvas;
			ctx = canvas.getContext('2d');
			reduced = !!d.reducedMotion;
			applyTheme(d.theme);
			resize(d.width, d.height, d.dpr);
			requestAnimationFrame(frame);
			break;
		case 'resize':
			resize(d.width, d.height, d.dpr);
			break;
		case 'theme':
			applyTheme(d);
			break;
		case 'motion':
			reduced = !!d.reducedMotion;
			break;
		case 'mousemove':
			mouse.x = d.x;
			mouse.y = d.y;
			mouse.target = 1;
			break;
	}
};`;

    let CANVAS_PRESETS = Storage.get('canvas');
    if (!Array.isArray(CANVAS_PRESETS) || CANVAS_PRESETS.length === 0) {
        CANVAS_PRESETS = [
            {
                name: "Tactical Liquid Grid",
                script: DEFAULT_CANVAS_SCRIPT
            }
        ];
        Storage.set('canvas', CANVAS_PRESETS);
        syncLibrary();
    }

    // No CSS presets ship with the function: the library holds the user's own
    let CSS_PRESETS = Storage.get('css');
    if (!Array.isArray(CSS_PRESETS)) CSS_PRESETS = [];

    let CUSTOM_GRADIENT_PRESETS = Storage.get('gradients', []);
    if (!Array.isArray(CUSTOM_GRADIENT_PRESETS)) CUSTOM_GRADIENT_PRESETS = [];

    // The server's library (source of truth), which it put in this page and
    // _libraryStore already reads. Once the page has loaded it's checked like
    // an import and drawn. When the server has none yet, an older build's copy
    // in the browser goes up to it.
    function loadServerLibrary() {
        const keptAs = (window.__THEME_PRO_CONFIG__ || {}).libraryKeptAs;
        if (keptAs) showToast(`⚠️ The gallery file couldn’t be read, so the gallery starts empty. The file was kept on the server as ${keptAs}.`, 10000);
        const lib = _serverLibrary;
        const hasServerData = (lib.snapshots && lib.snapshots.length > 0)
            || (lib.canvas_presets && lib.canvas_presets.length > 0)
            || (lib.css_presets && lib.css_presets.length > 0)
            || (lib.gradient_presets && lib.gradient_presets.length > 0);

        if (hasServerData) {
            // Validated like an import: this replaces the whole library on
            // every page load, and themes written by an older build would
            // otherwise reach the page with only the render-time sanitizers
            if (lib.snapshots && lib.snapshots.length > 0) saveSnapshots(sanitizeSnapshotList(lib.snapshots));
            if (lib.canvas_presets && lib.canvas_presets.length > 0) { CANVAS_PRESETS.splice(0, CANVAS_PRESETS.length, ...sanitizeCodePresets(lib.canvas_presets, 'script', 'Animation')); Storage.set('canvas', CANVAS_PRESETS); }
            if (lib.css_presets && lib.css_presets.length > 0) { CSS_PRESETS.splice(0, CSS_PRESETS.length, ...sanitizeCodePresets(lib.css_presets, 'code', 'Snippet')); Storage.set('css', CSS_PRESETS); }
            if (lib.gradient_presets && lib.gradient_presets.length > 0) { const g = sanitizeGradientPresets(lib.gradient_presets); CUSTOM_GRADIENT_PRESETS.splice(0, CUSTOM_GRADIENT_PRESETS.length, ...g); Storage.set('gradients', CUSTOM_GRADIENT_PRESETS); }
            renderSnapshots();
            renderCanvasPresets();
            renderCssPresets();
            renderGradientPresets();
            console.log('[Theme Pro] Library loaded from server');
        } else {
            const hasLocalData = getSnapshots().length > 0
                || CANVAS_PRESETS.length > 0
                || CSS_PRESETS.length > 0
                || CUSTOM_GRADIENT_PRESETS.length > 0;
            if (hasLocalData) {
                syncLibrary();
                console.log('[Theme Pro] Auto-migrated localStorage presets to server');
            }
        }
    }
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', loadServerLibrary);
    else setTimeout(loadServerLibrary, 0);

    // Open WebUI's Tailwind v4 gray ramp: at h 250, c 0, l 20 the palette
    // reproduces its default colours exactly
    const lightnessMap = { 50: 0.98, 100: 0.94, 200: 0.92, 300: 0.85, 400: 0.77, 500: 0.69, 600: 0.51, 700: 0.42, 800: 0.32, 850: 0.27, 900: 0.20, 950: 0.16 };

    // One ramp step, with chroma and lightness already scaled to 0-1
    function rampStepColor(step, h, c, l) {
        const targetL = Math.max(0.00, Math.min(0.98, lightnessMap[step] + (l - 0.20)));
        return `oklch(${targetL.toFixed(3)} ${c.toFixed(3)} ${c === 0 ? 0 : h})`;
    }

    // Library cards come from getSnapshots(), which reads localStorage
    // verbatim, so a theme installed under an older build can still carry
    // hostile values: getVariablesMap sanitizes them
    function renderTonalRampHTML(config) {
        const vars = getVariablesMap(config);
        return steps.map(step => `<div style="flex:1; height:100%; background:${vars[`--color-gray-${step}`]};"></div>`).join('');
    }

    // A personal theme this tab held when the server didn't take it (see
    // holdPersonalSave): offered when the designer opens (_keptToOffer), and
    // saved as it loads once the user said yes (_keptUnsaved)
    let _keptToOffer = null;
    const _keptUnsaved = (() => {
        if (HIDDEN_APPLY_FRAME || THEME_KIND !== 'personal') return null;
        try {
            // Kept until the user answers, and once they said yes until it saves
            const kept = JSON.parse(sessionStorage.getItem(UNSAVED_THEME_KEY) || 'null');
            if (!kept || kept.scope !== THEME_KIND || typeof kept.state !== 'string' || kept.state === window.__THEME_PRO_SAVED_STATE__) {
                sessionStorage.removeItem(UNSAVED_THEME_KEY);
                return null;
            }
            if (kept.confirmed) return kept.state;
            _keptToOffer = kept.state;
        } catch (x) {}
        return null;
    })();
    // If resuming a draft session, prefer draft state over published state
    const _resumingDraft = !HIDDEN_APPLY_FRAME && sessionStorage.getItem('owui_theme_draft_mode') === '1';
    const saved = (() => {
        if (_resumingDraft) {
            // Read draft state directly from sessionStorage. We can't use
            // Storage.get() here because _draftMode is still false at this
            // point, so it would route to localStorage (published state).
            try {
                const draftRaw = sessionStorage.getItem(Storage._resolve('theme'));
                if (draftRaw) return JSON.parse(draftRaw);
            } catch(x) {}
        }
        return Storage.get('theme', {});
    })();

    // Open WebUI 0.13.5 dropped its OLED Dark theme: a stored 'oled-dark'
    // becomes 'dark' plus a black custom colour on the next page load. So
    // OLED leaves 'theme' at 'dark' and says OLED under a key of its own,
    // read with it here and by the bootloader on every page.
    const OLED_KEY = 'owui_tdp_oled';
    function owuiTheme() {
        const theme = localStorage.getItem('theme');
        return theme === 'dark' && localStorage.getItem(OLED_KEY) === '1' ? 'oled-dark' : theme;
    }

    let activeMode = 'dark'; // 'dark', 'oled', 'light', 'her' or 'system'

    // Auto-detect OWUI theme to match designer appearance
    (function() {
        try {
            const current = owuiTheme() || 'dark';
            if (current === 'light') { activeMode = 'light'; document.body.classList.add('light-mode'); }
            else if (current === 'her') { activeMode = 'her'; document.body.classList.add('light-mode'); }
            else if (current === 'oled-dark') { activeMode = 'oled'; }
            else if (current === 'system') {
                const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
                if (!prefersDark) { activeMode = 'light'; document.body.classList.add('light-mode'); }
            }
        } catch(e) {}
    })();
    let shouldInject = true;
    let activeThemeRef = saved._activeThemeRef || createNullModeMap();
    let activeCanvasRef = saved._activeCanvasRef || createNullModeMap();
    let activeCssRef = saved._activeCssRef || createNullModeMap();
    let activeGradientRef = saved._activeGradientRef || createNullModeMap();
    // How much of Open WebUI's own background images shows while this theme
    // is in use (the bootloader's syncHiddenBackgrounds). A setting of the live
    // theme, not of a gallery theme: applying one leaves it as it is.
    let hiddenBackgrounds = readHiddenBackgrounds(saved._hiddenBackgrounds);
    // Set by the Backgrounds tab: puts its controls back in step after the
    // settings are replaced (the saved theme loading, a Global Reset)
    let refreshBackgroundsUi = () => {};

    let themeData = {
        dark: saved.dark || createDefaultModeData(),
        oled: saved.oled || createDefaultModeData({ l: 0 }),
        light: saved.light || createDefaultModeData(),
        her: saved.her || createDefaultModeData()
    };

    // Undo/Redo: deep copies of the theme and its refs, oldest first. The
    // first entry is the starting point, so the first edit can be undone.
    function captureHistoryState() {
        return structuredClone({ themeData, activeThemeRef, activeCanvasRef, activeCssRef, activeGradientRef });
    }
    let historyStack = [captureHistoryState()];
    let historyIndex = 0;

    // Controls that change the theme on every step (typing, a wheel, a stop
    // being dragged) record it for Undo once they pause. One pending entry
    // at a time: pushState captures the whole theme, so it covers them all.
    let _pendingPush = null;
    function pushStateSoon(source, ms) {
        if (_pendingPush && _pendingPush.source !== source) pushState();
        clearTimeout(_pendingPush && _pendingPush.timer);
        _pendingPush = { source, timer: setTimeout(pushState, ms) };
    }

    // Applies what the editors are still holding back and records any pending
    // step, so Undo, Redo and anything that replaces the theme start from it
    function flushPendingEdits() {
        document.querySelectorAll('textarea').forEach(t => { if (t._flushEdit) t._flushEdit(); });
        if (_pendingPush) pushState();
    }

    function hasPendingEdits() {
        return [].some.call(document.querySelectorAll('textarea'), t => !!t._pendingEdit);
    }

    function pushState() {
        if (_pendingPush) { clearTimeout(_pendingPush.timer); _pendingPush = null; }
        if (historyIndex < historyStack.length - 1) {
            historyStack = historyStack.slice(0, historyIndex + 1);
        }
        historyStack.push(captureHistoryState());
        if (historyStack.length > TIMING.historyLimit) {
            historyStack.shift();
        } else {
            historyIndex++;
        }
        updateHistoryButtons();
    }

    // The page's starting point. The history's first entry is taken before
    // the server's theme loads, from this browser's older copy or defaults,
    // and Undo back to it published that over the live theme.
    function resetHistoryBaseline() {
        historyStack = [captureHistoryState()];
        historyIndex = 0;
        updateHistoryButtons();
    }

    function commitChange({ clearRef = true, push = true, dm = null, snapshots = false } = {}) {
        const mode = dm || getActiveDataMode();
        if (clearRef) activeThemeRef[mode] = null;
        shouldInject = true;
        updatePalette();
        if (push) pushState();
        if (snapshots) renderSnapshots();
    }

    function migrateLegacyTheme(data) {
        const ov = data.overrides || {};
        const locks = {};
        Object.keys(ov).forEach(k => locks[k] = true);
        // Only the values the theme has: an undefined one spread over the
        // defaults would leave that mode without it
        const palette = {};
        ['h', 'c', 'l'].forEach(k => { const n = _toFiniteNumber(data[k]); if (n !== null) palette[k] = n; });
        return {
            name: data.name || 'Imported Theme',
            dark: createDefaultModeData({ ...palette, overrides: structuredClone(ov), locks: structuredClone(locks) }),
            oled: createDefaultModeData({ ...palette, l: 0, overrides: structuredClone(ov), locks: structuredClone(locks) }),
            light: createDefaultModeData({ ...palette }),
            her: createDefaultModeData({ ...palette }),
        };
    }

    // A theme file and a library entry as the designer imports them, or null
    // for one it refuses. Every import builds its themes with these, so
    // linkedImportProblem and the paste's duplicate check see exactly what
    // gets imported; a chat theme (chatTheme) carries less and builds its own
    function themeFromFile(data, name) {
        if (_isLegacyTheme(data)) data = migrateLegacyTheme({ ...data, name: data.name || name });
        if (!data || !_isModeObject(data.dark) || !_isModeObject(data.light)) return null;
        const theme = {
            ...themeMetadata(data),
            name: data.name || name,
            dark: data.dark,
            light: data.light,
            oled: _isModeObject(data.oled) ? data.oled : null,
            her: _isModeObject(data.her) ? data.her : null
        };
        ensureAllModes(theme);
        // A theme saved with its palette off stays off: normalizeModeData
        // fills it in only when the file has none
        MODES.forEach(m => { theme[m] = normalizeModeData(theme[m]); });
        return theme;
    }
    function themeFromEntry(t) {
        if (!_isThemeEntry(t)) return null;
        if (_isLegacyTheme(t)) t = migrateLegacyTheme(t);
        ['oled', 'her'].forEach(m => { if (!_isModeObject(t[m])) t[m] = null; });
        ensureAllModes(t);
        if (t.her.l === 0) t.her.l = 20;
        MODES.forEach(m => { t[m] = normalizeModeData(t[m]); });
        return t;
    }

    function initDragDrop(listEl, rowSelector, reorderFn) {
        let srcIndex = null, ghost = null, indicator = null, dropIndex = null, offsetY = 0;

        function getRowRects() {
            return Array.from(listEl.querySelectorAll(rowSelector)).map(r => ({
                el: r, index: parseInt(r.dataset.index), rect: r.getBoundingClientRect()
            }));
        }

        function cleanup() {
            if (ghost) { ghost.remove(); ghost = null; }
            if (indicator) { indicator.remove(); indicator = null; }
            listEl.querySelectorAll(rowSelector + '.dragging-src').forEach(r => r.classList.remove('dragging-src'));
            document.body.style.cursor = '';
            srcIndex = null;
            dropIndex = null;
        }

        listEl.querySelectorAll('.gradient-drag-handle').forEach(handle => {
            handle.addEventListener('pointerdown', (e) => {
                e.preventDefault();
                e.stopPropagation();
                const row = handle.closest(rowSelector);
                if (!row) return;
                srcIndex = parseInt(row.dataset.index);
                dropIndex = srcIndex;

                const rect = row.getBoundingClientRect();
                offsetY = e.clientY - rect.top;
                ghost = row.cloneNode(true);
                ghost.className = 'gradient-drag-ghost';
                ghost.style.width = rect.width + 'px';
                ghost.style.left = rect.left + 'px';
                ghost.style.top = (e.clientY - offsetY) + 'px';
                ghost.style.background = getComputedStyle(row).background;
                document.body.appendChild(ghost);

                indicator = document.createElement('div');
                indicator.className = 'gradient-drop-indicator';
                listEl.appendChild(indicator);

                row.classList.add('dragging-src');
                document.body.style.cursor = 'grabbing';
                handle.setPointerCapture(e.pointerId);

                const onMove = (ev) => {
                    if (srcIndex === null) return;
                    if (ghost) ghost.style.top = (ev.clientY - offsetY) + 'px';

                    const rows = getRowRects();
                    let newDropIndex = srcIndex;
                    const pointerY = ev.clientY;

                    for (let i = 0; i < rows.length; i++) {
                        const mid = rows[i].rect.top + rows[i].rect.height / 2;
                        if (pointerY < mid) { newDropIndex = i; break; }
                        newDropIndex = i + 1;
                    }
                    if (newDropIndex > rows.length) newDropIndex = rows.length;
                    dropIndex = newDropIndex;

                    if (indicator && rows.length > 0) {
                        const listRect = listEl.getBoundingClientRect();
                        let indicatorTop;
                        if (dropIndex === 0) {
                            indicatorTop = rows[0].rect.top - listRect.top - 4;
                        } else if (dropIndex >= rows.length) {
                            indicatorTop = rows[rows.length - 1].rect.bottom - listRect.top + 3;
                        } else {
                            indicatorTop = (rows[dropIndex - 1].rect.bottom + rows[dropIndex].rect.top) / 2 - listRect.top;
                        }
                        indicator.style.top = indicatorTop + 'px';
                    }
                };

                const onUp = () => {
                    handle.removeEventListener('pointermove', onMove);
                    handle.removeEventListener('pointerup', onUp);
                    handle.removeEventListener('pointercancel', onUp);

                    if (srcIndex !== null && dropIndex !== null && dropIndex !== srcIndex && dropIndex !== srcIndex + 1) {
                        const targetIndex = dropIndex > srcIndex ? dropIndex - 1 : dropIndex;
                        reorderFn(srcIndex, targetIndex);
                    }
                    cleanup();
                };

                handle.addEventListener('pointermove', onMove);
                handle.addEventListener('pointerup', onUp);
                handle.addEventListener('pointercancel', onUp);
            });
        });
    }

    // Open dialogs, newest last, each with the element that had focus when it
    // opened. Every close goes through hideModal, which gives that focus back
    // and fires `close` on the dialog.
    const openDialogs = [];
    function topDialog() {
        for (let i = openDialogs.length - 1; i >= 0; i--) {
            if (openDialogs[i].dialog.style.display !== 'none') return openDialogs[i].dialog;
        }
        return null;
    }
    function showModal(id, display = 'flex') {
        const dialog = $(id);
        if (!openDialogs.some(d => d.dialog === dialog)) openDialogs.push({ dialog, opener: document.activeElement });
        dialog.style.display = display;
        if (!dialog.contains(document.activeElement)) {
            dialog.tabIndex = -1;
            dialog.focus({ preventScroll: true });
        }
    }
    function hideModal(id) {
        const dialog = $(id);
        const hadFocus = dialog.contains(document.activeElement);
        dialog.style.display = 'none';
        const i = openDialogs.findIndex(d => d.dialog === dialog);
        if (i < 0) return;
        const { opener } = openDialogs.splice(i, 1)[0];
        if (hadFocus && opener && opener.isConnected) opener.focus({ preventScroll: true });
        dialog.dispatchEvent(new Event('close'));
    }
    document.addEventListener('keydown', (e) => {
        const dialog = e.key === 'Tab' && topDialog();
        if (!dialog) return;
        // checkVisibility, not layout boxes: the contents of a closed <details>
        // keep their boxes but can't take focus
        const stops = [...dialog.querySelectorAll('button, input, select, textarea, a[href], summary, [tabindex]')]
            .filter(el => el.tabIndex >= 0 && !el.disabled && el.checkVisibility({ visibilityProperty: true }));
        const at = document.activeElement;
        const edge = e.shiftKey ? stops[0] : stops[stops.length - 1];
        if (!stops.length || at === dialog || at === edge || !dialog.contains(at)) {
            e.preventDefault();
            if (stops.length) (e.shiftKey ? stops[stops.length - 1] : stops[0]).focus();
        }
    });

    // Asks in the designer's own dialog. A browser lets the user stop a page's
    // native dialogs, after which confirm() answers no without asking, and an
    // update or reset behind it failed with no explanation. Cancel, Escape or
    // the backdrop close the dialog, which counts as no.
    function askConfirm(title, message, confirmLabel) {
        const modal = $('ask-modal');
        if (!modal) return Promise.resolve(window.confirm(message));
        return new Promise(resolve => {
            $('ask-modal-title').textContent = title;
            const msg = $('ask-modal-msg');
            msg.textContent = message;
            msg.style.whiteSpace = 'pre-line';
            const btn = $('ask-modal-confirm-btn');
            btn.textContent = confirmLabel || 'Continue';
            let settled = false;
            const settle = (ok) => {
                if (settled) return;
                settled = true;
                btn.removeEventListener('click', onConfirm);
                modal.removeEventListener('close', onClose);
                hideModal('ask-modal');
                resolve(ok);
            };
            const onConfirm = () => settle(true);
            const onClose = () => settle(false);
            btn.addEventListener('click', onConfirm);
            modal.addEventListener('close', onClose);
            showModal('ask-modal');
        });
    }
    window.askConfirm = askConfirm;

    function restoreHistoryState(state) {
        const dm = getActiveDataMode();
        if (state.themeData) {
            themeData = state.themeData;
            activeThemeRef = state.activeThemeRef;
            activeCanvasRef = state.activeCanvasRef;
            activeCssRef = state.activeCssRef;
            activeGradientRef = state.activeGradientRef || activeGradientRef;
        } else {
            themeData = state;
            activeThemeRef[dm] = null;
            activeCanvasRef[dm] = null;
            activeCssRef[dm] = null;
            activeGradientRef[dm] = null;
        }
        commitChange({ clearRef: false, push: false });
        updateHistoryButtons();
    }

    function undo() {
        flushPendingEdits();
        if (historyIndex > 0) {
            const note = historyStack[historyIndex].undoNote;
            historyIndex--;
            restoreHistoryState(structuredClone(historyStack[historyIndex]));
            showToast(note || "Undone");
        }
    }

    function redo() {
        flushPendingEdits();
        if (historyIndex < historyStack.length - 1) {
            historyIndex++;
            restoreHistoryState(structuredClone(historyStack[historyIndex]));
            showToast("Redone");
        }
    }

    function updateHistoryButtons() {
        const undoBtn = document.getElementById('undo-btn');
        const redoBtn = document.getElementById('redo-btn');

        if (undoBtn) {
            undoBtn.disabled = historyIndex <= 0;
            undoBtn.style.opacity = undoBtn.disabled ? "0.3" : "1";
        }
        if (redoBtn) {
            redoBtn.disabled = historyIndex >= historyStack.length - 1;
            redoBtn.style.opacity = redoBtn.disabled ? "0.3" : "1";
        }
    }

    function showToast(msg, duration = TIMING.toastDuration) {
        const toast = document.getElementById('action-toast');
        if (toast) {
            toast.innerText = msg;
            toast.classList.add('show');
            clearTimeout(toast._hideTimer);
            toast._hideTimer = setTimeout(() => {
                toast.classList.remove('show');
            }, duration);
        }
    }

    // A mode's Custom CSS Snippet comes after the Gradient Builder's output,
    // so a background gradient in it hides the builder's gradient.
    function customCssHidesGradient(md) {
        const css = (md.customCSS || '').toLowerCase();
        return md.customCssEnabled !== false && !!css &&
            /linear-gradient|radial-gradient|conic-gradient/.test(css) && /background/.test(css);
    }

