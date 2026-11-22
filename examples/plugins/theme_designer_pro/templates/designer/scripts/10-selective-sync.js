    // --- Selective Sync ---
    const SYNC_SECTIONS = Object.keys(MODE_SECTION_FIELDS);
    let syncSourceType = 'active-mode'; // 'active-mode', 'snapshot'
    let syncSourceId = null;

    function updateTargetsHeaderToggleState() {
        const enabledTargets = MODES.filter(m => {
            const cb = $(`sync-target-${m}`);
            return cb && !cb.disabled;
        });
        const checkedTargets = enabledTargets.filter(m => {
            const cb = $(`sync-target-${m}`);
            return cb && cb.checked;
        });
        const toggleBtn = $('sync-toggle-targets');
        if (toggleBtn && enabledTargets.length > 0) {
            toggleBtn.innerText = (checkedTargets.length === enabledTargets.length) ? 'Deselect All' : 'Select All';
        }
    }

    function updateOptionsHeaderToggleState() {
        const checkedOptions = SYNC_SECTIONS.filter(opt => {
            const cb = $(`sync-opt-${opt}`);
            return cb && cb.checked;
        });
        const toggleBtn = $('sync-toggle-options');
        if (toggleBtn) {
            toggleBtn.innerText = (checkedOptions.length === SYNC_SECTIONS.length) ? 'Deselect All' : 'Select All';
        }
    }

    SYNC_SECTIONS.forEach(opt => {
        const cb = $(`sync-opt-${opt}`);
        if (cb) cb.addEventListener('change', updateOptionsHeaderToggleState);
    });

    $('sync-toggle-targets').onclick = () => {
        const toggleBtn = $('sync-toggle-targets');
        const shouldSelect = (toggleBtn.innerText === 'Select All');
        MODES.forEach(m => {
            const cb = $(`sync-target-${m}`);
            if (cb && !cb.disabled) {
                cb.checked = shouldSelect;
                const pill = cb.closest('.sync-mode-pill');
                if (pill) pill.classList.toggle('active', shouldSelect);
            }
        });
        toggleBtn.innerText = shouldSelect ? 'Deselect All' : 'Select All';
        updateSyncDeltaBadges();
    };

    $('sync-toggle-options').onclick = () => {
        const toggleBtn = $('sync-toggle-options');
        const shouldSelect = (toggleBtn.innerText === 'Select All');
        SYNC_SECTIONS.forEach(opt => {
            const cb = $(`sync-opt-${opt}`);
            if (cb) cb.checked = shouldSelect;
        });
        toggleBtn.innerText = shouldSelect ? 'Deselect All' : 'Select All';
    };

    // A library theme saved without this mode: OLED is its Dark at black,
    // Her its Light
    function snapshotModeData(s, mode) {
        if (s[mode]) return s[mode];
        if (mode === 'oled' && s.dark) { const src = structuredClone(s.dark); src.l = 0; return src; }
        if (mode === 'her' && s.light) return structuredClone(s.light);
        return structuredClone(s.dark || s.light);
    }

    // When the source and target modes were both applied from the same
    // library theme, that theme's own copy of the target mode: syncing from
    // it leaves the modes the theme sets apart (its Light against its Dark)
    // as the theme made them
    function linkedSnapshotMode(sourceMode, targetMode) {
        const srcRef = activeThemeRef[sourceMode];
        const tgtRef = activeThemeRef[targetMode];
        if (!srcRef || !tgtRef || srcRef.type !== 'snapshot' || tgtRef.type !== 'snapshot' || srcRef.id !== tgtRef.id) return null;
        return getSnapshots()[srcRef.id]?.[targetMode] || null;
    }

    function getSyncSourceData(targetMode) {
        if (syncSourceType === 'active-mode') {
            const dm = getActiveDataMode();
            const src = linkedSnapshotMode(dm, targetMode) || themeData[dm];
            // Syncing into OLED sets its lightness to 0 (adjustL in the
            // confirm handler), even when the linked theme gives OLED its own
            return targetMode === 'oled' ? { ...src, l: 0 } : src;
        } else if (syncSourceType === 'snapshot') {
            const s = getSnapshots()[syncSourceId];
            return s ? snapshotModeData(s, targetMode) : null;
        }
        return null;
    }

    function setSyncBadge(badge, isSync, diffCount) {
        if (!badge) return;
        badge.style.display = 'inline-flex';
        const settingKey = (badge.id || '').replace('sync-badge-', '');
        const chevron = document.querySelector(`.sync-diff-chevron[data-setting="${settingKey}"]`);
        if (isSync) {
            badge.className = 'sync-delta-badge in-sync';
            badge.innerHTML = '✓ In Sync';
            badge.onclick = null;
            badge.style.cursor = 'default';
            if (chevron) { chevron.style.display = 'none'; chevron.classList.remove('expanded'); chevron.setAttribute('aria-expanded', 'false'); }
            const panel = $(`sync-diff-${settingKey}`);
            if (panel) panel.style.display = 'none';
        } else {
            badge.className = 'sync-delta-badge diff-detected';
            badge.innerHTML = diffCount > 1 ? `⚠ ${diffCount} modes differ` : '⚠ Diff';
            badge.style.cursor = 'pointer';
            badge.onclick = (e) => { e.stopPropagation(); toggleSyncDiff(settingKey); };
            if (chevron) chevron.style.display = '';
        }
    }

    let syncDiffData = {};

    // What each section's diff panel shows of the current mode and the
    // incoming one
    const SYNC_DIFF_VIEWS = {
        palette: (cur, inc) => ({ src: _paletteView(cur), tgt: _paletteView(inc), srcOverrides: cur.overrides, tgtOverrides: inc.overrides }),
        overrides: (cur, inc) => ({ src: cur.overrides, tgt: inc.overrides }),
        css: (cur, inc) => ({ src: cur.customCSS, tgt: inc.customCSS }),
        canvas: (cur, inc) => ({ src: cur.canvasScript, tgt: inc.canvasScript }),
        gradient: (cur, inc) => ({ src: _gradientView(cur), tgt: _gradientView(inc) }),
        surfaces: (cur, inc) => ({ src: SURFACE_FIELDS.map(k => cur[k]), tgt: SURFACE_FIELDS.map(k => inc[k]) }),
        auth: (cur, inc) => ({ srcAuth: MODE_SECTION_FIELDS.auth.map(k => cur[k]), tgtAuth: MODE_SECTION_FIELDS.auth.map(k => inc[k]) })
    };

    function updateSyncDeltaBadges() {
        const targetModes = MODES.filter(m => {
            const cb = $(`sync-target-${m}`);
            return cb && cb.checked && !cb.disabled;
        });

        syncDiffData = Object.fromEntries(SYNC_SECTIONS.map(k => [k, []]));

        if (targetModes.length === 0) {
            SYNC_SECTIONS.forEach(k => {
                const badge = $(`sync-badge-${k}`);
                if (badge) badge.style.display = 'none';
                const chevron = document.querySelector(`.sync-diff-chevron[data-setting="${k}"]`);
                if (chevron) chevron.style.display = 'none';
                const panel = $(`sync-diff-${k}`);
                if (panel) panel.style.display = 'none';
            });
            return;
        }

        for (const mode of targetModes) {
            const rawSource = getSyncSourceData(mode);
            if (!rawSource) continue;
            const incoming = normalizeModeData(structuredClone(rawSource));
            const current = normalizeModeData(structuredClone(themeData[mode]));
            const differs = new Set(modeSectionDiffs(incoming, current));
            SYNC_SECTIONS.forEach(k => {
                syncDiffData[k].push({ mode, match: !differs.has(k), from: current, to: incoming, ...SYNC_DIFF_VIEWS[k](current, incoming) });
            });
        }

        SYNC_SECTIONS.forEach(k => {
            const diffCount = syncDiffData[k].filter(entry => !entry.match).length;
            setSyncBadge($(`sync-badge-${k}`), diffCount === 0, diffCount);
        });
        SYNC_SECTIONS.forEach(k => {
            const panel = $(`sync-diff-${k}`);
            if (panel && panel.style.display !== 'none') renderSyncDiffPanel(k);
        });
    }

    function collapseAllSyncDiffs() {
        SYNC_SECTIONS.forEach(k => {
            const panel = $(`sync-diff-${k}`);
            if (panel) panel.style.display = 'none';
            const chevron = document.querySelector(`.sync-diff-chevron[data-setting="${k}"]`);
            if (chevron) { chevron.classList.remove('expanded'); chevron.setAttribute('aria-expanded', 'false'); }
        });
    }

    function toggleSyncDiff(settingKey) {
        const panel = $(`sync-diff-${settingKey}`);
        const chevron = document.querySelector(`.sync-diff-chevron[data-setting="${settingKey}"]`);
        if (!panel) return;
        const isOpen = panel.style.display !== 'none';
        collapseAllSyncDiffs();
        if (!isOpen) {
            renderSyncDiffPanel(settingKey);
            panel.style.display = 'block';
            panel.setAttribute('data-animating', '');
            setTimeout(() => panel.removeAttribute('data-animating'), 260);
            if (chevron) { chevron.classList.add('expanded'); chevron.setAttribute('aria-expanded', 'true'); }
        }
    }

    // --- Sync diff panels ---
    function _esc(s) { const d = document.createElement('div'); d.textContent = s; return d.innerHTML; }

    function _rampSwatches(config) {
        // Generate 12 mini color swatches from OKLCH config. Update diffs feed
        // this REMOTE data, so h and override values are attacker-influenced.
        const h = _cssNum(config.h, 0), c = _cssNum(config.c, 0) / 1000, l = _cssNum(config.l, 0) / 100;
        const ov = config.overrides || {};
        const deltaL = l - 0.20;
        return steps.map(step => {
            const baseL = lightnessMap[step];
            const targetL = Math.max(0.00, Math.min(0.98, baseL + deltaL));
            const computedVal = _cssTok(ov[`--color-gray-${step}`], '') || `oklch(${targetL.toFixed(3)} ${c.toFixed(3)} ${c === 0 ? 0 : h})`;
            return `<div class="swatch" style="background:${computedVal}"></div>`;
        }).join('');
    }

    function renderSyncDiffPanel(key) {
        _codeDiffIdCounter = 0;
        const panel = $(`sync-diff-${key}`);
        if (!panel) return;
        const data = syncDiffData[key] || [];
        if (data.length === 0) { panel.innerHTML = '<div style="opacity:0.5; font-size:0.55rem; padding:4px;">No targets selected</div>'; return; }

        const useGrid = key === 'overrides' && data.length >= 2;
        let html = useGrid ? '<div class="sync-diff-grid">' : '';
        for (const entry of data) {
            html += `<div class="sync-diff-mode-row">`;
            html += `<div class="sync-diff-mode-header"><span class="mode-dot ${entry.mode}"></span> ${MODE_LABELS[entry.mode]} `;
            if (entry.match) {
                html += `<span class="sync-diff-match-tag">✓ Match</span>`;
                html += `</div></div>`;
                continue;
            }
            html += `</div>`;

            if (key === 'palette') html += _renderPaletteDiff(entry);
            else if (key === 'overrides') html += _renderOverridesDiff(entry);
            else if (key === 'css') html += _renderCssDiff(entry);
            else if (key === 'canvas') html += _renderCanvasDiff(entry);
            else if (key === 'gradient') html += _renderGradientDiff(entry);
            else if (key === 'surfaces') html += _renderSurfacesDiff(entry);
            else if (key === 'auth') html += _renderAuthDiff(entry);
            html += _renderSectionExtras(key, entry.from, entry.to, entry.mode);

            html += `</div>`;
        }
        if (useGrid) html += '</div>';
        panel.innerHTML = html;
    }

    function _renderPaletteDiff(entry) {
        const s = entry.src, t = entry.tgt;
        const srcConf = { h: s.h, c: s.c, l: s.l, overrides: entry.srcOverrides || {} };
        const tgtConf = { h: t.h, c: t.c, l: t.l, overrides: entry.tgtOverrides || {} };
        let h = '';
        h += `<div class="sync-diff-ramp-row"><span class="sync-diff-ramp-label">From</span><div class="sync-diff-ramp">${_rampSwatches(srcConf)}</div></div>`;
        h += `<div class="sync-diff-ramp-row"><span class="sync-diff-ramp-label">To</span><div class="sync-diff-ramp">${_rampSwatches(tgtConf)}</div></div>`;
        const fmt = (v) => v != null && !isNaN(v) ? Number(v).toFixed(1) : '—';
        const valueRow = (label, from, to) => {
            const delta = (from != null && to != null) ? (to - from).toFixed(1) : null;
            return `<span>${label}: ${fmt(from)}→${fmt(to)}${delta && delta !== '0.0' ? ` <span class="delta">(Δ${delta > 0 ? '+':''}${delta})</span>` : ''}</span>`;
        };
        h += `<div class="sync-diff-values">`;
        h += valueRow('H', s.h, t.h) + valueRow('C', s.c, t.c) + valueRow('L', s.l, t.l);
        // Counted, not shown: update diffs feed this remote data
        const sa = s.accents || [], ta = t.accents || [];
        const fmtA = (list) => { const n = list.filter(Boolean).length; return n ? `${n} set` : 'auto'; };
        if (sa.join() !== ta.join()) h += `<span>Accents: ${fmtA(sa)}→${fmtA(ta)}</span>`;
        if (s.enabled !== t.enabled) h += `<span>Palette: ${s.enabled ? 'on' : 'off'}→${t.enabled ? 'on' : 'off'}</span>`;
        h += `</div>`;
        return h;
    }

    // What the palette and gradient diff views show of a normalized mode
    function _paletteView(d) {
        return { h: d.h, c: d.c, l: d.l, enabled: d.paletteEnabled, accents: _accentList(d) };
    }

    function _gradientView(d) {
        return { stops: _objArr(d.gradientStops), type: d.gradientType, angle: d.gradientAngle, intensity: d.gradientIntensity, anim: d.gradientAnimation,
                 radialPosX: d.gradientRadialPosX, radialPosY: d.gradientRadialPosY, radialShape: d.gradientRadialShape, radialSize: d.gradientRadialSize,
                 meshPoints: _objArr(d.gradientMeshPoints), meshBgColor: d.gradientMeshBgColor };
    }

    // The fields of a section its own diff view leaves out: the on/off
    // switches, the animation speed and the manual overrides
    const _SECTION_SETTING_LABELS = {
        manualOverridesEnabled: 'Manual overrides', customCssEnabled: 'Custom CSS', autoScope: 'Auto-scope',
        canvasEnabled: 'Canvas FX', gradientEnabled: 'Gradient', gradientAnimationSpeed: 'Animation speed'
    };

    function _renderSectionExtras(section, from, to, mode) {
        if (!from || !to) return '';
        let h = '';
        if (section === 'overrides' && from.manualOverrides !== to.manualOverrides) {
            h += _renderCodeDiffClickable(from.manualOverrides, to.manualOverrides, mode, 'manual');
        }
        const keys = MODE_SECTION_FIELDS[section].filter(k => k in _SECTION_SETTING_LABELS && from[k] !== to[k]);
        if (!keys.length) return h;
        const show = (v) => typeof v === 'boolean' ? (v ? '✓ ON' : '✗ OFF') : _esc(String(v));
        h += `<table class="sync-diff-prop-table">`;
        keys.forEach(k => {
            h += `<tr><td class="prop-key">${_SECTION_SETTING_LABELS[k]}</td><td>${show(from[k])}</td><td style="opacity:0.3">→</td><td>${show(to[k])}</td><td class="prop-diff">⚠</td></tr>`;
        });
        h += `</table>`;
        return h;
    }

    // A mode's three accents as set ('' for each generated one)
    function _accentList(config) {
        return ACCENT_FIELDS.map(({ key }) => _accentHex(config && config[key]));
    }

    function _renderOverridesDiff(entry) {
        const srcKeys = Object.keys(entry.src);
        const tgtKeys = Object.keys(entry.tgt);
        const allKeys = [...new Set([...srcKeys, ...tgtKeys])].sort();
        const diffKeys = allKeys.filter(k => entry.src[k] !== entry.tgt[k]);

        let h = `<table class="sync-diff-prop-table"><tr style="opacity:0.5;font-size:0.45rem;"><td>Variable</td><td>Source</td><td>Target</td></tr>`;
        const maxShow = 5;
        diffKeys.slice(0, maxShow).forEach(k => {
            const sv = entry.src[k] ? _esc(entry.src[k]) : '<span style="opacity:0.3;">—</span>';
            const tv = entry.tgt[k] ? _esc(entry.tgt[k]) : '<span style="opacity:0.3;">—</span>';
            h += `<tr><td class="prop-key">${_esc(k)}</td><td>${sv}</td><td>${tv}</td></tr>`;
        });
        h += `</table>`;
        if (diffKeys.length > maxShow) {
            h += `<div style="font-size:0.45rem; opacity:0.4; margin-left:0;">...+${diffKeys.length - maxShow} more</div>`;
        }
        h += `<div style="font-size:0.45rem; opacity:0.5; margin-left:0; margin-top:2px;">${diffKeys.length} of ${allKeys.length} variables differ</div>`;
        return h;
    }

    let _codeDiffIdCounter = 0;

    function _renderCssDiff(entry) {
        return _renderCodeDiffClickable(entry.src, entry.tgt, entry.mode, 'css');
    }

    function _renderCanvasDiff(entry) {
        let srcLabel = '', tgtLabel = '';
        if (typeof CANVAS_PRESETS !== 'undefined') {
            CANVAS_PRESETS.forEach(p => {
                if (p.script === entry.src) srcLabel = ` "${_esc(p.name)}"`;
                if (p.script === entry.tgt) tgtLabel = ` "${_esc(p.name)}"`;
            });
        }
        return _renderCodeDiffClickable(entry.src, entry.tgt, entry.mode, 'canvas', srcLabel, tgtLabel);
    }

    function _renderCodeDiffClickable(srcCode, tgtCode, mode, type, srcExtra, tgtExtra) {
        const id = `cdiff-${type}-${mode}-${_codeDiffIdCounter++}`;
        const srcLines = srcCode ? srcCode.split('\n') : [];
        const tgtLines = tgtCode ? tgtCode.split('\n') : [];
        const srcCount = srcLines.length;
        const tgtCount = tgtLines.length;
        const srcDesc = srcCode ? `${srcCount} lines${srcExtra || ''}` : '(empty)';
        const tgtDesc = tgtCode ? `${tgtCount} lines${tgtExtra || ''}` : '(empty)';

        let h = '';
        h += `<button type="button" class="plain-button sync-diff-code-summary" onclick="_toggleCodeDiffExpand('${id}')">`;
        h += `<span class="summary-label">${srcDesc} → ${tgtDesc}</span>`;
        h += `<span class="summary-action" id="${id}-action">▸ View Diff</span>`;
        h += `</button>`;

        const srcSet = new Set(srcLines);
        const tgtSet = new Set(tgtLines);

        let srcHtml = '', tgtHtml = '';
        const maxLen = Math.max(srcCount, tgtCount);
        for (let i = 0; i < maxLen; i++) {
            const sl = i < srcCount ? srcLines[i] : null;
            const tl = i < tgtCount ? tgtLines[i] : null;
            if (sl !== null) {
                const cls = tgtSet.has(sl) && sl === (tgtLines[i] || null) ? 'unchanged' : 'removed';
                srcHtml += `<div class="diff-line ${cls}">${_esc(sl) || '&nbsp;'}</div>`;
            } else {
                srcHtml += `<div class="diff-line empty-placeholder">&nbsp;</div>`;
            }
            if (tl !== null) {
                const cls = srcSet.has(tl) && tl === (srcLines[i] || null) ? 'unchanged' : 'added';
                tgtHtml += `<div class="diff-line ${cls}">${_esc(tl) || '&nbsp;'}</div>`;
            } else {
                tgtHtml += `<div class="diff-line empty-placeholder">&nbsp;</div>`;
            }
        }

        h += `<div class="sync-diff-code-expanded" id="${id}" style="display:none;">`;
        h += `<div class="diff-header"><span>Current (${srcCount})</span><span>Incoming (${tgtCount})</span></div>`;
        h += `<div class="diff-body">`;
        h += `<div class="diff-col">${srcHtml || '<div class="diff-line empty-placeholder">(empty)</div>'}</div>`;
        h += `<div class="diff-col">${tgtHtml || '<div class="diff-line empty-placeholder">(empty)</div>'}</div>`;
        h += `</div></div>`;
        return h;
    }

    window._toggleCodeDiffExpand = function(id) {
        const el = document.getElementById(id);
        const action = document.getElementById(id + '-action');
        if (!el) return;
        const isOpen = el.style.display !== 'none';
        el.style.display = isOpen ? 'none' : 'block';
        if (action) action.textContent = isOpen ? '▸ View Diff' : '▾ Hide Diff';
    };

    function _renderGradientDiff(entry) {
        const s = entry.src, t = entry.tgt;
        let h = '';
        // Every field is sanitized: this renders in the update diff too, where
        // the data is a REMOTE theme fetched from an arbitrary updateUrl.
        const makeGradientCSS = (data) => {
            const def = DEFAULT_MODE_DATA;
            if (data.type === 'mesh' && data.meshPoints && data.meshPoints.length >= 2) {
                const layers = data.meshPoints.map(p => `radial-gradient(at ${_cssNum(p.x, 50)}% ${_cssNum(p.y, 50)}%, ${_cssTok(p.color)} 0%, transparent ${_cssNum(p.spread, 50)}%)`).join(', ');
                return `${_cssTok(data.meshBgColor, def.gradientMeshBgColor)}; background-image: ${layers}`;
            }
            if (!Array.isArray(data.stops) || data.stops.length === 0) return 'transparent';
            const stopStr = data.stops.map(st => `${_cssTok(st.color)} ${_cssNum(st.position, 0)}%`).join(', ');
            if (data.type === 'radial') {
                const rShape = _cssTok(data.radialShape, def.gradientRadialShape);
                const rSize = _cssTok(data.radialSize, def.gradientRadialSize);
                const rPosX = _cssNum(data.radialPosX, def.gradientRadialPosX);
                const rPosY = _cssNum(data.radialPosY, def.gradientRadialPosY);
                return `radial-gradient(${rShape} ${rSize} at ${rPosX}% ${rPosY}%, ${stopStr})`;
            }
            if (data.type === 'conic') return `conic-gradient(from ${_cssNum(data.angle, def.gradientAngle)}deg, ${stopStr})`;
            return `linear-gradient(${_cssNum(data.angle, def.gradientAngle)}deg, ${stopStr})`;
        };
        h += `<div class="sync-diff-gradient-row">`;
        h += `<span class="gradient-label">Source</span>`;
        h += `<div class="sync-diff-gradient-bar" style="background:${makeGradientCSS(s)};"></div>`;
        h += `<span class="gradient-arrow">→</span>`;
        h += `<span class="gradient-label">Target</span>`;
        h += `<div class="sync-diff-gradient-bar" style="background:${makeGradientCSS(t)};"></div>`;
        h += `</div>`;
        // The properties that differ. Escaped: on the update-diff path these
        // are a remote theme's values.
        const stops = (list) => (list || []).map(st => `${_cssTok(st.color, '?')} ${_cssNum(st.position, 0)}%`).join(', ') || 'none';
        const points = (list) => (list || []).map(p => `${_cssTok(p.color, '?')} ${_cssNum(p.x, 50)}/${_cssNum(p.y, 50)}`).join(', ') || 'none';
        const props = [
            ['Type', d => d.type, d => d.type],
            ['Angle', d => d.angle, d => d.angle + '°'],
            ['Intensity', d => d.intensity, d => d.intensity + '%'],
            ['Stops', d => d.stops, d => stops(d.stops)],
            ['Animated', d => d.anim, d => d.anim ? 'Yes' : 'No'],
            ['Radial position', d => [d.radialPosX, d.radialPosY], d => `${d.radialPosX}% ${d.radialPosY}%`],
            ['Radial shape', d => d.radialShape, d => d.radialShape],
            ['Radial size', d => d.radialSize, d => d.radialSize],
            ['Mesh points', d => d.meshPoints, d => points(d.meshPoints)],
            ['Mesh background', d => d.meshBgColor, d => d.meshBgColor]
        ].filter(([, value]) => _stableStringify(value(s)) !== _stableStringify(value(t)));
        if (!props.length) return h;
        h += `<table class="sync-diff-prop-table">`;
        h += `<thead><tr><td></td><td>Source</td><td></td><td>Target</td><td></td></tr></thead>`;
        props.forEach(([key, , show]) => {
            h += `<tr><td class="prop-key">${key}</td><td>${_esc(String(show(s)))}</td><td style="opacity:0.3">→</td><td>${_esc(String(show(t)))}</td><td class="prop-diff">⚠</td></tr>`;
        });
        h += `</table>`;
        return h;
    }

    function _renderSurfacesDiff(entry) {
        const show = (k, v) => k === 'surfacesEnabled' ? (v ? '✓ ON' : '✗ OFF') : v + (k.endsWith('Blur') ? 'px' : '%');
        const name = (k) => {
            if (k === 'surfacesEnabled') return 'Surfaces';
            const l = SURFACE_LAYERS.find(x => k === `surface${x.key}Opacity` || k === `surface${x.key}Blur`);
            return `${l.label} ${k.endsWith('Blur') ? 'blur' : (l.key === 'Backdrop' ? 'darkness' : 'opacity')}`;
        };
        let h = `<table class="sync-diff-prop-table">`;
        h += `<thead><tr><td></td><td>Source</td><td></td><td>Target</td><td></td></tr></thead>`;
        SURFACE_FIELDS.forEach((k, i) => {
            const sv = entry.src[i], tv = entry.tgt[i];
            if (sv === tv) return;
            h += `<tr><td class="prop-key">${name(k)}</td><td>${show(k, sv)}</td><td style="opacity:0.3">→</td><td>${show(k, tv)}</td><td class="prop-diff">⚠</td></tr>`;
        });
        h += `</table>`;
        return h;
    }

    function _renderAuthDiff(entry) {
        const labels = ['Theme on Auth', 'CSS on Auth', 'Canvas on Auth', 'Gradient on Auth',
                        'Theme Only on Auth', 'CSS Only on Auth', 'Canvas Only on Auth', 'Gradient Only on Auth'];
        let h = `<table class="sync-diff-prop-table">`;
        h += `<thead><tr><td></td><td>Source</td><td></td><td>Target</td><td></td></tr></thead>`;
        labels.forEach((label, i) => {
            const sv = entry.srcAuth[i];
            const tv = entry.tgtAuth[i];
            const match = sv === tv;
            h += `<tr><td class="prop-key">${label}</td><td>${sv ? '✓ ON' : '✗ OFF'}</td><td style="opacity:0.3">→</td><td>${tv ? '✓ ON' : '✗ OFF'}</td><td class="${match ? 'prop-match' : 'prop-diff'}">${match ? '✓' : '⚠'}</td></tr>`;
        });
        h += `</table>`;
        return h;
    }

    function applySyncToMode(mode, rawSource, opts) {
        // A field the source leaves out is applied as its default, the way
        // the comparisons (modeSectionDiffs) read it
        const sourceData = normalizeModeData(structuredClone(rawSource));
        if (opts.syncPalette) {
            themeData[mode].h = sourceData.h;
            themeData[mode].c = sourceData.c;
            themeData[mode].l = opts.adjustL ? opts.adjustL(mode, sourceData.l) : sourceData.l;
            // Off means the default ramp ships, so the h/c/l above only count
            // with it. Missing on themes saved before the switch: on.
            themeData[mode].paletteEnabled = sourceData.paletteEnabled !== false;
            ACCENT_FIELDS.forEach(({ key }) => { themeData[mode][key] = _accentHex(sourceData[key]); });
        }
        if (opts.syncOverrides) {
            themeData[mode].overrides = structuredClone(sourceData.overrides || {});
            if (opts.rebuildLocks) {
                themeData[mode].locks = {};
                Object.keys(themeData[mode].overrides).forEach(k => themeData[mode].locks[k] = true);
            } else {
                themeData[mode].locks = structuredClone(sourceData.locks || {});
            }
            themeData[mode].manualOverrides = sourceData.manualOverrides || '';
            // A snapshot saved before the switch was kept has none: text means on.
            themeData[mode].manualOverridesEnabled = sourceData.manualOverridesEnabled !== undefined
                ? !!sourceData.manualOverridesEnabled
                : !!(sourceData.manualOverrides && sourceData.manualOverrides.trim());
        }
        if (opts.syncCss) {
            themeData[mode].customCSS = sourceData.customCSS || '';
            themeData[mode].customCssEnabled = !!sourceData.customCssEnabled;
            themeData[mode].autoScope = sourceData.autoScope !== false;
            activeCssRef[mode] = opts.cssRef !== undefined ? opts.cssRef : null;
            if (themeData[mode].customCssEnabled && themeData[mode].customCSS) {
                CSS_PRESETS.forEach((cs, ci) => {
                    if (cs.code === themeData[mode].customCSS) activeCssRef[mode] = ci;
                });
            }
        }
        if (opts.syncCanvas) {
            themeData[mode].canvasEnabled = !!sourceData.canvasEnabled;
            themeData[mode].canvasScript = sourceData.canvasScript || '';
            activeCanvasRef[mode] = opts.canvasRef !== undefined ? opts.canvasRef : null;
            if (themeData[mode].canvasEnabled && themeData[mode].canvasScript) {
                CANVAS_PRESETS.forEach((cp, ci) => {
                    if (cp.script === themeData[mode].canvasScript) activeCanvasRef[mode] = ci;
                });
            }
        }
        if (opts.syncGradient) {
            copyGradientProps(themeData[mode], sourceData);
            activeGradientRef[mode] = opts.gradientRef !== undefined ? opts.gradientRef : null;
        }
        if (opts.syncSurfaces) {
            SURFACE_FIELDS.forEach(k => {
                themeData[mode][k] = k === 'surfacesEnabled' ? !!sourceData[k] : (sourceData[k] ?? DEFAULT_MODE_DATA[k]);
            });
        }
        if (opts.syncAuth) copyAuthProps(themeData[mode], sourceData);
    }

    function showSyncModal(sourceType, sourceId) {
        flushPendingEdits();
        syncSourceType = sourceType;
        syncSourceId = sourceId;

        const dm = getActiveDataMode();

        let titleText = "Selective Sync";
        let descText = "";
        let confirmText = "Sync Selected";
        let cancelText = "Do Not Sync";

        if (sourceType === 'active-mode') {
            const sourceName = activeMode === 'system' ? `System (${MODE_LABELS[dm]})` : MODE_LABELS[dm];
            descText = `Choose what to copy from <b>${sourceName}</b>.`;
        } else if (sourceType === 'snapshot') {
            const name = getSnapshots()[sourceId]?.name || `Theme ${sourceId}`;
            titleText = "Apply Library Theme";
            descText = `Choose where and what to apply from <b>${_esc(name)}</b>.`;
            confirmText = "Apply Theme";
            cancelText = "Do Not Apply";
        }

        $('sync-modal-title').innerText = titleText;
        $('sync-source-description').innerHTML = descText;
        $('confirm-sync-btn').innerText = confirmText;
        $('sync-cancel-btn').innerText = cancelText;

        const container = $('sync-target-container');
        container.innerHTML = '';
        MODES.forEach(m => {
            const isSource = (sourceType === 'active-mode' && m === dm);
            const isChecked = !isSource;

            const pill = document.createElement('div');
            pill.className = `sync-mode-pill ${isSource ? 'disabled' : ''} ${isChecked ? 'active' : ''}`;
            pill.setAttribute('role', 'checkbox');
            pill.setAttribute('aria-checked', String(isChecked));
            pill.setAttribute('aria-label', MODE_LABELS[m]);
            if (!isSource) pill.setAttribute('tabindex', '0');
            pill.innerHTML = `
                <input type="checkbox" id="sync-target-${m}" ${isSource ? 'disabled' : ''} ${isChecked ? 'checked' : ''} style="display:none">
                <span>${MODE_LABELS[m]}</span>
                <div class="selected-check">✓</div>
            `;
            if (!isSource) {
                const toggle = () => {
                    const cb = pill.querySelector('input');
                    cb.checked = !cb.checked;
                    pill.classList.toggle('active', cb.checked);
                    pill.setAttribute('aria-checked', String(cb.checked));
                    updateTargetsHeaderToggleState();
                    updateSyncDeltaBadges();
                };
                pill.onclick = toggle;
                pill.addEventListener('keydown', (e) => {
                    if (e.key === ' ' || e.key === 'Enter') { e.preventDefault(); toggle(); }
                });
            }
            container.appendChild(pill);
        });

        SYNC_SECTIONS.forEach(opt => {
            const cb = $(`sync-opt-${opt}`);
            if (cb) cb.checked = true;
        });

        const toggleTargets = $('sync-toggle-targets');
        if (toggleTargets) toggleTargets.innerText = 'Deselect All';
        const toggleOptions = $('sync-toggle-options');
        if (toggleOptions) toggleOptions.innerText = 'Deselect All';

        collapseAllSyncDiffs();
        updateSyncDeltaBadges();
        const cfg = window.__THEME_PRO_CONFIG__;
        if (cfg && cfg.autoSync) {
            const everySection = {
                syncPalette: true, syncOverrides: true, syncCss: true,
                syncCanvas: true, syncGradient: true, syncSurfaces: true, syncAuth: true,
            };
            if (sourceType === 'active-mode') {
                // The Sync button copies to every other mode
                const srcData = themeData[dm];
                MODES.filter(m => m !== dm).forEach(mode => {
                    applySyncToMode(mode, srcData, {
                        ...everySection,
                        adjustL: (m, l) => m === 'oled' ? 0 : l,
                        cssRef: activeCssRef[dm],
                        canvasRef: activeCanvasRef[dm],
                        gradientRef: activeGradientRef[dm],
                    });
                    activeThemeRef[mode] = activeThemeRef[dm] ? { ...activeThemeRef[dm] } : null;
                });
                showToast('Theme synced to all modes!');
            } else if (sourceType === 'snapshot') {
                const s = getSnapshots()[sourceId];
                if (!s) return;
                const syncAllToggle = $('sync-all-modes-toggle');
                const syncAll = syncAllToggle && syncAllToggle.checked;
                (syncAll ? MODES : [dm]).forEach(mode => {
                    applySyncToMode(mode, snapshotModeData(s, mode), { ...everySection, rebuildLocks: true });
                    activeThemeRef[mode] = { type: 'snapshot', id: sourceId };
                });
                showToast(syncAll ? `Theme "${s.name}" applied to all modes!` : `Theme "${s.name}" applied!`);
            }

            commitChange({ clearRef: false });
            return;
        }

        showModal('sync-modal');
    }

    $('sync-mode-btn').addEventListener('click', () => {
        showSyncModal('active-mode', null);
    });

    $('confirm-sync-btn').onclick = () => {
        flushPendingEdits();
        const syncPalette = $('sync-opt-palette').checked;
        const syncOverrides = $('sync-opt-overrides').checked;
        const syncCss = $('sync-opt-css').checked;
        const syncCanvas = $('sync-opt-canvas').checked;
        const syncGradient = $('sync-opt-gradient')?.checked;
        const syncSurfaces = $('sync-opt-surfaces')?.checked;
        const syncAuth = $('sync-opt-auth').checked;

        const targetModes = MODES.filter(m => {
            const cb = $(`sync-target-${m}`);
            return cb && cb.checked && !cb.disabled;
        });

        if (targetModes.length === 0) {
            showToast("No target modes selected!");
            return;
        }

        if (!syncPalette && !syncOverrides && !syncCss && !syncCanvas && !syncGradient && !syncSurfaces && !syncAuth) {
            showToast("Nothing selected to sync/apply!");
            return;
        }

        hideModal('sync-modal');
        collapseAllSyncDiffs();

        if (syncSourceType === 'active-mode') {
            const dm = getActiveDataMode();
            targetModes.forEach(mode => {
                const linked = linkedSnapshotMode(dm, mode);
                const usePerModeSource = !!linked;
                applySyncToMode(mode, linked || themeData[dm], {
                    syncPalette, syncOverrides, syncCss, syncCanvas, syncGradient, syncSurfaces, syncAuth,
                    rebuildLocks: usePerModeSource,
                    adjustL: (m, l) => m === 'oled' ? 0 : l,
                    cssRef: usePerModeSource ? undefined : activeCssRef[dm],
                    canvasRef: usePerModeSource ? undefined : activeCanvasRef[dm],
                    gradientRef: usePerModeSource ? undefined : activeGradientRef[dm],
                });
                if (syncPalette && syncOverrides && syncCss && syncCanvas) {
                    activeThemeRef[mode] = activeThemeRef[dm] ? { ...activeThemeRef[dm] } : null;
                }
            });
            showToast("Theme synced successfully!");

        } else if (syncSourceType === 'snapshot') {
            const s = getSnapshots()[syncSourceId];
            if (!s) return;

            targetModes.forEach(mode => {
                applySyncToMode(mode, snapshotModeData(s, mode), {
                    syncPalette, syncOverrides, syncCss, syncCanvas, syncGradient, syncSurfaces, syncAuth,
                    rebuildLocks: true,
                });
                if (syncPalette) activeThemeRef[mode] = { type: 'snapshot', id: syncSourceId };
            });
            showToast(`Theme "${s.name}" applied!`);
        }

        commitChange({ clearRef: false });
    };

    $('undo-btn').onclick = () => undo();
    $('redo-btn').onclick = () => redo();

    window.addEventListener('keydown', (e) => {
        // Modal configs: [modalId, confirmButtonId, allowBackspaceCancel]
        const modalConfigs = [
            ['delete-modal', 'confirm-delete-btn', true],
            ['overwrite-modal', 'confirm-overwrite-btn', true],
            ['save-modal', 'confirm-save-btn', false],
            ['rename-modal', 'confirm-rename-btn', false],
            ['nuclear-modal', 'confirm-nuclear-btn', true],
            ['factory-reset-modal', 'confirm-factory-reset-btn', true],
            ['save-canvas-modal', 'confirm-save-canvas-btn', false],
            ['delete-canvas-modal', 'confirm-delete-canvas-btn', true],
            ['rename-canvas-modal', 'confirm-rename-canvas-btn', false],
            ['save-css-modal', 'confirm-save-css-btn', false],
            ['delete-css-modal', 'confirm-delete-css-btn', true],
            ['rename-css-modal', 'confirm-rename-css-btn', false],
            ['delete-all-themes-modal', 'confirm-delete-all-themes-btn', true],
            ['delete-all-canvas-modal', 'confirm-delete-all-canvas-btn', true],
            ['delete-all-css-modal', 'confirm-delete-all-css-btn', true],
            ['reset-all-confirm-modal', 'confirm-reset-all-confirm-btn', true],
            ['sync-modal', 'confirm-sync-btn', true],
            ['reset-modal', 'confirm-reset-btn', true],
            ['import-clipboard-modal', 'confirm-clipboard-import-btn', true],
            ['json-view-modal', null, true],
            ['css-view-modal', null, true],
            ['update-modal', 'update-confirm-btn', true],
            ['update-results-modal', null, true],
            ['export-all-backups-modal', 'confirm-export-all-backups-btn', true],
            ['save-gradient-modal', 'confirm-save-gradient-btn', false],
            ['delete-gradient-modal', 'confirm-delete-gradient-btn', true],
            ['rename-gradient-modal', 'confirm-rename-gradient-btn', false],
            ['delete-all-gradient-modal', 'confirm-delete-all-gradient-btn', true],
            ['import-gradient-modal', null, true],
            ['import-theme-modal', null, true],
            ['import-css-modal', null, true],
            ['import-canvas-modal', null, true],
            ['ask-modal', 'ask-modal-confirm-btn', true],
            ['install-all-confirm-modal', 'confirm-install-all-btn', true],
            ['save-json-edit-modal', null, false],
            ['snapshot-json-edit-modal', null, false],
            ['tab-docs', null, false]
        ];

        const activeEl = document.activeElement;
        const isEditingInModal = activeEl && (activeEl.tagName === 'TEXTAREA' || activeEl.tagName === 'INPUT' ||
            // A focused button (Cancel) answers Enter itself; confirming here
            // ran the destructive action instead
            activeEl.tagName === 'BUTTON');

        // Only the dialog in front answers: the question askConfirm puts sits
        // over the dialog that asked it
        const dialog = topDialog();
        const config = dialog && modalConfigs.find(([modalId]) => modalId === dialog.id);
        // A held key repeats into the dialog it just opened, which has focus by
        // then: a held Enter on Delete would confirm the delete
        if (config && !e.repeat) {
            const [modalId, confirmBtnId, allowBackspace] = config;
            // A control in the dialog that answered Enter itself, such as a
            // Sync dialog mode pill, has already called preventDefault
            if (e.key === 'Enter' && confirmBtnId && !isEditingInModal && !e.defaultPrevented) {
                e.preventDefault();
                const btn = $(confirmBtnId);
                if (btn) btn.click();
                return;
            }
            if (e.key === 'Escape') {
                e.preventDefault();
                dismissDialog(dialog);
                return;
            }
            if (e.key === 'Backspace' && allowBackspace && !isEditingInModal) {
                e.preventDefault();
                hideModal(modalId);
                return;
            }
        }

        // Undo/Redo Shortcuts — skip when user is typing in a text field
        const isEditing = activeEl && (activeEl.tagName === 'TEXTAREA' || activeEl.tagName === 'INPUT');
        if ((e.ctrlKey || e.metaKey) && !isEditing) {
            // Shift and Caps Lock make the key 'Z' and 'Y'
            const key = (e.key || '').toLowerCase();
            if (key === 'z' && !e.shiftKey) {
                e.preventDefault();
                undo();
            } else if (key === 'z' && e.shiftKey) {
                e.preventDefault();
                redo();
            } else if (key === 'y') {
                e.preventDefault();
                redo();
            }
        }
    });

    const docsModalBtn = document.getElementById('docs-modal-btn');
    const docsModalClose = document.getElementById('docs-modal-close');
    const docsPanel = document.getElementById('tab-docs');
    if (docsModalBtn && docsPanel) {
        docsModalBtn.addEventListener('click', () => showModal('tab-docs', 'block'));
        if (docsModalClose) docsModalClose.addEventListener('click', () => hideModal('tab-docs'));
    }

    document.querySelectorAll('.tab').forEach(tab => {
        tab.addEventListener('click', () => {
            document.querySelectorAll('.tab').forEach(t => { t.classList.remove('active'); t.setAttribute('aria-selected', 'false'); t.setAttribute('tabindex', '-1'); });
            tab.classList.add('active');
            tab.setAttribute('aria-selected', 'true');
            tab.setAttribute('tabindex', '0');
            document.querySelectorAll('.tab-content').forEach(c => c.style.display = 'none');
            document.getElementById('tab-' + tab.dataset.tab).style.display = 'block';
            sessionStorage.setItem('owui_theme_tool_tab', tab.dataset.tab);
            
        });
    });

    const tabsBar = document.querySelector('.tabs');
    if (tabsBar) {
        tabsBar.addEventListener('wheel', (e) => {
            if (e.deltaY !== 0) {
                e.preventDefault();
                tabsBar.scrollLeft += e.deltaY;
            }
        }, { passive: false });
        // Arrow keys, Home and End move between the tabs and open the one
        // they land on; tabs hidden by a valve are skipped
        tabsBar.addEventListener('keydown', (e) => {
            const tabs = [...tabsBar.querySelectorAll('.tab')].filter(t => t.style.display !== 'none');
            const at = tabs.indexOf(document.activeElement);
            const to = { ArrowRight: at + 1, ArrowLeft: at - 1, Home: 0, End: tabs.length - 1 }[e.key];
            if (at < 0 || to === undefined) return;
            e.preventDefault();
            const tab = tabs[(to + tabs.length) % tabs.length];
            tab.focus();
            tab.click();
        });
    }

    document.querySelectorAll('.copy-css-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            const targetId = btn.getAttribute('data-target');
            const txt = document.getElementById(targetId).value;
            navigator.clipboard.writeText(txt).then(() => {
                const originalText = btn.innerText;
                btn.innerText = 'Copied';
                btn.style.color = 'var(--accent)';
                setTimeout(() => {
                    btn.innerText = originalText;
                    btn.style.color = '';
                }, 2000);
            });
        });
    });

    const downloadCssBtn = document.getElementById('download-css-btn');

    function getDownloadName() {
        const dm = getActiveDataMode();
        let activeName = "custom-theme";
        if (activeThemeRef[dm] && activeThemeRef[dm].type === 'snapshot') {
            const snapshots = getSnapshots();
            if (snapshots[activeThemeRef[dm].id] && snapshots[activeThemeRef[dm].id].name) {
                activeName = String(snapshots[activeThemeRef[dm].id].name).replace(/[^a-z0-9]/gi, '_').toLowerCase();
            }

        }
        return activeName;
    }

    if (downloadCssBtn) {
        downloadCssBtn.addEventListener('click', () => {
            const content = document.getElementById('raw-css').value;
            const blob = new Blob([content], { type: 'text/css' });
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = `owui-${getDownloadName()}.css`;
            a.click();
            URL.revokeObjectURL(url);
            showToast("CSS downloaded!");
        });
    }

    let renameIndex = null;
    window.requestRename = (index) => {
        const snapshots = getSnapshots();
        const snap = snapshots[index];
        if (!snap) return;
        renameIndex = index;
        const input = document.getElementById('rename-input');
        input.value = snap.name;
        const f = (id, val) => { const el = document.getElementById(id); if (el) el.value = val || ''; };
        f('rename-desc-input', snap.description);
        f('rename-author-input', snap.author);
        f('rename-version-input', snap.version);
        f('rename-target-input', snap.targetVersion);
        f('rename-repo-input', snap.repositoryUrl);
        f('rename-update-input', snap.updateUrl);
        showModal('rename-modal');
        setTimeout(() => input.focus(), 100);
    };

    document.getElementById('confirm-rename-btn').addEventListener('click', () => {
        const newName = document.getElementById('rename-input').value.trim();
        if (newName && renameIndex !== null) {
            const snapshots = getSnapshots();
            snapshots[renameIndex].name = newName;
            const g = (id) => (document.getElementById(id)?.value || '').trim();
            snapshots[renameIndex].description = g('rename-desc-input');
            snapshots[renameIndex].author = g('rename-author-input');
            snapshots[renameIndex].version = g('rename-version-input') || '1.0.0';
            snapshots[renameIndex].targetVersion = g('rename-target-input');
            snapshots[renameIndex].repositoryUrl = g('rename-repo-input');
            snapshots[renameIndex].updateUrl = g('rename-update-input');
            saveSnapshots(snapshots);
            renderSnapshots();
            showToast('Theme Updated!');
        }
        hideModal('rename-modal');
    });
    // Cancel and Escape close it too, through hideModal
    document.getElementById('rename-modal').addEventListener('close', () => { renameIndex = null; });

    document.getElementById('save-snapshot-btn').addEventListener('click', () => saveSnapshot());

    document.getElementById('random-btn').addEventListener('click', () => {
        const dm = getActiveDataMode();
        const rh = Math.floor(Math.random() * 360);
        const rc = 5 + Math.random() * 55;
        const rl = dm === 'oled' ? 0 : 10 + Math.random() * 30;
        applyBaseColorsToMode(activeMode, rh, rc, rl);
        commitChange();
    });

    function processImageForPalette(file) {
        if (!file) return;
        const img = new Image();
        img.onload = () => {
            const canvas = document.createElement('canvas');
            const ctx = canvas.getContext('2d');
            // Scale down large images for performance
            const maxDim = 150;
            const scale = Math.min(1, maxDim / Math.max(img.width, img.height));
            canvas.width = Math.round(img.width * scale) || 1;
            canvas.height = Math.round(img.height * scale) || 1;
            ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
            const data = ctx.getImageData(0, 0, canvas.width, canvas.height).data;

            // Dominant color extraction via hue histogram with saturation weighting
            const bucketCount = 36; // 10° per bucket
            const buckets = Array.from({length: bucketCount}, () => ({ weight: 0, sinSum: 0, cosSum: 0, satSum: 0, count: 0 }));

            for (let i = 0; i < data.length; i += 4) {
                const r = data[i], g = data[i+1], b = data[i+2];
                const cMax = Math.max(r, g, b), cMin = Math.min(r, g, b);
                const delta = cMax - cMin;
                const lightness = (cMax + cMin) / 510;
                // Skip near-black, near-white, and desaturated pixels
                if (lightness < 0.08 || lightness > 0.92 || delta < 25) continue;

                const sat = delta / 255;
                let h = 0;
                if (delta !== 0) {
                    if (cMax === r) h = ((g - b) / delta) % 6;
                    else if (cMax === g) h = (b - r) / delta + 2;
                    else h = (r - g) / delta + 4;
                }
                h = h * 60; if (h < 0) h += 360;

                const rad = h * Math.PI / 180;
                const idx = Math.min(Math.floor(h / 10), bucketCount - 1);
                buckets[idx].weight += sat;
                buckets[idx].sinSum += Math.sin(rad) * sat;
                buckets[idx].cosSum += Math.cos(rad) * sat;
                buckets[idx].satSum += sat;
                buckets[idx].count++;
            }

            let bestIdx = 0, bestWeight = 0;
            for (let i = 0; i < bucketCount; i++) {
                if (buckets[i].weight > bestWeight) { bestWeight = buckets[i].weight; bestIdx = i; }
            }

            const best = buckets[bestIdx];
            if (best.count === 0) {
                showToast('No dominant color found \u2014 image may be too desaturated.');
                return;
            }

            // Circular mean for accurate hue averaging across the bucket
            let h = Math.round(Math.atan2(best.sinSum, best.cosSum) * 180 / Math.PI);
            if (h < 0) h += 360;
            const chromaNorm = Math.min(100, Math.round((best.satSum / best.count) * 80));
            applyBaseColorsToMode(activeMode, h, chromaNorm, defaultLightness(getActiveDataMode()));
            commitChange();
            showToast(`Palette Extracted! (Hue ${h}°)`);
        };
        img.src = URL.createObjectURL(file);
        img.addEventListener('load', () => URL.revokeObjectURL(img.src), { once: true });
    }

    document.getElementById('extract-btn').addEventListener('click', () => document.getElementById('image-input').click());

    document.getElementById('image-input').addEventListener('change', (e) => {
        processImageForPalette(e.target.files[0]);
    });
    
    // Smart Paste Listener (Images OR JSON)
    let pendingClipboardData = null;
    // Ask before importing theme JSON from the clipboard or from an install
    // link: duplicates are skipped, and a Canvas FX script gets its warning.
    function offerJsonImport(text, parsed) {
        const existingSnaps = getSnapshots();
        let allDuplicates = false;
        // Built as the import builds them, under the name it gives the
        // clipboard-import.json file below
        if (parsed.isLibraryBackup && Array.isArray(parsed.themes)) {
            const themes = parsed.themes.map(t => themeFromEntry(structuredClone(t))).filter(Boolean);
            allDuplicates = themes.length > 0 && themes.every(t => isThemeDuplicate(t, existingSnaps));
        } else if (!parsed.canvas_presets && !parsed.css_presets) {
            const theme = themeFromFile(structuredClone(parsed), 'clipboard-import');
            allDuplicates = !!theme && isThemeDuplicate(theme, existingSnaps);
        }
        if (allDuplicates) {
            showToast('Theme already exists in your library.');
            return;
        }

        pendingClipboardData = text;

        // Detect Canvas FX for Security Warning
        let hasCanvas = false;
        // Both shapes are checked: a theme with a 'themes' list that isn't a
        // library backup imports its top-level modes, and checking only the
        // list let such a script skip this warning
        const modesHaveCanvas = (t) => !!t && ['dark', 'light', 'oled', 'her'].some(m => t[m]?.canvasScript && t[m]?.canvasEnabled);
        if ((Array.isArray(parsed.themes) && parsed.themes.some(modesHaveCanvas)) || modesHaveCanvas(parsed)) {
            hasCanvas = true;
        } else if (parsed.themes || parsed.dark || parsed.light || parsed.oled || parsed.her) {
            hasCanvas = false;
        } else if (parsed.canvas_presets) {
            hasCanvas = true;
        } else if (_isLegacyTheme(parsed)) {
             hasCanvas = parsed.canvasEnabled && parsed.canvasScript;
        }

        document.getElementById('canvas-warning').style.display = hasCanvas ? 'block' : 'none';
        showModal('import-clipboard-modal');
    }

    window.addEventListener('paste', async (e) => {
        const pasteTarget = document.activeElement;
        if (pasteTarget && (pasteTarget.tagName === 'INPUT' || pasteTarget.tagName === 'TEXTAREA')) return;

        const items = e.clipboardData.items;
        let handled = false;
        
        for (let index in items) {
            const item = items[index];
            if (item.kind === 'file' && item.type.indexOf('image/') !== -1) {
                processImageForPalette(item.getAsFile());
                handled = true;
                break;
            }
        }
        
        if (!handled) {
            const text = e.clipboardData.getData('text');
            if (text) {
                try {
                    const parsed = JSON.parse(text);
                    if (parsed && (_isLegacyTheme(parsed) || parsed.dark || parsed.themes || parsed.canvas_presets || parsed.css_presets || parsed.gradient_presets)) {
                        offerJsonImport(text, parsed);
                    }
                } catch(err) { console.warn('Theme Pro:', err); }
            }
        }
    });
    $('confirm-clipboard-import-btn').onclick = async () => {
        if (pendingClipboardData) {
            const file = new File([pendingClipboardData], "clipboard-import.json", { type: "application/json" });
            await handleFilesImport([file], { canvasConfirmed: true });
            pendingClipboardData = null;
        }
        hideModal('import-clipboard-modal');
    };

    $('clipboard-import-noapply-btn').onclick = async () => {
        if (pendingClipboardData) {
            const file = new File([pendingClipboardData], "clipboard-import.json", { type: "application/json" });
            await handleFilesImport([file], { applyAfter: false });
            pendingClipboardData = null;
        }
        hideModal('import-clipboard-modal');
    };

    // An install link from the Theme Designer Pro website: #tdp-import=<kind>:<value>.
    // A preset opens its Import dialog with its address filled in, and a theme
    // made in the Studio is offered the way a pasted one is. Nothing imports
    // until the user confirms, and the URL import valves apply as they do to
    // an address typed in by hand. A chat model can write the link, so what it
    // brings, in it or behind the address it filled in (linkedImport), gets
    // linkedImportProblem's check; an address the user types is not checked.
    let linkedImport = null;
    const INSTALL_DIALOGS = {
        theme: ['import-theme-modal', 'import-url-input', 'import-url-status', 'import-url-load-btn', null],
        bundle: ['import-theme-modal', 'import-url-input', 'import-url-status', 'import-url-load-btn', null],
        canvas: ['import-canvas-modal', 'import-canvas-url-input', 'import-canvas-url-status', 'import-canvas-url-load-btn', 'enableCanvasFx'],
        css: ['import-css-modal', 'import-css-url-input', 'import-css-url-status', 'import-css-url-load-btn', 'enableCustomCss'],
        gradient: ['import-gradient-modal', 'import-gradient-url-input', 'import-gradient-url-status', 'import-gradient-url-load-btn', 'enableGradientBuilder'],
    };
    function installFromLink() {
        const m = /^#tdp-import=(theme|bundle|canvas|css|gradient|json):(.+)$/.exec(location.hash);
        if (!m) return;
        // A reload must not offer it again
        history.replaceState(null, '', location.pathname + location.search);
        const kind = m[1];
        let value = null;
        try { value = decodeURIComponent(m[2]); } catch (e) {}
        if (kind === 'json') {
            try {
                if (value === null) throw new Error('unreadable');
                const b64 = value.replace(/-/g, '+').replace(/_/g, '/');
                const text = new TextDecoder().decode(Uint8Array.from(atob(b64), (ch) => ch.charCodeAt(0)));
                const parsed = JSON.parse(text);
                if (!themeFromFile(structuredClone(parsed), '')) throw new Error('not a theme');
                const problem = linkedImportProblem(text);
                if (problem) showToast(problem);
                else offerJsonImport(text, parsed);
            } catch (e) {
                showToast('That install link has no theme in it that Theme Designer Pro can read.');
            }
            return;
        }
        if (value === null) return;
        let url;
        try { url = new URL(value); } catch (e) { return; }
        if (url.protocol !== 'https:') return;
        const [modalId, inputId, statusId, loadId, valve] = INSTALL_DIALOGS[kind];
        const cfg = window.__THEME_PRO_CONFIG__ || {};
        if (valve && cfg[valve] === false) {
            showToast('This preset type is turned off on this instance, so it can\'t be installed here.');
            return;
        }
        if (!$(modalId) || !$(inputId)) return;
        $(inputId).value = url.href;
        if (kind !== 'canvas' && kind !== 'gradient') linkedImport = { inputId, href: url.href, isCss: kind === 'css' };
        showModal(modalId);
        const statusEl = $(statusId);
        if (cfg.enableUrlImport === false) {
            if (statusEl) showStatus(statusEl, 'Imports from an address are turned off on this instance. Download the preset and drop the file here instead.', 'error');
            return;
        }
        if (statusEl) showStatus(statusEl, 'From an install link. Choose Load URL to import it.', 'loading');
        if ($(loadId)) $(loadId).focus();
    }
    // After the rest of the page has wired its dialogs
    setTimeout(installFromLink, 0);

