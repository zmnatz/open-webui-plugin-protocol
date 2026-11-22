    // --- Ignored Updates ---
    let ignoredUpdates = Storage.get('ignored_updates', {});
    // Keyed by updateUrl, so a stored array is unusable
    if (Array.isArray(ignoredUpdates)) ignoredUpdates = {};

    function isUpdateIgnored(updateUrl, localVersion, remoteVersion) {
        if (!updateUrl) return false;
        const entry = ignoredUpdates[updateUrl];
        if (!entry) return false;
        // Legacy format (plain string): matched the remote version regardless
        // of the local version. Migrate lazily to the transition pair so a
        // later local-version change makes the update visible again.
        if (typeof entry === 'string') {
            if (entry !== remoteVersion) return false;
            ignoreUpdate(updateUrl, localVersion, remoteVersion);
            return true;
        }
        return entry.from === localVersion && entry.to === remoteVersion;
    }

    function ignoreUpdate(updateUrl, localVersion, remoteVersion) {
        if (!updateUrl) return;
        // Ignore the specific transition (from → to), not the target version:
        // if the user's local version changes (e.g. manually edited in the
        // library), the same remote version is offered again.
        ignoredUpdates[updateUrl] = { from: localVersion || '0.0.0', to: remoteVersion };
        Storage.set('ignored_updates', ignoredUpdates);
    }

    // --- Update Diff Builder ---
    const MODE_DOTS = { dark: '#6366f1', light: '#fbbf24', oled: '#1e1e1e', her: '#ec4899' };
    const UPDATE_DIFF_SECTION_NAMES = {
        palette: 'Palette', overrides: 'Overrides', css: 'Custom CSS', canvas: 'Canvas FX',
        gradient: 'Gradient', surfaces: 'Surfaces', auth: 'Auth pages'
    };
    let _updateDiffCounter = 0;

    function buildUpdateDiffHtml(local, remote) {
        const prefix = `ud${_updateDiffCounter++}`;
        _codeDiffIdCounter = 0;
        let html = '<div class="update-diff-container">';

        MODES.forEach(mode => {
            if (!local[mode] || !remote[mode]) return;
            // Remote values are unchecked JSON: normalizeModeData gives every
            // field its type before anything reads it
            const lm = normalizeModeData(structuredClone(local[mode]));
            const rm = normalizeModeData(structuredClone(remote[mode]));

            const changes = modeSectionDiffs(lm, rm).map(section => {
                let name = UPDATE_DIFF_SECTION_NAMES[section], html = '';
                if (section === 'palette') {
                    html = _renderPaletteDiff({ src: _paletteView(lm), tgt: _paletteView(rm), srcOverrides: lm.overrides, tgtOverrides: rm.overrides });
                } else if (section === 'overrides') {
                    const ovrKeys = [...new Set([...Object.keys(lm.overrides), ...Object.keys(rm.overrides)])];
                    const ovrDiffs = ovrKeys.filter(k => lm.overrides[k] !== rm.overrides[k]);
                    if (ovrDiffs.length > 0) {
                        name += ` (${ovrDiffs.length})`;
                        html = _renderOverridesDiff({ src: lm.overrides, tgt: rm.overrides });
                    }
                } else if (section === 'css' && lm.customCSS !== rm.customCSS) {
                    html = _renderCodeDiffClickable(lm.customCSS, rm.customCSS, mode, `${prefix}-css`, '', '');
                } else if (section === 'canvas' && lm.canvasScript !== rm.canvasScript) {
                    html = _renderCodeDiffClickable(lm.canvasScript, rm.canvasScript, mode, `${prefix}-canvas`, '', '');
                } else if (section === 'gradient') {
                    html = _renderGradientDiff({ src: _gradientView(lm), tgt: _gradientView(rm) });
                } else if (section === 'surfaces') {
                    html = _renderSurfacesDiff({ src: SURFACE_FIELDS.map(k => lm[k]), tgt: SURFACE_FIELDS.map(k => rm[k]) });
                } else if (section === 'auth') {
                    html = _renderAuthDiff({ srcAuth: MODE_SECTION_FIELDS.auth.map(k => lm[k]), tgtAuth: MODE_SECTION_FIELDS.auth.map(k => rm[k]) });
                }
                return { name, html: html + _renderSectionExtras(section, lm, rm, `${prefix}-${mode}`) };
            });

            const modeLabel = mode.charAt(0).toUpperCase() + mode.slice(1);
            const dotColor = MODE_DOTS[mode] || '#888';
            const dotBorder = mode === 'oled' ? '; border: 1px solid #444' : '';
            const sectionId = `${prefix}-${mode}`;
            const badge = changes.length > 0
                ? `<span class="update-diff-badge changed">${changes.length} change${changes.length !== 1 ? 's' : ''}</span>`
                : `<span class="update-diff-badge same">✓ in sync</span>`;

            html += `<div class="update-diff-section">`;
            html += `<button type="button" class="plain-button update-diff-header" aria-expanded="false" onclick="window._toggleUpdateDiffMode('${sectionId}', this)">`;
            html += `<span class="mode-dot" style="background:${dotColor}${dotBorder}"></span>`;
            html += `${modeLabel} Mode ${badge}`;
            html += `<span class="chevron">▼</span></button>`;
            html += `<div class="update-diff-body" id="${sectionId}">`;

            if (changes.length > 0) {
                changes.forEach(ch => {
                    html += `<div class="update-diff-sub">${ch.name}</div>`;
                    html += ch.html;
                });
            } else {
                html += `<div style="font-size:0.55rem; color:var(--text-muted); opacity:0.6; padding:4px 0;">No changes in this mode.</div>`;
            }

            html += `</div></div>`;
        });

        html += '</div>';
        return html;
    }

    window._toggleUpdateDiffMode = function(id, headerEl) {
        const body = document.getElementById(id);
        if (!body) return;
        const isOpen = body.classList.contains('visible');
        body.classList.toggle('visible', !isOpen);
        headerEl.classList.toggle('expanded', !isOpen);
        headerEl.setAttribute('aria-expanded', String(!isOpen));
    };

    window._toggleBatchDiff = async function(diffId, btn, snapIndex, viaManifest) {
        const panel = document.getElementById(diffId);
        if (!panel) return;

        if (panel.style.display !== 'none') {
            panel.style.display = 'none';
            btn.textContent = '▸ Diff';
            return;
        }

        if (panel.dataset.loaded) {
            panel.style.display = 'block';
            btn.textContent = '▾ Diff';
            return;
        }

        const snapshots = getSnapshots();
        const local = snapshots[snapIndex];
        if (!local) return;

        let remote;
        if (viaManifest) {
            // Lazy-fetch remote data for manifest-based updates
            btn.textContent = '⏳';
            btn.disabled = true;
            try {
                const url = window._pendingBatchMeta[snapIndex];
                remote = await fetchThemeData(url);
            } catch (e) {
                panel.innerHTML = `<div style="font-size:0.65rem; color:#ef4444; padding:8px 0;">Failed to load diff: ${_esc(e.message)}</div>`;
                panel.style.display = 'block';
                btn.textContent = '▾ Diff';
                btn.disabled = false;
                return;
            }
            btn.disabled = false;
        } else {
            remote = window._pendingBatchUpdates[snapIndex];
        }

        if (!remote) {
            panel.innerHTML = `<div style="font-size:0.65rem; color:var(--text-muted); opacity:0.6; padding:8px 0;">No diff data available.</div>`;
        } else {
            panel.innerHTML = buildUpdateDiffHtml(local, remote);
        }
        panel.dataset.loaded = '1';
        panel.style.display = 'block';
        btn.textContent = '▾ Diff';
    };

    // Remote theme JSON is unnormalized until the update is applied, so any
    // field may be a non-string
    function _remoteText(v) {
        return typeof v === 'string' ? v.trim() : '';
    }

    // 'adds' | 'none' | 'unknown'. A Canvas FX script runs on every user's
    // page, on the main thread when it references `document`, and with the
    // viewer's auth token when the Canvas API Access valve is on, so a theme
    // benign at install can turn hostile by changing what its updateUrl serves.
    // 'unknown' is a manifest match: only versions were compared and the body
    // is fetched lazily, so it must read as a caution, never an all-clear.
    function canvasUpdateRisk(local, remote) {
        if (!remote) return 'unknown';
        const adds = MODES.some(m => {
            const r = remote[m], l = local && local[m];
            const rs = _remoteText(r && r.canvasScript);
            const ls = _remoteText(l && l.canvasScript);
            if (rs && rs !== ls) return true;
            // Turning canvasEnabled on also counts: execution is gated on
            // canvasEnabled AND canvasScript, so an unchanged dormant script
            // starts running
            if (rs && !!(r && r.canvasEnabled) && !(l && l.canvasEnabled)) return true;
            return false;
        });
        return adds ? 'adds' : 'none';
    }

    function updateAddsCanvasCode(local, remote) {
        return canvasUpdateRisk(local, remote) === 'adds';
    }

    // customCSS and manualOverrides are free-form by design, and the widest
    // channel into the stylesheet served to every user: selector-based
    // exfiltration and UI spoofing live here, so a change gets the same notice
    // as a script.
    function updateAddsRemoteCss(local, remote) {
        if (!remote) return false;
        return MODES.some(m => {
            const r = remote[m], l = local && local[m];
            if (!r) return false;
            const pairs = [['customCSS', 'customCssEnabled'], ['manualOverrides', 'manualOverridesEnabled']];
            return pairs.some(([txt, flag]) => {
                const rs = _remoteText(r[txt]);
                const ls = _remoteText(l && l[txt]);
                if (rs && rs !== ls) return true;
                return !!(rs && r[flag] && !(l && l[flag]));
            });
        });
    }

    function renderCanvasUpdateWarning(el, local, remote) {
        if (!el) return;
        const risk = canvasUpdateRisk(local, remote);
        const cssChanged = updateAddsRemoteCss(local, remote);
        if (risk !== 'adds' && !cssChanged) { el.style.display = 'none'; el.innerHTML = ''; return; }
        const parts = [];
        if (risk === 'adds') {
            parts.push(`This update adds or changes a <b>Canvas FX animation script</b> (JavaScript). It will run in the browser of <b>every user</b> on this instance.`);
        }
        if (cssChanged) {
            parts.push(`This update changes <b>custom CSS</b>, which is applied instance-wide and can restyle or overlay any part of the interface.`);
        }
        el.style.display = 'block';
        el.innerHTML = `<div style="color:#ef4444; font-size:0.7rem; font-weight:bold; margin-bottom:4px; display:flex; align-items:center; gap:6px;"><span>&#9888;&#65039;</span> Security Warning</div>`
            + `<p style="font-size:0.65rem; color:var(--text-muted); margin:0;">${parts.join(' ')} Review the diff below and only update if you trust the source.</p>`;
    }

    window.checkSingleUpdate = async (index) => {
        try {
            showToast('Checking for update...');
            const result = await checkThemeUpdate(index);

            if (!result) {
                showToast('✓ Theme is up to date!');
                return;
            }
            if (result.error) {
                showToast(`Error: ${result.error}`);
                return;
            }

            pendingUpdate = result;
            const info = $('update-modal-info');
            const details = $('update-modal-details');
            info.innerHTML = `<b>${_esc(result.local.name)}</b> has an update available.`;

            let detailsHtml = `<div style="display:flex; justify-content:space-between; margin-bottom:8px;"><span>Current version</span><span style="color:var(--text-main); font-weight:700;">v${_esc(result.localVersion)}</span></div>`;
            detailsHtml += `<div style="display:flex; justify-content:space-between; margin-bottom:8px;"><span>Available version</span><span style="color:#10b981; font-weight:700;">v${_esc(result.remoteVersion)}</span></div>`;
            if (result.remote.author) detailsHtml += `<div style="display:flex; justify-content:space-between;"><span>Author</span><span style="color:var(--text-main);">${_esc(result.remote.author)}</span></div>`;
            if (result.remote.description) detailsHtml += `<div style="margin-top:10px; padding-top:10px; border-top:1px solid var(--border); font-style:italic;">${_esc(result.remote.description)}</div>`;
            details.innerHTML = detailsHtml;

            renderCanvasUpdateWarning($('update-canvas-warning'), result.local, result.remote);

            const diffToggleWrap = $('update-diff-toggle-wrap');
            const diffPanel = $('update-diff-panel');
            const diffToggleBtn = $('update-diff-toggle-btn');
            if (result.remote) {
                const diffHtml = buildUpdateDiffHtml(result.local, result.remote);
                diffPanel.innerHTML = diffHtml;
                diffPanel.style.display = 'none';
                diffToggleWrap.style.display = '';
                diffToggleBtn.textContent = '▸ View Changes';
            } else {
                diffToggleWrap.style.display = 'none';
                diffPanel.style.display = 'none';
            }

            showModal('update-modal');
        } catch (e) {
            console.error('Update check failed:', e);
            showToast(`Error: ${e.message}`);
        }
    };

    $('update-skip-btn').addEventListener('click', () => {
        hideModal('update-modal');
        pendingUpdate = null;
    });

    $('update-ignore-btn').addEventListener('click', () => {
        if (pendingUpdate) {
            ignoreUpdate(pendingUpdate.local.updateUrl, pendingUpdate.localVersion, pendingUpdate.remoteVersion);
            showToast(`Ignored v${pendingUpdate.localVersion} → v${pendingUpdate.remoteVersion} for "${pendingUpdate.local.name}"`);
        }
        hideModal('update-modal');
        pendingUpdate = null;
    });

    $('update-diff-toggle-btn').addEventListener('click', () => {
        const panel = $('update-diff-panel');
        const btn = $('update-diff-toggle-btn');
        const isOpen = panel.style.display !== 'none';
        panel.style.display = isOpen ? 'none' : 'block';
        btn.textContent = isOpen ? '▸ View Changes' : '▾ Hide Changes';
    });

    $('update-confirm-btn').addEventListener('click', async () => {
        if (pendingUpdate && !pendingUpdate.error) {
            // The modal showed the warning above this button, so the click is
            // the confirmation
            if (await applyThemeUpdate(pendingUpdate.index, pendingUpdate.remote, { alreadyConfirmed: true })) {
                showToast(`Updated "${pendingUpdate.local.name}" to v${pendingUpdate.remoteVersion}!`);
            }
        }
        hideModal('update-modal');
        pendingUpdate = null;
    });

    window.applyAllBatchUpdates = async function() {
        const indices = window._pendingBatchIndices || [];
        if (indices.length === 0) return;

        // One question for the batch: one per theme was dozens of dialogs in a
        // row, the point where a browser offers to stop the page asking
        const snaps = getSnapshots();
        const risky = indices.some(idx => {
            const remote = window._pendingBatchUpdates[idx];
            return !remote || updateAddsCanvasCode(snaps[idx], remote) || updateAddsRemoteCss(snaps[idx], remote);
        });
        if (risky && !(await askConfirm(`Install ${indices.length} update${indices.length === 1 ? '' : 's'}?`,
            'Some of these updates add or change a Canvas FX script, JavaScript that runs in the browser of every user on this instance, or custom CSS, which is applied instance-wide. Each update replaces all four of its theme\'s modes, so changes you made to them are lost.\n\nOnly continue if you trust the source.',
            'Install all'))) {
            showToast('Updates cancelled');
            return;
        }

        // Outcomes are counted, not assumed: applyManifestUpdate fails whenever
        // the import allowlist refuses the host
        let okCount = 0, noSource = 0;
        const failed = [];
        for (const idx of indices) {
            const remote = window._pendingBatchUpdates[idx];
            const manifestUrl = window._pendingBatchMeta[idx];
            let ok = false;
            if (remote) ok = await applyThemeUpdate(idx, remote, { alreadyConfirmed: true });
            else if (manifestUrl) ok = await applyManifestUpdate(idx, manifestUrl, { alreadyConfirmed: true });
            else noSource++;
            if (ok) okCount++;
            else failed.push(idx);
        }

        // Retry re-applies only the failures: a success applied again could hit
        // a snapshot index that has since shifted
        window._pendingBatchIndices = failed.slice();

        const listEl = $('update-results-list');
        if (listEl) {
            listEl.querySelectorAll('button.btn-primary').forEach(btn => {
                const row = btn.closest('[data-update-index]');
                const rowIdx = row ? _attrIndex(row, 'data-update-index') : null;
                if (rowIdx === null || failed.includes(rowIdx)) return;  // leave it actionable
                markUpdateApplied(btn);
            });
        }

        const updateAllBtn = $('update-all-btn');
        if (updateAllBtn) {
            updateAllBtn.innerText = failed.length ? 'Retry Failed' : 'All Updated!';
            updateAllBtn.disabled = failed.length === 0;
            updateAllBtn.style.opacity = failed.length ? '1' : '0.5';
        }

        if (failed.length) {
            const why = noSource ? ` (${noSource} with no update source)` : '';
            showToast(`⚠️ Updated ${okCount} of ${indices.length}: ${failed.length} could not be applied${why}`);
        } else {
            showToast(`Updated ${okCount} theme(s)!`);
        }
    };

    // App Initialization
    (function() {
            // The Her tab shows when Open WebUI's easter eggs are on, or when
            // Open WebUI is already in Her mode
            async function initHerMode() {
                const currentTheme = localStorage.getItem('theme') || 'dark';
                const hasHerClass = document.documentElement.classList.contains('her');
                let showHer = (currentTheme === 'her' || hasHerClass);

                try {
                    const headers = { 'Accept': 'application/json' };
                    if (authToken()) headers['Authorization'] = `Bearer ${authToken()}`;

                    let baseUrl = window.location.origin;
                    if (!baseUrl || baseUrl.includes('about:')) baseUrl = '';

                    const res = await fetch(baseUrl + '/api/config', { headers });
                    if (res.ok) {
                        const data = await res.json();
                        if (data?.features?.enable_easter_eggs === true) {
                            showHer = true;
                        } else if (currentTheme !== 'her' && !hasHerClass) {
                            showHer = false;
                        }
                    }
                } catch(e) { console.warn('Theme Pro:', e); }

                // Her mode's defaults above may have changed the theme
                if (historyIndex === 0) resetHistoryBaseline(); else pushState();

                const herBtn = document.getElementById('mode-btn-her');
                if (showHer) {
                    if (herBtn) herBtn.style.display = 'flex';
                } else {
                    if (herBtn) herBtn.style.display = 'none';
                    if (activeMode === 'her') {
                        document.querySelector('.mode-btn[data-mode="dark"]').click();
                    }
                }
            }
            initHerMode();

            // Follow Open WebUI's own theme switch in another tab
            window.addEventListener('storage', (e) => {
                if (e.key === 'theme' && e.newValue) {
                    let targetMode = e.newValue;
                    if (targetMode === 'oled-dark') targetMode = 'oled';

                    if (targetMode === 'her') {
                        const herBtn = document.getElementById('mode-btn-her');
                        if (herBtn) herBtn.style.display = 'flex';
                    }

                    const modeBtn = document.querySelector(`.mode-btn[data-mode="${targetMode}"]`);
                    if (modeBtn && activeMode !== targetMode) modeBtn.click();
                }
            });

            // Load the saved state, migrating legacy formats
            let stateLoad = 'pending';
            const personalDesigner = (window.__THEME_PRO_CONFIG__ || {}).scope === 'me';
            // A theme this page can't read must not be saved over by what it
            // opens on instead. The personal designer has no Draft mode.
            function holdUnreadableState() {
                _savedThemeUnreadable = true;
                if (personalDesigner || HIDDEN_APPLY_FRAME) window.__TDP_HOLD_SAVES__ = true;
                else setDraftMode(true);
            }
            function themeShape(s) {
                if (s && _isModeObject(s.dark) && _isModeObject(s.light)) return 'modes';
                if (_isLegacyTheme(s)) return 'legacy';
                return null;
            }
            try {
                if(localStorage) {
                    // Start from the server's saved theme, the way the main
                    // app's bootloader refreshes this key: a copy left by an
                    // earlier visit would otherwise be saved back over a newer
                    // theme the moment the page renders in Live mode.
                    const serverState = window.__THEME_PRO_SAVED_STATE__;
                    // Kept as a value: the storage write can fail, and reading
                    // the key back then gives an older theme, which the load's
                    // save would send over the real one
                    let loaded = Storage.getRaw('theme');
                    if (personalDesigner && _keptUnsaved) {
                        loaded = _keptUnsaved;
                        Storage.setRaw('theme', loaded);
                        // A change, so the load's save goes out as one
                        window.__TDP_START_STATE__ = serverState || '';
                        _userActed = true;
                    } else if (typeof serverState === 'string') {
                        loaded = serverState;
                        Storage.setRaw('theme', loaded);
                    } else if (serverState === null) {
                        loaded = null;
                        try { Storage.remove('theme'); } catch (x) {}
                    }
                    // A draft resumed after a refresh is what this page edits
                    // (_draftMode isn't on yet, so Storage reads the published
                    // copy); the server's theme stays the published one
                    let draftRaw = null;
                    if (_resumingDraft) { try { draftRaw = sessionStorage.getItem(Storage._resolve('theme')); } catch (x) {} }
                    const saved = draftRaw || loaded;
                    if (saved) {
                        const s = JSON.parse(saved);
                        const shape = themeShape(s);
                        if (shape === 'modes') {
                            const { _activeThemeRef, _activeCanvasRef, _activeCssRef, _activeGradientRef, _hiddenBackgrounds, ...pureThemeData } = s;
                            themeData = pureThemeData;
                            // The server's theme says which gallery entries it
                            // came from, or that it came from none of them. An
                            // older copy in this browser must not keep its own
                            // picks over it: after Use instance theme that left
                            // the previous personal theme selected.
                            const fromServer = typeof serverState === 'string' && !_resumingDraft && !_keptUnsaved;
                            if (_activeThemeRef || fromServer) activeThemeRef = _activeThemeRef || createNullModeMap();
                            if (_activeCanvasRef || fromServer) activeCanvasRef = _activeCanvasRef || createNullModeMap();
                            if (_activeCssRef || fromServer) activeCssRef = _activeCssRef || createNullModeMap();
                            if (_activeGradientRef || fromServer) activeGradientRef = _activeGradientRef || createNullModeMap();
                            if (_hiddenBackgrounds || fromServer) hiddenBackgrounds = readHiddenBackgrounds(_hiddenBackgrounds);
                            refreshBackgroundsUi();
                            ensureAllModes(themeData);

                            if (!themeData.dark.locks) themeData.dark.locks = {};
                            if (!themeData.light.locks) themeData.light.locks = {};
                            if (!themeData.oled.locks) themeData.oled.locks = {};
                            if (!themeData.her.locks) themeData.her.locks = {};

                            // Every override is locked, and fields older themes lack get defaults
                            MODES.forEach(m => {
                                if (themeData[m]) {
                                    Object.keys(themeData[m].overrides || {}).forEach(k => themeData[m].locks[k] = true);
                                    if (themeData[m].customCssEnabled === undefined) themeData[m].customCssEnabled = false;
                                    if (themeData[m].autoScope === undefined) themeData[m].autoScope = true;
                                    if (themeData[m].canvasEnabled === undefined) themeData[m].canvasEnabled = false;
                                    if (themeData[m].canvasScript === undefined) themeData[m].canvasScript = "";
                                }
                            });

                        } else if (shape === 'legacy') {
                            const migrated = migrateLegacyTheme(s);
                            MODES.forEach(m => { themeData[m] = migrated[m]; });
                        } else {
                            stateLoad = 'unreadable';
                        }
                        // Validated after both arms: this is straight from
                        // localStorage, possibly written by an older build, and
                        // migrateLegacyTheme builds its modes with a bare spread
                        MODES.forEach(m => {
                            if (themeData[m]) themeData[m] = validateModeData(themeData[m]);
                        });
                    }
                    // A resumed draft reads fine, but the server's theme under
                    // it may not: Publish must still ask before replacing it
                    if (draftRaw && typeof serverState === 'string') {
                        let published = null;
                        try { published = JSON.parse(serverState); } catch (x) {}
                        if (!themeShape(published)) stateLoad = 'unreadable';
                    }
                    if (stateLoad === 'pending') stateLoad = 'ok';
                    else holdUnreadableState();
                    resetHistoryBaseline();
                    // Before the mode click below: it repaints and saves, and
                    // with Draft not yet on that published a resumed draft to
                    // every user on a plain refresh.
                    restoreDraftMode();

                    const pTheme = localStorage.getItem('theme');
                    const pDoc = document.documentElement;
                    if (pTheme === 'system' || pDoc.getAttribute('data-theme') === 'system') {
                        const systemBtn = document.querySelector('.mode-btn[data-mode="system"]');
                        if (systemBtn) systemBtn.click();
                    } else if (pTheme === 'oled-dark' || pDoc.getAttribute('data-theme') === 'oled-dark') {
                        document.querySelector('.mode-btn[data-mode="oled"]')?.click();
                    } else if (pTheme === 'her' || pDoc.classList.contains('her') || pDoc.getAttribute('data-theme') === 'her') {
                        const herBtn = document.querySelector('.mode-btn[data-mode="her"]');
                        if (herBtn) herBtn.click();
                    } else if (pTheme === 'light' || pDoc.classList.contains('light') || pDoc.getAttribute('data-theme') === 'light') {
                        document.querySelector('.mode-btn[data-mode="light"]')?.click();
                    } else {
                        document.querySelector('.mode-btn[data-mode="dark"]')?.click();
                    }

                    const savedTab = sessionStorage.getItem('owui_theme_tool_tab');
                    if (savedTab) {
                        const targetTab = document.querySelector(`.tab[data-tab="${savedTab}"]`);
                        if (targetTab) targetTab.click();
                    }
                }
            } catch (e) {
                console.warn('Theme Pro:', e);
                if (stateLoad === 'pending') { stateLoad = 'unreadable'; holdUnreadableState(); }
            }
            if (!HIDDEN_APPLY_FRAME) try {
                if (sessionStorage.getItem(LIBRARY_DROPPED_KEY)) {
                    sessionStorage.removeItem(LIBRARY_DROPPED_KEY);
                    showToast('⚠️ Your gallery change wasn’t saved: the page reloaded to show a change made elsewhere', 8000);
                }
            } catch (x) {}
            if (_keptUnsaved) showToast('▶️ Saving the changes this tab kept when the server did not take them');
            if (_keptToOffer) {
                const kept = _keptToOffer;
                _offeringKept = true;
                askConfirm('Save the changes this tab kept?',
                    'The server didn\u2019t take this tab\u2019s last changes, so the designer shows the theme that is saved. Save this tab\u2019s changes over it?', 'Save them').then(ok => {
                    _offeringKept = false;
                    if (!ok) { try { sessionStorage.removeItem(UNSAVED_THEME_KEY); } catch (x) {} return; }
                    // Reloaded, the kept copy saves as it loads
                    try { sessionStorage.setItem(UNSAVED_THEME_KEY, JSON.stringify({ scope: THEME_KIND, state: kept, confirmed: true })); } catch (x) {}
                    location.reload();
                });
            }
            if (stateLoad === 'unreadable') {
                showToast(personalDesigner
                    ? 'Your saved theme could not be read, so the designer is not showing it. Nothing is saved until you change something.'
                    : 'The saved theme could not be read, so the designer is not showing it and opened in Draft mode. Publishing asks before replacing it.', 10000);
            }

            // Before updatePalette(), so syncToServer() is gated in Draft mode.
            // Normally done above; this catches a load that threw first.
            restoreDraftMode();

            updatePalette();
            renderSnapshots();
            const draftSwitch = document.getElementById('draft-switch');
            if (draftSwitch) draftSwitch.addEventListener('click', () => {
                if (_draftMode) {
                    publishTheme();  // Draft → Live: sync + toast + set Live
                } else {
                    setDraftMode(true);
                }
            });
            const publishBtn = document.getElementById('draft-publish-btn');
            if (publishBtn) publishBtn.addEventListener('click', publishTheme);
    })();

    // ═══════════════════════════════════════════════════════════════════════
    // VALVE ENFORCEMENT — Admin-controlled feature gating via Valves
    // Reads window.__THEME_PRO_CONFIG__ injected by the Python backend.
    // ═══════════════════════════════════════════════════════════════════════
    (function enforceValves() {
        const cfg = window.__THEME_PRO_CONFIG__;
        if (!cfg) return;

        // ── 0. Theme Active/Draft/Disabled badge — live via SSE + draft + function toggle ──
        const badge = document.getElementById('inactive-badge');
        const badgeText = document.getElementById('inactive-badge-text');

        // state: 'active' | 'draft' | 'inactive'
        function setBadgeState(state) {
            if (!badge || !badgeText) return;
            badge.classList.remove('active', 'draft');
            if (state === 'active') {
                badge.classList.add('active');
                badge.setAttribute('data-tooltip', 'Theme is active \u2014 changes reach ' + liveAudience() + ' in real time');
                badgeText.textContent = 'Theme Active';
            } else if (state === 'draft') {
                badge.classList.add('draft');
                badge.setAttribute('data-tooltip', 'Draft mode \u2014 changes stay local until you publish');
                badgeText.textContent = 'Draft Active';
            } else {
                badge.setAttribute('data-tooltip', 'Function is disabled \u2014 toggle it ON in Admin \u2192 Functions');
                badgeText.textContent = 'Theme Inactive';
            }
        }
        function updateBadge() {
            if (_functionDisabled) { setBadgeState('inactive'); return; }
            if (typeof _draftMode !== 'undefined' && _draftMode) { setBadgeState('draft'); return; }
            setBadgeState('active');
        }
        // For setDraftMode()
        window._updateThemeBadge = updateBadge;

        updateBadge();

        // Another open designer, in another tab or window, saved. This page
        // holds the theme and library in memory, so it reloads to show the
        // change instead of saving its older copy over it later.
        function fromOtherTab(e) {
            try {
                const d = JSON.parse(e.data || '{}') || {};
                return !!d.origin && d.origin !== TAB_ORIGIN && !d.settle;
            } catch (x) { return false; }
        }
        let _reloadPending = false, _reloadCheck = null;
        // Saves queued while the earlier ones were in flight count too
        function savesSettled() {
            const sync = _syncQueue, lib = _libQueue;
            return Promise.allSettled([sync, lib]).then(() => (sync !== _syncQueue || lib !== _libQueue) ? savesSettled() : undefined);
        }
        // stillNeeded, for a resync: asked again once this page's own saves
        // have answered, since their tags can be the ones the resync named
        function reloadForOtherTab(stillNeeded) {
            if (_reloadPending) {
                // A save from another tab reloads whatever the checks say;
                // otherwise any one resync that still finds a miss does
                const prev = _reloadCheck;
                _reloadCheck = !stillNeeded || !prev ? null : () => prev() || stillNeeded();
                return;
            }
            if (typeof _draftMode !== 'undefined' && _draftMode) {
                (stillNeeded ? savesSettled() : Promise.resolve()).then(() => {
                    if (!stillNeeded || stillNeeded()) showToast('The theme changed in another tab. Your draft stays here, and publishing it replaces that change.', 6000);
                });
                return;
            }
            _reloadPending = true;
            _reloadCheck = stillNeeded || null;
            // Not while this page is being typed in, is saving, holds a save
            // the server hasn't taken, or has a dialog open, and at most once every 5 seconds: a change that arrives in
            // several saves, as a Global Reset can, ends in one more reload
            // once that time is up. A reload would cut off a save in flight.
            const busy = () => hasPendingEdits() || _themeSaveHeld || Date.now() - _lastLocalSave < 1500 ||
                [].some.call(document.querySelectorAll('[id$="-modal"]'), m => m.style.display === 'flex');
            (function attempt() {
                if (busy()) { setTimeout(attempt, 1000); return; }
                let last = 0;
                try { last = Number(sessionStorage.getItem('owui_tdp_auto_reload') || 0); } catch (x) {}
                const wait = 5000 - (Date.now() - last);
                if (wait > 0) { setTimeout(attempt, wait); return; }
                savesSettled().then(() => {
                    if (_reloadCheck && !_reloadCheck()) {
                        _reloadPending = false;
                        _reloadCheck = null;
                        return;
                    }
                    if (busy()) { setTimeout(attempt, 1000); return; }
                    try { sessionStorage.setItem('owui_tdp_auto_reload', String(Date.now())); } catch (x) {}
                    // A gallery change still waiting is lost with the reload: said once the page is back
                    if (_librarySavePending) {
                        _librarySavePending = false;
                        noteLibraryDropped();
                    }
                    location.reload();
                });
            })();
        }

        // Reloads for a save in another tab, or for one a resync says this
        // page missed. Every update is noted, even one that doesn't apply.
        function reloadIfChanged(kind, e, applies) {
            const d = eventData(e);
            const missed = missedSave(kind, d);
            if (!applies) return;
            if (fromOtherTab(e)) reloadForOtherTab();
            else if (missed) reloadForOtherTab(() => missedSave(kind, d));
        }

        // Opened after page load: earlier, the browser reports the stream as
        // "interrupted while loading". Each connection starts with a resync of
        // what is saved now, for a save broadcast while it was down.
        let badgeEs = null, _badgeRetryTimer = 0, _badgeRetryN = 0;
        function initBadgeSSE() {
            try {
                clearTimeout(_badgeRetryTimer);
                badgeEs = new EventSource('{ROUTE_BASE}/events?_badge=' + Date.now() + (cfg.scope === 'me' ? '&scope=me' : ''));
                const mine = badgeEs;
                badgeEs.onopen = () => { _badgeRetryN = 0; };
                badgeEs.addEventListener('theme-update', (e) => {
                    // Saved in another open designer. A personal designer only
                    // cares while it still shows the instance theme.
                    reloadIfChanged('theme', e, cfg.scope !== 'me' || window.__TDP_HOLD_SAVES__);
                    _functionDisabled = false;
                    updateBadge();
                });
                badgeEs.addEventListener('theme-disable', (e) => {
                    // A Global Reset broadcasts theme-disable too, but saves
                    // still work, so only a real toggle may latch the
                    // save-hold: no theme-update would ever release it.
                    // Unparseable data reads as a disable.
                    var reason = 'disabled';
                    try { reason = (JSON.parse(e.data || '') || {}).reason || 'disabled'; } catch(x) {}
                    if (reason === 'reset') {
                        // A Factory Reset in another tab wiped the instance theme.
                        if (cfg.scope !== 'me' || window.__TDP_HOLD_SAVES__) reloadForOtherTab();
                        return;
                    }
                    _functionDisabled = true; updateBadge();
                });
                badgeEs.addEventListener('personal-theme-update', (e) => {
                    if (cfg.scope === 'me') reloadIfChanged('personal', e, true);
                });
                badgeEs.addEventListener('library-update', (e) => {
                    const d = eventData(e);
                    if (d.scope !== (cfg.scope === 'me' ? 'me' : 'instance')) return;
                    // Live mode reloads for it; a page that won't stops its gallery saves
                    if ((_draftMode || _themeSaveHeld) && (fromOtherTab(e) || missedSave('library', d))) pauseLibrary();
                    else reloadIfChanged('library', e, true);
                });
                // As the bootloader's connectSSE: an HTTP error (a proxy's 502
                // while Open WebUI restarts) closes it for good
                badgeEs.onerror = () => {
                    if (mine !== badgeEs || mine.readyState !== EventSource.CLOSED) return;
                    const delay = Math.min(60000, 3000 * Math.pow(2, _badgeRetryN++)) * (0.5 + Math.random());
                    _badgeRetryTimer = setTimeout(initBadgeSSE, delay);
                };
            } catch(e) { console.warn('[Theme Pro] Badge SSE error:', e); }
        }
        window.addEventListener('beforeunload', () => { clearTimeout(_badgeRetryTimer); if (badgeEs) badgeEs.close(); });
        if (document.readyState === 'complete') {
            initBadgeSSE();
        } else {
            window.addEventListener('load', () => setTimeout(initBadgeSSE, 100));
        }

        // ── 1. Hide tabs for disabled features ──
        const hiddenTabs = [];
        if (!cfg.enableCanvasFx) hiddenTabs.push('canvas');
        if (!cfg.enableCustomCss) hiddenTabs.push('custom');
        if (!cfg.enableGradientBuilder) hiddenTabs.push('bg');

        hiddenTabs.forEach(tabKey => {
            const tabEl = document.querySelector(`.tab[data-tab="${tabKey}"]`);
            if (tabEl) tabEl.style.display = 'none';
        });

        // ── Update checks turned off: no Updates button ──
        if (cfg.enableThemeUpdateChecks === false) {
            const updatesBtn = $('check-updates-btn');
            if (updatesBtn) updatesBtn.style.display = 'none';
        }

        // ── Community Themes section visibility ──
        if (!cfg.enableCommunityThemes) {
            const communitySection = $('community-themes-grid');
            if (communitySection) {
                // The grid sits in a scroll wrapper; the title row with its
                // search, sort, Install All and Refresh buttons is before that
                const wrap = communitySection.parentElement;
                const title = wrap && wrap.previousElementSibling;
                if (title && title.classList.contains('section-title')) title.style.display = 'none';
                (wrap || communitySection).style.display = 'none';
            }
            // Expand theme gallery to fill the page since community section is gone
            const snapshotScroll = $('snapshot-scroll');
            if (snapshotScroll) snapshotScroll.style.maxHeight = 'none';
        }

        // If the currently active tab was hidden, fall back to Core Palette
        const activeTab = document.querySelector('.tab.active');
        if (activeTab && hiddenTabs.includes(activeTab.dataset.tab)) {
            const fallback = document.querySelector('.tab[data-tab="lch"]');
            if (fallback) fallback.click();
        }


        // ── 3. Restrict URL imports ──
        if (!cfg.enableUrlImport) {
            loadFromUrl = function(opts) {
                const statusEl = document.getElementById(opts.statusId);
                if (statusEl) {
                    statusEl.style.display = 'block';
                    statusEl.style.background = 'rgba(239,68,68,0.15)';
                    statusEl.style.color = '#ef4444';
                    statusEl.style.borderRadius = '8px';
                    statusEl.style.padding = '8px 12px';
                    statusEl.style.fontSize = '0.7rem';
                    statusEl.textContent = '⛔ URL imports are disabled by your administrator.';
                }
            };
            ['import-url-load-btn', 'import-css-url-load-btn', 'import-canvas-url-load-btn', 'import-gradient-url-load-btn',
             'import-url-input', 'import-css-url-input', 'import-canvas-url-input', 'import-gradient-url-input']
                .forEach(id => { const el = document.getElementById(id); if (el) el.style.display = 'none'; });
        }
        // The domain allowlist is not wrapped around loadFromUrl: it is checked
        // inside it, after the URL is rewritten, by assertImportHostAllowed, the
        // same check every automated import runs. A wrapper would have to
        // rewrite the URL a second time to know which host to judge.

        // ── 4. Auto Sync — show/hide 'Sync All' toggle in footer ──
        if (cfg.autoSync) {
            const syncAllWrap = document.getElementById('sync-all-toggle-wrap');
            if (syncAllWrap) syncAllWrap.style.display = '';
            const syncBtn = document.getElementById('sync-mode-btn');
            if (syncBtn) syncBtn.setAttribute('data-tooltip', 'Instantly sync all settings from the current mode to every other mode');
        }

        // ── 5. Auth page theming — force off + hide toggles + overwrite localStorage ──
        const authToggleIds = ['toggle-theme-auth', 'toggle-custom-auth', 'toggle-canvas-auth', 'toggle-gradient-auth', ...AUTH_ONLY.map(a => a[3])];
        if (!cfg.enableAuthPageTheming) {
            authToggleIds.forEach(id => {
                const el = document.getElementById(id);
                if (el) {
                    el.checked = false;
                    const label = el.closest('label');
                    if (label) label.style.display = 'none';
                }
            });
            MODES.forEach(m => {
                if (themeData[m]) {
                    themeData[m].themeShowAuth = false;
                    themeData[m].customCssShowAuth = false;
                    themeData[m].canvasShowAuth = false;
                    themeData[m].gradientShowAuth = false;
                    AUTH_ONLY_KEYS.forEach(k => { themeData[m][k] = false; });
                }
            });
            // Persist to localStorage so the bootloader also respects this
            commitChange({ clearRef: false, push: false });
        }

        // ── 6. Personal themes — the auth pages always show the instance
        // theme, so the 'Show on Auth Pages' toggles would change nothing.
        // Hidden, not cleared: a personal theme exported and installed as the
        // instance theme keeps its auth choices. ──
        if (cfg.scope === 'me') {
            authToggleIds.forEach(id => {
                const label = document.getElementById(id)?.closest('label');
                if (label) label.style.display = 'none';
            });
            const syncAuth = document.getElementById('sync-opt-auth')?.closest('.sync-option');
            if (syncAuth) syncAuth.style.display = 'none';
        }
    })();

