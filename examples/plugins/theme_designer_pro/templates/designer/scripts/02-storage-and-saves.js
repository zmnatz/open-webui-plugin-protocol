    // --- Storage ---
    // Keys that the bootloader's `storage` event listener watches — must use sessionStorage in draft mode
    const _BOOTLOADER_WATCHED_KEYS = new Set(['theme', 'css_cache']);

    // The galleries (themes, Canvas FX scripts, CSS snippets, gradients) are
    // kept on the server, which puts them in this page. Copied into the
    // browser's storage as well, they filled it: a site gets about 5 MB,
    // shared with Open WebUI, and a personal designer kept a second set. So
    // they're kept in memory. An older build's copy in the browser is read
    // while the server has no copy of that gallery, and removed once it has.
    const _LIBRARY_FIELDS = {
        snapshots: 'owui_theme_snapshots', canvas_presets: 'owui_canvas_presets',
        css_presets: 'owui_css_presets', gradient_presets: 'owui_gradient_presets'
    };
    const _libraryKeys = new Set(Object.values(_LIBRARY_FIELDS));
    const _libraryMemory = new Map();
    const _libraryStore = {
        getItem(k) { return _libraryMemory.has(k) ? _libraryMemory.get(k) : localStorage.getItem(k); },
        setItem(k, v) { _libraryMemory.set(k, String(v)); },
        removeItem(k) { _libraryMemory.delete(k); localStorage.removeItem(k); }
    };
    const _serverLibrary = (() => {
        try {
            const lib = JSON.parse(window.__THEME_PRO_LIBRARY__ || 'null');
            return lib && typeof lib === 'object' ? lib : {};
        } catch (e) { return {}; }
    })();
    Object.entries(_LIBRARY_FIELDS).forEach(([field, key]) => {
        if (!Array.isArray(_serverLibrary[field]) || !_serverLibrary[field].length) return;
        _libraryMemory.set(key, JSON.stringify(_serverLibrary[field]));
        try { localStorage.removeItem(key); } catch (e) {}
    });

    const Storage = {
        _keys: {
            theme: STORAGE_KEY,
            css_cache: STORAGE_KEY + '_css',
            snapshots: _LIBRARY_FIELDS.snapshots,
            canvas: _LIBRARY_FIELDS.canvas_presets,
            css: _LIBRARY_FIELDS.css_presets,
            gradients: _LIBRARY_FIELDS.gradient_presets,
            metadata: 'owui_theme_last_metadata',
        },
        _resolve(key) { return this._keys[key] || key; },
        // In Draft the keys the bootloader watches go to sessionStorage, which
        // is tab-scoped, so a draft never reaches the other tabs
        _store(key) {
            if (_libraryKeys.has(this._resolve(key))) return _libraryStore;
            return (_draftMode && _BOOTLOADER_WATCHED_KEYS.has(key)) ? sessionStorage : localStorage;
        },
        get(key, fallback = null) {
            try { return JSON.parse(this._store(key).getItem(this._resolve(key))) || fallback; }
            catch { return fallback; }
        },
        // False when the write was rejected (quota exceeded, storage
        // disabled), so a loop of writes can stop cleanly instead of throwing
        // halfway through
        set(key, value) { return this.setRaw(key, JSON.stringify(value)); },
        getRaw(key) { return this._store(key).getItem(this._resolve(key)); },
        setRaw(key, value) {
            try {
                this._store(key).setItem(this._resolve(key), value);
                return true;
            } catch (e) {
                // QuotaExceededError (its name varies across browsers) or no
                // storage (private mode): a silent failure would look like data loss
                console.warn('[Theme Pro] Storage write failed for', key, e);
                if (typeof showToast === 'function') {
                    showToast('⚠️ This browser\'s storage is full, so its copy of the theme is out of date. Your changes still save to the server.');
                }
                return false;
            }
        },
        remove(key) { this._store(key).removeItem(this._resolve(key)); }
    };

    // --- Theme saves ---
    let _syncTimer = null;
    let _syncSeq = 0;
    let _syncQueue = Promise.resolve();
    // Run once with the state of the next save that lands
    let _afterThemeSaved = null;
    let _lastSyncAt = 0;  // When the last save went out (see syncToServer's delay)
    // Mirrors the admin's function ON/OFF toggle, driven by the badge's SSE
    // connection further down. The save endpoint answers 503 while the function
    // is disabled, so posting into that window would lose the edit silently.
    let _functionDisabled = false;
    // A theme save the server didn't take, with the function off or on the
    // way, is never sent again on its own: another designer may have saved
    // since. The instance designer keeps it as a draft, for Publish; the
    // personal one, which has no Draft, holds every save until Retry.
    let _themeSaveHeld = false;       // Personal designer only
    let _offeringKept = false;        // Asking whether to save a kept theme: nothing saves meanwhile
    let _personalSaveBase = null;     // The personal theme's tags it was made over
    let _librarySavePending = false;  // Sent again with the next library change
    // The gallery changed elsewhere while this page can't reload (Draft, a held
    // personal save): every library save sends the whole gallery, so they stop
    // until a reload brings theirs in
    let _libraryStale = false;
    function pauseLibrary() {
        if (_libraryStale) return;
        _libraryStale = true;
        const dropped = _librarySavePending || _libTimer !== null;
        clearTimeout(_libTimer);
        _libTimer = null;
        _librarySavePending = false;
        if (dropped) noteLibraryDropped();
        showToast('The gallery changed elsewhere. Gallery changes are paused until this page reloads; ' +
            (THEME_KIND === 'personal' ? 'your unsaved theme is kept.' : 'your draft is kept.'), 10000);
    }
    // Said after the next load
    function noteLibraryDropped() {
        if (HIDDEN_APPLY_FRAME) return;
        try { sessionStorage.setItem(LIBRARY_DROPPED_KEY, '1'); } catch (x) {}
    }
    let _latestState = null;          // The newest state handed to syncToServer
    let _syncEpoch = 0;               // Saves queued before a failure don't go out
    const THEME_KIND = (window.__THEME_PRO_CONFIG__ || {}).scope === 'me' ? 'personal' : 'theme';
    // The Launcher's hidden ?apply= frame shares this tab's sessionStorage with
    // any designer open in it, so it neither keeps a failed save nor takes
    // one, and never resumes a draft it didn't make
    const HIDDEN_APPLY_FRAME = ((window.__THEME_PRO_CONFIG__ || {}).applyOnLoad || {}).kind === 'theme';
    const UNSAVED_THEME_KEY = 'owui_tdp_unsaved_theme';
    const LIBRARY_DROPPED_KEY = 'owui_tdp_library_dropped';
    // epoch: the save's own, so a late answer from before Draft or a Publish does nothing
    function failedThemeSave(epoch) {
        if (epoch !== undefined && epoch !== _syncEpoch) return;
        clearTimeout(_syncTimer);
        _syncEpoch++;
        if (HIDDEN_APPLY_FRAME || !_latestState) return;
        if (THEME_KIND === 'personal') { holdPersonalSave(); return; }
        if (_draftMode) return;
        try { sessionStorage.setItem(Storage._resolve('theme'), _latestState); } catch (x) {}
        setDraftMode(true);
        showToast(_functionDisabled
            ? '⏸️ Function is disabled. Your change stays here as a draft, and Publish sends it once the function is back on.'
            : '⚠️ The server didn’t take your change. It stays here as a draft, and Publish sends it.', 10000);
    }
    // Kept as the save fails, not on unload: an embedded designer is removed
    // from the page without one, and a crash or a discarded tab runs none
    function holdPersonalSave() {
        if (!_themeSaveHeld) _personalSaveBase = JSON.stringify((_held.personal || [null, null]).map(plainTag));
        _themeSaveHeld = true;
        try { sessionStorage.setItem(UNSAVED_THEME_KEY, JSON.stringify({ scope: THEME_KIND, state: _latestState, base: _personalSaveBase })); } catch (x) {}
        const tabs = document.querySelector('.tabs');
        if (document.getElementById('tdp-held-save') || !tabs) return;
        const bar = document.createElement('div');
        bar.className = 'tdp-tool-offer';
        bar.id = 'tdp-held-save';
        bar.setAttribute('role', 'region');
        bar.setAttribute('aria-label', 'Unsaved changes');
        const text = document.createElement('span');
        text.textContent = 'The server didn’t take your last change. It is kept in this browser tab, and nothing is saved until you send it.';
        const retry = document.createElement('button');
        retry.type = 'button';
        retry.className = 'btn btn-primary';
        retry.textContent = 'Retry';
        retry.addEventListener('click', retryPersonalSave);
        bar.append(text, retry);
        tabs.parentNode.insertBefore(bar, tabs);
        showToast('⚠️ The server didn’t take your change. It is kept in this tab until you press Retry.', 8000);
    }
    // Sent over the theme it was made on, or over one saved since only when asked
    // These are the delivered files' tags, so a valve change since asks too:
    // no raw tag is served. Gzipping proxies weaken them to W/"...".
    const plainTag = (t) => (t && t.indexOf('W/') === 0) ? t.slice(2) : t;
    async function retryPersonalSave() {
        const cantCheck = () => showToast('⏸️ The function looks disabled, so your saved theme can’t be checked and nothing was sent. Try Retry once it is back on.');
        if (_functionDisabled) { cantCheck(); return; }
        let tags;
        try {
            const tag = async (path) => {
                const r = await fetch('{ROUTE_BASE}/me/' + path, { cache: 'no-store' });
                if (!r.ok) throw new Error('HTTP ' + r.status);
                return plainTag(r.headers.get('ETag'));
            };
            tags = [await tag('theme.css'), await tag('state.json')];
        } catch (x) {
            showToast('⚠️ The server isn’t answering, so nothing was sent. Try Retry again in a moment.');
            return;
        }
        const now = JSON.stringify(tags);
        if (now !== _personalSaveBase && !(await askConfirm('Replace the theme saved elsewhere?',
            'Your theme was saved or removed somewhere else after this change failed to save. Send this tab’s changes over it?', 'Replace it'))) return;
        _themeSaveHeld = false;
        document.getElementById('tdp-held-save')?.remove();
        try { injectLive(); } catch (err) { console.warn('[Theme Pro] Retry failed:', err); }
    }
    // Before a reset or a reload this page makes itself: nothing held may come back after it
    function forgetPendingSaves() {
        _themeSaveHeld = false;
        _librarySavePending = false;
        _latestState = null;
        document.getElementById('tdp-held-save')?.remove();
        if (HIDDEN_APPLY_FRAME) return;
        try { sessionStorage.removeItem(UNSAVED_THEME_KEY); } catch (x) {}
    }
    window.addEventListener('beforeunload', (e) => {
        if (_themeSaveHeld || _offeringKept || _librarySavePending) e.preventDefault();
    });
    // A save the server refused for what it holds (400, 413...) fails the same
    // way every time; one lost to a restart, a proxy or the network can go again
    function saveCanRetry(status) {
        return status >= 500 || status === 408 || status === 429;
    }
    let _disabledNoticeAt = 0;
    function noticeSaveBlocked() {
        // Editing fires a save per control change; one notice every few seconds
        // is informative, one per keystroke is noise.
        const now = Date.now();
        if (now - _disabledNoticeAt < 4000) return;
        _disabledNoticeAt = now;
        showToast('⏸️ Function is disabled. Gallery changes are kept on this page and sent with your next one once it is back on.');
    }
    let _draftMode = false;  // When true, syncToServer is suppressed
    // The theme on the server is one this page could not read (set as it loads)
    let _savedThemeUnreadable = false;

    // Who a live save reaches, for the badge, Draft and Publish: a personal
    // theme only its owner's own pages, and the instance theme everyone, or,
    // with personal themes on, everyone without a theme of their own
    function liveAudience() {
        const cfg = window.__THEME_PRO_CONFIG__ || {};
        if (cfg.scope === 'me') return 'your own open pages';
        return cfg.allowPersonalThemes ? 'everyone who isn\u2019t using a theme of their own' : 'all users';
    }

    function setDraftMode(on) {
        if (on && HIDDEN_APPLY_FRAME) return;  // Its saves go through chatTheme's save()
        if (on && !_draftMode) {
            // A Live save not sent yet, or one whose answer comes later, is
            // left to the draft and Publish
            clearTimeout(_syncTimer);
            _syncEpoch++;
            // Entering draft: seed sessionStorage with current localStorage values
            // so the designer starts with the live theme as baseline.
            // Skip seeding if sessionStorage already has data (preserves draft
            // state across page refresh — the previous session's writes survive).
            _BOOTLOADER_WATCHED_KEYS.forEach(key => {
                const resolved = Storage._resolve(key);
                if (!sessionStorage.getItem(resolved)) {
                    const val = localStorage.getItem(resolved);
                    if (val) sessionStorage.setItem(resolved, val);
                }
            });
        }
        if (!on && _draftMode) {
            // Exiting draft: migrate sessionStorage data back to localStorage
            // so the bootloader and live-mode reads see the published state
            _BOOTLOADER_WATCHED_KEYS.forEach(key => {
                const resolved = Storage._resolve(key);
                const val = sessionStorage.getItem(resolved);
                if (val) localStorage.setItem(resolved, val);
                sessionStorage.removeItem(resolved);
            });
        }
        _draftMode = on;
        // When exiting draft, persist the current mode to localStorage now that
        // the draft gate is lifted — this was suppressed during draft editing.
        if (!on) {
            syncParentNativeMode(activeMode);
        }
        const sw = document.getElementById('draft-switch');
        const labelLive = document.getElementById('draft-label-live');
        const labelDraft = document.getElementById('draft-label-draft');
        const publishBtn = document.getElementById('draft-publish-btn');
        const draftDot = document.getElementById('draft-dot');
        if (sw) { sw.classList.toggle('on', on); sw.setAttribute('aria-checked', String(on)); }
        if (labelLive) labelLive.classList.toggle('active', !on);
        if (labelDraft) labelDraft.classList.toggle('active', on);
        if (publishBtn) publishBtn.classList.toggle('visible', on);
        if (draftDot) draftDot.style.display = on ? 'inline-block' : 'none';
        if (sw) sw.setAttribute('data-tooltip', on ? 'Click to exit Draft and push changes live to ' + liveAudience() : 'Click to enter Draft mode \u2014 changes will stay local until you Publish');
        if (publishBtn) publishBtn.setAttribute('data-tooltip', 'Push all changes live to ' + liveAudience());
        sessionStorage.setItem('owui_theme_draft_mode', on ? '1' : '0');
        if (window._updateThemeBadge) window._updateThemeBadge();
    }

    let _draftRestored = false;
    function restoreDraftMode() {
        if (_draftRestored || HIDDEN_APPLY_FRAME) return;
        _draftRestored = true;
        if (sessionStorage.getItem('owui_theme_draft_mode') === '1' || window.__THEME_PRO_CONFIG__?.draftModeDefault) {
            setDraftMode(true);
        }
    }

    async function publishTheme() {
        if (_savedThemeUnreadable && !(await askConfirm('Replace the saved theme?',
            'The saved theme could not be read. Publishing replaces it with the theme shown here for ' + liveAudience() + '.', 'Publish'))) return;
        // CSS and sections regenerated from themeData rather than the css_cache
        // blob: the server needs matching sections with every CSS save (a
        // css-only POST deletes the sections file as stale).
        const sections = generateThemeSections();
        const css = assembleThemeCss(sections);
        const state = themeStateStr();
        _syncEpoch++;
        _latestState = state;
        fetch('{ROUTE_BASE}', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ css, state, sections, origin: TAB_ORIGIN })
        }).then(r => {
            if (r.ok) {
                _savedThemeUnreadable = false;
                showToast('Published! Theme pushed to ' + liveAudience() + '.');
                // Edits made while the request was in flight are not in it, and
                // Live mode would otherwise only show them, never save them
                const editedSince = themeStateStr() !== state;
                setDraftMode(false);
                // Uploads are deleted from the theme that is live, so with
                // those edits only once their save has landed
                if (editedSince) {
                    _afterThemeSaved = deleteUnpublishedUploads;
                    try { injectLive(); } catch (x) { console.warn('[Theme Pro] Publish follow-up failed:', x); }
                } else {
                    deleteUnpublishedUploads(state);
                }
                // As syncToServer does: the valve-postprocessed CSS, into
                // localStorage now that Draft is off
                r.json().then(d => {
                    try { Storage.setRaw('css_cache', (d && d.css) ? d.css : css); } catch(x) {}
                }).catch(() => {});
            } else {
                // A proxy's 502/504 page is not JSON
                r.json().catch(() => null).then(d => showToast('Publish failed: ' + ((d && d.error) || ('HTTP ' + r.status))));
            }
        }).catch(e => showToast('Publish error: ' + e.message));
    }

    function syncToServer(css, sections, stateStr) {
        if (_draftMode) return;
        _lastLocalSave = Date.now();
        const settle = !_userActed;
        // Personal mode holds saves until the theme actually changes, so
        // opening the designer, or switching it between modes, never turns
        // the instance theme into the user's own.
        // Decided here, not in the personal block at the end of the page:
        // the designer's first sync runs while the page is still loading.
        if (window.__TDP_HOLD_SAVES__ === undefined) {
            const cfg = window.__THEME_PRO_CONFIG__ || {};
            window.__TDP_HOLD_SAVES__ = cfg.scope === 'me' && !cfg.personalHasTheme;
        }
        if (window.__TDP_HOLD_SAVES__) {
            if (window.__TDP_START_STATE__ === undefined) window.__TDP_START_STATE__ = stateStr;
            if (stateStr === window.__TDP_START_STATE__) return;
            window.__TDP_HOLD_SAVES__ = false;
            window.dispatchEvent(new Event('tdp-personal-saving'));
        }
        // The state is taken now, with the css it belongs to, and never re-read
        // when the debounce fires: every Open WebUI tab's bootloader writes the
        // server's state into this key as its offline fallback, so an admin
        // with Open WebUI open beside the designer has a second writer racing
        // the debounce. Read late, the POST would pair the new css with the
        // previous state, and every client would snap back to the old theme.
        const state = stateStr;
        _latestState = state;
        if (_offeringKept) return;
        if (_themeSaveHeld) { holdPersonalSave(); return; }
        // Function toggled off: the POST would come back 503
        if (_functionDisabled) { failedThemeSave(); return; }
        clearTimeout(_syncTimer);
        // A change after a quiet spell goes out at once, but not in the same
        // tick: one action can commit several times in a row, and those still
        // go as one save. Changes in quick succession (a slider being dragged)
        // wait for a 250ms pause.
        const delay = Date.now() - _lastSyncAt >= 250 ? 40 : 250;
        _syncTimer = setTimeout(() => {
            _lastSyncAt = Date.now();
            // The queue keeps the server persisting saves in order: an earlier
            // request committing after a later one would pair stale CSS with
            // fresh state and broadcast that mix to every client. The sequence
            // number keeps a superseded response from overwriting css_cache.
            const mySeq = ++_syncSeq, epoch = _syncEpoch;
            // 'sections' is the same CSS split into {vars, structural,
            // gradient, custom}, so the bootloader's auth stripping and the
            // custom.css safe subset assemble the parts they need instead of
            // regex-slicing the blob
            _syncQueue = _syncQueue.then(() => epoch !== _syncEpoch ? null : fetch('{ROUTE_BASE}', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ css, state, sections, origin: TAB_ORIGIN, settle })
            }).then(r => {
                if (r.ok) {
                    console.log('[Theme Pro] CSS + state synced to server');
                    if (state === _latestState && THEME_KIND === 'personal') { try { sessionStorage.removeItem(UNSAVED_THEME_KEY); } catch (x) {} }
                    if (_afterThemeSaved) { const run = _afterThemeSaved; _afterThemeSaved = null; run(state); }
                    // The only css_cache write for live edits (injectLive leaves
                    // it to this): the valve-postprocessed CSS the server
                    // returns, the same every other client gets, so other tabs'
                    // 'storage' listeners and the recovery fallback never see
                    // the raw copy, whose opaque sidebar rules flash. No css in
                    // the answer means post-processing changed nothing.
                    return r.json().then(d => {
                        if (d && 'stateTag' in d) {
                            _held[THEME_KIND] = [d.cssTag || null, d.stateTag || null];
                            // An older save of this tab's landed under the held one
                            if (_themeSaveHeld) _personalSaveBase = JSON.stringify(_held.personal.map(plainTag));
                        }
                        if (mySeq !== _syncSeq || epoch !== _syncEpoch) return; // Superseded, or now a draft
                        try { Storage.setRaw('css_cache', (d && d.css) ? d.css : css); } catch(x) {}
                    }).catch(() => {});
                } else if (r.status === 503) {
                    // The function was toggled off while this POST was in
                    // flight. Latch the state the badge SSE would have set a
                    // moment later, so the next edit is held rather than
                    // fired into another rejection.
                    _functionDisabled = true;
                    failedThemeSave(epoch);
                } else if (saveCanRetry(r.status)) {
                    console.warn('[Theme Pro] Server sync failed');
                    failedThemeSave(epoch);
                } else {
                    // It would fail the same way again. A proxy's error page is not JSON.
                    return r.json().catch(() => null).then(d => showToast('⚠️ Server refused the save: ' + ((d && d.error) || ('HTTP ' + r.status))));
                }
            }).catch(e => {
                console.warn('[Theme Pro] Server sync error:', e);
                failedThemeSave(epoch);
            }));
        }, delay);
    }

    // --- Library saves (gallery themes and presets) ---
    let _libTimer = null;
    let _libQueue = Promise.resolve();
    function syncLibrary() {
        if (_libraryStale) {
            noteLibraryDropped();
            showToast('⚠️ Gallery changes are paused until this page reloads: the gallery changed elsewhere');
            return;
        }
        // While the function is off the endpoint answers 503, so an import or
        // snapshot made now is held, and goes with the next library change.
        if (_functionDisabled) {
            _librarySavePending = true;
            noticeSaveBlocked();
            return;
        }
        _lastLocalSave = Date.now();
        clearTimeout(_libTimer);
        _libTimer = setTimeout(postLibrary, 500);
    }
    // A library change still waiting out its debounce goes out now. Resolves
    // once every library save and upload queued so far has answered.
    function flushLibrary() {
        if (_libTimer !== null) {
            clearTimeout(_libTimer);
            postLibrary();
        }
        return _libQueue;
    }
    function postLibrary() {
        _libTimer = null;
        if (_libraryStale) return;
        const library = JSON.stringify({
            snapshots: getSnapshots(),
            canvas_presets: typeof CANVAS_PRESETS !== 'undefined' ? CANVAS_PRESETS : [],
            css_presets: typeof CSS_PRESETS !== 'undefined' ? CSS_PRESETS : [],
            gradient_presets: typeof CUSTOM_GRADIENT_PRESETS !== 'undefined' ? CUSTOM_GRADIENT_PRESETS : []
        });
        // Library only: CSS and state go through syncToServer alone, so two
        // writers never race. Queued like syncToServer: each POST replaces the
        // whole library, so a slow earlier one landing after a later one would
        // erase the newer presets.
        // Checked again at send time: one queued before the pause stays unsent
        _libQueue = _libQueue.then(() => _libraryStale ? (noteLibraryDropped(), null) : fetch('{ROUTE_BASE}', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ css: '', state: '', library, origin: TAB_ORIGIN, settle: !_userActed })
        })).then(r => {
            if (!r) return;
            if (r.ok) {
                console.log('[Theme Pro] Library synced to server');
                _librarySavePending = false;  // Each save sends the whole library
                return r.json().then(d => { if (d && 'tag' in d) _held.library = [d.tag || null, null]; }).catch(() => {});
            }
            if (r.status === 503) {
                // Toggled off while this POST was in flight, as in syncToServer
                _functionDisabled = true;
                _librarySavePending = true;
                noticeSaveBlocked();
            } else if (saveCanRetry(r.status)) {
                console.warn('[Theme Pro] Library sync failed');
                _librarySavePending = true;
                showToast('⚠️ Library sync failed. Gallery changes are kept on this page and sent with your next one.');
            } else {
                _librarySavePending = false;
                return r.json().catch(() => null).then(d => showToast('⚠️ Server refused the library save: ' + ((d && d.error) || ('HTTP ' + r.status))));
            }
        }).catch(e => {
            console.warn('[Theme Pro] Library sync error:', e);
            _librarySavePending = true;
            showToast('⚠️ Library sync failed. Gallery changes are kept on this page and sent with your next one.');
        });
    }

    function downloadFile(data, filename, mimeType = 'application/json') {
        const content = typeof data === 'string' ? data : JSON.stringify(data, null, 2);
        const blob = new Blob([content], { type: mimeType });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = filename;
        a.click();
        // Revoking in the same tick can cancel the download in Firefox and
        // Safari before it has read the blob
        setTimeout(() => URL.revokeObjectURL(url), 60000);
    }

    function downloadAllBackups() {
        const dateStr = new Date().toISOString().split('T')[0];
        const snapshots = getSnapshots();
        let count = 0;
        if (snapshots.length > 0) { downloadFile({ themes: snapshots, isLibraryBackup: true, version: "{VERSION}" }, `owui-themes-backup-${dateStr}.json`); count++; }
        if (CSS_PRESETS.length > 0) { downloadFile({ css_presets: CSS_PRESETS, isCssBackup: true, version: "{VERSION}" }, `owui-css-backup-${dateStr}.json`); count++; }
        if (CANVAS_PRESETS.length > 0) { downloadFile({ canvas_presets: CANVAS_PRESETS, isCanvasBackup: true, version: "{VERSION}" }, `owui-canvas-backup-${dateStr}.json`); count++; }
        if (CUSTOM_GRADIENT_PRESETS.length > 0) { downloadFile({ gradient_presets: CUSTOM_GRADIENT_PRESETS, isGradientBackup: true, version: "{VERSION}" }, `owui-gradient-presets-backup-${dateStr}.json`); count++; }
        return count;
    }

    function minifyCss(css) {
        return css.replace(/\/\*[\s\S]*?\*\//g, '').replace(/\n/g, ' ').replace(/\s{2,}/g, ' ')
                  .replace(/{\s+/g, '{').replace(/}\s+/g, '}').replace(/;\s+/g, ';').replace(/:\s+/g, ':').trim();
    }

    // --- Modals ---
    function buildModals() {
        const ctr = $('modal-factory-container');
        if (!ctr) return;

        const close = id => `onclick="hideModal('${id}')"`;
        const nameSpan = id => `<span id="${id}" style="color:var(--text-main); font-weight:bold; display:inline-block; vertical-align:bottom; max-width:200px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;"></span>`;

        const V = {
            danger:  { panel: ' modal-panel-danger',  tc: '#ef4444',      ic: 'modal-icon-danger', bc: 'btn btn-danger',  bs: 'flex:1; background:#ef4444 !important; border:none; color:white !important;' },
            info:    { panel: ' modal-panel-info',     tc: 'var(--accent)', ic: 'modal-icon-info',   bc: 'btn btn-primary', bs: 'flex:1; background:var(--accent-fill) !important; border:none; color:white !important;' },
            neutral: { panel: ' modal-panel-neutral',  tc: 'var(--accent)', ic: 'modal-icon-save',   bc: 'btn btn-primary', bs: 'flex:1;' },
            bare:    { panel: '',                      tc: 'var(--accent)', ic: '',                  bc: 'btn btn-primary', bs: 'flex:1;' },
        };

        function buildConfirm(d) {
            const v = V[d.variant || 'danger'];
            const zCls = d.zClass ? ` ${d.zClass}` : '';
            const icon = d.icon ? `<div class="modal-icon ${d.iconCls || v.ic}">${d.icon}</div>` : '';
            const mb = d.msgMb || '28px';
            const extra = d.msgCenter ? ' text-align:center;' : '';
            const bCls = d.btnCls || v.bc;
            const bStyle = d.btnStyle || v.bs;
            const center = d.noCenter ? '' : ' justify-content:center;';
            const msgId = d.msgId ? ` id="${d.msgId}"` : '';
            let cbHtml = '';
            if (d.cb) {
                const chk = d.cb.checked ? ' checked' : '';
                cbHtml = `<label style="display:flex; align-items:center; justify-content:center; gap:8px; margin-bottom:24px; cursor:pointer; font-size:0.75rem; color:var(--text-muted); user-select:none;"><input type="checkbox" id="${d.cb.id}"${chk} style="cursor:pointer;">${d.cb.label}</label>`;
            }
            return `<div id="${d.id}" class="modal-overlay${zCls}" role="dialog" aria-modal="true" aria-labelledby="${d.id}-title"><div class="control-group modal-panel${v.panel}">${icon}<div class="section-title" id="${d.id}-title" style="color:${v.tc}; justify-content:center; margin-bottom: 8px;">${d.title}</div><p${msgId} style="font-size: 0.75rem; color:var(--text-muted); margin-bottom:${mb}; line-height:1.6;${extra}">${d.msg}</p>${d.extraHtml || ''}${cbHtml}<div style="display:flex; flex-wrap:wrap; gap:12px;${center}"><button class="btn" style="flex:1; min-width:110px;" ${close(d.id)}>${d.cancelLabel || 'Cancel'}</button>${d.secondaryId ? `<button class="btn" id="${d.secondaryId}" style="flex:1; min-width:110px;">${d.secondaryLabel}</button>` : ''}<button class="${bCls}" id="${d.confirmId}" style="${bStyle}">${d.confirmLabel}</button></div></div></div>`;
        }

        function buildInput(d) {
            const v = V[d.variant || 'neutral'];
            const zCls = d.zClass ? ` ${d.zClass}` : '';
            const icon = d.icon ? `<div class="modal-icon ${d.iconCls || v.ic}">${d.icon}</div>` : '';
            const titleMb = d.icon ? '8px' : '16px';
            const desc = d.desc ? `<p style="font-size: 0.75rem; color:var(--text-muted); margin-bottom:20px; text-align:center;">${d.desc}</p>` : '';
            const center = d.noCenter ? '' : ' justify-content:center;';
            return `<div id="${d.id}" class="modal-overlay${zCls}" role="dialog" aria-modal="true" aria-labelledby="${d.id}-title"><div class="control-group modal-panel${v.panel}">${icon}<div class="section-title" id="${d.id}-title" style="color:${v.tc}; justify-content:center; margin-bottom: ${titleMb};">${d.title}</div>${desc}<input type="text" id="${d.inputId}" class="modal-input" placeholder="${d.placeholder}"><div style="display:flex; gap:12px;${center}"><button class="btn" style="flex:1;" ${close(d.id)}>Cancel</button><button class="btn btn-primary" id="${d.confirmId}" style="flex:1;">${d.confirmLabel}</button></div></div></div>`;
        }

        function buildImport(d) {
            const zCls = d.zClass ? ` ${d.zClass}` : '';
            return `<div id="${d.id}" class="modal-overlay${zCls}" role="dialog" aria-modal="true" aria-labelledby="${d.id}-title"><div class="control-group modal-panel-save" style="width: 480px;"><div class="modal-icon modal-icon-save">\u{1F4E5}</div><div class="section-title" id="${d.id}-title" style="margin-bottom: 16px;">${d.title}</div><p style="font-size: 0.75rem; color:var(--text-muted); margin-bottom:20px; line-height:1.6;">${d.desc}</p><div class="metadata-field" style="margin-bottom: 20px;"><div class="flex-center-gap8"><input type="text" id="${d.urlId}" placeholder="${d.urlPlaceholder}" style="flex:1; width:100%; background: var(--bg-deep) !important; border: 1px solid var(--border) !important; color: var(--text-main) !important; padding: 9px 11px; border-radius: 10px; font-family: 'Inter', sans-serif; font-size: 0.78rem; outline: none; transition: border-color 0.2s; box-sizing: border-box;"><button class="btn" id="${d.loadBtnId}" style="flex-shrink:0; display:flex; align-items:center; gap:6px;">${ICONS.download} Load URL</button></div><div id="${d.statusId}" style="display:none; margin-top:10px; font-size:0.7rem; padding:8px 12px; border-radius:8px;"></div></div><div style="display:flex; gap:12px; justify-content:flex-end; border-top: 1px solid var(--border); padding-top: 16px;"><button class="btn" ${close(d.id)}>Cancel</button><button class="btn" id="${d.fileBtnId}" style="display:flex; align-items:center; gap:6px;">${ICONS.file} Import File</button></div></div></div>`;
        }

        const canvasWarning = `<div id="canvas-warning" style="display:none; background:rgba(239, 68, 68, 0.1); border:1px solid rgba(239, 68, 68, 0.3); border-radius:12px; padding:12px; margin-bottom:20px; text-align:left;"><div style="color:#ef4444; font-size:0.7rem; font-weight:bold; margin-bottom:4px; display:flex; align-items:center; gap:6px;"><span>\u26A0\uFE0F</span> Security Warning</div><p style="font-size:0.65rem; color:var(--text-muted); margin:0;">This theme contains <b>Canvas FX animation scripts</b>. Only import if you trust the source.</p></div>`;

        const defs = [
            // ── Confirm: any question askConfirm puts ──
            { t:'c', id:'ask-modal', icon:'!', title:'Are you sure?', msg:'', msgId:'ask-modal-msg', confirmId:'ask-modal-confirm-btn', confirmLabel:'Continue', zClass:'z-top' },
            // ── Confirm: Delete with name ──
            { t:'c', id:'delete-modal', icon:'!', title:'Delete Theme?', msg:'Are you sure you want to permanently remove "'+nameSpan('delete-theme-name')+'"?', confirmId:'confirm-delete-btn', confirmLabel:'Delete' },
            { t:'c', id:'overwrite-modal', icon:'💾', title:'Overwrite Theme?', msg:'This will replace all saved data in "'+nameSpan('overwrite-theme-name')+'" with your current configuration. This cannot be undone.', confirmId:'confirm-overwrite-btn', confirmLabel:'Overwrite', variant:'info' },
            { t:'c', id:'delete-canvas-modal', icon:'!', title:'Delete Preset?', msg:'Are you sure you want to permanently remove "'+nameSpan('delete-canvas-name')+'"? This cannot be undone.', confirmId:'confirm-delete-canvas-btn', confirmLabel:'Delete' },
            { t:'c', id:'delete-css-modal', icon:'!', title:'Delete Snippet?', msg:'Are you sure you want to permanently remove "'+nameSpan('delete-css-name')+'"? This cannot be undone.', confirmId:'confirm-delete-css-btn', confirmLabel:'Delete' },
            { t:'c', id:'delete-gradient-modal', variant:'danger', title:'Delete Gradient Preset?', msg:'Are you sure you want to delete "'+nameSpan('delete-gradient-name')+'"?', msgMb:'20px', msgCenter:true, noCenter:true, confirmId:'confirm-delete-gradient-btn', confirmLabel:'Delete', btnCls:'btn btn-danger', btnStyle:'flex:1;' },

            // ── Confirm: Mass delete ──
            { t:'c', id:'delete-all-themes-modal', icon:'!', title:'Wipe Theme Gallery?', msg:'Are you sure you want to permanently remove <b>ALL</b> saved themes from your gallery?', confirmId:'confirm-delete-all-themes-btn', confirmLabel:'Wipe All' },
            { t:'c', id:'delete-all-canvas-modal', icon:'!', title:'Wipe Canvas Presets?', msg:'Are you sure you want to permanently remove <b>ALL</b> saved animation scripts? This cannot be undone.', confirmId:'confirm-delete-all-canvas-btn', confirmLabel:'Wipe All' },
            { t:'c', id:'delete-all-css-modal', icon:'!', title:'Wipe CSS Snippets?', msg:'Are you sure you want to permanently remove <b>ALL</b> saved CSS snippets? This cannot be undone.', confirmId:'confirm-delete-all-css-btn', confirmLabel:'Wipe All' },
            { t:'c', id:'delete-all-gradient-modal', icon:'!', title:'Wipe Gradient Presets?', msg:'Are you sure you want to permanently remove <b>ALL</b> saved gradient presets? Built-in presets will not be affected. This cannot be undone.', confirmId:'confirm-delete-all-gradient-btn', confirmLabel:'Wipe All' },

            // ── Confirm: Community Install All ──
            { t:'c', id:'install-all-confirm-modal', icon:'\u2B07\uFE0F', title:'Install All Community Themes?', msg:'<span id="install-all-msg"></span>', confirmId:'confirm-install-all-btn', confirmLabel:'Install All' },

            // ── Confirm: Danger with backup checkbox ──
            { t:'c', id:'nuclear-modal', icon:'\u2622\uFE0F', title:'Global Reset?', msg:'This will wipe all active overrides across ALL modes.', msgMb:'20px', confirmId:'confirm-nuclear-btn', confirmLabel:'Wipe', cb:{ id:'nuclear-backup-cb', label:'Create a backup snapshot' } },
            { t:'c', id:'factory-reset-modal', zClass:'z-top', icon:'\u{1F6A8}', title:'Factory Reset?', msg:'This will permanently WIPE all themes, snapshots, and settings. This action is irreversible.', msgMb:'20px', confirmId:'confirm-factory-reset-btn', confirmLabel:'Wipe All', cb:{ id:'factory-backup-cb', label:'Export a backup before wiping', checked:true } },
            { t:'c', id:'reset-modal', icon:'\u267B\uFE0F', title:'Reset Mode?', msg:'Are you sure you want to reset the <b><span id="reset-target-mode"></span></b> mode? All color overrides, locks, custom CSS, and Canvas FX for this mode will be wiped, and the Backgrounds tab goes back to its defaults in every mode.', msgMb:'20px', confirmId:'confirm-reset-btn', confirmLabel:'Reset Mode', cb:{ id:'reset-backup-cb', label:'Create a backup snapshot' } },

            // ── Confirm: Info ──
            { t:'c', id:'reset-all-confirm-modal', variant:'info', icon:'\u{1F512}', title:'Reset Overrides', msg:'Cannot reset because all color variable overrides are currently locked. Would you like to unlock all variables now?', confirmId:'confirm-reset-all-confirm-btn', confirmLabel:'Unlock & Reset' },
            { t:'c', id:'export-all-backups-modal', zClass:'z-top', variant:'info', icon:'\u{1F4E6}', title:'Export All Backups', msgId:'export-all-backups-desc', msg:'This will download separate <b>.json</b> backup files for your <b>Theme Gallery</b>, <b>CSS Snippets</b>, <b>Canvas Scripts</b>, and <b>Gradient Presets</b> (if any exist).', confirmId:'confirm-export-all-backups-btn', confirmLabel:'Export' },
            { t:'c', id:'import-clipboard-modal', variant:'info', icon:'\u{1F4CB}', title:'Import from Clipboard?', msg:"We've detected a theme configuration on your clipboard. Would you like to import and apply it now?", msgMb:'20px', confirmId:'confirm-clipboard-import-btn', confirmLabel:'Import & Apply', btnCls:'btn btn-primary', btnStyle:'flex:1; min-width:110px;', secondaryId:'clipboard-import-noapply-btn', secondaryLabel:'Import Without Applying', extraHtml:canvasWarning },

            // ── Save/Name ──
            { t:'i', id:'save-canvas-modal', zClass:'z-low', icon:'\u{1F3A8}', title:'Save Canvas Preset', desc:'Save the current animation as a reusable preset.', inputId:'canvas-name-input', placeholder:'Preset Name', confirmId:'confirm-save-canvas-btn', confirmLabel:'Save Preset' },
            { t:'i', id:'save-css-modal', zClass:'z-low', icon:'\u2702\uFE0F', title:'Save CSS Snippet', desc:'Save the current Custom CSS as a reusable snippet.', inputId:'css-name-input', placeholder:'Snippet Name', confirmId:'confirm-save-css-btn', confirmLabel:'Save Snippet' },
            { t:'i', id:'save-gradient-modal', variant:'bare', title:'Save Gradient Preset', inputId:'gradient-preset-name-input', placeholder:'Preset Name', confirmId:'confirm-save-gradient-btn', confirmLabel:'Save', noCenter:true },

            // ── Rename ──
            { t:'i', id:'rename-canvas-modal', icon:'\u270F\uFE0F', iconCls:'modal-icon-info', title:'Rename Preset', desc:'Enter a new name for this animation:', inputId:'rename-canvas-input', placeholder:'Preset Name', confirmId:'confirm-rename-canvas-btn', confirmLabel:'Rename' },
            { t:'i', id:'rename-css-modal', icon:'\u270F\uFE0F', iconCls:'modal-icon-info', title:'Rename Snippet', desc:'Enter a new name for this snippet:', inputId:'rename-css-input', placeholder:'Snippet Name', confirmId:'confirm-rename-css-btn', confirmLabel:'Rename' },
            { t:'i', id:'rename-gradient-modal', variant:'bare', title:'Rename Gradient Preset', inputId:'rename-gradient-input', placeholder:'New Name', confirmId:'confirm-rename-gradient-btn', confirmLabel:'Rename', noCenter:true },

            // ── Import + URL ──
            { t:'im', id:'import-theme-modal', zClass:'z-low', title:'Import Community Theme', desc:'Load a custom theme by providing a URL to a valid theme.json file.', urlId:'import-url-input', urlPlaceholder:'https://example.com/theme.json', loadBtnId:'import-url-load-btn', statusId:'import-url-status', fileBtnId:'import-file-trigger-btn' },
            { t:'im', id:'import-css-modal', zClass:'z-low', title:'Import CSS Snippet', desc:'Load a CSS snippet by providing a URL to a valid .css or .json file, or import from your device.', urlId:'import-css-url-input', urlPlaceholder:'https://example.com/snippet.css', loadBtnId:'import-css-url-load-btn', statusId:'import-css-url-status', fileBtnId:'import-css-file-trigger-btn' },
            { t:'im', id:'import-canvas-modal', zClass:'z-low', title:'Import Canvas Script', desc:'Load a canvas animation by providing a URL to a valid .js or .json file, or import from your device.', urlId:'import-canvas-url-input', urlPlaceholder:'https://example.com/animation.js', loadBtnId:'import-canvas-url-load-btn', statusId:'import-canvas-url-status', fileBtnId:'import-canvas-file-trigger-btn' },
            { t:'im', id:'import-gradient-modal', zClass:'z-low', title:'Import Gradient Presets', desc:'Load gradient presets by providing a URL to a valid .json file, or import from your device.', urlId:'import-gradient-url-input', urlPlaceholder:'https://example.com/gradients.json', loadBtnId:'import-gradient-url-load-btn', statusId:'import-gradient-url-status', fileBtnId:'import-gradient-file-trigger-btn' },
        ];

        ctr.innerHTML = defs.map(d => {
            if (d.t === 'c') return buildConfirm(d);
            if (d.t === 'i') return buildInput(d);
            if (d.t === 'im') return buildImport(d);
        }).join('');
    }
    buildModals();
    hydrateIcons();
    hydrateToolbars();

    const TIMING = { tooltipFade: 160, toastDuration: 2500, editorDebounce: 500, historyDebounce: 800, wheelDebounce: 400, gradientStopDebounce: 600, historyLimit: 50 };
    const createNullModeMap = () => ({ dark: null, oled: null, light: null, her: null });

