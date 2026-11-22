    // --- Snapshot System ---
    // What a gallery tag filter and its tooltip tag look for, in any mode
    function snapshotHasTag(s, tag) {
        switch (tag) {
            case 'css': return MODES.some(m => s[m] && s[m].customCSS && s[m].customCssEnabled !== false);
            case 'canvas': return MODES.some(m => s[m] && s[m].canvasEnabled && s[m].canvasScript);
            case 'overrides': return MODES.some(m => s[m] && ((s[m].overrides && Object.keys(s[m].overrides).length > 0) || (s[m].manualOverrides && s[m].manualOverrides.trim())));
            // A gradient that draws: 2 stops, or 2 points for a mesh
            case 'gradient': return MODES.some(m => s[m] && s[m].gradientEnabled && (s[m].gradientType === 'mesh' ? (s[m].gradientMeshPoints || []).length >= 2 : (s[m].gradientStops || []).length >= 2));
            case 'linked': return !!s.updateUrl;
            default: return true;
        }
    }
    function renderSnapshots() {
        // The community grid marks which entries are already in the library
        if (_communityCatalog) try { renderCommunityGrid(_communityCatalog); } catch(e) {}
        const dm = getActiveDataMode();
        try {
            const container = document.getElementById('snapshot-list');
            const scrollArea = document.getElementById('snapshot-scroll');
            const countWrap = document.getElementById('library-count-wrap');
            const countEl = document.getElementById('library-count');
            
            if (!container || !scrollArea) return;
            
            let snapshots = getSnapshots();
            let needsSave = false;

            snapshots = snapshots.map(s => {
                if (_isLegacyTheme(s)) {
                    needsSave = true;
                    return migrateLegacyTheme(s);
                }
                // No dark or light mode (an unreadable entry, or JSON saved
                // without them): give it modes so it shows and can be deleted.
                if (!s.dark || typeof s.dark !== 'object') {
                    needsSave = true;
                    s.dark = (s.light && typeof s.light === 'object') ? structuredClone(s.light) : createDefaultModeData();
                }
                if (!s.light || typeof s.light !== 'object') { needsSave = true; s.light = createDefaultModeData(); }
                if (!s.oled || !s.her) { needsSave = true; ensureAllModes(s); }
                MODES.forEach(m => {
                    if (s[m]) {
                        if (!s[m].locks) { needsSave = true; s[m].locks = {}; Object.keys(s[m].overrides || {}).forEach(k => s[m].locks[k] = true); }
                        const keysBefore = Object.keys(s[m]).length;
                        s[m] = normalizeModeData(s[m]);
                        if (Object.keys(s[m]).length !== keysBefore) needsSave = true;
                    }
                });
                return s;
            });
            if (needsSave) saveSnapshots(snapshots);

            const searchInput = document.getElementById('theme-search-input');
            const searchQuery = (searchInput ? searchInput.value : '').trim().toLowerCase();
            let filteredSnapshots = snapshots.map((s, i) => ({ ...s, _origIndex: i }));
            if (searchQuery) {
                filteredSnapshots = filteredSnapshots.filter(s => {
                    const name = (s.name || '').toLowerCase();
                    const author = (s.author || '').toLowerCase();
                    const desc = (s.description || '').toLowerCase();
                    return name.includes(searchQuery) || author.includes(searchQuery) || desc.includes(searchQuery);
                });
            }

            const hasTagFilter = activeTagFilter !== 'all';
            if (hasTagFilter) filteredSnapshots = filteredSnapshots.filter(s => snapshotHasTag(s, activeTagFilter));

            if (activeSort !== 'default') {
                filteredSnapshots.sort((a, b) => {
                    const nameA = (a.name || '').toLowerCase();
                    const nameB = (b.name || '').toLowerCase();
                    return activeSort === 'asc' ? nameA.localeCompare(nameB) : nameB.localeCompare(nameA);
                });
            }

            const isFiltered = searchQuery || hasTagFilter;
            if (countEl) countEl.innerText = isFiltered ? filteredSnapshots.length + '/' + snapshots.length : snapshots.length;
            if (countWrap) countWrap.style.display = snapshots.length > 0 ? 'inline' : 'none';
            
            if (snapshots.length === 0) { 
                scrollArea.style.display = 'block';
                container.style.display = 'block';
                container.innerHTML = `<div class="empty-state-lg"><div style="margin-bottom:8px;">Your theme gallery is empty.</div><div style="font-size:0.65rem; line-height:1.6;">Save your current theme using the <b>📸 Snapshot</b> button, or import community presets from <a href="https://silentoplayz.github.io/theme-designer-pro-presets/" target="_blank" rel="noopener" style="color:var(--accent); text-decoration:underline;">the preset gallery</a>.</div></div>`;
                return; 
            }

            if (filteredSnapshots.length === 0) {
                scrollArea.style.display = 'block';
                container.style.display = 'block';
                const filterLabels = { css: 'Custom CSS', canvas: 'Canvas FX', gradient: 'Gradient', overrides: 'Overrides', linked: 'Linked' };
                let emptyMsg = 'No themes match';
                if (searchQuery) emptyMsg += ` &ldquo;${_esc(searchQuery)}&rdquo;`;
                if (hasTagFilter) {
                    emptyMsg += (searchQuery ? ' with' : '') + ` the <strong>${filterLabels[activeTagFilter] || activeTagFilter}</strong> tag`;
                }
                container.innerHTML = `<div class="empty-state-lg">${emptyMsg}</div>`;
                return;
            }
            
            scrollArea.style.display = 'block';
            container.style.display = 'grid';
            
            _ttClearPrefix('snap:');
            setHtmlKeepingFocus(container, filteredSnapshots.map((s) => {
                const i = s._origIndex;
                const isMatch = s && s[dm] && isModeMatch(s[dm], themeData[dm]);
                const isRef = activeThemeRef[dm] && activeThemeRef[dm].type === 'snapshot' && activeThemeRef[dm].id === i;
                const active = isMatch && isRef;
                
                let ttHtml = `<div class="tt-row"><span class="tt-name">${_esc(s.name)}</span>`;
                if (s.version) ttHtml += `<span class="tt-version">v${_esc(s.version)}</span>`;
                ttHtml += `</div>`;
                if (s.author) ttHtml += `<div class="tt-author">by ${_esc(s.author)}</div>`;
                if (s.description) ttHtml += `<div class="tt-desc">${_esc(s.description)}</div>`;
                const hasCSS = snapshotHasTag(s, 'css');
                const hasCanvas = snapshotHasTag(s, 'canvas');
                const hasOverrides = snapshotHasTag(s, 'overrides');
                const hasGradient = snapshotHasTag(s, 'gradient');
                const hasTags = hasCSS || hasCanvas || hasGradient || hasOverrides || s.updateUrl;
                if (hasTags) {
                    ttHtml += `<div class="tt-tags">`;
                    if (hasCSS) ttHtml += `<span class="tt-tag tt-tag-css">Custom CSS</span>`;
                    if (hasCanvas) ttHtml += `<span class="tt-tag tt-tag-canvas">Canvas FX</span>`;
                    if (hasGradient) ttHtml += `<span class="tt-tag tt-tag-gradient">Gradient</span>`;
                    if (hasOverrides) ttHtml += `<span class="tt-tag tt-tag-overrides">Overrides</span>`;
                    if (s.updateUrl) ttHtml += `<span class="tt-tag tt-tag-url">Linked</span>`;
                    ttHtml += `</div>`;
                }
                const ttKey = _ttRegister(`snap:${i}`, ttHtml);

                return `
                <div class="preset-btn ${active ? 'active-theme' : ''}" data-index="${i}" data-item="${i}" data-tooltip-key="${ttKey}" role="group" aria-label="${_escAttr(s.name)}">
                    <button type="button" class="plain-button card-apply" data-control="apply" onclick="loadSnapshot(${i})" aria-label="Apply ${_escAttr(s.name)}"></button>
                    <button type="button" class="plain-button snapshot-action edit-snapshot" data-control="edit" onclick="event.stopPropagation(); requestRename(${i})" data-tooltip="Edit theme" aria-label="Edit theme">✎</button>
                    <button type="button" class="plain-button snapshot-action update-snapshot" data-control="update" onclick="event.stopPropagation(); updateSnapshot(${i})" data-tooltip="Overwrite with current values" aria-label="Overwrite with current values">💾</button>
                    <button type="button" class="plain-button snapshot-action delete-snapshot" data-control="delete" onclick="event.stopPropagation(); requestDelete(${i})" data-tooltip="Delete theme" aria-label="Delete theme">×</button>
                    <button type="button" class="plain-button snapshot-action export-snapshot" data-control="export" onclick="event.stopPropagation(); exportSnapshot(${i})" data-tooltip="Export theme" aria-label="Export theme">↓</button>
                    ${s.updateUrl && UPDATE_CHECKS ? '<button type="button" class="plain-button snapshot-action check-update-snapshot" data-control="check" onclick="event.stopPropagation(); checkSingleUpdate(' + i + ')" data-tooltip="Check for update" aria-label="Check for update">⟳</button>' : ''}
                    <div class="preset-dots">${renderTonalRampHTML(s[dm])}</div>
                    <span style="font-size: 10px; width: 100%; overflow: hidden; text-overflow: ellipsis; text-align: center; white-space: nowrap; display: block;">${_esc(s.name)}${s.version ? ' <span style="opacity:0.5;">v' + _esc(s.version) + '</span>' : ''}</span>
                    <div class="selected-check">✓</div>
                </div>
            `;}).join(''));
            
            updateActiveHighlights();
        } catch(e) { console.error("Render snapshots failed", e); }
    }

    let snapshotToDelete = null;
    window.requestDelete = (index) => {
        const snapshots = getSnapshots();
        if (!snapshots[index]) return;
        snapshotToDelete = index;
        document.getElementById('delete-theme-name').innerText = snapshots[index].name;
        showModal('delete-modal');
    };

    const confirmDeleteBtn = document.getElementById('confirm-delete-btn');
    if (confirmDeleteBtn) {
        confirmDeleteBtn.addEventListener('click', () => {
            if (snapshotToDelete === null) return;
            const snapshots = getSnapshots();
            snapshots.splice(snapshotToDelete, 1);
            saveSnapshots(snapshots);
            
            hideModal('delete-modal');
            const deletedIndex = snapshotToDelete;
            snapshotToDelete = null;

            // Only the gallery entry goes. The live theme stays as it is, even
            // in modes that came from this entry; a Global Reset is its own button.
            _remapSnapshotRefs(id => id === deletedIndex ? null : (id > deletedIndex ? id - 1 : id));
            renderSnapshots();
        });
    }

    let snapshotToOverwrite = null;
    window.updateSnapshot = (index) => {
        const snapshots = getSnapshots();
        if (snapshots[index]) {
            snapshotToOverwrite = index;
            document.getElementById('overwrite-theme-name').innerText = snapshots[index].name;
            showModal('overwrite-modal');
        }
    };

    const confirmOverwriteBtn = document.getElementById('confirm-overwrite-btn');
    if (confirmOverwriteBtn) {
        confirmOverwriteBtn.addEventListener('click', () => {
            if (snapshotToOverwrite === null) return;
            const index = snapshotToOverwrite;
            const snapshots = getSnapshots();
            if (snapshots[index]) {
                snapshots[index] = { ...snapshots[index], ...structuredClone(themeData) };
                saveSnapshots(snapshots);
                activeThemeRef[getActiveDataMode()] = { type: 'snapshot', id: index };
                renderSnapshots();
                showToast('Theme Updated!');
            }
            hideModal('overwrite-modal');
            snapshotToOverwrite = null;
        });
    }

    window.loadSnapshot = (index) => {
        showSyncModal('snapshot', index);
    };

    window.saveSnapshot = () => {
        const input = document.getElementById('theme-name-input');
        input.value = `Theme ${new Date().toLocaleTimeString()}`;

        // Metadata starts from what the last save used
        const descInput = document.getElementById('theme-desc-input');
        const authorInput = document.getElementById('theme-author-input');
        const versionInput = document.getElementById('theme-version-input');
        const targetInput = document.getElementById('theme-target-input');
        const repoInput = document.getElementById('theme-repo-input');
        const updateInput = document.getElementById('theme-update-input');
        
        const lastMeta = Storage.get('metadata', {});
        if (descInput) descInput.value = lastMeta.description || '';
        if (authorInput) authorInput.value = lastMeta.author || '';
        if (versionInput) versionInput.value = lastMeta.version || '1.0.0';
        if (targetInput) targetInput.value = lastMeta.targetVersion || '';
        if (repoInput) repoInput.value = lastMeta.repositoryUrl || '';
        if (updateInput) updateInput.value = lastMeta.updateUrl || '';
        
        showModal('save-modal');
        input.focus(); input.select();
    };

    const confirmSaveBtn = document.getElementById('confirm-save-btn');
    if (confirmSaveBtn) {
        confirmSaveBtn.addEventListener('click', () => {
            flushPendingEdits();
            try {
                const nameInput = document.getElementById('theme-name-input');
                const name = nameInput.value.trim();
                if (!name) return;

                const snapshots = getSnapshots();
                const metadata = {
                    description: (document.getElementById('theme-desc-input')?.value || '').trim(),
                    author: (document.getElementById('theme-author-input')?.value || '').trim(),
                    version: (document.getElementById('theme-version-input')?.value || '').trim() || '1.0.0',
                    targetVersion: (document.getElementById('theme-target-input')?.value || '').trim(),
                    repositoryUrl: (document.getElementById('theme-repo-input')?.value || '').trim(),
                    updateUrl: (document.getElementById('theme-update-input')?.value || '').trim()
                };
                Storage.set('metadata', metadata);

                snapshots.unshift({ name, ...metadata, ...structuredClone(themeData) });
                saveSnapshots(snapshots);
                // The new entry takes index 0, so every existing snapshot ref moves up one
                shiftThemeRefs(1);
                activeThemeRef[getActiveDataMode()] = { type: 'snapshot', id: 0 };
                renderSnapshots();
                hideModal('save-modal');
                showToast("Theme Saved!");
            } catch(e) { console.warn('Theme Pro:', e); }
        });
    }


    // --- Canvas & CSS Preset CRUD ---
    function setupPresetCRUD({
        presets, storageKey,
        // A getter: Undo, Global Reset and Delete All replace the ref
        // objects, and a captured one would be stale
        getRefMap,
        enabledKey, contentKey, editorId,
        saveModalId, deleteModalId, renameModalId,
        nameInputId, deleteNameId, renameInputId,
        confirmSaveId, confirmDeleteId, confirmRenameId,
        presetDataKey, defaultName, exportExt, exportMime, exportPrefix,
        // The name of the window function that redraws the list
        renderFn,
    }) {
        let itemToDelete = null;
        let renameIndex = null;

        const save = () => {
            const input = $(nameInputId);
            input.value = `${defaultName} ${new Date().toLocaleTimeString()}`;
            showModal(saveModalId);
            input.focus(); input.select();
        };

        const confirmSaveBtn = $(confirmSaveId);
        if (confirmSaveBtn) confirmSaveBtn.addEventListener('click', () => {
            try {
                const name = $(nameInputId).value.trim();
                if (!name) return;
                const content = $(editorId) ? $(editorId).value : "";
                if (!content) return;
                presets.push({ name, [presetDataKey]: content });
                Storage.set(storageKey, presets);
                syncLibrary();
                const dm = getActiveDataMode();
                themeData[dm][enabledKey] = true;
                themeData[dm][contentKey] = content;
                getRefMap()[dm] = presets.length - 1;
                commitChange({ clearRef: false });
                hideModal(saveModalId);
                showToast(`${defaultName} Saved!`);
            } catch(e) { console.warn('Theme Pro:', e); }
        });

        const requestDelete = (index) => {
            if (!presets[index]) return;
            itemToDelete = index;
            $(deleteNameId).innerText = presets[index].name;
            showModal(deleteModalId);
        };

        const confirmDeleteBtn = $(confirmDeleteId);
        if (confirmDeleteBtn) confirmDeleteBtn.addEventListener('click', () => {
            if (itemToDelete === null) return;
            presets.splice(itemToDelete, 1);
            Storage.set(storageKey, presets);
            syncLibrary();
            hideModal(deleteModalId);
            // Every mode's ref moves, not just the current one's. Modes using
            // the deleted preset keep its script or CSS live; only the saved
            // copy goes.
            const refs = getRefMap();
            MODES.forEach(m => {
                if (refs[m] === itemToDelete) {
                    refs[m] = null;
                } else if (refs[m] !== null && refs[m] > itemToDelete) {
                    refs[m]--;
                }
            });
            window[renderFn]();
            pushState();
            itemToDelete = null;
        });

        const requestRename = (index) => {
            if (!presets[index]) return;
            renameIndex = index;
            const input = $(renameInputId);
            input.value = presets[index].name;
            showModal(renameModalId);
            setTimeout(() => input.focus(), 100);
        };

        const confirmRenameBtn = $(confirmRenameId);
        if (confirmRenameBtn) confirmRenameBtn.addEventListener('click', () => {
            const newName = $(renameInputId).value.trim();
            if (newName && renameIndex !== null) {
                presets[renameIndex].name = newName;
                Storage.set(storageKey, presets);
                syncLibrary();
                window[renderFn]();
            }
            hideModal(renameModalId);
        });
        // Cancel and Escape close it too, through hideModal
        const renameModal = $(renameModalId);
        if (renameModal) renameModal.addEventListener('close', () => { renameIndex = null; });

        const update = (index) => {
            const content = $(editorId) ? $(editorId).value : "";
            if (!content || !presets[index]) return;
            presets[index][presetDataKey] = content;
            Storage.set(storageKey, presets);
            syncLibrary();
            const dm = getActiveDataMode();
            getRefMap()[dm] = index;
            themeData[dm][contentKey] = content;
            commitChange({ clearRef: false });
            showToast(`${defaultName} Overwritten!`);
        };

        const exportItem = (index) => {
            const p = presets[index];
            if (!p) return;
            downloadFile(p[presetDataKey], `${exportPrefix}${p.name.replace(/[^a-z0-9]/gi, '_').toLowerCase()}${exportExt}`, exportMime);
            showToast(`${defaultName} exported!`);
        };

        return { save, requestDelete, requestRename, update, export: exportItem };
    }

    // Canvas Presets
    const canvasCRUD = setupPresetCRUD({
        presets: CANVAS_PRESETS, storageKey: 'owui_canvas_presets', getRefMap: () => activeCanvasRef,
        enabledKey: 'canvasEnabled', contentKey: 'canvasScript', editorId: 'canvas-fx-editor',
        saveModalId: 'save-canvas-modal', deleteModalId: 'delete-canvas-modal', renameModalId: 'rename-canvas-modal',
        nameInputId: 'canvas-name-input', deleteNameId: 'delete-canvas-name', renameInputId: 'rename-canvas-input',
        confirmSaveId: 'confirm-save-canvas-btn', confirmDeleteId: 'confirm-delete-canvas-btn', confirmRenameId: 'confirm-rename-canvas-btn',
        presetDataKey: 'script', defaultName: 'Animation', exportExt: '.js', exportMime: 'text/javascript',
        exportPrefix: 'owui-canvas-', renderFn: 'renderCanvasPresets',
    });
    window.saveCanvasSnapshot = canvasCRUD.save;
    window.requestCanvasDelete = canvasCRUD.requestDelete;
    window.requestCanvasRename = canvasCRUD.requestRename;
    window.updateCanvasSnapshot = canvasCRUD.update;
    window.exportCanvasSnapshot = canvasCRUD.export;

    // CSS Presets
    const cssCRUD = setupPresetCRUD({
        presets: CSS_PRESETS, storageKey: 'owui_css_presets', getRefMap: () => activeCssRef,
        enabledKey: 'customCssEnabled', contentKey: 'customCSS', editorId: 'custom-css-editor',
        saveModalId: 'save-css-modal', deleteModalId: 'delete-css-modal', renameModalId: 'rename-css-modal',
        nameInputId: 'css-name-input', deleteNameId: 'delete-css-name', renameInputId: 'rename-css-input',
        confirmSaveId: 'confirm-save-css-btn', confirmDeleteId: 'confirm-delete-css-btn', confirmRenameId: 'confirm-rename-css-btn',
        presetDataKey: 'code', defaultName: 'Snippet', exportExt: '.css', exportMime: 'text/css',
        exportPrefix: 'owui-css-', renderFn: 'renderCssPresets',
    });
    window.saveCssSnapshot = cssCRUD.save;
    window.requestCssDelete = cssCRUD.requestDelete;
    window.requestCssRename = cssCRUD.requestRename;
    window.updateCssSnapshot = cssCRUD.update;
    window.exportCssSnapshot = cssCRUD.export;
    setupDelegation();
    setupVariableGridDelegation();
    setupAccentGridDelegation();
    commitChange({ clearRef: false, snapshots: true }); // Seed undo history with initial state

    // What keeps a chat theme's custom CSS off every user's page, or '': the
    // Launcher's _check_css again, so an older or modified Launcher can't sign
    // CSS that fetches. An escape is its own token, first: \/* opens no comment
    // and \" no string. Comments go and strings stay, as in the browser's
    // tokenizer; an escaped character is never syntax, so one that isn't a
    // letter, digit, - or _ becomes _. Whitespace is CSS's own: JS's \s isn't.
    function chatCssProblem(css) {
        const token = /\\[\s\S]|\/\*[\s\S]*?(?:\*\/|$)|"(?:[^"\\\n]|\\[\s\S])*(?:"|(?=\n)|$)|'(?:[^'\\\n]|\\[\s\S])*(?:'|(?=\n)|$)/y;
        const raw = String(css || '');
        if (/<\/style|<script/i.test(raw)) return 'it contains HTML tags';
        let open = false;
        const read = raw.replace(/\r\n?|\f/g, '\n')
            .replace(new RegExp(token.source, 'g'), t => {
                if (t.startsWith('/*')) {
                    if (t.length < 4 || !t.endsWith('*/')) open = true;
                    return '';
                }
                if (t[0] === '"' && !/^"(?:[^"\\\n]|\\[\s\S])*"$/.test(t)) open = true;
                if (t[0] === "'" && !/^'(?:[^'\\\n]|\\[\s\S])*'$/.test(t)) open = true;
                return t;
            })
            .replace(/\\(?:([0-9a-fA-F]{1,6})[ \t\n]?|(\n)|([\s\S]))/g, (m, hex, nl, other) => {
                if (nl) return '';
                let ch = other;
                if (hex) {
                    const n = parseInt(hex, 16);
                    ch = n > 0 && n < 0x110000 && !(n >= 0xD800 && n < 0xE000) ? String.fromCodePoint(n) : '_';
                }
                return /^[A-Za-z0-9_-]$/.test(ch) ? ch : '_';
            })
            .replace(/[A-Z]+/g, t => t.toLowerCase());
        // Whatever follows it in the stylesheet would be read into it
        if (open) return 'it leaves a comment or string unclosed';
        // An image-set() may hold only data: strings and gradients; a var()
        // could hold a string the browser fetches
        const candidate = /[ \t\n]*(?:["']data:|url\(|[a-z-]*gradient\()/y;
        const imageSetFetches = start => {
            let depth = 0, next = true;
            for (let i = start; i < read.length; i++) {
                if (next && depth === 0) {
                    candidate.lastIndex = i;
                    if (!candidate.test(read)) return true;
                    next = false;
                }
                const ch = read[i];
                if (ch === '"' || ch === "'") {
                    token.lastIndex = i;
                    if (token.test(read)) i = token.lastIndex - 1;
                } else if (ch === '(') depth++;
                else if (ch === ')') { if (depth === 0) return false; depth--; }
                else if (ch === ',' && depth === 0) next = true;
            }
            return false;
        };
        if (read.includes('@import')) return 'it uses @import';
        // Only a quoted data: URL: an unquoted one followed by anything but )
        // is a broken url token, which the browser skips to the next ),
        // comments and quotes included
        if (/(?:url|src)[ \t\n]*\((?![ \t\n]*['"]data:)/.test(read)
            || [...read.matchAll(/image(?:-set)?[ \t\n]*\(/g)].some(m => imageSetFetches(m.index + m[0].length))) {
            return 'it loads a url(), image-set() or src() that is not a quoted data: URL such as url("data:...")';
        }
        if (/expression[ \t\n]*\(|javascript:|-moz-binding|behavior[ \t\n]*:/.test(read)) return 'it uses script in CSS';
        return '';
    }

    // chatCssProblem over a theme with normalized modes: custom CSS as written
    // and as the designer puts it on pages, either way Auto-Scope is set, and
    // manual overrides, whose url() a var() in that CSS could load
    function themeCssProblem(theme) {
        for (const m of MODES) {
            const d = theme[m];
            const problem = chatCssProblem(d.customCSS) || [true, false].map(autoScope =>
                chatCssProblem(buildCustomCss({ ...d, customCssEnabled: true, autoScope }, 'html.dark'))).find(p => p);
            if (problem) return 'custom CSS can\'t be applied: ' + problem;
            const overrides = chatCssProblem(d.manualOverrides);
            if (overrides) return 'manual overrides can\'t be applied: ' + overrides;
        }
        return '';
    }

    // What keeps an install link's import out, or '': a chat model can write
    // the link, so every theme and CSS snippet the import would add gets a
    // chat theme's check. isCss: the text is a stylesheet unless it is JSON.
    function linkedImportProblem(text, isCss) {
        let data = null;
        try { data = JSON.parse(text); } catch (e) {}
        if (!data || typeof data !== 'object') {
            const problem = isCss ? chatCssProblem(text) : '';
            return problem ? 'This CSS snippet can\'t be applied: ' + problem + '.' : '';
        }
        const themes = data.isLibraryBackup && Array.isArray(data.themes)
            ? data.themes.map(t => themeFromEntry(structuredClone(t)))
            : [themeFromFile(structuredClone(data), '')];
        for (const theme of themes) {
            const problem = theme ? themeCssProblem(theme) : '';
            if (problem) return 'This theme\'s ' + problem + '.';
        }
        const snippets = data.isCssBackup && Array.isArray(data.css_presets) ? data.css_presets : [];
        for (const s of snippets) {
            const problem = s && typeof s.code === 'string' ? chatCssProblem(s.code) : '';
            if (problem) return 'This CSS snippet can\'t be applied: ' + problem + '.';
        }
        return '';
    }

    // A whole theme the Theme Designer Pro Launcher tool built in a chat. Its
    // signed link names the theme file's SHA-256; the chat's theme card opens
    // this designer out of sight and sends the file, and only a file with
    // that hash is applied. The card ran on the user's
    // click, so its Canvas FX script needs no second question here.
    function chatTheme(spec) {
        const cfg = window.__THEME_PRO_CONFIG__ || {};
        const peer = window.parent !== window ? window.parent : null;
        if (!peer) return;
        const send = msg => { try { peer.postMessage(Object.assign({ tdpChatTheme: spec.sha }, msg), '*'); } catch (x) {} };
        const beforeKey = 'owui_tdp_chat_before_' + spec.sha;
        let busy = false;

        // crypto.subtle only exists on HTTPS and localhost; plain HTTP on a
        // LAN address still has to check the hash
        async function sha256(text) {
            const bytes = new TextEncoder().encode(text);
            if (window.crypto && crypto.subtle) {
                const d = new Uint8Array(await crypto.subtle.digest('SHA-256', bytes));
                return Array.from(d, b => b.toString(16).padStart(2, '0')).join('');
            }
            const K = [0x428a2f98,0x71374491,0xb5c0fbcf,0xe9b5dba5,0x3956c25b,0x59f111f1,0x923f82a4,0xab1c5ed5,0xd807aa98,0x12835b01,0x243185be,0x550c7dc3,0x72be5d74,0x80deb1fe,0x9bdc06a7,0xc19bf174,0xe49b69c1,0xefbe4786,0x0fc19dc6,0x240ca1cc,0x2de92c6f,0x4a7484aa,0x5cb0a9dc,0x76f988da,0x983e5152,0xa831c66d,0xb00327c8,0xbf597fc7,0xc6e00bf3,0xd5a79147,0x06ca6351,0x14292967,0x27b70a85,0x2e1b2138,0x4d2c6dfc,0x53380d13,0x650a7354,0x766a0abb,0x81c2c92e,0x92722c85,0xa2bfe8a1,0xa81a664b,0xc24b8b70,0xc76c51a3,0xd192e819,0xd6990624,0xf40e3585,0x106aa070,0x19a4c116,0x1e376c08,0x2748774c,0x34b0bcb5,0x391c0cb3,0x4ed8aa4a,0x5b9cca4f,0x682e6ff3,0x748f82ee,0x78a5636f,0x84c87814,0x8cc70208,0x90befffa,0xa4506ceb,0xbef9a3f7,0xc67178f2];
            const H = [0x6a09e667,0xbb67ae85,0x3c6ef372,0xa54ff53a,0x510e527f,0x9b05688c,0x1f83d9ab,0x5be0cd19];
            const len = bytes.length, total = ((len + 9 + 63) >> 6) << 6, m = new Uint8Array(total);
            m.set(bytes); m[len] = 0x80;
            const view = new DataView(m.buffer);
            view.setUint32(total - 8, Math.floor(len / 0x20000000)); view.setUint32(total - 4, (len << 3) >>> 0);
            const w = new Uint32Array(64), rot = (x, n) => (x >>> n) | (x << (32 - n));
            for (let o = 0; o < total; o += 64) {
                for (let i = 0; i < 16; i++) w[i] = view.getUint32(o + i * 4);
                for (let i = 16; i < 64; i++) {
                    const s0 = rot(w[i - 15], 7) ^ rot(w[i - 15], 18) ^ (w[i - 15] >>> 3), s1 = rot(w[i - 2], 17) ^ rot(w[i - 2], 19) ^ (w[i - 2] >>> 10);
                    w[i] = (w[i - 16] + s0 + w[i - 7] + s1) >>> 0;
                }
                let [a, b, c, d, e, f, g, h] = H;
                for (let i = 0; i < 64; i++) {
                    const t1 = (h + (rot(e, 6) ^ rot(e, 11) ^ rot(e, 25)) + ((e & f) ^ (~e & g)) + K[i] + w[i]) >>> 0;
                    const t2 = ((rot(a, 2) ^ rot(a, 13) ^ rot(a, 22)) + ((a & b) ^ (a & c) ^ (b & c))) >>> 0;
                    h = g; g = f; f = e; e = (d + t1) >>> 0; d = c; c = b; b = a; a = (t1 + t2) >>> 0;
                }
                [a, b, c, d, e, f, g, h].forEach((v, i) => { H[i] = (H[i] + v) >>> 0; });
            }
            return H.map(v => v.toString(16).padStart(8, '0')).join('');
        }

        // Straight to the server, Draft or not, and only answered once it is
        // saved: the card closes this page as soon as it hears back
        async function save(body) {
            const r = await fetch('{ROUTE_BASE}', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(Object.assign({ origin: TAB_ORIGIN }, body))
            });
            if (!r.ok) {
                const d = await r.json().catch(() => null);
                throw new Error((d && d.error) || ('The theme could not be saved (HTTP ' + r.status + ').'));
            }
        }
        // This page's own saves (the one it makes as it loads, and the one a change
        // queues) would otherwise land after the card's and put back what it replaced
        async function quiet() {
            clearTimeout(_syncTimer);
            await _syncQueue;
        }
        async function saveTheme() {
            await quiet();
            _userActed = true;
            window.__TDP_HOLD_SAVES__ = false;
            const sections = generateThemeSections();
            await save({ css: assembleThemeCss(sections), state: themeStateStr(), sections });
            if (cfg.scope === 'me') window.dispatchEvent(new Event('tdp-personal-saving'));
            await flushLibrary();
        }

        async function apply(text) {
            if (await sha256(text) !== spec.sha) throw new Error('This theme does not match the one the chat signed.');
            const data = JSON.parse(text);
            if (!data || !_isModeObject(data.dark) || !_isModeObject(data.light)) throw new Error('The chat sent something that is not a theme.');
            const theme = {
                name: String(data.name || 'Chat theme'), description: String(data.description || ''),
                author: String(data.author || ''), version: String(data.version || '1.0.0'), targetVersion: String(data.targetVersion || ''),
                repositoryUrl: '', updateUrl: '',
                dark: data.dark, light: data.light,
                oled: _isModeObject(data.oled) ? data.oled : null, her: _isModeObject(data.her) ? data.her : null
            };
            ensureAllModes(theme);
            // A chat theme has no manual overrides: the Launcher never writes any
            MODES.forEach(m => {
                theme[m] = normalizeModeData(theme[m]);
                theme[m].manualOverrides = '';
                theme[m].manualOverridesEnabled = false;
            });
            const problem = themeCssProblem(theme);
            if (problem) throw new Error('This theme\'s ' + problem + '.');
            flushPendingEdits();
            // What Undo puts back: this theme, or for a user still on the
            // instance theme, the instance theme. Over a saved theme this page
            // couldn't read it shows the defaults, and the server refuses a
            // state that isn't a JSON object, so Undo has nothing to put back.
            const ownTheme = cfg.scope !== 'me' || !!cfg.personalHasTheme;
            try {
                sessionStorage.setItem(beforeKey, JSON.stringify(ownTheme && _savedThemeUnreadable
                    ? { unreadable: true }
                    : { ownTheme, state: captureHistoryState() }));
            } catch (x) {}
            const snapshots = getSnapshots();
            const known = isThemeDuplicate(theme, snapshots);
            if (!known) {
                snapshots.unshift(structuredClone(theme));
                saveSnapshots(snapshots);
                shiftThemeRefs(1);
            }
            const modes = spec.mode && spec.mode !== 'all' ? [spec.mode] : MODES.slice();
            modes.forEach(m => {
                themeData[m] = structuredClone(theme[m]);
                activeThemeRef[m] = known ? null : { type: 'snapshot', id: 0 };
                activeCanvasRef[m] = null; activeCssRef[m] = null; activeGradientRef[m] = null;
            });
            shouldInject = true;
            commitChange({ clearRef: false, snapshots: true });
            await saveTheme();
            return theme.name;
        }

        async function undo() {
            let before = null;
            try { before = JSON.parse(sessionStorage.getItem(beforeKey) || 'null'); } catch (x) {}
            if (!before) throw new Error('This tab no longer has the theme from before. Pick it from your gallery in the designer instead.');
            if (before.unreadable) throw new Error('The theme from before could not be read, so Undo can\u2019t put it back. Pick another theme in the designer instead.');
            flushPendingEdits();
            if (!before.ownTheme) {
                await quiet();
                await save({ reset: true });
                // Back on the instance theme: hold saves until something changes again
                window.__TDP_START_STATE__ = themeStateStr();
                window.__TDP_HOLD_SAVES__ = true;
            } else {
                restoreHistoryState(before.state);
                shouldInject = true;
                commitChange({ clearRef: false });
                await saveTheme();
            }
            try { sessionStorage.removeItem(beforeKey); } catch (x) {}
        }

        window.addEventListener('message', async e => {
            const msg = e.data;
            if (e.source !== peer || !msg || msg.tdpChatTheme !== spec.sha || busy) return;
            busy = true;
            try {
                if (msg.action === 'apply') send({ status: 'applied', name: await apply(String(msg.theme || '')) });
                else if (msg.action === 'undo') { await undo(); send({ status: 'undone' }); }
            } catch (err) {
                send({ status: 'error', message: (err && err.message) || String(err) });
            } finally {
                busy = false;
            }
        });
        let canUndo = false;
        try { canUndo = !!sessionStorage.getItem(beforeKey); } catch (x) {}
        // The card checks the version: a script from a chat needs 1.18.0's isolated runtime
        send({ status: 'ready', canUndo, version: '{VERSION}' });
    }

    // A theme the chat asked for through the Theme Designer Pro Launcher tool,
    // applied once the designer has loaded the theme it starts from.
    const _applyOnLoad = (window.__THEME_PRO_CONFIG__ || {}).applyOnLoad;
    if (_applyOnLoad && _applyOnLoad.kind === 'theme') {
        chatTheme(_applyOnLoad);
    } else if (_applyOnLoad) {
        // Once per link: the address keeps ?apply=, so a reload (another
        // designer's save reloads this one) or a re-rendered chat frame
        // applied it again over everything changed since
        const applyKey = 'owui_tdp_applied_' + (new URLSearchParams(location.search).get('apply') || '');
        let applied = false;
        try { applied = sessionStorage.getItem(applyKey) === '1'; } catch (x) {}
        if (!applied) {
            try { sessionStorage.setItem(applyKey, '1'); } catch (x) {}
            // A theme from a chat is a real change: the other designers should follow it.
            _userActed = true;
            AiConsultant.apply(_applyOnLoad, _applyOnLoad.mode && _applyOnLoad.mode !== 'all' ? [_applyOnLoad.mode] : MODES.slice());
        }
        try {
            const url = new URL(location.href);
            url.searchParams.delete('apply');
            history.replaceState(history.state, '', url);
        } catch (x) {}
    }

    // Mouse events over this iframe never reach the parent page, so Canvas FX
    // there would lose the cursor (transparent areas included). Coordinates are
    // moved from the iframe's frame to the parent's.
    document.addEventListener('mousemove', (e) => {
        try {
            const frame = window.frameElement;
            let ox = 0, oy = 0;
            if (frame) { const r = frame.getBoundingClientRect(); ox = r.left; oy = r.top; }
            window.parent.postMessage({ type: 'owui-canvas-mousemove', x: e.clientX + ox, y: e.clientY + oy }, '*');
        } catch(ex) { console.warn('Theme Pro:', ex); }
    });

