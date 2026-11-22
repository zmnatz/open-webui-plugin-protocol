    // === SURFACES TAB ===
    // One row per layer, built from SURFACE_LAYERS. The values are the mode's
    // own; with the switch off the theme leaves the layers to the instance's
    // Sidebar and Overlay Transparency settings.
    (function buildSurfacesTab() {
        const list = $('surfaces-list');
        if (!list) return;
        list.innerHTML = SURFACE_LAYERS.map(l => {
            const first = l.key === 'Backdrop' ? 'Darkness' : 'Opacity';
            // No for= on the label, as on Core Palette: a click on it would
            // focus the slider and scroll it into view between the two
            // clicks of a double-click. The slider carries its own name.
            const slider = (field, name, max, unit) =>
                `<div class="slider-row"><label data-reset="${field}"><span data-tooltip="Double-click to reset to ${DEFAULT_MODE_DATA[field]}${unit}" style="cursor:pointer">${name}</span> <span class="slider-val" id="val-${field}"></span></label>` +
                `<input type="range" id="sl-${field}" data-field="${field}" data-unit="${unit}" min="0" max="${max}" value="0" aria-label="${l.label} ${name.toLowerCase()}"></div>`;
            return `<div class="surface-row"><div class="surface-row-name">${l.label}</div><div class="surface-row-hint">${l.hint}</div>` +
                `<div class="surface-sliders">${slider(`surface${l.key}Opacity`, first, 100, '%')}` +
                (l.noBlur ? '' : slider(`surface${l.key}Blur`, 'Blur', 40, 'px')) + `</div></div>`;
        }).join('');
        list.querySelectorAll('input[type="range"]').forEach(slider => {
            slider.addEventListener('input', () => {
                const dm = getActiveDataMode();
                themeData[dm][slider.dataset.field] = parseInt(slider.value);
                $('val-' + slider.dataset.field).innerText = slider.value + slider.dataset.unit;
                commitChange({ push: false });
            });
            slider.addEventListener('change', () => pushState());
        });
    })();

    // Double-click on a slider's label: back to the default. Does nothing
    // while the switch is off, the same as dragging.
    window.resetSurfaceSlider = (field) => {
        const slider = $('sl-' + field);
        if (!slider || slider.disabled) return;
        slider.value = DEFAULT_MODE_DATA[field];
        slider.dispatchEvent(new Event('input'));
        slider.dispatchEvent(new Event('change'));
    };

    // Turning Surfaces on for the first time starts from what the instance
    // settings draw today, so nothing jumps
    function seedSurfacesFromValves(d) {
        if (!SURFACE_FIELDS.slice(1).every(k => d[k] === DEFAULT_MODE_DATA[k])) return;
        const cfg = window.__THEME_PRO_CONFIG__ || {};
        if (cfg.sidebarTransparency === 'translucent') { d.surfaceSidebarOpacity = 20; d.surfaceSidebarBlur = 20; }
        else if (cfg.sidebarTransparency === 'transparent') { d.surfaceSidebarOpacity = 0; d.surfaceSidebarBlur = 0; }
        if (cfg.overlayTransparency === 'translucent') {
            d.surfaceMenuOpacity = 25; d.surfaceMenuBlur = 20;
            d.surfaceDialogOpacity = 25; d.surfaceDialogBlur = 20;
            d.surfaceFadeOpacity = 0;
        }
    }

    $('toggle-surfaces')?.addEventListener('change', (e) => {
        const d = themeData[getActiveDataMode()];
        if (e.target.checked) seedSurfacesFromValves(d);
        d.surfacesEnabled = e.target.checked;
        commitChange();
    });

    function renderSurfacesTab() {
        const d = themeData[getActiveDataMode()];
        if (!d) return;
        const on = !!d.surfacesEnabled;
        const toggle = $('toggle-surfaces');
        if (toggle) toggle.checked = on;
        $('surfaces-list')?.classList.toggle('off', !on);
        document.querySelectorAll('#surfaces-list input[type="range"]').forEach(slider => {
            const k = slider.dataset.field;
            const v = d[k] ?? DEFAULT_MODE_DATA[k];
            slider.value = v;
            slider.disabled = !on;
            $('val-' + k).innerText = v + slider.dataset.unit;
        });
        const note = $('surfaces-note');
        if (note) {
            const cfg = window.__THEME_PRO_CONFIG__ || {};
            note.innerText = on
                ? "Opacity is how much of Open WebUI's own color covers each layer: 100% is solid, 0% is clear. Blur softens whatever shows through it. These win over the instance's Sidebar and Overlay Transparency settings in this mode."
                : `Off: this mode follows the instance's Sidebar Transparency (${cfg.sidebarTransparency || 'opaque'}) and Overlay Transparency (${cfg.overlayTransparency || 'opaque'}) settings. Turn it on to set each layer yourself.`;
        }
    }

    const MODE_LABELS = { dark: 'Dark', oled: 'OLED', light: 'Light', her: 'Her', system: 'System' };

    $('reset-mode-btn').onclick = () => {
        const dm = getActiveDataMode();
        const label = activeMode === 'system' ? `System (${MODE_LABELS[dm]})` : MODE_LABELS[activeMode];
        $('reset-target-mode').innerText = label;
        $('reset-backup-cb').checked = false;
        showModal('reset-modal');
    };

    $('confirm-reset-btn').onclick = () => {
        hideModal('reset-modal');
        const saveBackup = $('reset-backup-cb').checked;
        resetActiveMode(false, saveBackup);
    };
    
    $('nuclear-btn').onclick = () => {
        $('nuclear-backup-cb').checked = false;
        showModal('nuclear-modal');
    };
    
    $('confirm-nuclear-btn').onclick = () => {
        hideModal('nuclear-modal');
        const saveBackup = $('nuclear-backup-cb').checked;
        nuclearReset(false, saveBackup);
    };
    $('factory-reset-btn').onclick = () => showModal('factory-reset-modal');
    $('confirm-factory-reset-btn').onclick = async () => {
        flushPendingEdits();
        const backupCb = $('factory-backup-cb');
        if (backupCb && backupCb.checked) {
            // Up to four files, and the browser may ask before allowing more
            // than one; wiping and reloading at once could lose the rest
            if (downloadAllBackups() > 0 && !(await askConfirm('Wipe everything?', 'Your backup files are downloading. Wipe everything once they have saved?', 'Wipe everything'))) return;
        }
        const keysToWipe =[
            'owui_dev_theme_v1', 
            'owui_dev_theme_v1_css',
            'owui_theme_snapshots',
            'owui_canvas_presets',
            'owui_css_presets',
            'owui_gradient_presets',
            'owui_canvas_last_mode',
            'owui_canvas_last_script',
            'owui_theme_last_metadata',
            'owui_tdp_model_bg',
            'owui_tdp_chat_bg'
        ];
        keysToWipe.forEach(k => {
            Storage.remove(k);
            try { localStorage.removeItem(k); } catch(e) { console.warn('Theme Pro:', e); }
        });
        try { sessionStorage.removeItem('owui_theme_draft_mode'); } catch(e) {}
        // A save still queued would land after the reset and put the theme
        // back, and a library save or upload the wiped presets and pictures
        clearTimeout(_syncTimer);
        clearTimeout(_libTimer);
        _libTimer = null;
        await _syncQueue;
        await _libQueue;
        fetch('{ROUTE_BASE}', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            // A personal designer's reset keeps the library unless asked to wipe it.
            body: JSON.stringify({ css: '', reset: true, wipe_library: true, origin: TAB_ORIGIN })
        }).then(r => {
            if (r.ok) {
                console.log('[Theme Pro] Factory reset complete — reloading');
            } else {
                console.warn('[Theme Pro] Factory reset server responded with', r.status);
            }
            forgetPendingSaves();
            window.location.reload();
        }).catch(e => {
            console.warn('[Theme Pro] Factory reset server POST failed:', e);
            // Reload anyway — local state is already wiped
            forgetPendingSaves();
            window.location.reload();
        });
    };

