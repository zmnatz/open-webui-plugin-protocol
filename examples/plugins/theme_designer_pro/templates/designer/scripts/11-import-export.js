    // --- Mass Import/Export Portability ---
    document.getElementById('export-all-btn').onclick = () => {
        const snapshots = getSnapshots();
        if (snapshots.length === 0) return showToast("Error: Your library is empty!");
        const cleanedSnapshots = snapshots.map(s => structuredClone(s));
        const dateStr = new Date().toISOString().split('T')[0];
        downloadFile({ themes: cleanedSnapshots, isLibraryBackup: true, version: "{VERSION}" }, `owui-themes-backup-${dateStr}.json`);
    };

    const exportAllCanvasBtn = document.getElementById('export-all-canvas-btn');
    if (exportAllCanvasBtn) {
        exportAllCanvasBtn.onclick = () => {
            if (CANVAS_PRESETS.length === 0) return showToast("Error: No canvas presets to export!");
            const dateStr = new Date().toISOString().split('T')[0];
            downloadFile({ canvas_presets: CANVAS_PRESETS, isCanvasBackup: true, version: "{VERSION}" }, `owui-canvas-backup-${dateStr}.json`);
        };
    }

    const exportAllCssBtn = document.getElementById('export-all-css-btn');
    if (exportAllCssBtn) {
        exportAllCssBtn.onclick = () => {
            if (CSS_PRESETS.length === 0) return showToast("Error: No CSS presets to export!");
            const dateStr = new Date().toISOString().split('T')[0];
            downloadFile({ css_presets: CSS_PRESETS, isCssBackup: true, version: "{VERSION}" }, `owui-css-backup-${dateStr}.json`);
        };
    }

    const exportAllBackupsBtn = document.getElementById('export-all-backups-btn');
    if (exportAllBackupsBtn) {
        exportAllBackupsBtn.onclick = () => {
            const descEl = $('export-all-backups-desc');
            if (descEl) {
                const tCount = getSnapshots().length;
                const cCount = CSS_PRESETS.length;
                const vCount = CANVAS_PRESETS.length;
                const parts = [];
                if (tCount > 0) parts.push(`<b>${tCount}</b> theme${tCount !== 1 ? 's' : ''}`);
                if (cCount > 0) parts.push(`<b>${cCount}</b> CSS snippet${cCount !== 1 ? 's' : ''}`);
                if (vCount > 0) parts.push(`<b>${vCount}</b> canvas preset${vCount !== 1 ? 's' : ''}`);
                const gCount = CUSTOM_GRADIENT_PRESETS.length;
                if (gCount > 0) parts.push(`<b>${gCount}</b> gradient preset${gCount !== 1 ? 's' : ''}`);
                if (parts.length > 0) {
                    descEl.innerHTML = `Download separate <b>.json</b> backup files for: ${parts.join(', ')}.`;
                } else {
                    descEl.innerHTML = `No data available to export yet. Save some themes, CSS snippets, or canvas presets first.`;
                }
            }
            showModal('export-all-backups-modal');
        };

        document.getElementById('confirm-export-all-backups-btn').onclick = () => {
            hideModal('export-all-backups-modal');
            const exportedCount = downloadAllBackups();
            if (exportedCount > 0) {
                showToast(`Exported ${exportedCount} library backup files successfully!`);
            } else {
                showToast("Error: No data available to export.");
            }
        };
    }

    // --- JSON Modal Factory ---
    function setupJsonModal({ modalId, textareaId, collapseId, closeBtnId, openBtnId, onOpen, onCollapse }) {
        const modal = $(modalId), textarea = $(textareaId);
        const collapseBtn = $(collapseId), closeBtn = $(closeBtnId), openBtn = $(openBtnId);
        let collapsed = false;

        if (openBtn) openBtn.addEventListener('click', () => {
            collapsed = false;
            if (collapseBtn) collapseBtn.innerText = 'Collapse';
            onOpen(textarea, false);
            updateLineNumbers(textarea);
            modal.dataset.edited = 'false';
            showModal(modalId);
        });
        // Escape and the backdrop ask before they drop typed edits
        textarea.addEventListener('input', () => { modal.dataset.edited = 'true'; });

        if (closeBtn) closeBtn.addEventListener('click', () => hideModal(modalId));

        if (collapseBtn) collapseBtn.addEventListener('click', () => {
            const result = onCollapse(textarea, !collapsed);
            if (result === false) return; // validation failed
            collapsed = !collapsed;
            collapseBtn.innerText = collapsed ? 'Expand' : 'Collapse';
            updateLineNumbers(textarea);
        });

        return { modal, textarea };
    }

    // Normalize an entire snapshot object to ensure all mode fields have defaults
    function normalizeSnapshot(snap) {
        const normalized = themeMetadata(snap);
        MODES.forEach(mode => {
            if (snap[mode]) {
                normalized[mode] = normalizeModeData(structuredClone(snap[mode]));
            }
        });
        return normalized;
    }

    function themeMetadata(theme) {
        return {
            name: theme.name || '',
            description: theme.description || '',
            author: theme.author || '',
            version: theme.version || '1.0.0',
            targetVersion: theme.targetVersion || '',
            repositoryUrl: theme.repositoryUrl || '',
            updateUrl: theme.updateUrl || ''
        };
    }

    // The live theme, with the metadata of the gallery theme it was loaded from
    function buildThemeJson(collapsed) {
        const ref = activeThemeRef[getActiveDataMode()];
        const loadedFrom = ref && ref.type === 'snapshot' ? getSnapshots()[ref.id] : null;
        const snapshot = themeMetadata(loadedFrom || {});
        MODES.forEach(mode => {
            snapshot[mode] = normalizeModeData(structuredClone(themeData[mode]));
        });

        return JSON.stringify(snapshot, null, collapsed ? 0 : 2);
    }

    // JSON Viewer (read-only)
    setupJsonModal({
        modalId: 'json-view-modal', textareaId: 'json-view-textarea',
        collapseId: 'json-collapse-btn', closeBtnId: 'json-close-btn', openBtnId: 'json-view-btn',
        onOpen: (textarea) => { textarea.value = buildThemeJson(false); },
        onCollapse: (textarea, collapsed) => { textarea.value = buildThemeJson(collapsed); }
    });

    // === Snapshot JSON Manual Editor ===
    const snapshotJsonTextarea = $('snapshot-json-edit-textarea');
    const snapshotJsonValidBadge = $('snapshot-json-valid-badge');
    const snapshotJsonSaveBtn = $('snapshot-json-save-btn');
    const snapshotJsonDiscardBtn = $('snapshot-json-discard-btn');

    function validateJsonEditor(textarea, badge, saveBtn) {
        try {
            JSON.parse(textarea.value);
            badge.textContent = 'Valid JSON';
            badge.style.color = '#22c55e';
            saveBtn.disabled = false;
            saveBtn.style.opacity = '1';
            return true;
        } catch (e) {
            badge.textContent = '✗ Invalid JSON';
            badge.style.color = '#ef4444';
            saveBtn.disabled = true;
            saveBtn.style.opacity = '0.4';
            return false;
        }
    }

    function validateSnapshotJson() {
        return validateJsonEditor(snapshotJsonTextarea, snapshotJsonValidBadge, snapshotJsonSaveBtn);
    }

    setupJsonModal({
        modalId: 'snapshot-json-edit-modal', textareaId: 'snapshot-json-edit-textarea',
        collapseId: 'snapshot-json-collapse-btn', closeBtnId: 'snapshot-json-cancel-btn',
        openBtnId: 'snapshot-json-edit-btn',
        onOpen: (textarea) => {
            if (renameIndex === null) return;
            const snapshots = getSnapshots();
            const snap = snapshots[renameIndex];
            if (!snap) return;
            textarea.value = JSON.stringify(normalizeSnapshot(snap), null, 2);
            validateSnapshotJson();
        },
        onCollapse: (textarea, collapsed) => {
            if (!validateSnapshotJson()) return false;
            const parsed = JSON.parse(textarea.value);
            textarea.value = JSON.stringify(parsed, null, collapsed ? 0 : 2);
        }
    });

    if (snapshotJsonTextarea) {
        snapshotJsonTextarea.addEventListener('input', () => {
            validateSnapshotJson();
            updateLineNumbers(snapshotJsonTextarea);
        });
    }

    if (snapshotJsonDiscardBtn) snapshotJsonDiscardBtn.addEventListener('click', () => hideModal('snapshot-json-edit-modal'));

    if (snapshotJsonSaveBtn) {
        snapshotJsonSaveBtn.addEventListener('click', () => {
            if (!validateSnapshotJson() || renameIndex === null) return;
            const snapshots = getSnapshots();
            const parsedEdit = JSON.parse(snapshotJsonTextarea.value);
            if (!_isThemeEntry(parsedEdit)) { showToast('Not a theme: it needs "dark" and "light" modes'); return; }
            const edited = _repairSnapshotEntry(parsedEdit);
            snapshots[renameIndex] = edited;
            saveSnapshots(snapshots);
            // Update the rename modal fields to reflect any changes
            const g = (id, val) => { const el = document.getElementById(id); if (el) el.value = val || ''; };
            g('rename-input', edited.name);
            g('rename-desc-input', edited.description);
            g('rename-author-input', edited.author);
            g('rename-version-input', edited.version);
            g('rename-target-input', edited.targetVersion);
            g('rename-repo-input', edited.repositoryUrl);
            g('rename-update-input', edited.updateUrl);
            renderSnapshots();
            showToast('Snapshot updated from JSON!');
            hideModal('snapshot-json-edit-modal');
        });
    }

    // === Save (New Theme) JSON Manual Editor ===
    const saveJsonTextarea = $('save-json-edit-textarea');
    const saveJsonValidBadge = $('save-json-valid-badge');
    const saveJsonSaveBtn = $('save-json-save-btn');
    const saveJsonDiscardBtn = $('save-json-discard-btn');

    function validateSaveJson() {
        return validateJsonEditor(saveJsonTextarea, saveJsonValidBadge, saveJsonSaveBtn);
    }

    function buildNewThemeJson(collapsed) {
        const metadata = {
            name: (document.getElementById('theme-name-input')?.value || '').trim(),
            description: (document.getElementById('theme-desc-input')?.value || '').trim(),
            author: (document.getElementById('theme-author-input')?.value || '').trim(),
            version: (document.getElementById('theme-version-input')?.value || '').trim() || '1.0.0',
            targetVersion: (document.getElementById('theme-target-input')?.value || '').trim(),
            repositoryUrl: (document.getElementById('theme-repo-input')?.value || '').trim(),
            updateUrl: (document.getElementById('theme-update-input')?.value || '').trim()
        };
        const snapshot = { ...metadata };
        MODES.forEach(mode => {
            snapshot[mode] = normalizeModeData(structuredClone(themeData[mode]));
        });
        return JSON.stringify(snapshot, null, collapsed ? 0 : 2);
    }

    setupJsonModal({
        modalId: 'save-json-edit-modal', textareaId: 'save-json-edit-textarea',
        collapseId: 'save-json-collapse-btn', closeBtnId: 'save-json-cancel-btn',
        openBtnId: 'save-json-edit-btn',
        onOpen: (textarea) => {
            textarea.value = buildNewThemeJson(false);
            validateSaveJson();
        },
        onCollapse: (textarea, collapsed) => {
            if (!validateSaveJson()) return false;
            const parsed = JSON.parse(textarea.value);
            textarea.value = JSON.stringify(parsed, null, collapsed ? 0 : 2);
        }
    });

    if (saveJsonTextarea) {
        saveJsonTextarea.addEventListener('input', () => {
            validateSaveJson();
            updateLineNumbers(saveJsonTextarea);
        });
    }

    if (saveJsonDiscardBtn) saveJsonDiscardBtn.addEventListener('click', () => hideModal('save-json-edit-modal'));

    if (saveJsonSaveBtn) {
        saveJsonSaveBtn.addEventListener('click', () => {
            if (!validateSaveJson()) return;
            flushPendingEdits();
            try {
                const parsedNew = JSON.parse(saveJsonTextarea.value);
                if (!_isThemeEntry(parsedNew)) { showToast('Not a theme: it needs "dark" and "light" modes'); return; }
                const newTheme = _repairSnapshotEntry(parsedNew);
                if (!newTheme.name || !newTheme.name.trim()) {
                    showToast('Theme name is required');
                    return;
                }
                const snapshots = getSnapshots();
                snapshots.unshift(newTheme);
                saveSnapshots(snapshots);
                shiftThemeRefs(1);
                activeThemeRef[getActiveDataMode()] = { type: 'snapshot', id: 0 };
                // Update save modal fields to reflect the saved JSON
                const g = (id, val) => { const el = document.getElementById(id); if (el) el.value = val || ''; };
                g('theme-name-input', newTheme.name);
                g('theme-desc-input', newTheme.description);
                g('theme-author-input', newTheme.author);
                g('theme-version-input', newTheme.version);
                g('theme-target-input', newTheme.targetVersion);
                g('theme-repo-input', newTheme.repositoryUrl);
                g('theme-update-input', newTheme.updateUrl);
                // Persist metadata for next save
                Storage.set('metadata', {
                    description: newTheme.description || '',
                    author: newTheme.author || '',
                    version: newTheme.version || '1.0.0',
                    targetVersion: newTheme.targetVersion || '',
                    repositoryUrl: newTheme.repositoryUrl || '',
                    updateUrl: newTheme.updateUrl || ''
                });
                renderSnapshots();
                showToast('Theme saved from JSON!');
                hideModal('save-json-edit-modal');
                hideModal('save-modal');
            } catch(e) { console.warn('Theme Pro:', e); }
        });
    }

    // Escape and a click on the backdrop. A JSON editor typed in asks before
    // it drops the edits; its Close and Cancel buttons discard without asking.
    function dismissDialog(modal) {
        if (modal.dataset.edited !== 'true') return hideModal(modal.id);
        askConfirm('Discard your changes?', 'Your edits to this JSON are not saved.', 'Discard')
            .then(ok => { if (ok) hideModal(modal.id); });
    }

    document.querySelectorAll('.modal-overlay').forEach(modal => {
        modal.addEventListener('click', (e) => {
            if (e.target === modal) dismissDialog(modal);
        });
    });

    // --- Mass Delete Factory ---
    function setupMassDelete({ triggerId, modalId, confirmId, emptyMsg, toastMsg, onConfirm, isEmpty }) {
        const triggerBtn = $(triggerId);
        if (triggerBtn) triggerBtn.onclick = () => {
            if (isEmpty()) return showToast(emptyMsg);
            showModal(modalId);
        };
        const confirmBtn = $(confirmId);
        if (confirmBtn) confirmBtn.onclick = () => {
            onConfirm();
            hideModal(modalId);
            showToast(toastMsg);
        };
    }

    setupMassDelete({
        triggerId: 'delete-all-themes-btn', modalId: 'delete-all-themes-modal',
        confirmId: 'confirm-delete-all-themes-btn',
        emptyMsg: 'No themes to delete', toastMsg: 'Theme Gallery Cleared!',
        isEmpty: () => getSnapshots().length === 0,
        onConfirm: () => {
            saveSnapshots([]);
            activeThemeRef = { dark: null, oled: null, light: null, her: null };
            renderSnapshots();
        }
    });

    setupMassDelete({
        triggerId: 'delete-all-canvas-btn', modalId: 'delete-all-canvas-modal',
        confirmId: 'confirm-delete-all-canvas-btn',
        emptyMsg: 'No presets to delete', toastMsg: 'Canvas Presets Cleared!',
        isEmpty: () => CANVAS_PRESETS.length === 0,
        onConfirm: () => {
            CANVAS_PRESETS.length = 0;
            Storage.set('canvas', CANVAS_PRESETS);
            syncLibrary();
            // Only the saved presets go; the live theme's scripts stay
            activeCanvasRef = { dark: null, oled: null, light: null, her: null };
            commitChange({ clearRef: false });
        }
    });

    setupMassDelete({
        triggerId: 'delete-all-css-btn', modalId: 'delete-all-css-modal',
        confirmId: 'confirm-delete-all-css-btn',
        emptyMsg: 'No snippets to delete', toastMsg: 'CSS Snippets Cleared!',
        isEmpty: () => CSS_PRESETS.length === 0,
        onConfirm: () => {
            CSS_PRESETS.length = 0;
            Storage.set('css', CSS_PRESETS);
            syncLibrary();
            // Only the saved snippets go; the live theme's custom CSS stays
            activeCssRef = { dark: null, oled: null, light: null, her: null };
            commitChange({ clearRef: false });
        }
    });

    // --- Duplicate Detection Helpers ---
    function isDuplicate(preset, collection, contentKey) {
        const name = (preset.name || '').trim().toLowerCase();
        const content = (preset[contentKey] || '').trim();
        return collection.some(existing =>
            (existing.name || '').trim().toLowerCase() === name &&
            (existing[contentKey] || '').trim() === content
        );
    }
    const isCanvasDuplicate = (preset) => isDuplicate(preset, CANVAS_PRESETS, 'script');
    const isCssDuplicate = (preset) => isDuplicate(preset, CSS_PRESETS, 'code');

    function isGradientDuplicate(preset) {
        const name = (preset.name || '').trim().toLowerCase();
        const stopsStr = JSON.stringify(preset.stops || []);
        const meshStr = JSON.stringify(preset.meshPoints || []);
        return CUSTOM_GRADIENT_PRESETS.some(existing =>
            (existing.name || '').trim().toLowerCase() === name &&
            JSON.stringify(existing.stops || []) === stopsStr &&
            JSON.stringify(existing.meshPoints || []) === meshStr
        );
    }

    // sanitize(entry, index) returns the entry to add, or null for one that isn't valid
    function addNewPresets(presets, collection, alreadyHas, sanitize) {
        let imported = 0, skipped = 0, invalid = 0;
        presets.forEach((entry, i) => {
            const p = sanitize(entry, i);
            if (!p) { invalid++; return; }
            if (alreadyHas(p)) { skipped++; return; }
            collection.push(p); imported++;
        });
        return { imported, skipped, invalid };
    }
    const sanitizeCanvasPreset = (p, i) => sanitizeCodePreset(p, 'script', `Animation ${i + 1}`);
    const sanitizeCssPreset = (p, i) => sanitizeCodePreset(p, 'code', `Snippet ${i + 1}`);

    // "CSS Snippet" reads "CSS snippet" mid-sentence, not "css snippet"
    function lowerNoun(noun) {
        return noun.replace(/\w+/g, w => w === 'CSS' ? w : w.toLowerCase());
    }

    function createPresetImporter({ collection, storageKey, renderFn, label, parseFile }) {
        return async function(files) {
            let importedCount = 0, skippedCount = 0, invalidCount = 0;
            for (const file of files) {
                try {
                    if (file.size > 16 * 1024 * 1024) { showToast(`File too large: ${_esc(file.name)} (max 16MB)`); skippedCount++; continue; }
                    const text = await file.text();
                    const result = parseFile(file, text);
                    importedCount += result.imported;
                    skippedCount += result.skipped;
                    invalidCount += result.invalid;
                } catch (err) {
                    console.error(`${label} import error on`, file.name, err);
                }
            }
            const invalidMsg = invalidCount > 0 ? ` (${invalidCount} invalid skipped)` : '';
            if (importedCount > 0) {
                Storage.set(storageKey, collection);
                syncLibrary();
                renderFn();
                const notes = [];
                if (skippedCount > 0) notes.push(`${skippedCount} duplicate${skippedCount > 1 ? 's' : ''}`);
                if (invalidCount > 0) notes.push(`${invalidCount} invalid`);
                const skippedMsg = notes.length > 0 ? ` (${notes.join(', ')} skipped)` : '';
                showToast(`Imported ${importedCount} ${label}(s)!${skippedMsg}`);
            } else if (skippedCount > 0) {
                showToast(`${label}${skippedCount > 1 ? 's' : ''} already in library \u2014 no duplicates imported.${invalidMsg}`);
            } else {
                showToast(`Error: No valid ${lowerNoun(label)}s found.${invalidMsg}`);
            }
        };
    }

    const handleCanvasImport = createPresetImporter({
        collection: CANVAS_PRESETS, storageKey: 'owui_canvas_presets',
        renderFn: renderCanvasPresets, label: 'Animation',
        parseFile(file, text) {
            if (file.name.endsWith('.json')) {
                const data = JSON.parse(text);
                if (data.isCanvasBackup && Array.isArray(data.canvas_presets)) return addNewPresets(data.canvas_presets, CANVAS_PRESETS, isCanvasDuplicate, sanitizeCanvasPreset);
            } else if (file.name.endsWith('.js')) {
                return addNewPresets([{ name: file.name.replace('.js', ''), script: text }], CANVAS_PRESETS, isCanvasDuplicate, sanitizeCanvasPreset);
            }
            return { imported: 0, skipped: 0, invalid: 0 };
        }
    });

    const handleCssImport = createPresetImporter({
        collection: CSS_PRESETS, storageKey: 'owui_css_presets',
        renderFn: renderCssPresets, label: 'CSS Snippet',
        parseFile(file, text) {
            if (file.name.endsWith('.json')) {
                const data = JSON.parse(text);
                if (data.isCssBackup && Array.isArray(data.css_presets)) return addNewPresets(data.css_presets, CSS_PRESETS, isCssDuplicate, sanitizeCssPreset);
            } else if (file.name.endsWith('.css')) {
                return addNewPresets([{ name: file.name.replace('.css', ''), code: text }], CSS_PRESETS, isCssDuplicate, sanitizeCssPreset);
            }
            return { imported: 0, skipped: 0, invalid: 0 };
        }
    });

    const handleGradientImport = createPresetImporter({
        collection: CUSTOM_GRADIENT_PRESETS, storageKey: 'owui_gradient_presets',
        renderFn: renderGradientPresets, label: 'Gradient Preset',
        parseFile(file, text) {
            if (!file.name.endsWith('.json')) return { imported: 0, skipped: 0, invalid: 0 };
            const data = JSON.parse(text);
            let presets = [];
            if (data.isGradientBackup && Array.isArray(data.gradient_presets)) {
                presets = data.gradient_presets;
            } else if (Array.isArray(data)) {
                presets = data;
            } else if (data && (data.stops || data.meshPoints)) {
                presets = [data];
            }
            return addNewPresets(presets, CUSTOM_GRADIENT_PRESETS, isGradientDuplicate, sanitizeGradientPreset);
        }
    });

    function openImportModal(modalId, urlInputId, statusId) {
        const urlInput = document.getElementById(urlInputId);
        const statusEl = document.getElementById(statusId);
        if (urlInput) urlInput.value = '';
        if (statusEl) { statusEl.style.display = 'none'; statusEl.textContent = ''; }
        showModal(modalId);
    }

    const importCanvasBtn = document.getElementById('import-canvas-btn');
    if (importCanvasBtn) importCanvasBtn.onclick = () => openImportModal('import-canvas-modal', 'import-canvas-url-input', 'import-canvas-url-status');

    document.getElementById('import-canvas-file-trigger-btn').onclick = () => triggerFileImport({
        accept: '.json,.js', modalId: 'import-canvas-modal', importFn: handleCanvasImport
    });

    document.getElementById('import-canvas-url-load-btn').onclick = () => loadFromUrl({
        urlInputId: 'import-canvas-url-input', statusId: 'import-canvas-url-status',
        loadBtnId: 'import-canvas-url-load-btn', modalId: 'import-canvas-modal',
        fetchMsg: 'Fetching script from URL...', emptyMsg: 'Please enter a URL to a JS or JSON file.',
        defaultName: 'animation.js', defaultExt: '.js', mimeType: 'application/javascript',
        importFn: handleCanvasImport
    });

    document.getElementById('import-canvas-url-input').addEventListener('keydown', (e) => {
        if (e.key === 'Enter') document.getElementById('import-canvas-url-load-btn').click();
    });


    const importCssBtn = document.getElementById('import-css-btn');
    if (importCssBtn) importCssBtn.onclick = () => openImportModal('import-css-modal', 'import-css-url-input', 'import-css-url-status');

    document.getElementById('import-css-file-trigger-btn').onclick = () => triggerFileImport({
        accept: '.json,.css', modalId: 'import-css-modal', importFn: handleCssImport
    });

    document.getElementById('import-css-url-load-btn').onclick = () => loadFromUrl({
        urlInputId: 'import-css-url-input', statusId: 'import-css-url-status',
        loadBtnId: 'import-css-url-load-btn', modalId: 'import-css-modal',
        fetchMsg: 'Fetching CSS from URL...', emptyMsg: 'Please enter a URL to a CSS or JSON file.',
        defaultName: 'snippet.css', defaultExt: '.css', mimeType: 'text/css',
        importFn: handleCssImport
    });

    document.getElementById('import-css-url-input').addEventListener('keydown', (e) => {
        if (e.key === 'Enter') document.getElementById('import-css-url-load-btn').click();
    });


    function isThemeDuplicate(newTheme, existingSnapshots) {
        const nameOf = (t) => String((t && t.name) || '').trim().toLowerCase();
        const sameMode = (a, b) => isModeMatch(a, b) || (!a && !b);
        return existingSnapshots.some(existing => existing && nameOf(existing) === nameOf(newTheme)
            && MODES.every(m => sameMode(existing[m], newTheme[m])));
    }

    async function handleFilesImport(files, { applyAfter = true, canvasConfirmed = false } = {}) {
        let snapshots = getSnapshots();
        let importedCount = 0;
        let skippedCount = 0;
        let routedCount = 0;
        let invalidCount = 0;
        let invalidThemes = 0;

        // One summary toast for every file: "3 Animations (1 dup.)" for what
        // was added, "Animations" for a gallery whose every entry was a duplicate
        // or (invalidSummary) invalid, and how many entries were skipped as invalid
        const importSummary = [];
        const dupSummary = [];
        const invalidSummary = [];
        const importBackup = (presets, sanitize, collection, alreadyHas, save, render, noun) => {
            const { imported, skipped, invalid } = addNewPresets(presets, collection, alreadyHas, sanitize);
            invalidCount += invalid;
            if (imported > 0) {
                save();
                render();
                const skMsg = skipped > 0 ? ` (${skipped} dup.)` : '';
                importSummary.push(`${imported} ${noun}${imported !== 1 ? 's' : ''}${skMsg}`);
                routedCount++;
            } else if (skipped > 0) {
                dupSummary.push(`${noun}s`);
                routedCount++;
            } else if (invalid > 0) {
                invalidSummary.push(`${lowerNoun(noun)}s`);
            }
        };

        for (const file of files) {
            try {
                if (file.size > 16 * 1024 * 1024) { showToast(`File too large: ${_esc(file.name)} (max 16MB)`); skippedCount++; continue; }
                const text = await file.text();
                const data = JSON.parse(text);

                if (data.isCanvasBackup && Array.isArray(data.canvas_presets)) {
                    importBackup(data.canvas_presets, sanitizeCanvasPreset, CANVAS_PRESETS, isCanvasDuplicate,
                        () => { Storage.set('canvas', CANVAS_PRESETS); syncLibrary(); }, renderCanvasPresets, 'Animation');
                }
                if (data.isCssBackup && Array.isArray(data.css_presets)) {
                    importBackup(data.css_presets, sanitizeCssPreset, CSS_PRESETS, isCssDuplicate,
                        () => { Storage.set('css', CSS_PRESETS); syncLibrary(); }, renderCssPresets, 'CSS Snippet');
                }
                // Through the same sanitizer as every other gradient import: a
                // malformed one threw on every render after
                if (data.isGradientBackup && Array.isArray(data.gradient_presets)) {
                    importBackup(data.gradient_presets, sanitizeGradientPreset, CUSTOM_GRADIENT_PRESETS, isGradientDuplicate,
                        persistGradientPresets, renderGradientPresets, 'Gradient Preset');
                }

                if (data.isLibraryBackup && Array.isArray(data.themes)) {
                    data.themes.reverse().forEach(entry => {
                        const t = themeFromEntry(entry);
                        if (!t) { invalidCount++; invalidThemes++; return; }

                        if (isThemeDuplicate(t, snapshots)) { skippedCount++; return; }
                        snapshots.unshift(t);
                        importedCount++;
                    });
                } else {
                    let newTheme = null;
                    if ((data.dark && data.light) || _isLegacyTheme(data)) {
                        newTheme = themeFromFile(data, file.name.replace('.json', '').replace('owui-theme-', '').replace(/_/g, ' '));
                        if (!newTheme) { invalidCount++; invalidThemes++; }
                    } else if (!data.isCanvasBackup && !data.isCssBackup && !data.isGradientBackup) {
                        invalidCount++; invalidThemes++;
                    }
                    if (newTheme) {
                        if (isThemeDuplicate(newTheme, snapshots)) {
                            skippedCount++;
                        } else {
                            snapshots.unshift(newTheme);
                            importedCount++;
                        }
                    }
                }
            } catch (err) {
                console.error("Import error on", file.name, err);
            }
        }

        if (importedCount > 0) {
            saveSnapshots(snapshots);
            shiftThemeRefs(importedCount);
            // A Canvas FX script is JavaScript that runs for everyone who sees
            // the theme, so applying one from a file or URL asks first. The
            // clipboard import already warned in its own dialog.
            if (applyAfter && !canvasConfirmed) {
                const first = snapshots[0];
                const runsScript = MODES.some(m => first[m] && first[m].canvasEnabled && first[m].canvasScript);
                if (runsScript && !(await askConfirm('Apply this theme?', `"${first.name || 'This theme'}" runs a Canvas FX script, which is JavaScript that runs in the browser of everyone who sees this theme. Apply it now? It stays in your gallery either way.`, 'Apply'))) {
                    applyAfter = false;
                }
            }
            if (applyAfter) {
                flushPendingEdits();
                const firstImport = snapshots[0];
                shouldInject = true;

                themeData = structuredClone({
                    dark: firstImport.dark,
                    light: firstImport.light,
                    oled: firstImport.oled,
                    her: firstImport.her
                });
                MODES.forEach(m => {
                    activeThemeRef[m] = { type: 'snapshot', id: 0 };
                });
                commitChange({ clearRef: false, snapshots: true });
            } else {
                // Import into the gallery without activating the theme. The
                // shifted refs are saved with the theme's state.
                commitChange({ clearRef: false, push: false, snapshots: true });
            }

            const skMsg = skippedCount > 0 ? ` (${skippedCount} dup.)` : '';
            importSummary.push(`${importedCount} Theme${importedCount !== 1 ? 's' : ''}${skMsg}`);
        } else if (skippedCount > 0) {
            dupSummary.push('Themes');
        } else if (invalidThemes > 0) {
            invalidSummary.push('themes');
        }

        // Build consolidated summary toast
        const invalidNote = invalidCount > 0 ? ` | Invalid skipped: ${invalidCount}` : '';
        if (importSummary.length > 0) {
            const dupNote = dupSummary.length > 0 ? ` | Dupes skipped: ${dupSummary.join(', ')}` : '';
            showToast(`Imported ${importSummary.join(', ')}${dupNote}${invalidNote}`);
        } else if (dupSummary.length > 0) {
            showToast(`Already in library, no duplicates imported: ${dupSummary.join(', ')}${invalidNote}`);
        } else if (invalidSummary.length > 0) {
            showToast(`Error: No valid ${invalidSummary.join(', ')} found in file.${invalidNote}`);
        } else if (routedCount === 0) {
            showToast("Error: No valid themes found in file.");
        }
    }

    function setupGalleryFilter(btnId, dropdownId, setFilter, renderFn) {
        const btn = document.getElementById(btnId);
        const dropdown = document.getElementById(dropdownId);
        if (!btn || !dropdown) return;
        btn.addEventListener('click', (e) => {
            e.stopPropagation();
            dropdown.classList.toggle('open');
        });
        dropdown.querySelectorAll('.tag-filter-option').forEach(opt => {
            opt.addEventListener('click', (e) => {
                e.stopPropagation();
                const filter = opt.getAttribute('data-filter');
                setFilter(filter);
                dropdown.querySelectorAll('.tag-filter-option').forEach(o => o.classList.remove('active'));
                opt.classList.add('active');
                btn.classList.toggle('has-filter', filter !== 'all');
                dropdown.classList.remove('open');
                renderFn();
            });
        });
        document.addEventListener('click', (e) => {
            if (!btn.contains(e.target) && !dropdown.contains(e.target)) {
                dropdown.classList.remove('open');
            }
        });
    }

    function setupGallerySort(btnId, sortStateGetter, sortStateSetter, renderFn) {
        const btn = document.getElementById(btnId);
        if (btn) {
            const sortCycle = ['default', 'asc', 'desc'];
            const sortLabels = { default: 'Default Sort', asc: 'Sort Ascending', desc: 'Sort Descending' };
            btn.addEventListener('click', () => {
                const current = sortStateGetter();
                const idx = sortCycle.indexOf(current);
                const next = sortCycle[(idx + 1) % sortCycle.length];
                sortStateSetter(next);
                btn.setAttribute('data-sort', next);
                btn.setAttribute('data-tooltip', sortLabels[next]);
                btn.setAttribute('aria-label', sortLabels[next]);
                btn.classList.toggle('has-sort', next !== 'default');
                renderFn();
            });
        }
    }

    setupGallerySearch('theme-search-toggle-btn', 'theme-search-input', renderSnapshots);

    let activeTagFilter = 'all';
    setupGalleryFilter('tag-filter-toggle-btn', 'tag-filter-dropdown', (v) => { activeTagFilter = v; }, renderSnapshots);
    let activeGradientTypeFilter = 'all';
    setupGalleryFilter('gradient-filter-toggle-btn', 'gradient-filter-dropdown', (v) => { activeGradientTypeFilter = v; }, renderGradientPresets);
    // Badge-based: WebGL / Context / DOM Access
    let activeCanvasTypeFilter = 'all';
    setupGalleryFilter('canvas-filter-toggle-btn', 'canvas-filter-dropdown', (v) => { activeCanvasTypeFilter = v; }, renderCanvasPresets);

    let activeSort = 'default';
    setupGallerySort('theme-sort-btn', () => activeSort, (v) => { activeSort = v; }, renderSnapshots);
    let activeCssSort = 'default';
    setupGallerySort('css-sort-btn', () => activeCssSort, (v) => { activeCssSort = v; }, renderCssPresets);
    let activeCanvasSort = 'default';
    setupGallerySort('canvas-sort-btn', () => activeCanvasSort, (v) => { activeCanvasSort = v; }, renderCanvasPresets);
    let activeGradientSort = 'default';
    setupGallerySort('gradient-sort-btn', () => activeGradientSort, (v) => { activeGradientSort = v; }, renderGradientPresets);

    function setupGallerySearch(toggleId, inputId, renderFn) {
        const toggle = document.getElementById(toggleId);
        const input = document.getElementById(inputId);
        const clearBtn = document.getElementById(inputId + '-clear');
        let isOpen = false;

        function updateClearBtn() {
            if (clearBtn) {
                if (isOpen && input.value.length > 0) {
                    clearBtn.classList.add('visible');
                } else {
                    clearBtn.classList.remove('visible');
                }
            }
        }

        if (toggle && input) {
            toggle.onclick = () => {
                isOpen = !isOpen;
                if (isOpen) {
                    input.style.width = '140px';
                    input.style.padding = '4px 8px 4px 26px';
                    input.style.opacity = '1';
                    input.style.borderColor = 'var(--border)';
                    input.style.background = 'rgba(255,255,255,0.05)';
                    input.tabIndex = 0;
                    input.focus();
                    updateClearBtn();
                } else {
                    input.value = '';
                    input.style.width = '0';
                    input.style.padding = '0';
                    input.style.opacity = '0';
                    input.style.borderColor = 'transparent';
                    input.style.background = 'transparent';
                    input.tabIndex = -1;
                    updateClearBtn();
                    renderFn();
                }
            };
            input.addEventListener('input', () => { updateClearBtn(); renderFn(); });
            input.addEventListener('keydown', (e) => {
                if (e.key === 'Escape') { e.stopPropagation(); toggle.click(); }
            });
        }
        if (clearBtn && input) {
            clearBtn.onclick = () => {
                input.value = '';
                updateClearBtn();
                input.focus();
                renderFn();
            };
        }
    }
    setupGallerySearch('css-search-toggle-btn', 'css-search-input', renderCssPresets);
    setupGallerySearch('canvas-search-toggle-btn', 'canvas-search-input', renderCanvasPresets);
    setupGallerySearch('gradient-search-toggle-btn', 'gradient-search-input', renderGradientPresets);
    setupGallerySearch('community-search-toggle-btn', 'community-search-input', () => { if (_communityCatalog) renderCommunityGrid(_communityCatalog); });
    let activeCommunitySort = 'default';
    setupGallerySort('community-sort-btn', () => activeCommunitySort, (v) => { activeCommunitySort = v; }, () => { if (_communityCatalog) renderCommunityGrid(_communityCatalog); });

    document.getElementById('import-json-btn').onclick = () => openImportModal('import-theme-modal', 'import-url-input', 'import-url-status');

    document.getElementById('import-file-trigger-btn').onclick = () => triggerFileImport({
        accept: '.json', modalId: 'import-theme-modal', importFn: handleFilesImport
    });

    document.getElementById('import-url-load-btn').onclick = () => loadFromUrl({
        urlInputId: 'import-url-input', statusId: 'import-url-status',
        loadBtnId: 'import-url-load-btn', modalId: 'import-theme-modal',
        fetchMsg: 'Fetching theme from URL...', emptyMsg: 'Please enter a URL to a theme JSON file.',
        defaultName: 'theme.json', defaultExt: '.json', mimeType: 'application/json',
        importFn: handleFilesImport
    });

    document.getElementById('import-url-input').addEventListener('keydown', (e) => {
        if (e.key === 'Enter') {
            e.preventDefault();
            document.getElementById('import-url-load-btn').click();
        }
    });


    // Drag and Drop Import Logic
    const dropOverlay = document.getElementById('drop-overlay');
    window.addEventListener('dragover', (e) => {
        e.preventDefault();
        dropOverlay.style.display = 'flex';
    });
    window.addEventListener('dragleave', (e) => {
        if (e.target === dropOverlay) dropOverlay.style.display = 'none';
    });
    window.addEventListener('drop', async (e) => {
        e.preventDefault();
        dropOverlay.style.display = 'none';
        const allFiles = Array.from(e.dataTransfer.files);
        if (allFiles.length === 0) return; // Not a file drop (text, link, image drag) — ignore silently
        const files = allFiles.filter(f => f.name.endsWith('.json') || f.name.endsWith('.js') || f.name.endsWith('.css'));
        if (files.length > 0) {
            const jsFiles = files.filter(f => f.name.endsWith('.js'));
            const cssFiles = files.filter(f => f.name.endsWith('.css'));
            const jsonFiles = files.filter(f => f.name.endsWith('.json'));
            if (jsFiles.length > 0) await handleCanvasImport(jsFiles);
            if (cssFiles.length > 0) await handleCssImport(cssFiles);
            // A gradient preset file (one gradient, or a list of them) goes to
            // the Gradient gallery; themes, bundles and backups to the theme import
            const isGradient = (d) => d && typeof d === 'object' && !Array.isArray(d) && !d.dark && !d.light && typeof d.name === 'string' && (Array.isArray(d.stops) || Array.isArray(d.meshPoints));
            const gradientFiles = [], otherJson = [];
            for (const f of jsonFiles) {
                let data = null;
                try { data = JSON.parse(await f.text()); } catch (x) {}
                const gradient = isGradient(data) || (Array.isArray(data) && data.length > 0 && data.every(isGradient));
                (gradient ? gradientFiles : otherJson).push(f);
            }
            if (gradientFiles.length > 0) await handleGradientImport(gradientFiles);
            if (otherJson.length > 0) await handleFilesImport(otherJson);
        } else {
            showToast("Error: Only .json, .js, or .css files are supported.");
        }
    });

    window.exportSnapshot = (index) => {
        const snapshots = getSnapshots();
        const s = snapshots[index];
        if (!s) return;
        const data = {
            name: s.name,
            description: s.description || '',
            author: s.author || '',
            version: s.version || '1.0.0',
            targetVersion: s.targetVersion || '',
            repositoryUrl: s.repositoryUrl || '',
            updateUrl: s.updateUrl || '',
            dark: structuredClone(s.dark),
            light: structuredClone(s.light),
            oled: structuredClone(s.oled),
            her: structuredClone(s.her)
        };
        const cleanName = s.name ? String(s.name).replace(/[^a-z0-9]/gi, '_').toLowerCase() : 'custom-theme';
        const dateStr = new Date().toISOString().split('T')[0];
        downloadFile(data, `owui-theme-${cleanName}-${dateStr}.json`);
    };

