    // --- Community Themes Browser ---
    let _communityManifest = null;
    let _communityCatalog = null;
    const CATALOG_URL = 'https://raw.githubusercontent.com/silentoplayz/theme-designer-pro-presets/main/docs/catalog.json';
    const COMMUNITY_BADGE_CLASS = { CSS: 'badge-css', FX: 'badge-fx', Gradient: 'badge-gradient', Overrides: 'badge-overrides' };

    // The catalog's c is on a 0-100 scale; oklch() takes 0-1. Coerced because
    // h and c are remote values landing in a style attribute.
    function oklchToCSS(h, c, l) {
        return `oklch(${_cssNum(l, 50)}% ${_cssNum(c, 0) / 100} ${_cssNum(h, 0)})`;
    }

    function communityGridMessage(text) {
        return `<div class="empty-state-lg" style="grid-column:1/-1;">${text}</div>`;
    }

    // Both spellings of every installed theme's updateUrl, since a catalog
    // entry's importUrl may be written either way
    function installedUpdateUrls(snapshots) {
        const urls = new Set();
        snapshots.forEach(s => {
            if (s.updateUrl && typeof s.updateUrl === 'string') { urls.add(toRawGitHub(s.updateUrl)); urls.add(s.updateUrl); }
        });
        return urls;
    }

    function isInstalledUrl(installedUrls, url) {
        return installedUrls.has(toRawGitHub(url)) || installedUrls.has(url);
    }

    function uninstalledCommunityThemes() {
        const installedUrls = installedUpdateUrls(getSnapshots());
        return _communityCatalog.themes.filter(t => {
            const url = t.importUrl || '';
            return url && !isInstalledUrl(installedUrls, url);
        });
    }

    async function loadCommunityThemes(force) {
        const grid = $('community-themes-grid');
        if (!grid) return;
        const cfg = window.__THEME_PRO_CONFIG__;
        if (cfg && !cfg.enableCommunityThemes) return;

        if (_communityCatalog && !force) {
            renderCommunityGrid(_communityCatalog);
            return;
        }

        grid.innerHTML = communityGridMessage('Loading community themes...');

        try {
            // The catalog carries per-mode data and features; the manifest is
            // only for update versions
            const data = await fetchGatedJson(CATALOG_URL);
            if (!data.themes || !Array.isArray(data.themes)) throw new Error('Invalid catalog');
            _communityCatalog = data;
            if (UPDATE_CHECKS) _communityManifest = await fetchManifest();
            renderCommunityGrid(data);
            return;
        } catch(e) {}
        // Fallback: the manifest alone, which has fewer fields than the catalog
        try {
            const manifest = UPDATE_CHECKS ? await fetchManifest() : null;
            if (manifest && manifest.themes) {
                _communityManifest = manifest;
                _communityCatalog = { themes: Object.entries(manifest.themes).map(([k, v]) => ({ ...v, importUrl: v.updateUrl, _key: k })) };
                renderCommunityGrid(_communityCatalog);
                return;
            }
        } catch {}
        grid.innerHTML = communityGridMessage('Could not load community themes.');
    }

    function collectThemeFeatures(modes) {
        const features = new Set();
        if (!modes) return features;
        for (const m of MODES) {
            const mode = modes[m];
            if (!mode) continue;
            if (mode.hasCSS) features.add('CSS');
            if (mode.hasFX) features.add('FX');
            if (mode.hasGradient) features.add('Gradient');
            if (mode.hasOverrides) features.add('Overrides');
        }
        return features;
    }

    function renderCommunityGrid(catalog) {
        const grid = $('community-themes-grid');
        const countEl = $('community-count');
        if (!grid) return;

        // Indexed before filtering and sorting: installCommunityTheme looks
        // the theme up in the catalog by this
        let themes = (catalog.themes || []).map((t, i) => ({ ...t, _origIdx: i }));

        const searchInput = $('community-search-input');
        const searchQuery = searchInput ? searchInput.value.trim().toLowerCase() : '';
        if (searchQuery) {
            themes = themes.filter(t => {
                const name = (t.name || '').toLowerCase();
                const desc = (t.description || '').toLowerCase();
                const author = (t.author || '').toLowerCase();
                return name.includes(searchQuery) || desc.includes(searchQuery) || author.includes(searchQuery);
            });
        }

        if (activeCommunitySort === 'asc') {
            themes = [...themes].sort((a, b) => (a.name || '').localeCompare(b.name || ''));
        } else if (activeCommunitySort === 'desc') {
            themes = [...themes].sort((a, b) => (b.name || '').localeCompare(a.name || ''));
        }

        if (countEl) countEl.textContent = themes.length;

        const snapshots = getSnapshots();
        const installedUrls = installedUpdateUrls(snapshots);
        const installedVersions = {};
        snapshots.forEach(s => {
            if (s.updateUrl) installedVersions[toRawGitHub(s.updateUrl)] = s.version || '0.0.0';
        });

        const cards = themes.map(t => {
            const importUrl = t.importUrl || '';
            const isInstalled = isInstalledUrl(installedUrls, importUrl);
            const hasUpdate = UPDATE_CHECKS && isInstalled && _communityManifest && semverCompare(t.version || '0.0.0', installedVersions[toRawGitHub(importUrl)] || '0.0.0') > 0;
            const statusBadge = hasUpdate ? '<span class="community-status-badge s-update">Update</span>' : '';

            const modes = t.modes || {};
            const features = collectThemeFeatures(modes);
            const badgesHTML = features.size ? `<div class="community-badges">
                ${[...features].map(f => `<span class="community-badge-feat ${COMMUNITY_BADGE_CLASS[f] || ''}">${f}</span>`).join('')}
            </div>` : '';
            const dotColor = modes.dark ? oklchToCSS(modes.dark.h, Math.max(modes.dark.c, 20), 55) : 'var(--accent)';

            const btnClass = isInstalled ? 'installed' : '';
            const btnLabel = hasUpdate ? '⟳ Update' : (isInstalled ? '✓ Installed' : '↓ Install');

            const descEscaped = _escAttr(t.description || '');

            return `<div class="preset-btn community-card" data-community-idx="${t._origIdx}" ${descEscaped ? `data-tooltip="${descEscaped}"` : ''}>
                ${statusBadge}
                <div class="community-header">
                    <span class="community-name">${_esc(t.name || '')}</span>
                    ${t.version ? `<span class="community-version">v${_esc(t.version)}</span>` : ''}
                </div>
                <div class="community-desc">${_esc(t.description || '')}</div>
                <div class="community-author"><span class="community-author-dot" style="background:${dotColor}"></span>${_esc(t.author || 'Unknown')}</div>
                ${badgesHTML}
                <button class="community-install-btn ${btnClass}" onclick="event.stopPropagation(); installCommunityTheme(${t._origIdx})">${btnLabel}</button>
            </div>`;
        });

        grid.innerHTML = cards.join('');

        const installAllBtn = $('community-install-all-btn');
        if (installAllBtn) {
            installAllBtn.style.display = uninstalledCommunityThemes().length > 0 ? '' : 'none';
        }
    }

    window.installCommunityTheme = async function(idx) {
        if (!_communityCatalog || !_communityCatalog.themes[idx]) return;
        const t = _communityCatalog.themes[idx];
        const updateUrl = t.importUrl || '';
        if (!updateUrl) { showToast('No import URL available'); return; }

        showToast('Downloading theme...');
        try {
            const remote = await fetchThemeData(updateUrl);
            delete remote._meta;
            const newTheme = {
                name: remote.name || t.name,
                description: remote.description || t.description || '',
                author: remote.author || t.author || '',
                version: remote.version || t.version || '1.0.0',
                targetVersion: remote.targetVersion || '',
                repositoryUrl: remote.repositoryUrl || '',
                updateUrl: remote.updateUrl || updateUrl,
                dark: remote.dark,
                light: remote.light,
                oled: remote.oled || null,
                her: remote.her || null
            };
            ensureAllModes(newTheme);
            MODES.forEach(m => { if (newTheme[m]) newTheme[m] = normalizeModeData(newTheme[m]); });

            const snapshots = getSnapshots();
            const rawUrl = toRawGitHub(updateUrl);
            const existingIdx = snapshots.findIndex(s => s.updateUrl && (toRawGitHub(s.updateUrl) === rawUrl || s.updateUrl === updateUrl));

            if (existingIdx >= 0) {
                if (await applyThemeUpdate(existingIdx, remote)) showToast(`✓ Updated "${newTheme.name}" to v${newTheme.version}`);
            } else {
                snapshots.unshift(newTheme);
                saveSnapshots(snapshots);
                shiftThemeRefs(1);
                commitChange({ clearRef: false, push: false, snapshots: true });
                showToast(`✓ Installed "${newTheme.name}"`);
            }

            renderSnapshots();
        } catch(e) {
            showToast(`Error: ${e.message}`);
        }
    };

    const _communityRefreshBtn = $('community-refresh-btn');
    if (_communityRefreshBtn) {
        _communityRefreshBtn.addEventListener('click', () => loadCommunityThemes(true));
    }

    const _communityInstallAllBtn = $('community-install-all-btn');
    if (_communityInstallAllBtn) {
        _communityInstallAllBtn.addEventListener('click', async () => {
            if (!_communityCatalog || !_communityCatalog.themes) return;
            const uninstalled = uninstalledCommunityThemes();
            if (uninstalled.length === 0) {
                showToast('All community themes are already installed!');
                return;
            }

            const hasFx = uninstalled.some(t => {
                const modes = t.modes || {};
                return MODES.some(m => modes[m] && modes[m].hasFX);
            });
            const msgEl = $('install-all-msg');
            if (msgEl) {
                let html = `This will download and add <b>${uninstalled.length}</b> community theme${uninstalled.length > 1 ? 's' : ''} to your library.`;
                if (hasFx) {
                    html += `<br><br><span style="color:#fbbf24;">⚠️ Some themes include Canvas FX animation scripts (JavaScript).</span> These scripts run in your browser and are authored by community contributors. Only install if you trust the source.`;
                }
                msgEl.innerHTML = html;
            }
            showModal('install-all-confirm-modal');
        });
    }

    const _confirmInstallAllBtn = $('confirm-install-all-btn');
    if (_confirmInstallAllBtn) {
        _confirmInstallAllBtn.addEventListener('click', async () => {
            hideModal('install-all-confirm-modal');
            if (!_communityCatalog || !_communityCatalog.themes) return;
            if (uninstalledCommunityThemes().length === 0) return;

            // One fetch of the bundle instead of one per theme
            _communityInstallAllBtn.disabled = true;
            const origHTML = _communityInstallAllBtn.innerHTML;
            _communityInstallAllBtn.innerHTML = '<span class="spin" style="font-size:12px;line-height:1;">⟳</span>';

            const BUNDLE_URL = 'https://raw.githubusercontent.com/silentoplayz/theme-designer-pro-presets/main/bundles/themes-all.json';
            try {
                const bundle = await fetchGatedJson(BUNDLE_URL, MAX_BUNDLE_BYTES);
                if (!bundle.themes || !Array.isArray(bundle.themes)) throw new Error('Invalid bundle format');

                // Read again: the library may have changed during the fetch
                const currentSnaps = getSnapshots();
                const currentUrls = installedUpdateUrls(currentSnaps);

                let installed = 0, invalid = 0;
                bundle.themes.forEach(entry => {
                    const theme = themeFromEntry(entry);
                    if (!theme) { invalid++; return; }
                    if (isInstalledUrl(currentUrls, theme.updateUrl)) return;
                    currentSnaps.push(theme);
                    installedUpdateUrls([theme]).forEach(u => currentUrls.add(u));
                    installed++;
                });

                saveSnapshots(currentSnaps);
                _communityInstallAllBtn.innerHTML = origHTML;
                _communityInstallAllBtn.disabled = false;
                renderSnapshots();
                if (_communityCatalog) try { renderCommunityGrid(_communityCatalog); } catch(e) {}
                const skipped = invalid ? ` (${invalid} invalid skipped)` : '';
                if (installed) showToast(`✓ Installed ${installed} theme${installed !== 1 ? 's' : ''}${skipped}`);
                else showToast(invalid ? `No themes installed${skipped}` : 'Nothing new to install');
            } catch(e) {
                _communityInstallAllBtn.innerHTML = origHTML;
                _communityInstallAllBtn.disabled = false;
                showToast(`Error: ${e.message}`);
            }
        });
    }

    // Themes is the default tab
    loadCommunityThemes(false);

    $('check-updates-btn').addEventListener('click', async () => {
        const btn = $('check-updates-btn');
        const origHTML = btn.innerHTML;
        const origLabel = btn.getAttribute('aria-label');
        const restoreBtn = () => { btn.innerHTML = origHTML; btn.setAttribute('aria-label', origLabel); btn.disabled = false; };
        btn.innerHTML = '<span class="spin" style="font-size: 13px; line-height: 1;">⟳</span> Checking…';
        btn.setAttribute('aria-label', 'Checking themes for updates…');
        btn.disabled = true;

        const snapshots = getSnapshots();
        const updatable = snapshots.map((s, i) => ({ index: i, snap: s })).filter(x => x.snap.updateUrl);

        if (updatable.length === 0) {
            restoreBtn();
            showToast('No themes have an Update URL set.');
            return;
        }

        // The manifest answers for every theme it lists in one fetch; the
        // rest, or all of them without a manifest, are checked one by one
        let results = [];
        try {
            const manifestResult = await checkUpdatesViaManifest(snapshots);
            if (manifestResult) {
                results = manifestResult.results.filter(r => r !== null);
                if (manifestResult.unmatched.length > 0) {
                    const fallbackResults = await Promise.all(
                        manifestResult.unmatched.map(i => checkThemeUpdate(i))
                    );
                    results = results.concat(fallbackResults.filter(r => r !== null));
                }
            } else {
                const allResults = await Promise.all(updatable.map(x => checkThemeUpdate(x.index)));
                results = allResults.filter(r => r !== null);
            }
        } catch (e) {
            restoreBtn();
            console.warn('[Theme Pro] Update check failed:', e);
            showToast('⚠️ Update check failed: ' + (e && e.message ? e.message : e));
            return;
        }
        restoreBtn();

        const updates = results.filter(r => r && !r.error);
        const errors = results.filter(r => r && r.error);
        const upToDate = updatable.length - updates.length - errors.length;

        if (updates.length === 0 && errors.length === 0) {
            showToast(`✓ All ${upToDate} theme(s) are up to date!`);
            return;
        }

        let html = '';

        // Cleared on every run, not only one that finds updates: a stale
        // "Retry Failed" would apply old indices, which a deleted snapshot
        // may have re-pointed at a different theme
        window._pendingBatchUpdates = {};
        window._pendingBatchIndices = [];
        window._pendingBatchMeta = {};
        const updateAllBtn = $('update-all-btn');
        if (updateAllBtn) {
            updateAllBtn.style.display = 'none';
            updateAllBtn.disabled = false;
            updateAllBtn.innerText = 'Update All';
            updateAllBtn.style.opacity = '1';
        }

        if (updates.length > 0) {
            html += `<div style="font-size: 0.7rem; font-weight: 700; color: #10b981; text-transform: uppercase; letter-spacing: 1px; margin-bottom: 10px;">Updates Available (${updates.length})</div>`;
            updates.forEach((u, idx) => {
                const rowId = `batch-upd-row-${idx}`;
                const diffId = `batch-upd-diff-${idx}`;
                // data-update-index lets applyAllBatchUpdates leave failed rows actionable
                html += `<div class="update-result-row" id="${rowId}" data-update-index="${u.index}" style="background: var(--bg-deep); border: 1px solid var(--border); border-radius: 10px; margin-bottom: 8px; overflow: hidden;">`;
                html += `<div style="display:flex; align-items:center; justify-content:space-between; padding: 10px 12px;">`;
                html += `<div><div style="font-size: 0.78rem; font-weight: 700; color: var(--text-main);">${_esc(u.local.name)}</div><div style="font-size: 0.65rem; color: var(--text-muted);">v${_esc(u.localVersion)} → <span style="color:#10b981;">v${_esc(u.remoteVersion)}</span></div></div>`;
                html += `<div style="display:flex; gap:6px; align-items:center;">`;
                html += `<button class="btn" style="padding:4px 10px; font-size:0.6rem; opacity:0.7;" onclick="window._toggleBatchDiff('${diffId}', this, ${u.index}, ${u.viaManifest ? 'true' : 'false'})">▸ Diff</button>`;
                // The url and versions are remote strings, so they travel as
                // escaped data-* attributes for bindUpdateResultActions: in an
                // onclick a double quote would close the attribute and inject
                // a live handler
                html += `<button class="btn js-ignore-update" style="padding:4px 10px; font-size:0.6rem; color:var(--text-muted);" data-row="${_escAttr(rowId)}" data-url="${_escAttr(u.local.updateUrl || '')}" data-lv="${_escAttr(u.localVersion)}" data-rv="${_escAttr(u.remoteVersion)}">Ignore</button>`;
                if (u.viaManifest) {
                    html += `<button class="btn btn-primary js-apply-manifest-update" style="background:#10b981; padding: 6px 14px; font-size: 0.68rem;" data-index="${u.index}" data-url="${_escAttr(u.remoteUpdateUrl || '')}">Update</button>`;
                } else {
                    html += `<button class="btn btn-primary js-apply-batch-update" style="background:#10b981; padding: 6px 14px; font-size: 0.68rem;" data-index="${u.index}">Update</button>`;
                }
                html += `</div></div>`;
                html += `<div id="${diffId}" style="display:none; padding: 0 12px 12px; border-top: 1px solid var(--border);"></div>`;
                html += `</div>`;
            });
            window._pendingBatchIndices = updates.map(u => u.index);
            updates.forEach(u => {
                if (u.viaManifest) {
                    window._pendingBatchMeta[u.index] = u.remoteUpdateUrl;
                } else {
                    window._pendingBatchUpdates[u.index] = u.remote;
                }
            });

            // "Update All" skips the per-theme modal, so its warnings are here
            const risks = updates.map(u => canvasUpdateRisk(u.local, u.remote));
            const fxCount = risks.filter(r => r === 'adds').length;
            const unknownCount = risks.filter(r => r === 'unknown').length;
            const cssCount = updates.filter(u => updateAddsRemoteCss(u.local, u.remote)).length;
            if (fxCount > 0 || unknownCount > 0 || cssCount > 0) {
                let msg = '';
                if (fxCount > 0) {
                    msg += `${fxCount} of these update${fxCount > 1 ? 's' : ''} add${fxCount > 1 ? '' : 's'} or change${fxCount > 1 ? '' : 's'} a <b>Canvas FX script</b> (JavaScript) that will run in the browser of <b>every user</b> on this instance.`;
                }
                if (cssCount > 0) {
                    if (msg) msg += '<br><br>';
                    msg += `${cssCount} of these update${cssCount > 1 ? 's change' : ' changes'} <b>custom CSS</b>, which is applied instance-wide and can restyle or overlay any part of the interface.`;
                }
                if (unknownCount > 0) {
                    if (msg) msg += '<br><br>';
                    msg += `${unknownCount} update${unknownCount > 1 ? 's have' : ' has'} not been downloaded yet, so ${unknownCount > 1 ? 'they' : 'it'} may also add a Canvas FX script.`;
                }
                if (updates.length >= 2) msg += ` Update All asks you to confirm once for the whole batch.`;
                html += `<div style="background:rgba(239, 68, 68, 0.1); border:1px solid rgba(239, 68, 68, 0.3); border-radius:10px; padding:10px 12px; margin-top:12px; font-size:0.68rem; color:var(--text-muted); text-align:left;">`
                     + `<b style="color:#ef4444;">&#9888;&#65039; Security Warning</b><br>${msg} Review each diff before updating.`
                     + `</div>`;
            }

            if (updateAllBtn) updateAllBtn.style.display = updates.length >= 2 ? '' : 'none';
        }

        if (upToDate > 0) {
            html += `<div style="font-size: 0.7rem; color: var(--text-muted); margin-top: 12px; text-align:center;">✓ ${upToDate} theme(s) up to date</div>`;
        }

        if (errors.length > 0) {
            html += `<div style="font-size: 0.7rem; font-weight: 700; color: #ef4444; text-transform: uppercase; letter-spacing: 1px; margin: 12px 0 10px;">Errors (${errors.length})</div>`;
            errors.forEach(e => {
                html += `<div style="padding: 8px 12px; background: rgba(239, 68, 68, 0.05); border: 1px solid rgba(239, 68, 68, 0.2); border-radius: 10px; margin-bottom: 6px; font-size: 0.72rem;">`;
                html += `<span style="color:var(--text-main); font-weight:600;">${_esc(e.local.name)}</span> <span style="color:#ef4444;">${_esc(e.error)}</span>`;
                html += `</div>`;
            });
        }

        $('update-results-list').innerHTML = html;
        showModal('update-results-modal');
    });

    function markUpdateApplied(btn) {
        btn.innerText = 'Updated!';
        btn.disabled = true;
        btn.style.opacity = '0.5';
    }

    // The update-results rows' remote strings are read back from data-*
    // attributes here, never from an inline onclick
    (function bindUpdateResultActions() {
        const list = $('update-results-list');
        if (!list) return;
        list.addEventListener('click', async (e) => {
            const ignoreBtn = e.target.closest('.js-ignore-update');
            if (ignoreBtn) {
                const url = ignoreBtn.getAttribute('data-url') || '';
                const lv = ignoreBtn.getAttribute('data-lv') || '';
                const rv = ignoreBtn.getAttribute('data-rv') || '';
                const row = document.getElementById(ignoreBtn.getAttribute('data-row') || '');
                ignoreUpdate(url, lv, rv);
                if (row) { row.style.opacity = '0.3'; row.style.pointerEvents = 'none'; }
                showToast(`Ignored v${lv} → v${rv}`);
                return;
            }
            const updBtn = e.target.closest('.js-apply-manifest-update');
            if (updBtn) {
                const idx = _attrIndex(updBtn, 'data-index');
                const url = updBtn.getAttribute('data-url') || '';
                if (idx === null) return;
                if (await applyManifestUpdate(idx, url)) markUpdateApplied(updBtn);
                return;
            }
            // Non-manifest rows already hold the payload
            const batchBtn = e.target.closest('.js-apply-batch-update');
            if (batchBtn) {
                const idx = _attrIndex(batchBtn, 'data-index');
                if (idx === null) return;
                const remote = (window._pendingBatchUpdates || {})[idx];
                if (!remote) return;
                if (await applyThemeUpdate(idx, remote)) markUpdateApplied(batchBtn);
                return;
            }
        });
    })();

    window.applyThemeUpdate = async function(index, remoteData, opts) {
        const snapshots = getSnapshots();
        if (!snapshots[index]) return false;

        // Every update path ends here, so the gate is here. alreadyConfirmed is
        // for callers that showed the warning and took a click for it.
        if (!(opts && opts.alreadyConfirmed)) {
            const reasons = [];
            if (updateAddsCanvasCode(snapshots[index], remoteData)) {
                reasons.push('adds or changes a Canvas FX script (JavaScript), which will run in the browser of every user on this instance');
            }
            if (updateAddsRemoteCss(snapshots[index], remoteData)) {
                reasons.push('changes custom CSS, which is applied instance-wide and can restyle or overlay any part of the interface');
            }
            if (reasons.length) {
                const name = snapshots[index].name || 'This theme';
                if (!(await askConfirm('Install this update?',
                    `${name} ${reasons.join(', and ')}.\n\nOnly continue if you trust the source.`, 'Install'))) {
                    showToast('Update cancelled');
                    return false;
                }
            }
        }

        MODES.forEach(m => { if (remoteData[m]) remoteData[m] = normalizeModeData(remoteData[m]); });
        ensureAllModes(remoteData);
        delete remoteData._meta;

        // The local name, updateUrl and repositoryUrl are kept
        snapshots[index].dark = remoteData.dark;
        snapshots[index].light = remoteData.light;
        snapshots[index].oled = remoteData.oled;
        snapshots[index].her = remoteData.her;
        snapshots[index].version = remoteData.version || snapshots[index].version;
        if (remoteData.description) snapshots[index].description = remoteData.description;
        if (remoteData.author) snapshots[index].author = remoteData.author;
        if (remoteData.targetVersion) snapshots[index].targetVersion = remoteData.targetVersion;
        saveSnapshots(snapshots);

        // Reload every mode that shows this theme
        flushPendingEdits();
        let needsInject = false;
        MODES.forEach(m => {
            if (activeThemeRef[m] && activeThemeRef[m].type === 'snapshot' && activeThemeRef[m].id === index) {
                themeData[m] = structuredClone(snapshots[index][m]);
                needsInject = true;
            }
        });
        if (needsInject) {
            commitChange({ clearRef: false, snapshots: true });
        } else {
            pushState();
            renderSnapshots();
        }
        return true;
    };

    let pendingUpdate = null;

