(function() {
        // Prevent duplicate listener/observer registration on hot-reload re-injection
        if (window._owuiBootloaderReady) return;
        window._owuiBootloaderReady = true;
        try {
            // Theme active state — controlled by function toggle.
            // When the function is disabled, the bootloader is re-injected with
            // __THEME_ACTIVE__=false to keep SSE alive while stripping the theme.
            // When active, this is always true.
            var _themeActive = __THEME_ACTIVE__;
            // Personal themes: a signed-in user's own theme, when the admin allows them.
            var _personalEnabled = __PERSONAL_THEMES__;
            // This browser's copy of the user's personal theme, stamped with the
            // account it belongs to, so a second account here never sees it.
            var PERSONAL_KEYS = ['owui_tdp_personal_css', 'owui_tdp_personal_state', 'owui_tdp_personal_uid'];
            // Older designers left this flag, which hid Canvas FX after the valve came back on
            try { localStorage.removeItem('owui_theme_valve_no_canvas'); } catch(x) {}
            if (!_themeActive) {
                try {
                    localStorage.removeItem('owui_dev_theme_v1_css');
                    localStorage.removeItem('owui_dev_theme_v1');
                    PERSONAL_KEYS.forEach(function(k) { localStorage.removeItem(k); });
                } catch(x) {}
                ['owui-dev-live-theme', 'owui-server-theme', 'owui-theme-style',
                 'owui-theme-canvas-bg', 'owui-theme-bg-color', 'owui-canvas-script-runner'
                ].forEach(function(id) {
                    var el = document.getElementById(id);
                    if (el) el.remove();
                });
            }

            // In-memory theme state — primary source for canvas, eliminates localStorage dependency
            var _owuiThemeState = null;
            // In-memory CSS — primary source for draft mode, where sessionStorage is invisible to bootloader
            var _owuiThemeCss = null;
            // Cached parsed state — invalidated when _owuiThemeState changes.
            // Avoids JSON.parse on every enforceTheme() + initCanvas() call.
            var _parsedState = null;
            // Monotonic version counter — prevents stale fetch responses from overwriting fresher SSE data
            var _themeVersion = 0;
            // Delivery ETags of the last APPLIED css/state — when an SSE broadcast
            // carries matching tags, this client already has that exact version
            // and skips the refetch (avoids a fleet-wide request storm on save).
            var _lastCssTag = null;
            var _lastStateTag = null;

            // The Enable Canvas FX valve as this page load's loader saw it.
            // Until the first answer from the server, the state in use is this
            // browser's cached copy, which still carries any script the admin
            // has since switched off, and ran it once more on every page load.
            // The server's own copy is stripped already when the valve is off.
            var _cachedCanvasOk = __CANVAS_FX__;

            function getParsedState() {
                if (_parsedState) return _parsedState;
                try {
                    // The localStorage copy is the instance theme's; a personal
                    // theme without state of its own must not borrow it
                    var raw = _owuiThemeState || (_personal ? null : localStorage.getItem('owui_dev_theme_v1')) || '{}';
                    if (typeof raw === 'string' && raw.charAt(0) === '{') {
                        _parsedState = JSON.parse(raw);
                    }
                } catch(e) { _parsedState = {}; }
                if (!_cachedCanvasOk && _parsedState) {
                    ['dark', 'oled', 'light', 'her'].forEach(function(m) {
                        var c = _parsedState[m];
                        if (c && typeof c === 'object') { c.canvasEnabled = false; delete c.canvasScript; }
                    });
                }
                return _parsedState || {};
            }

            // Fetch the latest CSS + state from the server and apply them.
            // Shared by: initial page load, SSE theme-update (the broadcast
            // carries only a version token — clients refetch), and iOS PWA
            // foreground resume. cache: 'no-cache' forces conditional
            // revalidation (If-None-Match) — the server answers 304 when
            // nothing changed, so repeat fetches are cheap.
            // True while this page shows the signed-in user's personal theme.
            var _personal = false;
            // What the latest fetch read of the personal theme (see bindStream)
            var _personalRead = Promise.resolve(null);
            // The last CSS enforceTheme() cleaned, and the result
            var _strippedFrom = null;
            var _strippedCss = '';
            // The account the theme on screen was picked for (null: signed
            // out). Open WebUI signs in without a page load, so checkAccount()
            // compares it with the account signed in now.
            var _themeUid = null;
            // Set once the live stream is open: claims it for the signed-in
            // account (bindStream, by the SSE code below).
            var _claimStream = null;

            // The account Open WebUI's sign-in token names, or null
            function tokenUserId() {
                try {
                    var token = localStorage.getItem('token');
                    if (!token) return null;
                    var part = token.split('.')[1].replace(/-/g, '+').replace(/_/g, '/');
                    var claims = JSON.parse(atob(part));
                    return claims && claims.id ? String(claims.id) : null;
                } catch(x) { return null; }
            }

            // The signed-in account, or null: signed out or on the sign-in page
            function signedInUser() {
                return window.location.pathname.startsWith('/auth') ? null : tokenUserId();
            }

            function personalUser() {
                return _personalEnabled ? signedInUser() : null;
            }

            function fetchThemeFromServer() {
                var _fetchVersion = _themeVersion;  // Capture before async fetch
                // Body + ETag, or null when the request itself failed. A null
                // must stay distinguishable from an empty body: empty means
                // "the server has no theme", a network error means "we learned
                // nothing" — treating the second as the first would wipe a
                // perfectly good theme on one dropped request.
                function readAsset(url, signedIn) {
                    var init = { cache: 'no-cache' };
                    // Personal routes read the account from the sign-in token.
                    if (signedIn) {
                        try { init.headers = { Authorization: 'Bearer ' + (localStorage.getItem('token') || '') }; } catch(x) {}
                    }
                    return fetch(url, init)
                        .then(function(r) {
                            // A proxy error while Open WebUI restarts (502, 503),
                            // rate limiting, a timeout, or a proxy's 401/403 says
                            // nothing about the theme: keep what's on screen. The
                            // server says "no theme" with 204 or an empty 200;
                            // only a missing route (404/410) also means it.
                            if (!r.ok && r.status !== 404 && r.status !== 410) return null;
                            if (r.ok && r.status !== 204) {
                                // A gzipping proxy hands the tag on weakened to
                                // W/"...", and the server's broadcasts compare it
                                // with the strong one
                                var tag = r.headers.get('ETag');
                                if (tag && tag.indexOf('W/') === 0) tag = tag.slice(2);
                                return r.text().then(function(t) { return { body: t, tag: tag }; });
                            }
                            return { body: '', tag: null };
                        })
                        .catch(function() { return null; });
                }
                // Both halves are applied together in ONE synchronous block:
                // applied apart, the page runs one theme's CSS against another's
                // state (an outgoing canvas over the incoming colours) between
                // the faster and the slower response.
                function readInstance() {
                    return Promise.all([
                        readAsset('__THEME_ROUTE__/theme.css'),
                        readAsset('__THEME_ROUTE__/state.json')
                    ]);
                }
                // A signed-in user's personal theme wins; with none saved (or
                // personal themes off) both come back empty and the instance
                // theme applies, as it always has.
                var uid = personalUser();
                _themeUid = uid;
                var mineRead = uid ? Promise.all([
                    readAsset('__THEME_ROUTE__/me/theme.css', true),
                    readAsset('__THEME_ROUTE__/me/state.json', true)
                ]) : null;
                // The tags of the personal theme this fetch read (both null for
                // none), which a stream claim compares with what's saved now
                _personalRead = !mineRead ? Promise.resolve(null) : mineRead.then(function(mine) {
                    return mine[0] && mine[1] ? { uid: uid, tags: [mine[0].tag, mine[1].tag] } : null;
                });
                var pick = !uid ? readInstance().then(function(r) { return { results: r, personal: false }; })
                    : mineRead.then(function(mine) {
                        if (!mine[0] || !mine[1]) return null; // Network error: learned nothing
                        if (mine[0].body && mine[0].body.trim()) return { results: mine, personal: true, uid: uid };
                        return readInstance().then(function(r) { return { results: r, personal: false }; });
                    });
                pick.then(function(picked) {
                    if (!picked) return;
                    var results = picked.results;
                    if (_themeVersion > _fetchVersion) return; // A newer update superseded this fetch
                    if (_disabled) return; // Disable fired while fetch was in-flight
                    var cssRes = results[0], stateRes = results[1];
                    if (!cssRes || !stateRes) return; // A half failed — apply neither
                    _personal = picked.personal;
                    if (_personal) {
                        // The personal copy is kept apart from the instance one,
                        // which stays as it was for this browser's other accounts.
                        _lastCssTag = cssRes.tag;
                        _lastStateTag = stateRes.tag;
                        _owuiThemeCss = cssRes.body;
                        var pState = stateRes.body && stateRes.body.trim() && stateRes.body !== '{}' ? stateRes.body : null;
                        _owuiThemeState = pState;
                        _parsedState = null;
                        _cachedCanvasOk = true;
                        try {
                            localStorage.setItem('owui_tdp_personal_uid', picked.uid);
                            localStorage.setItem('owui_tdp_personal_css', cssRes.body);
                            if (pState) localStorage.setItem('owui_tdp_personal_state', pState);
                            else localStorage.removeItem('owui_tdp_personal_state');
                        } catch(x) {}
                        initCanvas();
                        enforceTheme();
                        return;
                    }
                    // No personal theme for this account: drop any copy of one.
                    // Signed out, the copy stays for when its account signs back in.
                    if (uid) {
                        try { PERSONAL_KEYS.forEach(function(k) { localStorage.removeItem(k); }); } catch(x) {}
                    }

                    var css = cssRes.body;
                    var state = stateRes.body;
                    // Record both tags only here, where both halves are known
                    // good. Updating one alone would let the next broadcast's
                    // skip check match on a pair this client never applied.
                    _lastCssTag = cssRes.tag;
                    _lastStateTag = stateRes.tag;

                    if (css && css.trim()) {
                        _owuiThemeCss = css;
                        // Write-through to localStorage (Watchtower recovery fallback)
                        try { localStorage.setItem('owui_dev_theme_v1_css', css); } catch(x) {}
                    } else {
                        // Server returned empty — theme is inactive, clear stale cache
                        var _hadTheme = !!_owuiThemeCss || !!document.getElementById('owui-dev-live-theme');
                        _owuiThemeCss = null;
                        try { localStorage.removeItem('owui_dev_theme_v1_css'); } catch(x) {}
                        var _staleStyle = document.getElementById('owui-dev-live-theme');
                        if (_staleStyle) _staleStyle.remove();
                        // This is the path a backgrounded PWA takes: iOS kills
                        // the SSE connection, so the theme-disable broadcast
                        // never arrives and the first the client hears of it is
                        // this empty response on resume. Drop the shared
                        // stylesheet's copy of the palette here too, or the
                        // colours linger with nothing left to override them.
                        // Only when there was one: with no theme at all, every
                        // load and focus re-downloaded it for nothing.
                        if (_hadTheme) refreshSharedCustomCss();
                    }

                    _cachedCanvasOk = true;
                    if (state && state.trim() && state !== '{}') {
                        _owuiThemeState = state;
                        _parsedState = null;  // Invalidate — state source changed
                        // Write-through to localStorage (Watchtower recovery fallback)
                        try { localStorage.setItem('owui_dev_theme_v1', state); } catch(x) {}
                    } else {
                        // Server returned empty — theme is inactive, clear stale cache
                        _owuiThemeState = null;
                        _parsedState = null;  // Invalidate cached parse
                        try { localStorage.removeItem('owui_dev_theme_v1'); } catch(x) {}
                    }

                    // Once, after BOTH halves are in place. initCanvas() reads
                    // the state and enforceTheme() reads the css, so calling
                    // either from inside a half is what published the mismatch.
                    // Both are no-ops when their source was cleared above.
                    initCanvas();
                    enforceTheme();
                });
            }

            // Fetch server-side CSS and state — keeps ALL users in sync with admin's theme
            // Skip on the designer page (it manages its own state directly)
            if (!window.__THEME_DESIGNER__ && _themeActive) {
            // State JSON inlined into this loader fragment by the server, so it
            // is rebuilt on every page load instead of only on the next event().
            var embeddedState = __EMBEDDED_STATE__;
            if (embeddedState) { _owuiThemeState = embeddedState; }

            // Seed in-memory CSS from localStorage immediately so the synchronous
            // initial refresh() below has the latest data (localStorage is shared
            // across all tabs for the same origin and is updated by SSE handlers).
            // This prevents stale embedded CSS from persisting on duplicated tabs.
            try {
                // The Theme Designer Pro Tool kept each browser's theme under
                // these same keys, and the first fetch below overwrites them
                // with the instance theme. Keep that theme aside once, so the
                // personal designer can offer to start from it.
                if (!localStorage.getItem('owui_tdp_seen')) {
                    var oldState = localStorage.getItem('owui_dev_theme_v1');
                    var oldCss = localStorage.getItem('owui_dev_theme_v1_css');
                    if (oldState) localStorage.setItem('owui_tdp_tool_state', oldState);
                    if (oldCss) localStorage.setItem('owui_tdp_tool_css', oldCss);
                    localStorage.setItem('owui_tdp_seen', '1');
                }
                var lsCss = localStorage.getItem('owui_dev_theme_v1_css');
                if (lsCss) _owuiThemeCss = lsCss;
                var lsState = localStorage.getItem('owui_dev_theme_v1');
                if (lsState) _owuiThemeState = lsState;
                // This account's personal theme, from this browser's copy, so it
                // is in place before Open WebUI draws its interface. Signed out
                // (the sign-in page included), the copy is kept but not shown,
                // so signing back in paints it at once; another account signing
                // in here drops it.
                var me = personalUser();
                if (!me) {
                    // Nothing to show: the instance theme applies
                } else if (localStorage.getItem('owui_tdp_personal_uid') !== me) {
                    PERSONAL_KEYS.forEach(function(k) { localStorage.removeItem(k); });
                } else if (localStorage.getItem('owui_tdp_personal_css')) {
                    _owuiThemeCss = localStorage.getItem('owui_tdp_personal_css');
                    _owuiThemeState = localStorage.getItem('owui_tdp_personal_state') || null;
                    _personal = true;
                }
            } catch(x) {}

            // Fetch CSS + state from server (always needed — /static/custom.css
            // carries only the safe subset, without structural/gradient. Both
            // composed assets track the latest save now that they are built per
            // request, so this fetch is about completing the CSS rather than
            // correcting a stale copy; it still runs to pick up the deferred
            // structural + gradient rules once the canvas is up.)
            fetchThemeFromServer();
            }

            // In-memory disable flag — prevents storage/MutationObserver from re-injecting after theme-disable
            var _disabled = !_themeActive;

            // The mode <html> shows, and what enforceTheme() last left it at
            function rootMode() {
                var html = document.documentElement;
                return (html.getAttribute('data-theme') || '') + '|' + ['dark', 'light', 'her'].filter(function(c) { return html.classList.contains(c); }).join();
            }
            var _rootModeSet = '';

            function themeToMode(theme) {
                if (theme === 'system') return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
                return { 'oled-dark': 'oled', her: 'her', light: 'light', dark: 'dark' }[theme] || 'dark';
            }

            // Re-fetch Open WebUI's shared /static/custom.css stylesheet.
            //
            // That file is composed per request from every plugin's fragment
            // plus whatever the admin wrote there by hand, and this function's
            // share of it is the flash-free subset: the palette variables and
            // custom CSS. While a theme is active that does not matter, because
            // enforceTheme() appends owui-dev-live-theme last and wins the
            // cascade. But when the theme is switched OFF there is no live
            // element left to override it, and the <link> keeps the last
            // content the browser fetched — so the palette stays applied until
            // a full page load. On a phone PWA that can be a very long time.
            //
            // The link cannot simply be removed: it belongs to Open WebUI and
            // carries other plugins' fragments. Re-pointing it at the same path
            // with a cache-busting query re-fetches the freshly composed file,
            // which no longer contains this plugin's block while preserving
            // everyone else's.
            function refreshSharedCustomCss() {
                try {
                    var links = document.querySelectorAll('link[rel="stylesheet"]');
                    for (var i = 0; i < links.length; i++) {
                        var href = links[i].getAttribute('href') || '';
                        if (href.indexOf('/static/custom.css') !== 0) continue;
                        // The new copy arrives with the instance block back in
                        links[i].addEventListener('load', syncInstanceSharedCss, { once: true });
                        links[i].setAttribute('href', '/static/custom.css?_t=' + Date.now());
                        return;
                    }
                } catch(x) {}
            }

            // /static/custom.css gives every page the instance theme's colors
            // and custom CSS for a first paint without a flash, inside an
            // @supports block the server marks with --tdp-instance. Where the
            // instance theme doesn't belong, this page's copy of that block is
            // removed (the file itself is untouched) and put back when it does:
            // a signed-in user's personal theme replaces it, a sign-in page
            // whose mode hides the colors or the custom CSS, and an app page
            // whose mode shows them only on sign-in pages, get only what's
            // allowed there, from the CSS enforceTheme() assembles.
            function instanceSharedCssWanted() {
                if (_personal) return false;
                var st = getParsedState();
                var c = st && st[themeToMode(localStorage.getItem('theme') || 'dark')];
                if (!c) return true;
                if (window.location.pathname.startsWith('/auth')) {
                    return !(c.themeShowAuth === false || c.customCssShowAuth === false);
                }
                return !(c.themeAuthOnly === true || c.customCssAuthOnly === true);
            }
            function syncInstanceSharedCss() {
                var want = instanceSharedCssWanted();
                var links = document.querySelectorAll('link[rel="stylesheet"]');
                for (var i = 0; i < links.length; i++) {
                    var link = links[i];
                    if ((link.getAttribute('href') || '').indexOf('/static/custom.css') !== 0) continue;
                    var sheet = link.sheet, rules = null;
                    try { rules = sheet && sheet.cssRules; } catch(x) {}
                    if (!rules) {
                        // Not loaded yet: check again once it is
                        link.addEventListener('load', syncInstanceSharedCss, { once: true });
                        continue;
                    }
                    if (!want && !sheet.__tdpInstanceOff) {
                        for (var r = 0; r < rules.length; r++) {
                            if ((rules[r].conditionText || '').indexOf('--tdp-instance') === -1) continue;
                            sheet.__tdpInstanceOff = { index: r, text: rules[r].cssText };
                            try { sheet.deleteRule(r); } catch(x) { sheet.__tdpInstanceOff = null; }
                            break;
                        }
                    } else if (want && sheet.__tdpInstanceOff) {
                        var off = sheet.__tdpInstanceOff;
                        sheet.__tdpInstanceOff = null;
                        try { sheet.insertRule(off.text, Math.min(off.index, rules.length)); } catch(x) {}
                    }
                }
            }

            var _refreshPending = false;
            // Tells the Themes tabs in Settings which theme this page shows:
            // the signed-in user's own ('personal'), the instance theme
            // ('instance') or none (''), so they can mark the one in use
            function announceThemeSource() {
                var src = _disabled ? '' : _personal ? 'personal' : (_owuiThemeCss ? 'instance' : '');
                if (window.__owuiThemeSource === src) return;
                window.__owuiThemeSource = src;
                try { window.dispatchEvent(new Event('owui-theme-source')); } catch(x) {}
            }
            function enforceTheme() {
                announceThemeSource();
                syncHiddenBackgrounds();
                if (_disabled) { _rootModeSet = rootMode(); return; }
                const savedCss = _owuiThemeCss || localStorage.getItem('owui_dev_theme_v1_css');
                if (savedCss) {
                    // Legacy cleanup only. Pre-registry builds wrote a stale CSS
                    // subset into index.html as <style id="owui-server-theme">,
                    // which could outlive a save and fight the full live CSS.
                    // The server strips it once on startup and the safe subset
                    // now ships via /static/custom.css (composed per request, so
                    // never stale), leaving this a no-op on current installs.
                    var serverStyle = document.getElementById('owui-server-theme');
                    if (serverStyle) serverStyle.remove();

                    let style = document.getElementById('owui-dev-live-theme');
                    if (!style) {
                        style = document.createElement('style');
                        style.id = 'owui-dev-live-theme';
                        document.head.appendChild(style);
                    }
                    
                    // Sanitize: strip any stale body::before rules from cached CSS (legacy hue-rotate feature).
                    // Kept until the CSS changes: this runs on every refresh.
                    if (savedCss !== _strippedFrom) {
                        _strippedFrom = savedCss;
                        _strippedCss = savedCss.replace(/[^{}]*body\s*::before\s*\{[^}]*\}/g, '');
                    }
                    let finalCss = _strippedCss;
                    const isAuthPage = window.location.pathname.startsWith('/auth');

                    // Palette vars for disabled modes are emitted as defaults
                    // by generateCoreCSS(), so no bootloader stripping needed.
                    var parsedState = getParsedState();

                    if (parsedState) {
                        const mode = themeToMode(localStorage.getItem('theme') || 'dark');
                        const config = parsedState[mode];
                        // Sign-in pages show what Show on Auth Pages allows; app
                        // pages leave out what's Only on Auth Pages. A personal
                        // theme never reaches sign-in pages, so it shows it all.
                        const authOnly = !!config && !_personal && !isAuthPage &&
                            (config.themeAuthOnly === true || config.customCssAuthOnly === true ||
                             config.canvasAuthOnly === true || config.gradientAuthOnly === true);
                        if (isAuthPage || authOnly) {
                            try {
                                if (config) {
                                    var vis = isAuthPage ? {
                                        theme: config.themeShowAuth !== false, custom: config.customCssShowAuth !== false,
                                        canvas: config.canvasShowAuth !== false, gradient: config.gradientShowAuth !== false
                                    } : {
                                        theme: config.themeAuthOnly !== true, custom: config.customCssAuthOnly !== true,
                                        canvas: config.canvasAuthOnly !== true, gradient: config.gradientAuthOnly !== true
                                    };
                                    // A background hidden here leaves Open WebUI's panels
                                    // opaque: its clearing goes, the rest of structural stays
                                    var shown = { CANVAS: vis.canvas && config.canvasEnabled !== false, GRADIENT: vis.gradient };
                                    var dropHiddenClearing = function(css) {
                                        return css.replace(/\/\*\[OWUI_CLEAR_(CANVAS_GRADIENT|CANVAS|GRADIENT)_START\]\*\/[\s\S]*?\/\*\[OWUI_CLEAR_\1_END\]\*\//g, function(block, kinds) {
                                            return kinds.split('_').some(function(k) { return shown[k]; }) ? block : '';
                                        });
                                    };
                                    var sec = parsedState._cssSections;
                                    if (sec && typeof sec.vars === 'string') {
                                        // Structured sections (merged into state.json by the
                                        // server at delivery time): assemble only the sections
                                        // allowed on auth pages — no regex-slicing needed.
                                        var parts = [];
                                        if (vis.theme) parts.push(sec.vars);
                                        if (vis.canvas || vis.gradient) parts.push(dropHiddenClearing(sec.structural || ''));
                                        if (vis.gradient) parts.push(sec.gradient || '');
                                        if (vis.custom) parts.push(sec.custom || '');
                                        parts.push(sec.extra || ''); // valve-appended rules — never auth-gated
                                        // Re-apply the body::before sanitizer (assembly replaced finalCss)
                                        finalCss = parts.join('').replace(/[^{}]*body\s*::before\s*\{[^}]*\}/g, '');
                                    } else {
                                        // Legacy fallback: saved theme predates structured
                                        // sections — regex-strip the flat CSS by markers.
                                        if (!vis.theme) {
                                            finalCss = finalCss.replace(/\/\*\[OWUI_VARS_START\]\*\/[\s\S]*?\/\*\[OWUI_VARS_END\]\*\//g, '');
                                        }
                                        if (!vis.custom) {
                                            finalCss = finalCss.replace(/\/\*\[OWUI_CUSTOM_START\]\*\/[\s\S]*?\/\*\[OWUI_CUSTOM_END\]\*\//g, '');
                                        }
                                        if (!vis.canvas && !vis.gradient) {
                                            finalCss = finalCss.replace(/\/\*\[OWUI_STRUCTURAL_START\]\*\/[\s\S]*?\/\*\[OWUI_STRUCTURAL_END\]\*\//g, '');
                                        }
                                        if (!vis.gradient) {
                                            finalCss = finalCss.replace(/\/\*\[OWUI_GRADIENT_START\]\*\/[\s\S]*?\/\*\[OWUI_GRADIENT_END\]\*\//g, '');
                                        }
                                        finalCss = finalCss.replace(/\/\*\[OWUI_STRUCTURAL_START\]\*\/[\s\S]*?\/\*\[OWUI_STRUCTURAL_END\]\*\//g, dropHiddenClearing);
                                    }
                                }
                            } catch(e) { console.warn('Theme Pro:', e); }
                        }
                    }
                    
                    if (style.textContent !== finalCss) style.textContent = finalCss;
                }
                
                const storedTheme = localStorage.getItem('theme');
                if (storedTheme) {
                    if (document.documentElement.getAttribute('data-theme') !== storedTheme) {
                        document.documentElement.setAttribute('data-theme', storedTheme);
                    }
                    const html = document.documentElement;
                    const currentTheme = storedTheme === 'system' ? (window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light') : storedTheme;
                    const classMap = { dark: 'dark', 'oled-dark': 'dark', her: 'her', light: 'light' };
                    const target = classMap[currentTheme];
                    if (target) {
                        if (!html.classList.contains(target)) html.classList.add(target);
                        // Only classes it has: removing an absent one still
                        // counts as a class change
                        ['dark', 'light', 'her'].filter(c => c !== target && html.classList.contains(c)).forEach(c => html.classList.remove(c));
                    }
                }
                _rootModeSet = rootMode();
                // Some paths start the canvas before this applies the CSS
                pushCanvasTheme();
                syncInstanceSharedCss();
            }
            
            // Exact token counts for context-aware Canvas FX, read from the
            // usage in Open WebUI's Socket.IO frames and passed on as an
            // 'owui-canvas-context' event. Open WebUI exposes no socket, and
            // engine.io-client keeps the WebSocket constructor it found when
            // its module loaded, which can be before this script runs. So the
            // hook goes on the prototype's send: a socket is heard from its
            // next send on, and Open WebUI's socket sends every second while a
            // reply streams. The patch can't be taken back out from under
            // other wrappers, so it stays, idle while no script reads context.
            function onUsageFrame(evt) {
                if (!window._owuiContextReaders) return;
                try {
                    // Socket.IO v4 packets look like '42["events",{...}]'
                    var raw = typeof evt.data === 'string' ? evt.data : '';
                    if (raw.indexOf('"usage"') === -1) return;
                    var jsonStart = raw.indexOf('[');
                    if (jsonStart === -1) return;
                    var arr = JSON.parse(raw.slice(jsonStart));
                    if (!Array.isArray(arr) || arr.length < 2 || !arr[1]) return;
                    var payload = arr[1];
                    // Open WebUI's own filters: frames for every saved chat of
                    // the account reach every tab, and the chat's room sends this
                    // user's other tabs a shared copy as well. A temporary
                    // chat's frames go to its own tab only. A chat started from
                    // / or a folder gets its /c/ address only after the reply's
                    // first frames, which Open WebUI matches by message.
                    if (payload.shared && String(payload.user_id) === tokenUserId()) return;
                    var chatId = payload.chat_id;
                    if (chatId && !/^(temporary|local):/.test(chatId)) {
                        var path = location.pathname.split('/');
                        if (path[1] === 'c' ? decodeURIComponent(path[2] || '') !== chatId
                            : !document.getElementById('message-' + payload.message_id)) return;
                    }
                    // chat:completion nests it at payload.data.data.usage
                    var obj = payload, usage = null;
                    for (var depth = 0; obj && typeof obj === 'object' && depth < 4; depth++, obj = obj.data) {
                        var u = obj.usage;
                        if (u && typeof u === 'object' && (u.total_tokens || u.prompt_tokens || u.completion_tokens || u.input_tokens || u.output_tokens)) { usage = u; break; }
                    }
                    if (!usage) return;
                    var prompt = usage.prompt_tokens || usage.input_tokens || 0;
                    var completion = usage.completion_tokens || usage.output_tokens || 0;
                    window.dispatchEvent(new CustomEvent('owui-canvas-context', {
                        detail: { exactTokens: usage.total_tokens || (prompt + completion), promptTokens: prompt, completionTokens: completion, source: 'socket' }
                    }));
                } catch (x) {}
            }
            function hookSocketUsage() {
                if (window._owuiTokenInterceptor || !window.WebSocket) return;
                window._owuiTokenInterceptor = true;
                var proto = window.WebSocket.prototype;
                var nativeSend = proto.send;
                var heard = new WeakSet();
                proto.send = function() {
                    try {
                        if (!heard.has(this)) { heard.add(this); this.addEventListener('message', onUsageFrame); }
                    } catch (x) {}
                    return nativeSend.apply(this, arguments);
                };
            }

            // Whether a Canvas FX script handles { type: 'context' } messages:
            // it names the string 'context' outside comments (getContext
            // doesn't count). The designer's Context badge uses the same test.
            function readsContext(script) {
                return /['"`]context['"`]/.test(script.replace(/\/\*[\s\S]*?\*\//g, '').replace(/(^|\s)\/\/.*$/gm, '$1'));
            }

            // Open WebUI fires nothing once a page has rendered, and a chat's
            // markup mounts only after its messages load, so a look at the page
            // right after a route change can come too early. check() runs now
            // and again on this schedule after each navigation, then rests until
            // the next one; a page slower than that to render is picked up then.
            var ROUTE_RECHECK_MS = [400, 1500, 4000, 10000];
            function watchRoutes(check) {
                var timers = [];
                function run() {
                    timers.forEach(clearTimeout);
                    check();
                    timers = ROUTE_RECHECK_MS.map(function(ms) { return setTimeout(check, ms); });
                }
                window.addEventListener('owui-tdp-route', run);
                window.addEventListener('popstate', run);
                run();
                return function() {
                    timers.forEach(clearTimeout);
                    window.removeEventListener('owui-tdp-route', run);
                    window.removeEventListener('popstate', run);
                };
            }

            // Context observer for Canvas FX — watches chat DOM for message
            // count/size and sends periodic { type: 'context' } updates to the
            // Canvas FX Worker/handler. Enables context-aware animations.
            function startContextObserver(sendFn) {
                var _observer = null;
                var _scanTimer = 0;
                var _lastChars = -1;
                var _lastMsgCount = -1;
                var _watched = null;  // the #messages-container being observed
                var _paneObserver = null;
                var _pane = null;  // the #chat-pane watched until a container mounts
                hookSocketUsage();
                window._owuiContextReaders = (window._owuiContextReaders || 0) + 1;

                // Custom event API — any Open WebUI plugin/extension can dispatch
                // window.dispatchEvent(new CustomEvent('owui-canvas-context', { detail: { ratio: 0.65, ... } }))
                var _onCustom = function(e) {
                    if (e.detail) sendFn(Object.assign({ type: 'context' }, e.detail));
                };
                window.addEventListener('owui-canvas-context', _onCustom);

                function report(msgCount, totalChars) {
                    if (totalChars === _lastChars && msgCount === _lastMsgCount) return;
                    _lastChars = totalChars;
                    _lastMsgCount = msgCount;
                    sendFn({
                        type: 'context',
                        messages: msgCount,
                        chars: totalChars,
                        estimatedTokens: Math.ceil(totalChars / 4)
                    });
                }

                function scan() {
                    if (!_watched) return;
                    // One of these per message. The message-* ids also name a
                    // message's edit box, sibling picker and rating form.
                    var messageEls = _watched.querySelectorAll('.chat-user, .chat-assistant');
                    var totalChars = 0;
                    messageEls.forEach(function(el) {
                        totalChars += (el.textContent || '').length;
                    });
                    report(messageEls.length, totalChars);
                }

                // Another chat or New Chat replaces the container; a page
                // without a chat has none. On / the container mounts with the
                // first message, and a temporary chat's first message changes
                // no address, so the pane is watched until it does.
                function retarget() {
                    var current = document.getElementById('messages-container');
                    var pane = current ? null : document.getElementById('chat-pane');
                    if (pane !== _pane) {
                        if (_paneObserver) _paneObserver.disconnect();
                        _pane = pane;
                        if (pane) {
                            _paneObserver = _paneObserver || new MutationObserver(retarget);
                            _paneObserver.observe(pane, { childList: true });
                        }
                    }
                    if (current === _watched) return;
                    if (_observer) { _observer.disconnect(); _observer = null; }
                    _watched = current;
                    if (!current) {
                        report(0, 0);
                        return;
                    }
                    // Scan at most every 2s, during a streaming reply too: a change
                    // starts the timer only when none is running, so a steady
                    // stream of changes can't keep pushing the scan back.
                    _observer = new MutationObserver(function() {
                        if (_scanTimer) return;
                        _scanTimer = setTimeout(function() { _scanTimer = 0; scan(); }, 2000);
                    });
                    _observer.observe(current, { childList: true, subtree: true, characterData: true });
                    scan();
                }
                var _stopRouteWatch = watchRoutes(retarget);

                return function() {
                    _stopRouteWatch();
                    window._owuiContextReaders--;
                    window.removeEventListener('owui-canvas-context', _onCustom);
                    if (_observer) _observer.disconnect();
                    if (_paneObserver) _paneObserver.disconnect();
                    clearTimeout(_scanTimer);
                };
            }

            let lastCanvasScript = null;
            let lastCanvasWasEnabled = null;
            var _canvasGeneration = 0;
            // Palette channel for Canvas FX. A script gets the active mode's
            // colors with 'init' (as e.data.theme) and again as a { type:
            // 'theme' } message whenever they change: a mode switch, a theme
            // update, or a palette edit in the designer. A script that does
            // not handle it never notices, so every existing script keeps
            // drawing in its own colors.
            var _canvasThemeSend = null, _lastCanvasTheme = '', _paletteCtx = null;
            function _colorToRgb(value) {
                if (!_paletteCtx) {
                    var c = document.createElement('canvas');
                    c.width = c.height = 1;
                    _paletteCtx = c.getContext('2d', { willReadFrequently: true });
                }
                var g = _paletteCtx;
                g.clearRect(0, 0, 1, 1);
                g.fillStyle = '#808080';
                g.fillStyle = value;
                g.fillRect(0, 0, 1, 1);
                var d = g.getImageData(0, 0, 1, 1).data;
                return [d[0], d[1], d[2]];
            }
            // The same function builds the payload on the website's previews
            function buildCanvasTheme(readVar, toRgb, mode, hue, chroma, set) {
                var dark = mode === 'dark' || mode === 'oled';
                var hex = function(c) { return '#' + c.map(function(v) { return (v < 16 ? '0' : '') + v.toString(16); }).join(''); };
                var ramp = {}, rampRgb = {};
                [50, 100, 200, 300, 400, 500, 600, 700, 800, 850, 900, 950].forEach(function(s) {
                    rampRgb[s] = toRgb(readVar('--color-gray-' + s) || '#808080');
                    ramp[s] = hex(rampRgb[s]);
                });
                // Accents in the theme's hue, as colorful as the theme itself
                var ac = chroma > 0 ? Math.min(0.18, Math.max(0.06, chroma / 250)) : 0;
                var al = dark ? 0.74 : 0.56;
                var accent = function(dh) { return toRgb('oklch(' + al + ' ' + ac.toFixed(3) + ' ' + ((hue + dh + 360) % 360).toFixed(1) + ')'); };
                // A theme can set its own accents as '#rrggbb'. Checked again
                // here: the state can come from an older build or be edited.
                var pick = function(k, dh) {
                    var v = set && set[k];
                    return typeof v === 'string' && /^#[0-9a-fA-F]{6}$/.test(v) ? toRgb(v.toLowerCase()) : accent(dh);
                };
                var src = {
                    background: rampRgb[dark ? 900 : 50], surface: rampRgb[dark ? 850 : 100],
                    text: rampRgb[dark ? 100 : 900], muted: rampRgb[dark ? 400 : 500],
                    accent: pick('accent', 0), accent2: pick('accent2', 40), accent3: pick('accent3', -40)
                };
                var colors = {}, rgb = {};
                Object.keys(src).forEach(function(k) {
                    colors[k] = hex(src[k]);
                    rgb[k] = src[k].map(function(v) { return Math.round(v / 2.55) / 100; });
                });
                return { type: 'theme', mode: mode, dark: dark, hue: hue, chroma: chroma / 1000, colors: colors, rgb: rgb, ramp: ramp };
            }
            function canvasTheme(mode, config) {
                var hue = Number(config.h) || 0;
                var chroma = config.paletteEnabled === false ? 0 : (Number(config.c) || 0);
                var cs = getComputedStyle(document.documentElement);
                return buildCanvasTheme(function(name) { return cs.getPropertyValue(name).trim(); }, _colorToRgb, mode, hue, chroma, config);
            }
            function pushCanvasTheme() {
                if (!_canvasThemeSend) return;
                var mode = themeToMode(document.documentElement.getAttribute('data-theme') || 'dark');
                var config = (getParsedState() || {})[mode] || {};
                // A mode with another script gets its palette with that script's init
                if (!config.canvasEnabled || config.canvasScript !== lastCanvasScript) return;
                var t;
                try { t = canvasTheme(mode, config); } catch(x) { return; }
                var key = JSON.stringify(t);
                if (key === _lastCanvasTheme) return;
                _lastCanvasTheme = key;
                _canvasThemeSend(t);
            }

            // The chat column, as the input pill shows it: its center and width in
            // CSS pixels, plus the left and right edges of the chat area around it
            // (the sidebar excluded), or null on a page without one. With the
            // sidebar open the column sits right of the screen's center.
            // Widescreen mode stretches the pill across the whole chat area, which
            // would calm the entire scene, so the column counts as no wider than
            // Open WebUI's usual 58rem. A window too narrow for margins would calm
            // it all the same, so the column then narrows until the calm band
            // (half the width plus 56 px, fading out by 1.2 times that, as the
            // house standard draws it) ends a strip short of each edge.
            function _columnLayout() {
                var el = document.getElementById('message-input-container');
                if (!el) return null;
                var r = el.getBoundingClientRect();
                if (r.width < 50) return null;
                var pane = document.getElementById('chat-container');
                var p = pane ? pane.getBoundingClientRect() : null;
                var left = p && p.width > r.width ? Math.max(0, Math.round(p.left)) : 0;
                var right = p && p.width > r.width ? Math.min(window.innerWidth, Math.round(p.right)) : window.innerWidth;
                var cap = 58 * (parseFloat(getComputedStyle(document.documentElement).fontSize) || 16);
                var x = Math.round(r.left + r.width / 2), width = Math.min(r.width, cap);
                var room = Math.min(x - left, right - x), clear = Math.max(56, (right - left) * 0.08);
                var fit = 2 * ((room - clear) / 1.2 - 56);
                if (width > fit) width = Math.max(Math.min(width, 320), fit);
                return { x: x, width: Math.round(width), left: left, right: right };
            }

            function _prefersReducedMotion() {
                return !!(window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches);
            }

            // A Canvas FX script a chat model wrote: the Theme Designer Pro Launcher
            // marks its first line. It runs in a sandboxed frame with no origin (so
            // no cookies or storage) and a policy that allows no requests, so it can
            // draw and nothing else. The frame is the background layer: it makes its
            // own canvas and worker, since Chrome can't hand a canvas to a frame
            // without an origin, and the page passes the usual messages through.
            const ISOLATED_MARK = '/* tdp:isolated */';
            function _isolatedWorker(source, canvas) {
                const relay = function () {
                    var worker = null, queue = [];
                    function deliver(d, transfer) {
                        if (d && d.type === 'init' && !d.canvas) {
                            var c = document.createElement('canvas');
                            c.width = d.width || innerWidth; c.height = d.height || innerHeight;
                            c.style.cssText = 'position:fixed;inset:0;width:100%;height:100%;display:block';
                            document.body.appendChild(c);
                            d.canvas = c.transferControlToOffscreen();
                            transfer = [d.canvas];
                        }
                        worker.postMessage(d, transfer || []);
                    }
                    addEventListener('message', function (e) {
                        if (e.source !== parent || !e.data) return;
                        var m = e.data;
                        if (typeof m.boot === 'string') {
                            try {
                                worker = new Worker(URL.createObjectURL(new Blob([m.boot], { type: 'application/javascript' })));
                            } catch (err) {
                                parent.postMessage({ tdpIsolatedError: String(err && err.message || err) }, '*');
                                return;
                            }
                            worker.onerror = function (ev) { ev.preventDefault(); parent.postMessage({ tdpIsolatedError: String(ev.message || 'The script failed') }, '*'); };
                            queue.forEach(function (q) { deliver(q.data, q.transfer); });
                            queue = [];
                        } else if ('data' in m) {
                            if (worker) deliver(m.data, m.transfer); else queue.push(m);
                        }
                    });
                    parent.postMessage({ tdpIsolatedReady: true }, '*');
                };
                const q = "'";
                const frame = document.createElement('iframe');
                frame.setAttribute('sandbox', 'allow-scripts');
                frame.setAttribute('aria-hidden', 'true');
                frame.tabIndex = -1;
                frame.id = canvas.id;
                // A color-scheme that differs from the frame's document makes it opaque
                frame.style.cssText = canvas.style.cssText + ';border:0;background:transparent;color-scheme:normal';
                // Built from pieces: this script is also inlined in index.html
                frame.srcdoc = '<meta http-equiv="Content-Security-Policy" content="default-src ' + q + 'none' + q +
                    '; script-src ' + q + 'unsafe-inline' + q + ' blob:; worker-src blob:; style-src ' + q + 'unsafe-inline' + q + '">' +
                    '<style>html,body{margin:0;background:transparent;overflow:hidden}</style>' +
                    '<scr' + 'ipt>(' + relay.toString() + ')();</scr' + 'ipt>';
                const proxy = { onerror: null };
                let ready = false, pending = [], lastInit = null, lastTheme = null;
                const send = function (m) { try { frame.contentWindow.postMessage(m, '*'); } catch (x) {} };
                const onMessage = function (e) {
                    if (e.source !== frame.contentWindow || !e.data) return;
                    if (e.data.tdpIsolatedReady) {
                        // Again after a reload of the frame: start the script over where it was
                        const replay = ready ? [lastInit, lastTheme].filter(Boolean) : pending;
                        ready = true;
                        send({ boot: source });
                        replay.forEach(send);
                        pending = [];
                    } else if (typeof e.data.tdpIsolatedError === 'string' && proxy.onerror) {
                        proxy.onerror({ message: e.data.tdpIsolatedError, preventDefault: function () {} });
                    }
                };
                window.addEventListener('message', onMessage);
                proxy.postMessage = function (data) {
                    const m = { data: data };
                    if (data && data.type === 'init') lastInit = m;
                    else if (data && data.type === 'theme') lastTheme = m;
                    if (ready) send(m); else pending.push(m);
                };
                proxy.terminate = function () {
                    window.removeEventListener('message', onMessage);
                    // Removing the frame ends its worker
                    frame.remove();
                };
                canvas.replaceWith(frame);
                return proxy;
            }

            // Keeps going past a cleanup that throws: a main-thread script can
            // register its own. Leaves owui-tdp-hidden-bg, which holds the
            // Backgrounds tab's rules and outlives any one canvas.
            function teardownCanvas() {
                if (window.owuiCanvasCleanups) {
                    window.owuiCanvasCleanups.forEach(function(fn) { try { fn(); } catch(x) {} });
                    window.owuiCanvasCleanups = [];
                }
                ['owui-theme-canvas-bg', 'owui-canvas-script-runner', 'owui-theme-bg-color'].forEach(function(id) {
                    var el = document.getElementById(id);
                    if (el) el.remove();
                });
            }

            // Forwards the page's pointer, touch and resize input to a running
            // canvas script and returns what stops it. send() returns false
            // while the script has no handler yet, which keeps a move for the
            // next frame. ownCanvas is the canvas to resize on this thread, if
            // the script draws on it here; onFrame runs on every page frame.
            function bridgeCanvasInput(send, ownCanvas, onFrame) {
                // mousemove fires at 120Hz+ on high-refresh displays: moves
                // are sent once per animation frame
                let _mouseX = -9999, _mouseY = -9999, _mouseDirty = false;
                const _onMouse = (e) => { _mouseX = e.clientX; _mouseY = e.clientY; _mouseDirty = true; };

                // Debounced, so a worker doesn't re-allocate its buffers dozens
                // of times during a drag-resize
                let _resizeTimer = 0;
                const _onResize = () => {
                    clearTimeout(_resizeTimer);
                    _resizeTimer = setTimeout(() => {
                        if (ownCanvas) { ownCanvas.width = window.innerWidth; ownCanvas.height = window.innerHeight; }
                        send({ type: 'resize', width: window.innerWidth, height: window.innerHeight, dpr: window.devicePixelRatio || 1 });
                    }, 150);
                };
                // Child iframes forward their mousemove, which can't bubble to this window
                const _onIframeMsg = (e) => {
                    if (!e.data || e.data.type !== 'owui-canvas-mousemove') return;
                    // Any frame can post this, including Open WebUI's sandboxed
                    // iframes (artifacts, HTML previews) whose origin is "null",
                    // so no origin allowlist can gate it. Only finite numbers
                    // pass: anything else reaches the script as coordinates, and
                    // a non-cloneable value throws in worker.postMessage() on
                    // every frame. typeof, not Number(): coercing a Symbol or an
                    // object with a throwing valueOf raises in this listener.
                    const mx = e.data.x, my = e.data.y;
                    if (typeof mx !== 'number' || typeof my !== 'number') return;
                    if (!isFinite(mx) || !isFinite(my)) return;
                    _mouseX = mx; _mouseY = my; _mouseDirty = true;
                };

                // Clicks and touch start/end are discrete and sent at once;
                // touchmove is sent once per frame like mousemove
                const _sendPoint = (type, e) => { send({ type: type, x: e.clientX, y: e.clientY }); };
                const _onClick = (e) => _sendPoint('click', e);
                const _onMouseDown = (e) => _sendPoint('mousedown', e);
                const _onMouseUp = (e) => _sendPoint('mouseup', e);
                const _touchCoords = (list) => Array.from(list).map(t => ({ x: t.clientX, y: t.clientY }));
                let _touchDirty = false, _touchData = [];
                const _onTouchStart = (e) => {
                    var c = _touchCoords(e.touches);
                    send({ type: 'touchstart', touches: c });
                    if (c.length > 0) send({ type: 'mousedown', x: c[0].x, y: c[0].y });
                };
                const _onTouchMove = (e) => {
                    _touchData = _touchCoords(e.touches);
                    _touchDirty = true;
                    if (_touchData.length > 0) { _mouseX = _touchData[0].x; _mouseY = _touchData[0].y; _mouseDirty = true; }
                };
                const _onTouchEnd = (e) => {
                    var c = _touchCoords(e.changedTouches);
                    send({ type: 'touchend', touches: c });
                    if (c.length > 0) send({ type: 'mouseup', x: c[0].x, y: c[0].y });
                };

                window.addEventListener('mousemove', _onMouse);
                window.addEventListener('resize', _onResize);
                window.addEventListener('message', _onIframeMsg);
                window.addEventListener('click', _onClick, true);
                window.addEventListener('mousedown', _onMouseDown, true);
                window.addEventListener('mouseup', _onMouseUp, true);
                let _inputRaf = 0;
                (function _sendInput() {
                    _inputRaf = requestAnimationFrame(_sendInput);
                    if (onFrame) onFrame();
                    if (_mouseDirty && send({ type: 'mousemove', x: _mouseX, y: _mouseY }) !== false) _mouseDirty = false;
                    if (_touchDirty && send({ type: 'touchmove', touches: _touchData }) !== false) _touchDirty = false;
                })();
                window.addEventListener('touchstart', _onTouchStart, { passive: true });
                window.addEventListener('touchmove', _onTouchMove, { passive: true });
                window.addEventListener('touchend', _onTouchEnd, { passive: true });

                return () => {
                    window.removeEventListener('mousemove', _onMouse);
                    window.removeEventListener('resize', _onResize);
                    window.removeEventListener('message', _onIframeMsg);
                    window.removeEventListener('click', _onClick, true);
                    window.removeEventListener('mousedown', _onMouseDown, true);
                    window.removeEventListener('mouseup', _onMouseUp, true);
                    window.removeEventListener('touchstart', _onTouchStart);
                    window.removeEventListener('touchmove', _onTouchMove);
                    window.removeEventListener('touchend', _onTouchEnd);
                    cancelAnimationFrame(_inputRaf);
                    clearTimeout(_resizeTimer);
                };
            }

            function initCanvas(forceFallback) {
                // Bumped only where a canvas is torn down or started below: a
                // call that changes nothing must not make a starting canvas's
                // Worker-error fallback think it's stale
                var myGen = _canvasGeneration;
                try {
                    var savedData = getParsedState();
                    if (!savedData || Object.keys(savedData).length === 0) {
                        // No theme left (turned off while this page slept, or
                        // removed): a canvas still running belongs to the old one
                        if (lastCanvasWasEnabled || document.getElementById('owui-theme-canvas-bg')) {
                            myGen = ++_canvasGeneration;
                            teardownCanvas();
                            lastCanvasScript = null;
                            lastCanvasWasEnabled = false;
                        }
                        return;
                    }
                    const mode = themeToMode(document.documentElement.getAttribute('data-theme') || 'dark');
                    const config = savedData[mode];
                    
                    const isAuthPage = window.location.pathname.startsWith('/auth');
                    const canvasHidden = !!config && (isAuthPage ? config.canvasShowAuth === false
                        : (config.canvasAuthOnly === true && !_personal));
                    if (canvasHidden) {
                        myGen = ++_canvasGeneration;
                        teardownCanvas();
                        lastCanvasScript = "_AUTH_HIDDEN_";
                        lastCanvasWasEnabled = false;
                        return;
                    }
                    
                    const existingCanvas = document.getElementById('owui-theme-canvas-bg');
                    const isCanvasExpected = config && config.canvasEnabled && config.canvasScript && config.canvasScript.trim() !== '';
                    
                    if (!forceFallback && config && lastCanvasScript === config.canvasScript && lastCanvasWasEnabled === isCanvasExpected) {
                        // Same script: a mode switch or palette edit only recolors it
                        if (!isCanvasExpected || existingCanvas) { pushCanvasTheme(); return; }
                    }

                    myGen = ++_canvasGeneration;
                    teardownCanvas();
                    
                    if (config && config.canvasEnabled && config.canvasScript) {
                        lastCanvasScript = config.canvasScript;
                        lastCanvasWasEnabled = true;
                        
                        const bg = document.createElement('div');
                        bg.id = 'owui-theme-bg-color';
                        bg.style = 'position: fixed; top: 0; left: 0; width: 100vw; height: 100vh; z-index: -2; pointer-events: none;';
                        document.body.prepend(bg);

                        const canvas = document.createElement('canvas');
                        canvas.id = 'owui-theme-canvas-bg';
                        canvas.width = window.innerWidth;
                        canvas.height = window.innerHeight;
                        canvas.style = 'position: fixed; top: 0; left: 0; width: 100vw; height: 100vh; z-index: 0; pointer-events: none;';
                        document.body.prepend(canvas);
                        
                        window.owuiCanvasCleanups = window.owuiCanvasCleanups ||[];
                        // Pre-detect scripts that reference `document` — they'll always
                        // throw ReferenceError in a Worker. Skip straight to fallback
                        // to avoid async onerror race with rapid initCanvas() calls.
                        // Comments don't count: the README's own skeleton ends with
                        // "// NO DOM access (no document, ...)", which sent every
                        // script that kept it to the main thread.
                        const _scriptNeedsDOM = /\bdocument\b/.test(config.canvasScript.replace(/\/\*[\s\S]*?\*\//g, '').replace(/(^|\s)\/\/.*$/gm, '$1'));
                        const _isolated = config.canvasScript.startsWith(ISOLATED_MARK);
                        // With the Calm Chat Column valve off, the script's Center Calm
                        // setting counts as 0, so nothing fades behind the chat
                        const _script = __CALM_CHAT_COLUMN__ ? config.canvasScript : config.canvasScript.replace(/^(\s*const\s+CENTER_CALM\s*=\s*)[0-9.]+/m, function (m, head) { return head + '0'; });
                        const useWorker = !forceFallback && (_isolated || !_scriptNeedsDOM) && !!canvas.transferControlToOffscreen;
                        let _canvasSend = null;
                        let _initTheme = null;
                        try { _initTheme = canvasTheme(mode, config); } catch(x) {}
                        _lastCanvasTheme = _initTheme ? JSON.stringify(_initTheme) : '';
                        
                        if (useWorker) {
                            // REAL WORKER MODE (OffscreenCanvas)
                            // Firefox keeps running a worker's frames while the page gets none,
                            // and hands the whole backlog to the GPU when it returns, enough to
                            // fill RAM. This runs ahead of the script and holds its frame
                            // requests meanwhile. One line, so the script's line numbers hold.
                            const _framePause = [
                                '(function () {',
                                'var raf = self.requestAnimationFrame, caf = self.cancelAnimationFrame;',
                                'if (!raf) return;',
                                'var hold = false, next = 0, frames = new Map();',
                                'function ask(id, f) { f.n = raf.call(self, function (t) { frames.delete(id); f.cb(t); }); }',
                                'self.requestAnimationFrame = function (cb) { var id = ++next, f = { cb: cb, n: 0 }; frames.set(id, f); if (!hold) ask(id, f); return id; };',
                                'self.cancelAnimationFrame = function (id) { var f = frames.get(id); if (!f) return; frames.delete(id); if (f.n) caf.call(self, f.n); };',
                                'self.addEventListener("message", function (e) {',
                                'if (!e.data || e.data.type !== "owui-hold-frames") return;',
                                'e.stopImmediatePropagation();',
                                'hold = !!e.data.hold;',
                                'frames.forEach(function (f, id) { if (hold && f.n) { caf.call(self, f.n); f.n = 0; } else if (!hold && !f.n) ask(id, f); });',
                                '});',
                                '})();'
                            ].join(' ');
                            const blob = new Blob([_framePause, _script], { type: 'application/javascript' });
                            const objectURL = URL.createObjectURL(blob);
                            const worker = _isolated ? _isolatedWorker(_framePause + _script, canvas) : new Worker(objectURL);
                            let workerFailed = false;
                            // The page gets no frames while hidden, and also while its window is
                            // covered, which Firefox still reports as visible. Timers keep running
                            // then, so a stale page frame is what holds the worker's frames.
                            let _lastPageFrame = performance.now(), _framesHeld = null;
                            const _syncFrames = () => {
                                const hold = document.visibilityState === 'hidden' || performance.now() - _lastPageFrame > 500;
                                if (hold === _framesHeld) return;
                                _framesHeld = hold;
                                worker.postMessage({ type: 'owui-hold-frames', hold: hold });
                            };
                            _syncFrames();
                            document.addEventListener('visibilitychange', _syncFrames);
                            const _framesTimer = setInterval(_syncFrames, 250);

                            // Fallback: if the script throws (e.g., uses `document` which Workers lack),
                            // terminate the worker and re-run via main-thread fallback mode.
                            worker.onerror = function(ev) {
                                if (workerFailed) return;
                                workerFailed = true;
                                // Stale — a newer initCanvas() already ran, don't tear down its canvas
                                if (myGen !== _canvasGeneration) return;
                                ev.preventDefault(); // Suppress console error for the re-thrown ReferenceError
                                worker.terminate();
                                URL.revokeObjectURL(objectURL);
                                teardownCanvas();
                                // A script from a chat never runs on the page itself
                                if (!_isolated) initCanvas(true); // force fallback
                            };

                            // An isolated script's frame makes its own canvas
                            const offscreen = _isolated ? null : canvas.transferControlToOffscreen();
                            
                            const _env = {
                                authToken: __CANVAS_API_ACCESS__ && !_isolated ? ((document.cookie.match(/(?:^|;\s*)token=([^;]+)/) || [])[1] || localStorage.getItem('token') || '') : '',
                                baseUrl: window.location.origin,
                                locale: navigator.language || 'en-US',
                                timezone: (function() { try { return Intl.DateTimeFormat().resolvedOptions().timeZone; } catch(e) { return ''; } })()
                            };
                            worker.postMessage({ type: 'init', canvas: offscreen, width: window.innerWidth, height: window.innerHeight, dpr: window.devicePixelRatio || 1, reducedMotion: _prefersReducedMotion(), column: _columnLayout(), env: _env, theme: _initTheme },[offscreen]);
                            
                            const _stopInput = bridgeCanvasInput((msg) => { worker.postMessage(msg); }, null, () => {
                                _lastPageFrame = performance.now();
                                if (_framesHeld) _syncFrames();
                            });

                            window.owuiCanvasCleanups.push(() => {
                                document.removeEventListener('visibilitychange', _syncFrames);
                                clearInterval(_framesTimer);
                                _stopInput();
                                worker.terminate();
                                URL.revokeObjectURL(objectURL);
                            });

                            _canvasSend = function(data) { try { worker.postMessage(data); } catch(x) {} };
                        } else if (_isolated) {
                            // Without OffscreenCanvas a script from a chat doesn't run at all
                            canvas.remove();
                            bg.remove();
                            lastCanvasScript = null;
                        } else {
                            // FALLBACK MODE (Main Thread Fake Worker)
                            const scriptEl = document.createElement('script');
                            scriptEl.id = 'owui-canvas-script-runner';
                            const nonceScript = document.querySelector('script[nonce]');
                            if (nonceScript && nonceScript.nonce) scriptEl.setAttribute('nonce', nonceScript.nonce);
                            
                            scriptEl.textContent = `
                            try {
                                (function() {
                                    const _canvas = document.getElementById('owui-theme-canvas-bg');
                                    if (!_canvas) return;
                                    
                                    // The script's self.onmessage writes _fbHandler; the window
                                    // property is how the bootloader's senders reach it
                                    let _fbHandler = null;
                                    Object.defineProperty(window, '__owuiFbHandler', {
                                        get: function() { return _fbHandler; },
                                        set: function(fn) { _fbHandler = fn; },
                                        configurable: true
                                    });

                                    // First paint isn't debounced
                                    _canvas.width = window.innerWidth; _canvas.height = window.innerHeight;
    
                                    // Only PENDING ids: a callback drops its own id as it runs.
                                    // Arrays that only grew held one id per frame forever
                                    // (~5M a day at 60fps) and teardown walked all of them.
                                    const _rAFs = new Set();
                                    const _intervals = new Set();
                                    const _timeouts = new Set();
                                    let _stopped = false;
                                    const requestAnimationFrame = (fn) => { if (_stopped) return -1; const id = window.requestAnimationFrame(t => { _rAFs.delete(id); fn(t); }); _rAFs.add(id); return id; };
                                    const cancelAnimationFrame = (id) => { _rAFs.delete(id); window.cancelAnimationFrame(id); };
                                    const setInterval = (fn, delay, ...a) => { if (_stopped) return -1; const id = window.setInterval(fn, delay, ...a); _intervals.add(id); return id; };
                                    const clearInterval = (id) => { _intervals.delete(id); window.clearInterval(id); };
                                    const setTimeout = (fn, delay, ...a) => { if (_stopped) return -1; const id = typeof fn === 'function' ? window.setTimeout(() => { _timeouts.delete(id); fn(...a); }, delay) : window.setTimeout(fn, delay); _timeouts.add(id); return id; };
                                    const clearTimeout = (id) => { _timeouts.delete(id); window.clearTimeout(id); };
                                    
                                    // A Worker's self also has addEventListener('message'),
                                    // which shipped presets use; without it the script threw
                                    // before init and the canvas stayed blank.
                                    const _fbListeners = [];
                                    const self = {
                                        postMessage: (msg) => {},
                                        set onmessage(fn) { _fbHandler = fn; },
                                        get onmessage() { return _fbHandler; },
                                        addEventListener: (t, fn) => { if (t === 'message' && typeof fn === 'function' && _fbListeners.indexOf(fn) === -1) _fbListeners.push(fn); },
                                        removeEventListener: (t, fn) => { const i = _fbListeners.indexOf(fn); if (i !== -1) _fbListeners.splice(i, 1); }
                                    };
    
                                    window.owuiCanvasCleanups.push(() => {
                                        _stopped = true;
                                        _rAFs.forEach(id => window.cancelAnimationFrame(id));
                                        _intervals.forEach(id => window.clearInterval(id));
                                        _timeouts.forEach(id => window.clearTimeout(id));
                                        _rAFs.clear(); _intervals.clear(); _timeouts.clear();
                                        // The handler's closure holds the script's context and canvas
                                        _fbHandler = null;
                                        _fbListeners.length = 0;
                                        delete window.__owuiFbHandler;
                                    });
    
                                    (function() {
                                        let onmessage = null;
                                        ${_script}
                                        const _own = onmessage || _fbHandler;
                                        const finalHandler = !_fbListeners.length ? _own : function (ev) {
                                            if (_own) _own(ev);
                                            _fbListeners.slice().forEach(function (l) { l(ev); });
                                        };
                                        if (finalHandler) {
                                            _fbHandler = finalHandler;
                                            const _fbEnv = {
                                                authToken: __CANVAS_API_ACCESS__ ? ((document.cookie.match(/(?:^|;\\s*)token=([^;]+)/) || [])[1] || localStorage.getItem('token') || '') : '',
                                                baseUrl: window.location.origin,
                                                locale: navigator.language || 'en-US',
                                                timezone: (function() { try { return Intl.DateTimeFormat().resolvedOptions().timeZone; } catch(e) { return ''; } })()
                                            };
                                            finalHandler({ data: { type: 'init', canvas: _canvas, width: window.innerWidth, height: window.innerHeight, dpr: window.devicePixelRatio || 1, reducedMotion: ${_prefersReducedMotion()}, column: ${JSON.stringify(_columnLayout())}, env: _fbEnv, theme: ${JSON.stringify(_initTheme)} } });
                                        }
                                    })();
                                })();
                            } catch(e) { console.error('Canvas FX Fallback Error:', e); }`;
                            // Before the script runs, so its own listeners come after these
                            const _stopInput = bridgeCanvasInput(function(msg) {
                                const h = window.__owuiFbHandler;
                                if (!h) return false;
                                h({ data: msg });
                            }, canvas);
                            window.owuiCanvasCleanups.push(_stopInput);
                            document.body.appendChild(scriptEl);
                            // The runner never started (the script doesn't parse, CSP
                            // blocked it, or the canvas is gone): no input for it
                            if (!Object.getOwnPropertyDescriptor(window, '__owuiFbHandler')) _stopInput();

                            // try/catch like the Worker branch: a script that throws on a
                            // message it doesn't know aborted enforceTheme()/refresh()
                            _canvasSend = function(data) { try { if (window.__owuiFbHandler) window.__owuiFbHandler({ data: data }); } catch (x) { console.warn('Canvas FX:', x); } };
                        }

                        // Start context observer — sends { type: 'context' } updates
                        // to the Canvas FX script with live chat metrics
                        if (_canvasSend) {
                            // A worker can't query media features, so the setting is sent to it
                            var _motionQuery = window.matchMedia ? window.matchMedia('(prefers-reduced-motion: reduce)') : null;
                            if (_motionQuery && _motionQuery.addEventListener) {
                                var _sendMotion = _canvasSend;
                                var _onMotion = function() { _sendMotion({ type: 'motion', reducedMotion: _motionQuery.matches }); };
                                _motionQuery.addEventListener('change', _onMotion);
                                window.owuiCanvasCleanups.push(function() { _motionQuery.removeEventListener('change', _onMotion); });
                            }
                            // The window, the sidebar and Widescreen Mode move the column by
                            // resizing the chat area or the input pill
                            var _sendLayout = _canvasSend;
                            var _lastColumn = _columnLayout();
                            var _checkColumn = function() {
                                var c = _columnLayout(), p = _lastColumn;
                                if (!c && !p) return;
                                if (c && p && Math.abs(c.x - p.x) < 3 && Math.abs(c.width - p.width) < 3 && Math.abs(c.left - p.left) < 3 && Math.abs(c.right - p.right) < 3) return;
                                _lastColumn = c;
                                _sendLayout({ type: 'layout', column: c });
                            };
                            // A temporary chat's first message swaps the input pill for
                            // another without a route change. Removing an observed
                            // element is a resize too, so each resize looks again.
                            var _columnEls = [];
                            var _watchColumn = function() {
                                var els = ['chat-container', 'message-input-container'].map(function(id) { return document.getElementById(id); });
                                if (els[0] !== _columnEls[0] || els[1] !== _columnEls[1]) {
                                    _columnEls = els;
                                    _columnObserver.disconnect();
                                    els.forEach(function(el) { if (el) _columnObserver.observe(el); });
                                }
                                _checkColumn();
                            };
                            var _columnObserver = new ResizeObserver(_watchColumn);
                            var _stopColumnWatch = watchRoutes(_watchColumn);
                            window.owuiCanvasCleanups.push(function() { _stopColumnWatch(); _columnObserver.disconnect(); });
                            if (readsContext(config.canvasScript)) window.owuiCanvasCleanups.push(startContextObserver(_canvasSend));
                            _canvasThemeSend = _canvasSend;
                            window.owuiCanvasCleanups.push(function() { _canvasThemeSend = null; _lastCanvasTheme = ''; });
                        }
                    } else {
                        lastCanvasScript = "_DISABLED_";
                        lastCanvasWasEnabled = false;
                    }
                } catch(e) {
                    lastCanvasScript = "_DISABLED_";
                    lastCanvasWasEnabled = false;
                }
            }
            
            // Open WebUI lays a model's, a folder's or the person's own Chat
            // Background Image over the chat, so over this theme's background,
            // with a dimming layer on top. The theme in use sets how much of
            // each shows, from 0 (hidden) to 100 (as Open WebUI shows it): a
            // model's image found by its address, a folder's on that folder's
            // page, the only place Open WebUI shows one, and the Chat
            // Background Image by the end of its address in this person's
            // settings. Those addresses are looked up once a page, again when
            // the server says one changed, and kept in this browser, so after
            // a reload the image fades before it shows. Each tab compares an
            // answer with what it fades itself, since another tab may have
            // answered first, and keeps fading the few addresses it faded
            // before: Open WebUI doesn't tell other tabs about a change, so
            // they show the old image until they reload. The theme can also
            // put them all behind the Canvas FX animation instead of in front
            // of it, while an animation runs.
            var MODEL_BG_KEY = 'owui_tdp_model_bg';
            // "<account> <end of its address>"
            var CHAT_BG_KEY = 'owui_tdp_chat_bg';
            var CHAT_BG = 'div.pointer-events-none.absolute.bg-cover';
            // The sign-in the lookups below were made with: a new one starts
            // them over, and without one there are none
            var _lookupsToken = null, _lookupsUid = null;
            var _modelBgLookups = Object.create(null);
            var _chatBgLookedUp = false;
            var _pageChatBgLookedUp = false;
            // What this tab fades, once it has an answer of its own
            var _modelBgSeen = Object.create(null);
            var _chatBgTail = null;
            var _earlierModelBgs = Object.create(null);
            var _earlierChatBgs = [];
            function followSignIn() {
                var uid = signedInUser(), token = null;
                try { token = uid && localStorage.getItem('token'); } catch(x) {}
                if ((token || null) === _lookupsToken) return;
                _lookupsToken = token || null;
                _modelBgLookups = Object.create(null);
                _chatBgLookedUp = _pageChatBgLookedUp = false;
                _settingsRead = null;
                if (!_pageUpload) dropPageUpload();
                if (uid === _lookupsUid) return;
                _lookupsUid = uid;
                _modelBgSeen = Object.create(null);
                _chatBgTail = null;
                _earlierModelBgs = Object.create(null);
                _earlierChatBgs = [];
                if (_pageChatBg && _pageChatBg.indexOf('blob:') === 0) URL.revokeObjectURL(_pageChatBg);
                _pageChatBg = '';
                _pageChatBgOf = null;
                dropPageUpload();
            }
            // The answer, or null when the lookup learned nothing, and the
            // caller keeps what it has. retry() lets a later sync ask again,
            // except after a refusal, which holds until the next sign-in.
            function lookUp(url, retry) {
                return fetch(url, { headers: { Authorization: 'Bearer ' + _lookupsToken } })
                    .then(function(r) {
                        if (r.ok) return r.json().then(function(answer) { return answer || {}; });
                        if (r.status === 404) return {};
                        if (r.status !== 401 && r.status !== 403) retry();
                        return null;
                    })
                    .catch(function() { retry(); return null; });
            }
            function remember(list, url) {
                if (!url || list.indexOf(url) !== -1) return;
                list.push(url);
                if (list.length > 4) list.shift();
            }
            function modelBgUrls() {
                try { return JSON.parse(localStorage.getItem(MODEL_BG_KEY) || '{}') || {}; } catch(x) { return {}; }
            }
            function modelBg(id) {
                return id in _modelBgSeen ? _modelBgSeen[id] : (modelBgUrls()[id] || null);
            }
            function lookUpModelBg(id) {
                if (!_lookupsToken || _modelBgLookups[id]) return;
                _modelBgLookups[id] = true;
                var uid = _lookupsUid;
                lookUp('/api/v1/models/model?id=' + encodeURIComponent(id), function() { delete _modelBgLookups[id]; })
                    .then(function(model) {
                        // Asked for an account that has signed out since
                        if (!model || uid !== _lookupsUid) return;
                        var url = (model.meta && model.meta.background_image_url) || null;
                        var known = id in _modelBgSeen, was = modelBg(id);
                        _modelBgSeen[id] = url;
                        var urls = modelBgUrls();
                        if ((urls[id] || null) !== url) {
                            if (url) urls[id] = url; else delete urls[id];
                            try { localStorage.setItem(MODEL_BG_KEY, JSON.stringify(urls)); } catch(x) {}
                        }
                        if (was === url) return;
                        if (known) remember(_earlierModelBgs[id] = _earlierModelBgs[id] || [], was);
                        syncHiddenBackgrounds();
                    })
                    .catch(function() {});
            }
            // One request for both lookups that need this person's settings,
            // answering null once the account it was asked for signed out
            var _settingsRead = null;
            function readSettings() {
                if (!_settingsRead) {
                    var uid = _lookupsUid;
                    var read = _settingsRead = lookUp('/api/v1/users/user/settings', function() {
                        _chatBgLookedUp = _pageChatBgLookedUp = false;
                    }).then(function(settings) { return uid === _lookupsUid ? settings : null; });
                    read.then(function() { if (_settingsRead === read) _settingsRead = null; });
                }
                return _settingsRead;
            }
            function chatBgTail() {
                if (_chatBgTail !== null) return _chatBgTail;
                var stored = '';
                try { stored = localStorage.getItem(CHAT_BG_KEY) || ''; } catch(x) {}
                var space = stored.indexOf(' ');
                // Saved before it named the account: taken as this one's
                if (space === -1) return stored;
                return stored.slice(0, space) === _lookupsUid ? stored.slice(space + 1) : '';
            }
            function lookUpChatBg() {
                if (!_lookupsToken || _chatBgLookedUp) return;
                _chatBgLookedUp = true;
                readSettings().then(function(settings) {
                    if (!settings) return;
                    var url = settings.ui && settings.ui.backgroundImageUrl;
                    // An uploaded image is a long data address; its last
                    // characters are enough to find it on the page
                    var tail = typeof url === 'string' ? url.slice(-64) : '';
                    var known = _chatBgTail !== null, was = chatBgTail();
                    _chatBgTail = tail;
                    try { if (tail) localStorage.setItem(CHAT_BG_KEY, _lookupsUid + ' ' + tail); else localStorage.removeItem(CHAT_BG_KEY); } catch(x) {}
                    if (was === tail) return;
                    if (known) remember(_earlierChatBgs, was);
                    syncHiddenBackgrounds();
                }).catch(function() {});
            }
            // Look the backgrounds up again, after a change this page heard
            // of or may have missed: scope 'chat' or 'models' (ids, or all of
            // them). A hidden page asks once it is shown, and spread
            // spreads the lookups of the pages that hear it together.
            var _bgSyncTimer = 0, _bgSyncPending = false;
            function lookUpBackgroundsAgain(scope, ids, spread) {
                if (scope !== 'models') _chatBgLookedUp = _pageChatBgLookedUp = false;
                if (scope !== 'chat') {
                    if (Array.isArray(ids)) ids.forEach(function(id) { delete _modelBgLookups[id]; });
                    else _modelBgLookups = Object.create(null);
                }
                if (document.visibilityState === 'hidden') { _bgSyncPending = true; return; }
                if (_bgSyncTimer) return;
                _bgSyncTimer = setTimeout(function() {
                    _bgSyncTimer = 0;
                    syncHiddenBackgrounds();
                }, Math.random() * (spread || 0));
            }
            document.addEventListener('visibilitychange', function() {
                if (document.visibilityState !== 'visible' || !_bgSyncPending) return;
                _bgSyncPending = false;
                syncHiddenBackgrounds();
            });
            // Whether the theme fades this person's own Chat Background Image,
            // the one change only their own stream hears of
            function fadesChatBg() {
                var hidden = _disabled ? null : getParsedState()._hiddenBackgrounds;
                if (!hidden || typeof hidden !== 'object') return false;
                var pages = hidden.pages;
                return bgShare(hidden.chat) < 100 || !!(pages && typeof pages === 'object' && pages.source === 'chat' && bgShare(pages.share) > 0);
            }
            // How much of a background shows, 0 to 100. Themes saved before
            // the sliders listed the hidden ones, which read as 0.
            function bgShare(v) {
                if (v === null || v === undefined || v === '') return 100;
                var n = Number(v);
                return isFinite(n) ? Math.max(0, Math.min(100, Math.round(n))) : 100;
            }
            function bgShares(list) {
                var out = {};
                if (Array.isArray(list)) {
                    list.forEach(function(id) { if (typeof id === 'string' && id) out[id] = 0; });
                } else if (list && typeof list === 'object') {
                    Object.keys(list).forEach(function(id) { if (id) out[id] = bgShare(list[id]); });
                }
                return out;
            }
            // The picture behind the pages without a chat (Workspace, Notes,
            // Calendar, Channels, the admin pages), where Open WebUI draws no
            // background. It can be the person's own Chat Background Image,
            // looked up like the one in chats: an uploaded one is a long data
            // address, so it's turned into a short blob address the CSS can
            // carry. _pageChatBgOf is the address it was made from.
            var _pageChatBg = '';
            var _pageChatBgOf = null;
            function lookUpPageChatBg() {
                if (!_lookupsToken || _pageChatBgLookedUp) return;
                _pageChatBgLookedUp = true;
                var uid = _lookupsUid;
                readSettings().then(function(settings) {
                    if (!settings) return;
                    var url = settings.ui && settings.ui.backgroundImageUrl;
                    if (typeof url !== 'string') url = '';
                    if (url === _pageChatBgOf) return;
                    var shown = url.indexOf('data:image/') === 0 ? blobAddress(url) : Promise.resolve(url);
                    return shown.then(function(shownUrl) {
                        if (uid !== _lookupsUid) return;
                        if (_pageChatBg.indexOf('blob:') === 0) URL.revokeObjectURL(_pageChatBg);
                        _pageChatBg = shownUrl;
                        _pageChatBgOf = url;
                        syncHiddenBackgrounds();
                    });
                }).catch(function() {});
            }
            // A blob address for the picture at url, rejecting with the
            // response when the server refuses
            function blobAddress(url, init) {
                return fetch(url, init).then(function(r) {
                    if (!r.ok) throw r;
                    return r.blob();
                }).then(function(b) { return URL.createObjectURL(b); });
            }
            // A picture uploaded with the theme, fetched with the token: from
            // a stylesheet the browser sends Open WebUI's token cookie alone,
            // which isn't always there (see bindStream). _pageUploadOf is the
            // address asked for, and _pageUpload its blob address once fetched.
            // An answer counts only for the latest ask: a sign-in since makes
            // an earlier one another account's, or a token's that ran out.
            var _pageUpload = '', _pageUploadOf = null, _pageUploadAsk = 0;
            function isPageUpload(url) {
                return url.indexOf('__THEME_ROUTE__/page-background?') === 0 || url.indexOf('__THEME_ROUTE__/me/page-background?') === 0;
            }
            function pageUpload(url) {
                if (!_lookupsToken) return '';
                if (url === _pageUploadOf) return _pageUpload;
                dropPageUpload();
                _pageUploadOf = url;
                var ask = _pageUploadAsk;
                blobAddress(url, { headers: { Authorization: 'Bearer ' + _lookupsToken } }).then(function(blob) {
                    if (ask !== _pageUploadAsk) { URL.revokeObjectURL(blob); return; }
                    if (_pageUpload) URL.revokeObjectURL(_pageUpload);
                    _pageUpload = blob;
                    syncHiddenBackgrounds();
                }).catch(function(r) {
                    // Asked again by a later sync, except after a refusal,
                    // which holds until the next sign-in
                    if (ask === _pageUploadAsk && !(r && [401, 403, 404].indexOf(r.status) !== -1)) _pageUploadOf = null;
                });
                return '';
            }
            function dropPageUpload() {
                if (_pageUpload) URL.revokeObjectURL(_pageUpload);
                _pageUpload = '';
                _pageUploadOf = null;
                _pageUploadAsk++;
            }
            // Every page of the app but the chat pages (new chat, a chat, a
            // folder), the sign-in pages and shared chats. By address alone:
            // this runs before Open WebUI has drawn the page.
            function onOtherPage() {
                var p = window.location.pathname;
                return p !== '/' && !/^\/(c|folders|auth|s)(\/|$)/.test(p);
            }
            function syncHiddenBackgrounds() {
                followSignIn();
                var off = _disabled || window.__THEME_DESIGNER__;
                var hidden = off ? null : getParsedState()._hiddenBackgrounds;
                var shares = {};
                function fade(selector, share) {
                    if (share < 100) shares[selector] = selector in shares ? Math.min(shares[selector], share) : share;
                }
                // Only an address that can't break out of the selector
                var SAFE = /^[\w:\/.?=&%+-]{1,512}$/;
                // On unless the theme turned it off
                var behind = !off && !(hidden && typeof hidden === 'object' && hidden.behind === false);
                // How much of Open WebUI's dimming layer covers the images
                var dimming = 100;
                if (hidden && typeof hidden === 'object') {
                    dimming = bgShare(hidden.dimming);
                    var path = window.location.pathname.split('/');
                    var folders = bgShares(hidden.folders);
                    var folder = path[1] === 'folders' && path[2] ? decodeURIComponent(path[2]) : '';
                    if (folder && folders.hasOwnProperty(folder)) fade(CHAT_BG + '[style*="background-image"]', folders[folder]);
                    var models = bgShares(hidden.models);
                    Object.keys(models).forEach(function(id) {
                        if (models[id] >= 100) return;
                        lookUpModelBg(id);
                        [modelBg(id)].concat(_earlierModelBgs[id] || []).forEach(function(url) {
                            if (typeof url === 'string' && SAFE.test(url)) fade(CHAT_BG + '[style*="' + url + '"]', models[id]);
                        });
                    });
                    var chat = bgShare(hidden.chat);
                    if (chat < 100) {
                        lookUpChatBg();
                        [chatBgTail()].concat(_earlierChatBgs).forEach(function(t) {
                            if (SAFE.test(t)) fade(CHAT_BG + '[style*="' + t + '"]', chat);
                        });
                    }
                }
                // An image under a wash like the chat's dimming layer, so the
                // shared Dimming means the same on every page, in dark and light
                function washedImage(target, lead, url, share) {
                    var d = dimming / 100;
                    var layer = function(from, to) {
                        return lead + 'background-image: linear-gradient(to top, ' + from + ', ' + to + '), url("' + url + '") !important; ' +
                            'background-size: cover !important; background-position: center !important; opacity: ' + share / 100 + ' !important;';
                    };
                    return [
                        'html.dark ' + target + ' { ' + layer('color-mix(in oklab, var(--color-gray-900) ' + Math.round(100 * d) + '%, transparent)', 'color-mix(in oklab, var(--color-gray-900) ' + Math.round(90 * d) + '%, transparent)') + ' }',
                        'html:not(.dark) ' + target + ' { ' + layer('rgb(255 255 255 / ' + d + ')', 'rgb(255 255 255 / ' + Math.round(85 * d) / 100 + ')') + ' }'
                    ];
                }
                // The sign-in page's own picture (instance theme only), drawn on
                // Open WebUI's backdrop there
                var authRules = [];
                var auth = hidden && typeof hidden === 'object' && hidden.auth && typeof hidden.auth === 'object' ? hidden.auth : null;
                var authShare = auth ? bgShare(auth.share) : 0;
                if (auth && authShare > 0 && typeof auth.url === 'string' && /^(https:\/\/|\/)[^\s"'()\\<>]{1,2048}$/.test(auth.url)) {
                    var back = '#auth-page#auth-page > div.absolute.bg-white';
                    authRules = washedImage(back, 'background-color: transparent !important; ', auth.url, authShare);
                    if (behind) authRules.push('html:has(#owui-theme-canvas-bg) ' + back + ' { z-index: -1 !important; }');
                }
                // The picture behind the other pages, on a fixed layer under the
                // app. Those pages' solid panels clear, as they do under Canvas FX.
                var pageRules = [];
                var pages = hidden && typeof hidden === 'object' && hidden.pages && typeof hidden.pages === 'object' ? hidden.pages : null;
                var pageShare = pages ? bgShare(pages.share) : 0;
                var upload = pages && pageShare > 0 && pages.source !== 'chat' && typeof pages.url === 'string' && isPageUpload(pages.url);
                if (!upload) dropPageUpload();
                if (pages && pageShare > 0 && onOtherPage()) {
                    var pageUrl = '';
                    if (pages.source === 'chat') {
                        lookUpPageChatBg();
                        pageUrl = _pageChatBg;
                    } else if (typeof pages.url === 'string') {
                        pageUrl = upload ? pageUpload(pages.url) : pages.url;
                    }
                    if (/^(https:\/\/|\/|blob:)[^\s"'()\\<>]{1,2048}$/.test(pageUrl)) {
                        pageRules = washedImage('.app::before', 'content: "" !important; position: fixed !important; inset: 0 !important; z-index: -1 !important; pointer-events: none !important; ', pageUrl, pageShare);
                        var gEx = ':not(button):not(a):not(input):not(select):not(label):not(span):not(.chat-user *):not([class*="rounded"]):not(#message-input-container *)';
                        var gWhere = ['[class^="bg-gray-"]', '[class*=" bg-gray-"]', '[class^="dark:bg-gray-"]', '[class*=" dark:bg-gray-"]', '[class^="bg-base-"]', '[class*=" bg-base-"]', '[class^="dark:bg-base-"]', '[class*=" dark:bg-base-"]'].map(function(t) { return t + gEx; }).join(', ');
                        pageRules.push('.app, .app > div, .app main { background-color: transparent !important; background-image: none !important; }');
                        pageRules.push('.app :where(' + gWhere + ') { background-color: transparent !important; background-image: none !important; }');
                        // In front of the animation when the theme says so
                        if (!behind) pageRules.push('body:has(#owui-theme-canvas-bg) .app { z-index: 1 !important; }');
                    }
                }
                var style = document.getElementById('owui-tdp-hidden-bg');
                var selectors = Object.keys(shares);
                if (!selectors.length && !behind && dimming >= 100 && !authRules.length && !pageRules.length) { if (style) style.remove(); return; }
                var css = [];
                if (dimming < 100) css.push(CHAT_BG + '[style*="background-image"] + div.pointer-events-none { opacity: ' + dimming / 100 + ' !important; }');
                // The image and the dimming layer over it fade together; these
                // come after the rule above, so they win for their own image
                selectors.forEach(function(s) {
                    if (!shares[s]) { css.push(s + ', ' + s + ' + div.pointer-events-none { display: none !important; }'); return; }
                    css.push(s + ' { opacity: ' + shares[s] / 100 + ' !important; }');
                    css.push(s + ' + div.pointer-events-none { opacity: ' + Math.round(shares[s] * dimming / 10) / 1000 + ' !important; }');
                });
                if (behind) {
                    // Under the canvas, only while an animation runs: without
                    // one, Open WebUI's own page background would cover them
                    var b = 'body:has(#owui-theme-canvas-bg) ' + CHAT_BG + '[style*="background-image"]';
                    css.push(b + ', ' + b + ' + div.pointer-events-none { z-index: -1 !important; }');
                }
                css = css.concat(authRules, pageRules).join('\n');
                if (!style) {
                    style = document.createElement('style');
                    style.id = 'owui-tdp-hidden-bg';
                    document.head.appendChild(style);
                }
                if (style.textContent !== css) style.textContent = css;
                // A theme that starts fading the Chat Background Image needs
                // the frames of this account's own stream
                if (_claimStream) _claimStream();
            }

            function refresh() {
                if (_disabled) return;
                // Debounce via rAF — collapses rapid MutationObserver triggers into one paint.
                // Prevents strobe-like flashing on auth pages where class/data-theme mutations
                // from Open WebUI's init fire multiple times in quick succession.
                if (_refreshPending) return;
                _refreshPending = true;
                requestAnimationFrame(function() {
                    _refreshPending = false;
                    checkAccount();
                    enforceTheme(); initCanvas();
                    // An account that signed in after the page loaded
                    if (_claimStream) _claimStream();
                });
            }

            // Signing in, or into another account, happens without a page
            // load, so the theme picked at load can belong to nobody or to
            // someone else. Swap to the signed-in account's personal theme
            // (this browser's copy at once, then the server's), or back to
            // the instance theme when it has none.
            function checkAccount() {
                if (!_personalEnabled || _disabled || window.__THEME_DESIGNER__) return;
                var uid = personalUser();
                if (uid === _themeUid) return;
                try {
                    if (uid && localStorage.getItem('owui_tdp_personal_uid') === uid &&
                        localStorage.getItem('owui_tdp_personal_css')) {
                        _owuiThemeCss = localStorage.getItem('owui_tdp_personal_css');
                        _owuiThemeState = localStorage.getItem('owui_tdp_personal_state') || null;
                        _parsedState = null;
                        // A browser copy again, until the server's answer
                        _cachedCanvasOk = __CANVAS_FX__;
                        _personal = true;
                        enforceTheme(); initCanvas();
                    }
                } catch(x) {}
                ++_themeVersion;  // Supersede a fetch made for the previous account
                fetchThemeFromServer();
            }

            // Open WebUI's sign-in ends in a client-side goto(), which changes
            // the address with history.pushState and fires nothing we listen
            // to. Each history change repaints: the account may have changed,
            // and sign-in pages and app pages can show different parts.
            ['pushState', 'replaceState'].forEach(function(name) {
                var original = history[name];
                if (typeof original !== 'function') return;
                history[name] = function() {
                    var result = original.apply(this, arguments);
                    setTimeout(function() {
                        refresh();
                        try { window.dispatchEvent(new Event('owui-tdp-route')); } catch(x) {}
                    }, 0);
                    return result;
                };
            });

            // Open WebUI's setTheme() calls this after every mode switch,
            // OLED Dark included, which changes no class on <html>
            var _previousApplyTheme = window.applyTheme;
            window.applyTheme = function() {
                if (typeof _previousApplyTheme === 'function') {
                    try { _previousApplyTheme.apply(this, arguments); } catch(x) { console.warn('Theme Pro:', x); }
                }
                refresh();
            };

            refresh();
            
            // Also kept for a mode another plugin on loader.js or an extension
            // writes to <html>, which then gets put back. Comparing with what
            // enforceTheme() set skips its own writes and unrelated classes
            // such as high-contrast.
            const observer = new MutationObserver(() => {
                // owui-server-theme is no longer a signal that a theme exists —
                // the server subset ships as a <link> to /static/custom.css that
                // is present regardless. The inlined state above covers it.
                if ((!document.getElementById('owui-dev-live-theme') && (_owuiThemeCss || _owuiThemeState)) ||
                    rootMode() !== _rootModeSet) {
                    refresh();
                }
            });
            
            observer.observe(document.documentElement, { attributes: true, attributeFilter:['class', 'data-theme'] });
            if (document.head) observer.observe(document.head, { childList: true });
            
            // Cross-tab sync. The two theme keys are NOT written together: the
            // designer stores its state synchronously in injectLive() but defers
            // the css write until its POST comes back, so the browser fires two
            // storage events a full network round trip apart (~500ms locally).
            // Repainting on each one separately published the state of the new
            // theme against the css of the old one for that whole gap — the
            // exact hybrid seen while swapping themes with the app open beside
            // the designer.
            //
            // So: coalesce, and re-read from the server rather than trusting a
            // half-updated localStorage. fetchThemeFromServer() applies css and
            // state atomically, which is the only place a coherent pair exists.
            var _storageSyncTimer = null;
            window.addEventListener('storage', (e) => {
                const triggerKeys =['theme', 'owui_dev_theme_v1_css', 'owui_dev_theme_v1', 'owui_tdp_personal_css', 'owui_tdp_personal_state'];
                if (!triggerKeys.includes(e.key) || !e.newValue) return;
                if (e.key === 'theme') {
                    // Mode switch — cheap, unambiguous, apply immediately.
                    document.documentElement.setAttribute('data-theme', e.newValue);
                    refresh();
                }
                // The designer owns its own editing state; another tab's
                // write-through must never repaint it out from under the admin.
                if (window.__THEME_DESIGNER__) return;
                // Deliberately DO NOT copy the incoming value into the in-memory
                // caches. Doing so half-updates the pair the moment one key
                // arrives, and any repaint that happens before the refetch below
                // then publishes that half, including the mode switch above.
                // That is how a canvas could be torn down while the CSS of the
                // outgoing theme stayed on screen for the length of this debounce.
                //
                // Leaving the caches alone keeps the last COHERENT pair live and
                // renderable until the refetch replaces both together. The
                // written-through localStorage values stay untouched and remain
                // the offline fallback for the next cold load.
                clearTimeout(_storageSyncTimer);
                _storageSyncTimer = setTimeout(function() {
                    if (_disabled) return;
                    // The only place a coherent pair exists: applied atomically.
                    fetchThemeFromServer();
                }, 300);
            });

            window.addEventListener('popstate', refresh);
            window.addEventListener('owui-theme-updated', function(e) {
                // Designer passes theme state and CSS directly via CustomEvent.detail
                // so draft-mode updates work (sessionStorage is invisible to bootloader)
                if (e.detail && e.detail.state) { _owuiThemeState = e.detail.state; _parsedState = null; }
                if (e.detail && e.detail.css) _owuiThemeCss = e.detail.css;
                refresh();
            });
            window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', refresh);

            // Repaints after SPA navigation come from the popstate listener and
            // the MutationObserver above; the history wrappers only check for
            // a change of account.

            // Live theme push via Server-Sent Events (cross-tab/browser/device)
            if (!window.__THEME_DESIGNER__) {
                try {
                    // --- SSE handler functions (shared between initial and reconnected EventSource) ---
                    // Tells the Themes tab in Settings whether the function is on.
                    function announceFunctionOff(off) {
                        if (!!window.__owuiThemeFunctionOff === off) return;
                        window.__owuiThemeFunctionOff = off;
                        try { window.dispatchEvent(new Event('owui-theme-function-state')); } catch(x) {}
                    }
                    function handleThemeUpdate(e) {
                        _disabled = false;  // Re-enable if admin turned it back on
                        announceFunctionOff(false);
                        // The broadcast carries only a version token (+ delivery
                        // ETags) and clients refetch the post-processed CSS + state,
                        // so a frame never carries a whole canvas script to every client.
                        var d = {};
                        try {
                            d = JSON.parse(e.data || '{}') || {};
                            // Its own resync (personal-theme-update) covers a personal theme
                            if (d.resync && _personal) return;
                            if (d.cssTag && d.stateTag &&
                                d.cssTag === _lastCssTag && d.stateTag === _lastStateTag) {
                                return; // Already applied this exact version — skip refetch
                            }
                        } catch(x) {}
                        refetchSpread(d);
                    }
                    function refetchSpread(d) {
                        var myV = ++_themeVersion;  // Supersede any in-flight fetch
                        // A hidden page refetches when it's shown (visibilitychange
                        // below), so it adds nothing to the rush now
                        if (document.visibilityState === 'hidden') return;
                        // Jitter the refetch over the spread the server sized to
                        // the pages it has (0-2s; an older server sends none) so
                        // one broadcast doesn't stampede it with every client.
                        var spread = typeof d.spread === 'number' ? Math.max(0, Math.min(2000, d.spread)) : 2000;
                        setTimeout(function() {
                            if (myV !== _themeVersion || _disabled) return; // Superseded while waiting
                            fetchThemeFromServer();
                        }, Math.random() * spread);
                    }
                    function handleThemeDisable(e) {
                        // A Global Reset strips the theme the same way, but the
                        // function stays on, so only a real disable hides the tab.
                        var d = {};
                        try { d = JSON.parse((e && e.data) || '') || {}; } catch(x) {}
                        if (d.reason === 'reset') {
                            // The instance theme was emptied; the function is still
                            // on and personal themes are untouched. Fetch what's
                            // left (a personal theme, or none) instead of stripping
                            // everything and ignoring updates until the next save.
                            _lastCssTag = null;
                            _lastStateTag = null;
                            refetchSpread(d);
                            return;
                        }
                        announceFunctionOff(true);
                        // Admin disabled — set disable flag, clear state, strip DOM
                        _disabled = true;
                        _themeVersion++;  // Invalidate any in-flight fetch callbacks
                        _owuiThemeState = null;
                        _owuiThemeCss = null;
                        _parsedState = null;  // Invalidate cached parse
                        _lastCssTag = null;   // Theme is no longer applied — clear the
                        _lastStateTag = null; // ETags so a re-enable with an unchanged theme
                                              // still refetches instead of skipping as "already applied"
                        teardownCanvas();
                        try {
                            ['owui_dev_theme_v1_css', 'owui_dev_theme_v1'].concat(PERSONAL_KEYS).forEach(function(k) {
                                localStorage.removeItem(k);
                            });
                        } catch(x) {}
                        ['owui-dev-live-theme', 'owui-server-theme', 'owui-theme-style', 'owui-tdp-hidden-bg'
                        ].forEach(function(id) {
                            var el = document.getElementById(id);
                            if (el) el.remove();
                        });
                        // The palette also lives in the shared stylesheet, which
                        // is not ours to delete — re-fetch it so our block drops
                        // out. Without this the colours survive a disable until
                        // the next full page load.
                        refreshSharedCustomCss();
                        // NOTE: SSE stays open — if admin re-enables, theme-update will re-apply
                    }

                    // EventSource can't send the Authorization header, and Open
                    // WebUI's token cookie isn't always there for a signed-in
                    // page (a session cookie after a browser restart, a Secure
                    // cookie on plain http). Without one the server can't tell
                    // whose page this is, so saves to this account's personal
                    // theme on another device never arrived. The stream's first
                    // message gives its id, and the page claims it with the
                    // token it signs everything else with.
                    var _streamId = null, _streamUid = null, _claimed = null, _claimRetryAt = 0;
                    // d names the personal theme saved now (the bind answer, a
                    // resync); seen is what this page's last fetch read
                    function personalCurrent(d, seen, uid) {
                        return !!d && !!seen && seen.uid === uid && 'cssTag' in d &&
                            seen.tags[0] === (d.cssTag || null) && seen.tags[1] === (d.stateTag || null);
                    }
                    // Without personal themes, only a page that fades the Chat
                    // Background Image needs its own frames, and a stream the
                    // token cookie already named needs no claim
                    function bindStream() {
                        var uid = signedInUser();
                        if (!uid || !_streamId) return;
                        if (!_personalEnabled && (!fadesChatBg() || _streamUid === uid)) return;
                        var key = _streamId + ':' + uid;
                        if (_claimed === key || Date.now() < _claimRetryAt) return;
                        _claimed = key;
                        var token = '';
                        try { token = localStorage.getItem('token') || ''; } catch(x) {}
                        var failed = function() {
                            if (_claimed !== key) return;
                            _claimed = null;
                            _claimRetryAt = Date.now() + 30000;
                        };
                        fetch('__THEME_ROUTE__/events/bind', {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + token },
                            body: JSON.stringify({ cid: _streamId })
                        }).then(function(r) {
                            if (!r.ok) { failed(); return; }
                            // A personal save that landed between this page's
                            // fetch and the claim was sent to nobody. The answer
                            // names the personal theme saved now: fetch only when
                            // this page shows something else (or can't tell)
                            return Promise.all([r.json().catch(function() { return null; }), _personalRead]).then(function(both) {
                                if (_claimed !== key) return;
                                if (_personalEnabled && !personalCurrent(both[0], both[1], uid)) fetchThemeFromServer();
                            });
                        }).catch(failed);
                    }
                    _claimStream = bindStream;

                    var _sseRetryTimer = 0, _sseRetryN = 0, _sseOpens = 0;
                    function connectSSE() {
                        clearTimeout(_sseRetryTimer);
                        if (es) try { es.close(); } catch(x) {}
                        es = new EventSource('__THEME_ROUTE__/events?_=' + Date.now());
                        var mine = es;
                        es.onopen = function() { _sseRetryN = 0; _sseOpens++; };
                        es.addEventListener('theme-update', handleThemeUpdate);
                        es.addEventListener('theme-disable', handleThemeDisable);
                        // Sent first on every connection, also one over the cap
                        es.addEventListener('hello', function(e) {
                            var d = {};
                            try { d = JSON.parse(e.data) || {}; } catch(x) {}
                            _streamId = d.cid || null;
                            _streamUid = d.uid || null;
                            _claimed = null;
                            _claimRetryAt = 0;
                            bindStream();
                            // Not the first open: a save may have landed while
                            // the stream was down, and nothing would resend it
                            if (_sseOpens > 1) {
                                refetchSpread(d);
                                lookUpBackgroundsAgain('models', null, typeof d.spread === 'number' ? Math.max(0, Math.min(2000, d.spread)) : 2000);
                            }
                        });
                        // Sent only to this account's pages when its personal theme changes.
                        es.addEventListener('personal-theme-update', function(e) {
                            var d = {};
                            try { d = JSON.parse(e.data || '{}') || {}; } catch(x) {}
                            if (d.resync) {
                                var uid = personalUser();
                                _personalRead.then(function(seen) {
                                    if (!personalCurrent(d, seen, uid)) refetchSpread(d);
                                });
                                return;
                            }
                            _disabled = false;
                            ++_themeVersion;
                            fetchThemeFromServer();
                        });
                        // A background image the theme may fade changed: this
                        // account's Chat Background Image, or a model's, which
                        // every page hears, so they spread their lookups
                        es.addEventListener('backgrounds-update', function(e) {
                            var d = {};
                            try { d = JSON.parse(e.data || '{}') || {}; } catch(x) {}
                            if (d.scope !== 'models') { lookUpBackgroundsAgain('chat'); return; }
                            var spread = typeof d.spread === 'number' ? Math.max(0, Math.min(2000, d.spread)) : 2000;
                            lookUpBackgroundsAgain('models', Array.isArray(d.ids) ? d.ids : null, spread);
                        });
                        // EventSource retries a dropped stream by itself, but an HTTP
                        // error (a proxy's 502 while Open WebUI restarts) closes it
                        // for good, and a visible tab never reopened it.
                        es.onerror = function() {
                            if (mine !== es || es.readyState !== EventSource.CLOSED) return;
                            var delay = Math.min(60000, 3000 * Math.pow(2, _sseRetryN++)) * (0.5 + Math.random());
                            clearTimeout(_sseRetryTimer);
                            _sseRetryTimer = setTimeout(function() { if (mine === es) connectSSE(); }, delay);
                        };
                    }

                    var es = null;
                    connectSSE();

                    // Free the HTTP/1.1 connection slot before the new page starts loading —
                    // prevents NetworkError in Open WebUI's ModelSelector caused by
                    // connection pool exhaustion (6 per-domain limit) during refresh.
                    // Uses `es` directly (mutable var) so beforeunload always closes the
                    // CURRENT EventSource, even after iOS PWA reconnect reassigns it.
                    // Open WebUI can still cancel the unload with its own leave
                    // prompt; then the page stays and needs its stream back.
                    window.addEventListener('beforeunload', function() {
                        if (es) es.close();
                        clearTimeout(_sseRetryTimer);
                        _sseRetryTimer = setTimeout(function() { connectSSE(); }, 3000);
                    });

                    // iOS PWA resilience: when the app returns to foreground, the EventSource
                    // connection may have been silently killed by WebKit. Force a reconnect
                    // and re-fetch fresh state to pick up any edits made while inactive.
                    document.addEventListener('visibilitychange', function() {
                        if (document.visibilityState !== 'visible') return;
                        if (es.readyState === EventSource.CLOSED) {
                            connectSSE();
                            lookUpBackgroundsAgain('models');
                        }
                        bindStream();
                        fetchThemeFromServer();
                    });
                } catch(e) { console.warn('Theme Pro SSE:', e); }
            }
        } catch(e) { console.warn('Theme Pro:', e); }
    })();
