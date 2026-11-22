    // === GRADIENT BUILDER LOGIC ===

    window._gradientSliderActive = false;

    function dimGradientToggles(on) {
        ['toggle-gradient-animation', 'toggle-gradient-auth'].forEach(id => dimLabel(id, on));
    }

    const GRADIENT_PRESETS = {
        midnight: { name: 'Midnight', stops: [{color:'#0f0c29',position:0},{color:'#302b63',position:50},{color:'#24243e',position:100}], type:'linear', angle:135 },
        emerald: { name: 'Emerald', stops: [{color:'#0d2818',position:0},{color:'#04471c',position:40},{color:'#058c42',position:100}], type:'linear', angle:135 },
        amethyst: { name: 'Amethyst', stops: [{color:'#1a0a2e',position:0},{color:'#3d1e6d',position:50},{color:'#6b3fa0',position:100}], type:'linear', angle:135 },
        sapphire: { name: 'Sapphire', stops: [{color:'#041e42',position:0},{color:'#0c2d5a',position:50},{color:'#1e40af',position:100}], type:'linear', angle:135 },
        aurora: { name: 'Aurora', stops: [{color:'#0f0c29',position:0},{color:'#1b5e20',position:33},{color:'#1a237e',position:66},{color:'#6a1b9a',position:100}], type:'linear', angle:135, animation:true },
        sunset: { name: 'Sunset', stops: [{color:'#1a0a2e',position:0},{color:'#b91c1c',position:33},{color:'#d97706',position:66},{color:'#f59e0b',position:100}], type:'linear', angle:180 },
        ocean: { name: 'Ocean', stops: [{color:'#001219',position:0},{color:'#005f73',position:50},{color:'#0a9396',position:100}], type:'linear', angle:180 },
        neon: { name: 'Neon', stops: [{color:'#0d0221',position:0},{color:'#0d0b52',position:25},{color:'#6a11cb',position:50},{color:'#f953c6',position:100}], type:'linear', angle:135 },
        meshNebula: { name: 'Nebula', type: 'mesh', meshBgColor: '#08081a', meshPoints: [{color:'#6366f1',x:20,y:18,spread:55},{color:'#ec4899',x:72,y:12,spread:48},{color:'#06b6d4',x:50,y:78,spread:52},{color:'#8b5cf6',x:82,y:62,spread:42}] },
        meshLagoon: { name: 'Lagoon', type: 'mesh', meshBgColor: '#040f0f', meshPoints: [{color:'#0d9488',x:18,y:28,spread:55},{color:'#22d3ee',x:78,y:18,spread:48},{color:'#059669',x:45,y:72,spread:52},{color:'#0284c7',x:85,y:72,spread:42}] },
        meshEmber: { name: 'Ember', type: 'mesh', meshBgColor: '#0f0500', meshPoints: [{color:'#dc2626',x:28,y:22,spread:52},{color:'#ea580c',x:72,y:18,spread:48},{color:'#d97706',x:48,y:72,spread:55},{color:'#991b1b',x:14,y:78,spread:42}] },
        meshArctic: { name: 'Arctic', type: 'mesh', meshBgColor: '#050a14', meshPoints: [{color:'#38bdf8',x:28,y:18,spread:52},{color:'#22d3ee',x:72,y:22,spread:48},{color:'#818cf8',x:45,y:78,spread:55},{color:'#2563eb',x:85,y:62,spread:42}] }
    };

    function renderGradientTab() {
        const dm = getActiveDataMode();
        const config = themeData[dm];
        const def = DEFAULT_MODE_DATA;

        const syncCheck = (id, val) => { const el = $(id); if (el) el.checked = val; };
        syncCheck('toggle-gradient-bg', config.gradientEnabled === true);
        syncCheck('toggle-gradient-auth', config.gradientShowAuth !== false);
        syncCheck('toggle-gradient-animation', config.gradientAnimation === true);
        dimGradientToggles(config.gradientEnabled);

        const conflictWarning = $('gradient-conflict-warning');
        if (conflictWarning) {
            const hasConflict = config.gradientEnabled && customCssHidesGradient(config);
            conflictWarning.style.display = hasConflict ? 'block' : 'none';
        }

        document.querySelectorAll('.gradient-type-pill').forEach(pill => {
            pill.classList.toggle('active', pill.dataset.gtype === (config.gradientType || def.gradientType));
        });

        const angle = config.gradientAngle != null ? config.gradientAngle : def.gradientAngle;
        const intensity = config.gradientIntensity != null ? config.gradientIntensity : def.gradientIntensity;
        const speed = config.gradientAnimationSpeed || def.gradientAnimationSpeed;
        if ($('sl-gradient-angle')) $('sl-gradient-angle').value = angle;
        if ($('val-gradient-angle')) $('val-gradient-angle').innerText = angle + '°';
        if ($('sl-gradient-intensity')) $('sl-gradient-intensity').value = intensity;
        if ($('val-gradient-intensity')) $('val-gradient-intensity').innerText = intensity + '%';
        if ($('sl-gradient-speed')) $('sl-gradient-speed').value = speed;
        if ($('val-gradient-speed')) $('val-gradient-speed').innerText = speed + 's';

        const angleRow = $('gradient-angle-row');
        const isMesh = config.gradientType === 'mesh';
        const isLinear = config.gradientType !== 'radial' && !isMesh;
        if (angleRow) angleRow.style.display = isLinear ? 'flex' : 'none';
        const controlsGrid = $('gradient-controls-grid');
        if (controlsGrid) controlsGrid.style.gridTemplateColumns = isLinear ? '1fr 1fr' : '1fr';

        const stopsSection = $('gradient-stops-section');
        if (stopsSection) stopsSection.style.display = isMesh ? 'none' : '';
        const previewSection = $('gradient-preview-section');
        if (previewSection) previewSection.style.display = isMesh ? 'none' : '';

        const radialControls = $('gradient-radial-controls');
        if (radialControls) {
            radialControls.style.display = (config.gradientType === 'radial') ? 'block' : 'none';
            if (config.gradientType === 'radial') {
                const posX = config.gradientRadialPosX ?? def.gradientRadialPosX;
                const posY = config.gradientRadialPosY ?? def.gradientRadialPosY;
                const dot = $('radial-xy-dot');
                if (dot) { dot.style.left = posX + '%'; dot.style.top = posY + '%'; }
                const xyLabel = $('radial-xy-label');
                if (xyLabel) xyLabel.innerText = posX + '%, ' + posY + '%';
                const rShape = config.gradientRadialShape || def.gradientRadialShape;
                document.querySelectorAll('.radial-shape-pill').forEach(p => p.classList.toggle('active', p.dataset.shape === rShape));
                const rSize = config.gradientRadialSize || def.gradientRadialSize;
                document.querySelectorAll('.radial-size-pill').forEach(p => p.classList.toggle('active', p.dataset.size === rSize));
                const xyPad = $('radial-xy-pad');
                if (xyPad && config.gradientStops && config.gradientStops.length >= 2) {
                    const rdIntensity = config.gradientIntensity != null ? config.gradientIntensity : def.gradientIntensity;
                    const sorted = [...config.gradientStops].sort((a, b) => a.position - b.position);
                    const xyStopsStr = sorted.map(s => `${adjustHexIntensity(s.color, rdIntensity)} ${s.position}%`).join(', ');
                    xyPad.style.backgroundImage = `radial-gradient(${rShape} ${rSize} at ${posX}% ${posY}%, ${xyStopsStr})`;
                } else if (xyPad) {
                    xyPad.style.backgroundImage = '';
                }
            }
        }

        const meshControls = $('gradient-mesh-controls');
        if (meshControls) {
            meshControls.style.display = isMesh ? 'block' : 'none';
            if (isMesh) {
                const meshPad = $('mesh-editor-pad');
                const points = config.gradientMeshPoints || [];
                const rdIntensity = config.gradientIntensity != null ? config.gradientIntensity : def.gradientIntensity;

                if (meshPad) {
                    if (points.length >= 2) {
                        const bgColor = config.gradientMeshBgColor || def.gradientMeshBgColor;
                        const layers = points.map(p => {
                            const c = adjustHexIntensity(p.color, rdIntensity);
                            return `radial-gradient(at ${p.x}% ${p.y}%, ${c} 0%, transparent ${p.spread}%)`;
                        }).join(', ');
                        meshPad.style.backgroundImage = layers;
                        meshPad.style.backgroundColor = bgColor;
                    } else {
                        meshPad.style.backgroundImage = '';
                        meshPad.style.backgroundColor = '';
                    }

                    // Not during a drag, which moves its dot directly
                    if (!window._meshDragActive) {
                        meshPad.innerHTML = points.map((p, i) => `<div class="mesh-dot ${i === window._selectedMeshPoint ? 'selected' : ''}" data-index="${i}" style="left:${_cssNum(p.x, 50)}%;top:${_cssNum(p.y, 50)}%;background:${_cssTok(p.color)};"></div>`).join('');
                    }
                }

                const countEl = $('mesh-stop-count');
                if (countEl) countEl.innerText = `${points.length}/16 points`;

                const hint = $('mesh-hint');
                if (hint) hint.textContent = points.length >= 16 ? 'Maximum 16 points reached' : 'Click to add \u00b7 Drag to move \u00b7 Double-click to remove';

                const addBtn = $('mesh-add-stop-btn');
                if (addBtn) addBtn.style.display = points.length >= 16 ? 'none' : '';

                // Not while a spread slider is dragged: rebuilding the list
                // would replace the slider under the pointer
                const meshStopsList = $('mesh-stops-list');
                if (meshStopsList && !window._meshSpreadSliderActive) {
                    setHtmlKeepingFocus(meshStopsList, points.map((p, i) => `
                        <div class="mesh-stop-row ${i === window._selectedMeshPoint ? 'selected' : ''}" data-index="${i}" data-item="${i}" onclick="window.selectMeshPoint(${i})">
                            <button type="button" class="plain-button mesh-stop-select" data-control="select" aria-pressed="${i === window._selectedMeshPoint}" aria-label="Mesh point ${i + 1}: ${_escAttr(_cssTok(p.color))} at ${_cssNum(p.x, 50)}%, ${_cssNum(p.y, 50)}%"></button>
                            <div class="gradient-drag-handle" data-tooltip="Drag to reorder">
                                ${ICONS.dragHandle}
                            </div>
                            <div class="gradient-stop-swatch" style="background: ${_cssTok(p.color)};">
                                <input type="color" value="${_escAttr(_cssTok(p.color))}" aria-label="Mesh point ${i + 1} color" onchange="window.updateMeshStop(${i}, {color: this.value})" oninput="this.parentElement.style.background = this.value">
                            </div>
                            <input type="range" class="gradient-stop-slider" min="10" max="80" value="${_cssNum(p.spread, 50)}" aria-label="Mesh point ${i + 1} spread" onpointerdown="window._meshSpreadSliderActive = true" onpointerup="window._meshSpreadSliderActive = false" onpointercancel="window._meshSpreadSliderActive = false" oninput="window.updateMeshStop(${i}, {spread: parseInt(this.value)}); this.nextElementSibling.innerText = this.value + '%'" onchange="window._meshSpreadSliderActive = false; window.updateMeshStop(${i}, {spread: parseInt(this.value)})">
                            <span class="gradient-stop-pos">${_cssNum(p.spread, 50)}%</span>
                            <button class="gradient-stop-delete" data-control="delete" onclick="event.stopPropagation(); window.removeMeshStop(${i})" ${points.length <= 2 ? 'disabled style="opacity:0.3;cursor:not-allowed;"' : ''} data-tooltip="Remove stop" aria-label="Remove mesh point ${i + 1}">×</button>
                        </div>
                    `).join(''));

                    initDragDrop(meshStopsList, '.mesh-stop-row', window.reorderMeshStop);
                }

                const bgSw = $('mesh-bg-swatch');
                if (bgSw) bgSw.style.background = config.gradientMeshBgColor || def.gradientMeshBgColor;
                const bgIn = $('mesh-bg-color');
                if (bgIn && !window._meshDragActive) bgIn.value = config.gradientMeshBgColor || def.gradientMeshBgColor;
            }
        }

        const speedRow = $('gradient-speed-row');
        if (speedRow) speedRow.style.display = config.gradientAnimation ? 'flex' : 'none';

        // Not while a position slider is dragged: rebuilding the list
        // would replace the slider under the pointer
        const stopsList = $('gradient-stops-list');
        if (stopsList && !window._gradientSliderActive) {
            const stops = config.gradientStops || [];
            const stopCount = $('gradient-stop-count');
            if (stopCount) stopCount.innerText = `${stops.length}/16 stops`;

            const gradAddBtn = $('gradient-add-stop-btn');
            if (gradAddBtn) gradAddBtn.style.display = stops.length >= 16 ? 'none' : '';

            stopsList.innerHTML = stops.map((stop, i) => `
                <div class="gradient-stop-row" data-index="${i}" role="listitem">
                    <div class="gradient-drag-handle" data-tooltip="Drag to reorder">
                        ${ICONS.dragHandle}
                    </div>
                    <div class="gradient-stop-swatch" style="background: ${_cssTok(stop.color)};">
                        <input type="color" value="${_escAttr(_cssTok(stop.color))}" aria-label="Stop ${i + 1} color" onchange="window.updateGradientStop(${i}, {color: this.value})" oninput="this.parentElement.style.background = this.value">
                    </div>
                    <input type="range" class="gradient-stop-slider" min="0" max="100" value="${_cssNum(stop.position, 0)}" aria-label="Stop ${i + 1} position" onpointerdown="window._gradientSliderActive = true" onpointerup="window._gradientSliderActive = false" onpointercancel="window._gradientSliderActive = false" oninput="window.updateGradientStop(${i}, {position: parseInt(this.value)}); this.nextElementSibling.innerText = this.value + '%'" onchange="window._gradientSliderActive = false; window.updateGradientStop(${i}, {position: parseInt(this.value)})">
                    <span class="gradient-stop-pos">${_cssNum(stop.position, 0)}%</span>
                    <button class="gradient-stop-dup" onclick="window.duplicateGradientStop(${i})" ${stops.length >= 16 ? 'disabled style="opacity:0.3;cursor:not-allowed;"' : ''} data-tooltip="Duplicate stop" aria-label="Duplicate color stop ${i + 1}">⧉</button>
                    <button class="gradient-stop-delete" onclick="window.removeGradientStop(${i})" ${stops.length <= 2 && config.gradientEnabled ? 'disabled style="opacity:0.3;cursor:not-allowed;"' : ''} data-tooltip="Remove stop" aria-label="Remove color stop ${i + 1}">×</button>
                </div>
            `).join('');

            initDragDrop(stopsList, '.gradient-stop-row', window.reorderGradientStop);
        }

        const previewBar = $('gradient-preview-bar');
        if (previewBar) {
            const gType = config.gradientType || def.gradientType;
            if (gType === 'mesh') {
                const points = config.gradientMeshPoints || [];
                if (points.length >= 2) {
                    const bgColor = config.gradientMeshBgColor || def.gradientMeshBgColor;
                    const layers = points.map(p => {
                        const c = adjustHexIntensity(p.color, intensity);
                        return `radial-gradient(at ${p.x}% ${p.y}%, ${c} 0%, transparent ${p.spread}%)`;
                    }).join(', ');
                    previewBar.style.backgroundImage = layers;
                    previewBar.style.backgroundColor = bgColor;
                    previewBar.classList.remove('empty');
                } else {
                    previewBar.style.backgroundImage = '';
                    previewBar.style.backgroundColor = '';
                    previewBar.classList.add('empty');
                }
            } else {
                previewBar.style.backgroundColor = '';
                const stops = config.gradientStops || [];
                if (stops.length >= 2) {
                    const sorted = [...stops].sort((a, b) => a.position - b.position);
                    const stopsStr = sorted.map(s => `${adjustHexIntensity(s.color, intensity)} ${s.position}%`).join(', ');
                    let gradFunc;
                    if (gType === 'radial') {
                        const rShape = config.gradientRadialShape || def.gradientRadialShape;
                        const rSize = config.gradientRadialSize || def.gradientRadialSize;
                        const rPosX = config.gradientRadialPosX ?? def.gradientRadialPosX;
                        const rPosY = config.gradientRadialPosY ?? def.gradientRadialPosY;
                        gradFunc = `radial-gradient(${rShape} ${rSize} at ${rPosX}% ${rPosY}%, ${stopsStr})`;
                    } else if (gType === 'conic') {
                        // buildGradientCss emits a real conic gradient, so a linear
                        // preview here would show the admin something other than
                        // what every user receives.
                        gradFunc = `conic-gradient(from ${_cssNum(config.gradientAngle, def.gradientAngle)}deg, ${stopsStr})`;
                    } else gradFunc = `linear-gradient(90deg, ${stopsStr})`;
                    previewBar.style.backgroundImage = gradFunc;
                    previewBar.classList.remove('empty');
                } else {
                    previewBar.style.backgroundImage = '';
                    previewBar.classList.add('empty');
                }
            }
        }

        renderGradientPresets();
    }

    function renderGradientPresets() {
        const def = DEFAULT_MODE_DATA;
        const gallery = $('gradient-preset-gallery');
        if (!gallery) return;
        const dm = getActiveDataMode();
        const config = themeData[dm];

        const searchInput = $('gradient-search-input');
        const searchTerm = searchInput ? searchInput.value.toLowerCase().trim() : '';

        const sortState = activeGradientSort;

        const builtInEntries = Object.entries(GRADIENT_PRESETS).map(([id, preset]) => ({
            type: 'builtin', id, preset
        }));
        const customEntries = CUSTOM_GRADIENT_PRESETS.map((preset, i) => ({
            type: 'custom', index: i, preset
        }));
        let allEntries = [...builtInEntries, ...customEntries];

        const typeFilter = activeGradientTypeFilter;
        if (typeFilter !== 'all') {
            allEntries = allEntries.filter(e => (e.preset.type || def.gradientType) === typeFilter);
        }

        if (searchTerm) {
            allEntries = allEntries.filter(e => e.preset.name.toLowerCase().includes(searchTerm));
        }

        if (sortState === 'asc') {
            allEntries.sort((a, b) => a.preset.name.localeCompare(b.preset.name));
        } else if (sortState === 'desc') {
            allEntries.sort((a, b) => b.preset.name.localeCompare(a.preset.name));
        }

        const totalCount = Object.keys(GRADIENT_PRESETS).length + CUSTOM_GRADIENT_PRESETS.length;
        const isFiltered = searchTerm || typeFilter !== 'all';
        const countWrap = $('gradient-quick-count-wrap');
        const countEl = $('gradient-quick-count');
        if (countEl) countEl.innerText = isFiltered ? allEntries.length + '/' + totalCount : totalCount;
        if (countWrap) countWrap.style.display = totalCount > 0 ? '' : 'none';

        function swatchBackground(preset) {
            let gradStr, bgColorStyle = '';
            // sanitizeGradientPreset covers presets at the door; these calls are
            // the second layer, for presets already in a library from before it.
            if (preset.type === 'mesh' && preset.meshPoints) {
                const layers = preset.meshPoints.map(p =>
                    `radial-gradient(at ${_cssNum(p.x, 50)}% ${_cssNum(p.y, 50)}%, ${_cssTok(p.color)} 0%, transparent ${_cssNum(p.spread, 50)}%)`
                ).join(', ');
                gradStr = layers;
                bgColorStyle = `background-color:${_cssTok(preset.meshBgColor, def.gradientMeshBgColor)};`;
            } else {
                const stops = preset.stops || [];
                if (stops.length === 0) return { gradStr: 'none', bgColorStyle: '' };
                const sorted = [...stops].sort((a, b) => _cssNum(a.position, 0) - _cssNum(b.position, 0));
                const stopsStr = sorted.map(s => `${_cssTok(s.color)} ${_cssNum(s.position, 0)}%`).join(', ');
                if (preset.type === 'radial') {
                    gradStr = `radial-gradient(${_cssTok(preset.radialShape, def.gradientRadialShape)} ${_cssTok(preset.radialSize, def.gradientRadialSize)} at ${_cssNum(preset.radialPosX, def.gradientRadialPosX)}% ${_cssNum(preset.radialPosY, def.gradientRadialPosY)}%, ${stopsStr})`;
                } else if (preset.type === 'conic') {
                    gradStr = `conic-gradient(from ${_cssNum(preset.angle, def.gradientAngle)}deg, ${stopsStr})`;
                } else {
                    // Linear swatches stay at 90deg on purpose: the chip is a wide
                    // strip and the preset's own angle would clip it to a corner.
                    gradStr = `linear-gradient(90deg, ${stopsStr})`;
                }
            }
            return { gradStr, bgColorStyle };
        }

        const gradRef = activeGradientRef[dm];

        let html = allEntries.map(entry => {
            const { gradStr, bgColorStyle } = swatchBackground(entry.preset);
            const isActive = gradRef && gradRef.type === entry.type && (entry.type === 'builtin' ? gradRef.id === entry.id : gradRef.index === entry.index);
            const escapedName = _escAttr(entry.preset.name);
            const onclick = entry.type === 'builtin' ? `window.applyGradientPreset('${entry.id}')` : `window.applyCustomGradientPreset(${entry.index})`;
            const customActions = entry.type === 'custom' ? `
                    <button type="button" class="plain-button snapshot-action edit-snapshot" data-control="edit" onclick="event.stopPropagation(); window.requestRenameGradientPreset(${entry.index})" data-tooltip="Rename preset" aria-label="Rename preset">✎</button>
                    <button type="button" class="plain-button snapshot-action delete-snapshot" data-control="delete" onclick="event.stopPropagation(); window.requestDeleteGradientPreset(${entry.index})" data-tooltip="Delete preset" aria-label="Delete preset">×</button>` : '';
            return `
                <div class="gradient-preset-chip ${isActive ? 'active' : ''}" data-item="${entry.type}:${entry.type === 'builtin' ? entry.id : entry.index}" data-tooltip="${escapedName}" style="position:relative;" role="group" aria-label="${escapedName}">
                    <button type="button" class="plain-button card-apply" data-control="apply" onclick="${onclick}" aria-label="Apply ${escapedName}"></button>
                    <div class="gradient-preset-swatch" style="${bgColorStyle}background-image: ${gradStr};"></div>${customActions}
                    <div class="gradient-preset-label">${_esc(entry.preset.name)}</div>
                    <div class="selected-check">✓</div>
                </div>`;
        }).join('');

        if (allEntries.length === 0 && searchTerm) {
            html = `<div style="grid-column:1/-1; text-align:center; padding:20px 0; color:var(--text-muted); font-size:0.7rem;">No presets match "${_esc(searchTerm)}"</div>`;
        }

        setGalleryHtml(gallery, html);
    }

    function randomHex() { return '#' + Math.floor(Math.random()*16777215).toString(16).padStart(6, '0'); }

    function getStopsProp(type) { return type === 'mesh' ? 'gradientMeshPoints' : 'gradientStops'; }

    function persistGradientPresets() { Storage.set('gradients', CUSTOM_GRADIENT_PRESETS); syncLibrary(); }

    const stopCRUD = {
        remove(type, index) {
            const dm = getActiveDataMode();
            const prop = getStopsProp(type);
            const arr = themeData[dm][prop] || [];
            if (arr.length <= 2) return;
            if (type === 'gradient') window._gradientSliderActive = false;
            if (type === 'mesh') {
                arr.splice(index, 1);
                if (window._selectedMeshPoint === index) window._selectedMeshPoint = null;
                else if (window._selectedMeshPoint != null && window._selectedMeshPoint > index) window._selectedMeshPoint--;
            } else {
                themeData[dm][prop] = arr.filter((_, i) => i !== index);
            }
            commitChange();
        },
        update(type, index, updates) {
            const dm = getActiveDataMode();
            const arr = themeData[dm][getStopsProp(type)] || [];
            if (index < 0 || index >= arr.length) return;
            Object.assign(arr[index], updates);
            if (type === 'gradient') themeData[dm].gradientStops = [...arr];
            commitChange({ push: false });
            pushStateSoon(type, 600);
        },
    };

    window.addGradientStop = (color, position) => {
        window._gradientSliderActive = false;
        const dm = getActiveDataMode();
        const stops = themeData[dm].gradientStops || [];
        if (stops.length >= 16) return;
        const newColor = color || randomHex();
        let newPos = position;
        if (newPos == null) {
            if (stops.length === 0) newPos = 0;
            else if (stops.length === 1) newPos = 100;
            else {
                const sorted = [...stops].sort((a, b) => a.position - b.position);
                let maxGap = 0, gapStart = 0;
                for (let i = 0; i < sorted.length - 1; i++) {
                    const gap = sorted[i+1].position - sorted[i].position;
                    if (gap > maxGap) { maxGap = gap; gapStart = i; }
                }
                newPos = Math.round((sorted[gapStart].position + sorted[gapStart+1].position) / 2);
            }
        }
        themeData[dm].gradientStops = [...stops, { color: newColor, position: newPos }];
        if (!themeData[dm].gradientEnabled && themeData[dm].gradientStops.length >= 2) {
            themeData[dm].gradientEnabled = true;
        }
        commitChange();
    };

    window.removeGradientStop = (index) => stopCRUD.remove('gradient', index);

    window.duplicateGradientStop = (index) => {
        window._gradientSliderActive = false;
        const dm = getActiveDataMode();
        const stops = themeData[dm].gradientStops || [];
        if (stops.length >= 16 || index < 0 || index >= stops.length) return;
        const src = stops[index];
        const newPos = Math.min(100, Math.max(0, src.position + 5));
        stops.splice(index + 1, 0, { color: src.color, position: newPos });
        themeData[dm].gradientStops = [...stops];
        commitChange();
    };

    window.updateGradientStop = (index, updates) => stopCRUD.update('gradient', index, updates);

    window.reorderGradientStop = (fromIndex, toIndex) => {
        const dm = getActiveDataMode();
        const stops = [...(themeData[dm].gradientStops || [])];
        if (fromIndex < 0 || fromIndex >= stops.length || toIndex < 0 || toIndex >= stops.length) return;
        const positions = stops.map(s => s.position);
        const colors = stops.map(s => s.color);
        const [movedColor] = colors.splice(fromIndex, 1);
        colors.splice(toIndex, 0, movedColor);
        themeData[dm].gradientStops = positions.map((pos, i) => ({ color: colors[i], position: pos }));
        commitChange();
    };

    window.addMeshStop = () => {
        const dm = getActiveDataMode();
        const points = themeData[dm].gradientMeshPoints || [];
        if (points.length >= 16) return;
        const color = randomHex();
        const x = Math.floor(Math.random() * 60) + 20;
        const y = Math.floor(Math.random() * 60) + 20;
        points.push({ color, x, y, spread: 50 });
        themeData[dm].gradientMeshPoints = points;
        window._selectedMeshPoint = points.length - 1;
        if (!themeData[dm].gradientEnabled && points.length >= 2) {
            themeData[dm].gradientEnabled = true;
        }
        commitChange();
    };

    window.removeMeshStop = (index) => stopCRUD.remove('mesh', index);

    window.updateMeshStop = (index, updates) => stopCRUD.update('mesh', index, updates);

    window.selectMeshPoint = (index) => {
        const dm = getActiveDataMode();
        const points = themeData[dm].gradientMeshPoints || [];
        if (index >= 0 && index < points.length) {
            window._selectedMeshPoint = (window._selectedMeshPoint === index) ? null : index;
            updatePalette();
        }
    };

    window.reorderMeshStop = (fromIndex, toIndex) => {
        const dm = getActiveDataMode();
        const points = [...(themeData[dm].gradientMeshPoints || [])];
        if (fromIndex < 0 || fromIndex >= points.length || toIndex < 0 || toIndex >= points.length) return;
        const [moved] = points.splice(fromIndex, 1);
        points.splice(toIndex, 0, moved);
        themeData[dm].gradientMeshPoints = points;
        if (window._selectedMeshPoint === fromIndex) window._selectedMeshPoint = toIndex;
        else if (window._selectedMeshPoint != null) {
            if (fromIndex < window._selectedMeshPoint && toIndex >= window._selectedMeshPoint) window._selectedMeshPoint--;
            else if (fromIndex > window._selectedMeshPoint && toIndex <= window._selectedMeshPoint) window._selectedMeshPoint++;
        }
        commitChange();
    };

    window.randomGradient = () => {
        window._gradientSliderActive = false;
        const dm = getActiveDataMode();
        const numStops = 3 + Math.floor(Math.random() * 3);
        const hueBase = Math.floor(Math.random() * 360);
        const stops = [];
        for (let i = 0; i < numStops; i++) {
            const hue = (hueBase + Math.floor(Math.random() * 120) - 60 + 360) % 360;
            const sat = 50 + Math.floor(Math.random() * 50);
            const lit = 10 + Math.floor(Math.random() * 40);
            const pos = Math.round((i / (numStops - 1)) * 100);
            // Convert HSL to Hex
            const c = (1 - Math.abs(2 * lit / 100 - 1)) * sat / 100;
            const x = c * (1 - Math.abs((hue / 60) % 2 - 1));
            const m = lit / 100 - c / 2;
            let r, g, b;
            if (hue < 60) { r = c; g = x; b = 0; }
            else if (hue < 120) { r = x; g = c; b = 0; }
            else if (hue < 180) { r = 0; g = c; b = x; }
            else if (hue < 240) { r = 0; g = x; b = c; }
            else if (hue < 300) { r = x; g = 0; b = c; }
            else { r = c; g = 0; b = x; }
            const toHex = v => Math.round((v + m) * 255).toString(16).padStart(2, '0');
            stops.push({ color: '#' + toHex(r) + toHex(g) + toHex(b), position: pos });
        }
        themeData[dm].gradientStops = stops;
        themeData[dm].gradientEnabled = true;
        const rType = ['linear', 'radial', 'mesh'][Math.floor(Math.random() * 3)];
        themeData[dm].gradientType = rType;
        themeData[dm].gradientAngle = Math.floor(Math.random() * 360);
        if (rType === 'radial') {
            themeData[dm].gradientRadialPosX = Math.floor(Math.random() * 80) + 10;
            themeData[dm].gradientRadialPosY = Math.floor(Math.random() * 80) + 10;
            themeData[dm].gradientRadialShape = ['circle', 'ellipse'][Math.floor(Math.random() * 2)];
            themeData[dm].gradientRadialSize = ['farthest-corner', 'closest-side', 'farthest-side', 'closest-corner'][Math.floor(Math.random() * 4)];
        }
        if (rType === 'mesh') {
            const numPoints = 3 + Math.floor(Math.random() * 3);
            const hueBase = Math.floor(Math.random() * 360);
            const meshPts = [];
            for (let mi = 0; mi < numPoints; mi++) {
                const hue = (hueBase + Math.floor(Math.random() * 160) - 80 + 360) % 360;
                const sat = 60 + Math.floor(Math.random() * 35);
                const lit = 40 + Math.floor(Math.random() * 25);
                const c = `hsl(${hue}, ${sat}%, ${lit}%)`;
                const tempEl = document.createElement('div');
                tempEl.style.color = c;
                document.body.appendChild(tempEl);
                const rgb = getComputedStyle(tempEl).color;
                document.body.removeChild(tempEl);
                const match = rgb.match(/\d+/g);
                const hex = match ? '#' + match.slice(0,3).map(v => parseInt(v).toString(16).padStart(2,'0')).join('') : '#6366f1';
                meshPts.push({ color: hex, x: Math.floor(Math.random() * 80) + 10, y: Math.floor(Math.random() * 80) + 10, spread: 30 + Math.floor(Math.random() * 30) });
            }
            themeData[dm].gradientMeshPoints = meshPts;
            themeData[dm].gradientMeshBgColor = '#' + Math.floor(Math.random() * 0x0f0f0f).toString(16).padStart(6, '0');
            window._selectedMeshPoint = null;
        }
        commitChange();
        showToast('Random gradient generated!');
    };

    window.resetGradient = () => {
        window._gradientSliderActive = false;
        const dm = getActiveDataMode();
        const def = DEFAULT_MODE_DATA;
        themeData[dm].gradientEnabled = def.gradientEnabled;
        themeData[dm].gradientStops = [];
        themeData[dm].gradientType = def.gradientType;
        themeData[dm].gradientAngle = def.gradientAngle;
        themeData[dm].gradientIntensity = def.gradientIntensity;
        themeData[dm].gradientAnimation = def.gradientAnimation;
        themeData[dm].gradientAnimationSpeed = def.gradientAnimationSpeed;
        themeData[dm].gradientRadialPosX = def.gradientRadialPosX;
        themeData[dm].gradientRadialPosY = def.gradientRadialPosY;
        themeData[dm].gradientRadialShape = def.gradientRadialShape;
        themeData[dm].gradientRadialSize = def.gradientRadialSize;
        themeData[dm].gradientMeshPoints = [];
        themeData[dm].gradientMeshBgColor = def.gradientMeshBgColor;
        window._selectedMeshPoint = null;
        commitChange();
        showToast('Gradient cleared');
    };

    window.toggleTransferPanel = () => {
        const panel = document.getElementById('gradient-transfer-panel');
        if (!panel) return;
        const isOpen = panel.style.display !== 'none';
        if (isOpen) { panel.style.display = 'none'; return; }
        const dm = getActiveDataMode();
        const currentType = themeData[dm].gradientType || DEFAULT_MODE_DATA.gradientType;
        const sourceLabel = document.getElementById('transfer-source-label');
        if (sourceLabel) sourceLabel.textContent = currentType.charAt(0).toUpperCase() + currentType.slice(1);
        ['linear', 'radial', 'mesh'].forEach(t => {
            const label = document.getElementById('transfer-target-' + t);
            if (label) {
                label.style.display = (t === currentType) ? 'none' : 'flex';
                const cb = label.querySelector('input[type="checkbox"]');
                if (cb) cb.checked = (t !== currentType);
            }
        });
        panel.style.display = 'block';
    };

    window.executeTransferColors = () => {
        const dm = getActiveDataMode();
        const config = themeData[dm];
        const currentType = config.gradientType || DEFAULT_MODE_DATA.gradientType;
        const targets = [];
        document.querySelectorAll('#transfer-targets input[type="checkbox"]:checked').forEach(cb => targets.push(cb.value));
        if (targets.length === 0) { showToast('Select at least one target type'); return; }

        const colors = currentType === 'mesh'
            ? (config.gradientMeshPoints || []).map(p => p.color)
            : (config.gradientStops || []).map(s => s.color);
        if (colors.length < 2) { showToast('Need at least 2 colors to transfer'); return; }

        const transferred = [];
        for (const target of targets) {
            if (target === currentType) continue;
            if (target === 'mesh') {
                const points = colors.map((color, i) => {
                    const t = colors.length > 1 ? i / (colors.length - 1) : 0.5;
                    return { color, x: Math.round(15 + t * 70), y: Math.round(15 + t * 70), spread: 50 };
                });
                config.gradientMeshPoints = points;
                config.gradientMeshBgColor = config.gradientMeshBgColor || DEFAULT_MODE_DATA.gradientMeshBgColor;
            } else {
                const stops = colors.map((color, i) => ({
                    color,
                    position: colors.length > 1 ? Math.round((i / (colors.length - 1)) * 100) : 50
                }));
                config.gradientStops = stops;
            }
            transferred.push(target.charAt(0).toUpperCase() + target.slice(1));
        }

        hideModal('gradient-transfer-panel');
        activeGradientRef[dm] = null;
        commitChange({ clearRef: false });
        showToast(`Colors transferred to ${transferred.join(' & ')}!`);
    };

    window.reverseGradientStops = () => {
        window._gradientSliderActive = false;
        const dm = getActiveDataMode();
        const gType = themeData[dm].gradientType || DEFAULT_MODE_DATA.gradientType;
        if (gType === 'mesh') {
            const points = themeData[dm].gradientMeshPoints || [];
            if (points.length < 2) return;
            points.forEach(p => { p.x = 100 - p.x; p.y = 100 - p.y; });
            themeData[dm].gradientMeshPoints = [...points];
        } else {
            const stops = themeData[dm].gradientStops || [];
            if (stops.length < 2) return;
            stops.forEach(s => { s.position = 100 - s.position; });
            themeData[dm].gradientStops = [...stops];
        }
        commitChange();
        showToast('Gradient reversed');
    };

    window.distributeGradientStops = () => {
        window._gradientSliderActive = false;
        const dm = getActiveDataMode();
        const gType = themeData[dm].gradientType || DEFAULT_MODE_DATA.gradientType;
        if (gType === 'mesh') {
            const points = themeData[dm].gradientMeshPoints || [];
            if (points.length < 2) return;
            const cols = Math.ceil(Math.sqrt(points.length));
            const rows = Math.ceil(points.length / cols);
            const padX = 15, padY = 15;
            points.forEach((p, i) => {
                const col = i % cols;
                const row = Math.floor(i / cols);
                p.x = Math.round(padX + (col / Math.max(cols - 1, 1)) * (100 - 2 * padX));
                p.y = Math.round(padY + (row / Math.max(rows - 1, 1)) * (100 - 2 * padY));
            });
            themeData[dm].gradientMeshPoints = [...points];
        } else {
            const stops = themeData[dm].gradientStops || [];
            if (stops.length < 2) return;
            stops.forEach((s, i) => { s.position = Math.round(i / (stops.length - 1) * 100); });
            themeData[dm].gradientStops = [...stops];
        }
        commitChange();
        showToast('Stops distributed evenly');
    };

    // The single funnel through which every gradient preset — built-in, imported
    // file, imported URL, server library — becomes live mode data. Validating
    // here covers all of them at once, including presets that predate
    // sanitizeGradientPreset and are already sitting in a user's library.
    function presetToGradientData(p) {
        const def = DEFAULT_MODE_DATA;
        return validateModeData({
            gradientEnabled: true, gradientType: p.type || def.gradientType, gradientAngle: p.angle ?? def.gradientAngle,
            gradientStops: p.stops || [], gradientAnimation: !!p.animation,
            gradientIntensity: p.intensity ?? def.gradientIntensity, gradientAnimationSpeed: p.speed || def.gradientAnimationSpeed,
            gradientRadialPosX: p.radialPosX ?? def.gradientRadialPosX, gradientRadialPosY: p.radialPosY ?? def.gradientRadialPosY,
            gradientRadialShape: p.radialShape || def.gradientRadialShape, gradientRadialSize: p.radialSize || def.gradientRadialSize,
            gradientMeshPoints: p.meshPoints || [], gradientMeshBgColor: p.meshBgColor || def.gradientMeshBgColor,
        });
    }

    function applyGradient(preset, ref) {
        window._gradientSliderActive = false;
        const dm = getActiveDataMode();
        copyGradientProps(themeData[dm], presetToGradientData(preset));
        if (preset.type === 'mesh' && preset.meshPoints) window._selectedMeshPoint = null;
        activeThemeRef[dm] = null;
        activeGradientRef[dm] = ref;
        commitChange({ clearRef: false });
        showToast(`Loaded "${preset.name}" gradient`);
    }

    window.applyGradientPreset = (presetId) => {
        const preset = GRADIENT_PRESETS[presetId];
        if (!preset) return;
        applyGradient(preset, { type: 'builtin', id: presetId });
    };

    let _gradientPresetToDelete = null;

    window.saveGradientPreset = () => {
        const dm = getActiveDataMode();
        const config = themeData[dm];
        const stops = config.gradientStops || [];
        const meshPoints = config.gradientMeshPoints || [];
        const gType = config.gradientType || DEFAULT_MODE_DATA.gradientType;
        if ((gType === 'mesh' && meshPoints.length < 2) || (gType !== 'mesh' && stops.length < 2)) {
            showToast('Add at least 2 stops first');
            return;
        }
        const input = $('gradient-preset-name-input');
        input.value = `Gradient ${new Date().toLocaleTimeString()}`;
        showModal('save-gradient-modal');
        input.focus(); input.select();
    };

    const confirmSaveGradientBtn = $('confirm-save-gradient-btn');
    if (confirmSaveGradientBtn) confirmSaveGradientBtn.addEventListener('click', () => {
        const name = $('gradient-preset-name-input').value.trim();
        if (!name) { showToast('Please enter a preset name'); return; }
        const config = themeData[getActiveDataMode()];
        const def = DEFAULT_MODE_DATA;
        const preset = {
            name,
            type: config.gradientType || def.gradientType,
            stops: structuredClone(config.gradientStops || []),
            angle: config.gradientAngle ?? def.gradientAngle,
            intensity: config.gradientIntensity ?? def.gradientIntensity,
            animation: !!config.gradientAnimation,
            speed: config.gradientAnimationSpeed || def.gradientAnimationSpeed,
            radialPosX: config.gradientRadialPosX ?? def.gradientRadialPosX,
            radialPosY: config.gradientRadialPosY ?? def.gradientRadialPosY,
            radialShape: config.gradientRadialShape || def.gradientRadialShape,
            radialSize: config.gradientRadialSize || def.gradientRadialSize,
        };
        if (preset.type === 'mesh') {
            preset.meshPoints = structuredClone(config.gradientMeshPoints || []);
            preset.meshBgColor = config.gradientMeshBgColor || def.gradientMeshBgColor;
        }
        CUSTOM_GRADIENT_PRESETS.push(preset);
        persistGradientPresets();
        hideModal('save-gradient-modal');
        renderGradientPresets();
        showToast('Gradient preset saved!');
    });

    window.applyCustomGradientPreset = (index) => {
        const preset = CUSTOM_GRADIENT_PRESETS[index];
        if (!preset) return;
        applyGradient(preset, { type: 'custom', index: index });
    };

    window.requestDeleteGradientPreset = (index) => {
        if (!CUSTOM_GRADIENT_PRESETS[index]) return;
        _gradientPresetToDelete = index;
        $('delete-gradient-name').innerText = CUSTOM_GRADIENT_PRESETS[index].name;
        showModal('delete-gradient-modal');
    };

    const confirmDeleteGradientBtn = $('confirm-delete-gradient-btn');
    if (confirmDeleteGradientBtn) confirmDeleteGradientBtn.addEventListener('click', () => {
        if (_gradientPresetToDelete === null) return;
        const deletedIdx = _gradientPresetToDelete;
        CUSTOM_GRADIENT_PRESETS.splice(deletedIdx, 1);
        persistGradientPresets();
        // Every mode's active marker, or another mode would mark the wrong preset
        MODES.forEach(m => {
            if (activeGradientRef[m] && activeGradientRef[m].type === 'custom') {
                if (activeGradientRef[m].index === deletedIdx) {
                    activeGradientRef[m] = null;
                } else if (activeGradientRef[m].index > deletedIdx) {
                    activeGradientRef[m].index--;
                }
            }
        });
        hideModal('delete-gradient-modal');
        renderGradientPresets();
        _gradientPresetToDelete = null;
        showToast('Gradient preset deleted');
    });

    let _gradientPresetToRename = null;

    window.requestRenameGradientPreset = (index) => {
        if (!CUSTOM_GRADIENT_PRESETS[index]) return;
        _gradientPresetToRename = index;
        const input = $('rename-gradient-input');
        input.value = CUSTOM_GRADIENT_PRESETS[index].name;
        showModal('rename-gradient-modal');
        input.focus(); input.select();
    };

    const confirmRenameGradientBtn = $('confirm-rename-gradient-btn');
    if (confirmRenameGradientBtn) confirmRenameGradientBtn.addEventListener('click', () => {
        if (_gradientPresetToRename === null) return;
        const newName = $('rename-gradient-input').value.trim();
        if (!newName) return;
        CUSTOM_GRADIENT_PRESETS[_gradientPresetToRename].name = newName;
        persistGradientPresets();
        hideModal('rename-gradient-modal');
        renderGradientPresets();
        _gradientPresetToRename = null;
        showToast('Gradient preset renamed');
    });

    const exportAllGradientBtn = $('export-all-gradient-btn');
    if (exportAllGradientBtn) exportAllGradientBtn.onclick = () => {
        if (CUSTOM_GRADIENT_PRESETS.length === 0) return showToast('No custom gradient presets to export');
        const dateStr = new Date().toISOString().split('T')[0];
        downloadFile({ gradient_presets: CUSTOM_GRADIENT_PRESETS, isGradientBackup: true, version: '{VERSION}' }, `owui-gradient-presets-backup-${dateStr}.json`);
        showToast('Gradient presets exported!');
    };

    setupMassDelete({
        triggerId: 'delete-all-gradient-btn', modalId: 'delete-all-gradient-modal',
        confirmId: 'confirm-delete-all-gradient-btn',
        emptyMsg: 'No presets to delete', toastMsg: 'Gradient Presets Cleared!',
        isEmpty: () => CUSTOM_GRADIENT_PRESETS.length === 0,
        onConfirm: () => {
            CUSTOM_GRADIENT_PRESETS.length = 0;
            persistGradientPresets();
            activeGradientRef = { dark: null, oled: null, light: null, her: null };
            renderGradientPresets();
        }
    });

    const importGradientBtn = $('import-gradient-btn');
    if (importGradientBtn) importGradientBtn.onclick = () => {
        const urlInput = $('import-gradient-url-input');
        const statusEl = $('import-gradient-url-status');
        if (urlInput) urlInput.value = '';
        if (statusEl) { statusEl.style.display = 'none'; statusEl.textContent = ''; }
        showModal('import-gradient-modal');
    };

    document.getElementById('import-gradient-file-trigger-btn').onclick = () => triggerFileImport({
        accept: '.json', modalId: 'import-gradient-modal', importFn: handleGradientImport
    });

    document.getElementById('import-gradient-url-load-btn').onclick = () => loadFromUrl({
        urlInputId: 'import-gradient-url-input', statusId: 'import-gradient-url-status',
        loadBtnId: 'import-gradient-url-load-btn', modalId: 'import-gradient-modal',
        fetchMsg: 'Fetching gradient presets from URL...', emptyMsg: 'Please enter a URL to a JSON file.',
        defaultName: 'gradients.json', defaultExt: '.json', mimeType: 'application/json',
        importFn: handleGradientImport
    });

    document.getElementById('import-gradient-url-input').addEventListener('keydown', (e) => {
        if (e.key === 'Enter') document.getElementById('import-gradient-url-load-btn').click();
    });

    // Prevent the global drop overlay from showing when dragging over the gradient modal
    const gradientModal = $('import-gradient-modal');
    if (gradientModal) {
        gradientModal.addEventListener('dragover', (e) => { e.preventDefault(); e.stopPropagation(); });
        gradientModal.addEventListener('drop', (e) => { e.preventDefault(); e.stopPropagation(); });
    }

    function resetGradientProp(prop) { themeData[getActiveDataMode()][prop] = DEFAULT_MODE_DATA[prop]; commitChange(); }
    window.resetGradientAngle = () => resetGradientProp('gradientAngle');
    window.resetGradientIntensity = () => resetGradientProp('gradientIntensity');
    window.resetGradientSpeed = () => resetGradientProp('gradientAnimationSpeed');

    document.querySelectorAll('.gradient-type-pill').forEach(pill => {
        pill.addEventListener('click', () => {
            document.querySelectorAll('.gradient-type-pill').forEach(p => p.setAttribute('aria-pressed', 'false'));
            pill.setAttribute('aria-pressed', 'true');
            const dm = getActiveDataMode();
            themeData[dm].gradientType = pill.dataset.gtype;
            if (pill.dataset.gtype === 'mesh' && themeData[dm].gradientEnabled && (!themeData[dm].gradientMeshPoints || themeData[dm].gradientMeshPoints.length < 2)) {
                themeData[dm].gradientMeshPoints = structuredClone(DEFAULT_MESH_POINTS);
                themeData[dm].gradientMeshBgColor = themeData[dm].gradientMeshBgColor || DEFAULT_MODE_DATA.gradientMeshBgColor;
            }
            window._selectedMeshPoint = null;
            commitChange();
        });
    });

    // Where a pointer event falls on a pad, as whole percents clamped to 0-100
    function padPercent(pad, e) {
        const rect = pad.getBoundingClientRect();
        return {
            x: Math.max(0, Math.min(100, Math.round((e.clientX - rect.left) / rect.width * 100))),
            y: Math.max(0, Math.min(100, Math.round((e.clientY - rect.top) / rect.height * 100)))
        };
    }

    const xyPad = $('radial-xy-pad');
    if (xyPad) {
        let xyDragging = false;
        function updateXYFromEvent(e) {
            const { x, y } = padPercent(xyPad, e);
            const dm = getActiveDataMode();
            themeData[dm].gradientRadialPosX = x;
            themeData[dm].gradientRadialPosY = y;
            const dot = $('radial-xy-dot');
            if (dot) { dot.style.left = x + '%'; dot.style.top = y + '%'; }
            const label = $('radial-xy-label');
            if (label) label.innerText = x + '%, ' + y + '%';
            commitChange({ push: false });
        }
        xyPad.addEventListener('pointerdown', (e) => {
            e.preventDefault();
            xyDragging = true;
            xyPad.setPointerCapture(e.pointerId);
            updateXYFromEvent(e);
        });
        xyPad.addEventListener('pointermove', (e) => { if (xyDragging) updateXYFromEvent(e); });
        const endXYDrag = () => { if (xyDragging) { xyDragging = false; pushState(); } };
        xyPad.addEventListener('pointerup', endXYDrag);
        xyPad.addEventListener('lostpointercapture', endXYDrag);
        xyPad.addEventListener('dblclick', () => {
            const dm = getActiveDataMode();
            themeData[dm].gradientRadialPosX = DEFAULT_MODE_DATA.gradientRadialPosX;
            themeData[dm].gradientRadialPosY = DEFAULT_MODE_DATA.gradientRadialPosY;
            commitChange();
        });

        xyPad.addEventListener('keydown', (e) => {
            if (!['ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight', 'Home'].includes(e.key)) return;
            e.preventDefault();
            const dm = getActiveDataMode();
            const step = e.shiftKey ? 5 : 1;

            if (e.key === 'Home') {
                themeData[dm].gradientRadialPosX = DEFAULT_MODE_DATA.gradientRadialPosX;
                themeData[dm].gradientRadialPosY = DEFAULT_MODE_DATA.gradientRadialPosY;
            } else {
                let x = themeData[dm].gradientRadialPosX ?? DEFAULT_MODE_DATA.gradientRadialPosX;
                let y = themeData[dm].gradientRadialPosY ?? DEFAULT_MODE_DATA.gradientRadialPosY;
                if (e.key === 'ArrowLeft')  x = Math.max(0, x - step);
                if (e.key === 'ArrowRight') x = Math.min(100, x + step);
                if (e.key === 'ArrowUp')    y = Math.max(0, y - step);
                if (e.key === 'ArrowDown')  y = Math.min(100, y + step);
                themeData[dm].gradientRadialPosX = x;
                themeData[dm].gradientRadialPosY = y;
            }
            commitChange();
        });
    }

    [
        ['.radial-shape-pill', 'shape', 'gradientRadialShape'],
        ['.radial-size-pill', 'size', 'gradientRadialSize'],
    ].forEach(([sel, attr, prop]) => {
        document.querySelectorAll(sel).forEach(pill => {
            pill.addEventListener('click', () => {
                document.querySelectorAll(sel).forEach(p => p.setAttribute('aria-pressed', 'false'));
                pill.setAttribute('aria-pressed', 'true');
                themeData[getActiveDataMode()][prop] = pill.dataset[attr];
                commitChange();
            });
        });
    });

    window._selectedMeshPoint = null;
    window._meshDragActive = false;
    const meshPad = $('mesh-editor-pad');
    if (meshPad) {
        let meshDragIdx = null, meshDragMoved = false;
        meshPad.addEventListener('pointerdown', (e) => {
            const dot = e.target.closest('.mesh-dot');
            if (dot) {
                meshDragIdx = parseInt(dot.dataset.index);
                window._meshDragActive = true;
                meshDragMoved = false;
                meshPad.setPointerCapture(e.pointerId);
                e.preventDefault();
                window._selectedMeshPoint = meshDragIdx;
                // Selected in place: an updatePalette() rebuild would replace the
                // dot, and a double-click needs both clicks on the same element
                meshPad.querySelectorAll('.mesh-dot').forEach(d => d.classList.remove('selected'));
                dot.classList.add('selected');
                const meshStopsListEl = $('mesh-stops-list');
                if (meshStopsListEl) {
                    meshStopsListEl.querySelectorAll('.mesh-stop-row').forEach(r => {
                        const on = r.dataset.index === String(meshDragIdx);
                        r.classList.toggle('selected', on);
                        r.querySelector('.mesh-stop-select')?.setAttribute('aria-pressed', String(on));
                    });
                }
            } else {
                const dm = getActiveDataMode();
                const points = themeData[dm].gradientMeshPoints || [];
                if (points.length >= 16) return;
                const { x, y } = padPercent(meshPad, e);
                const color = randomHex();
                points.push({ color, x, y, spread: 50 });
                themeData[dm].gradientMeshPoints = points;
                window._selectedMeshPoint = points.length - 1;
                commitChange();
            }
        });
        meshPad.addEventListener('pointermove', (e) => {
            if (!window._meshDragActive || meshDragIdx == null) return;
            meshDragMoved = true;
            const { x, y } = padPercent(meshPad, e);
            const dm = getActiveDataMode();
            const points = themeData[dm].gradientMeshPoints || [];
            if (points[meshDragIdx]) {
                points[meshDragIdx].x = x;
                points[meshDragIdx].y = y;
                const dotEl = meshPad.querySelector(`.mesh-dot[data-index="${meshDragIdx}"]`);
                if (dotEl) { dotEl.style.left = x + '%'; dotEl.style.top = y + '%'; }
                commitChange({ push: false });
            }
        });
        const endMeshDrag = () => {
            if (!window._meshDragActive) return;
            window._meshDragActive = false;
            if (meshDragMoved) commitChange({ clearRef: false });
            meshDragIdx = null;
        };
        meshPad.addEventListener('pointerup', endMeshDrag);
        meshPad.addEventListener('lostpointercapture', endMeshDrag);
        meshPad.addEventListener('dblclick', (e) => {
            const el = document.elementFromPoint(e.clientX, e.clientY);
            const dot = el && el.closest('.mesh-dot');
            if (dot) stopCRUD.remove('mesh', parseInt(dot.dataset.index));
        });

        meshPad.addEventListener('keydown', (e) => {
            const dm = getActiveDataMode();
            const points = themeData[dm].gradientMeshPoints || [];
            const selIdx = window._selectedMeshPoint;

            if (['ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight'].includes(e.key) && selIdx !== null && points[selIdx]) {
                e.preventDefault();
                const step = e.shiftKey ? 5 : 1;
                if (e.key === 'ArrowLeft')  points[selIdx].x = Math.max(0, points[selIdx].x - step);
                if (e.key === 'ArrowRight') points[selIdx].x = Math.min(100, points[selIdx].x + step);
                if (e.key === 'ArrowUp')    points[selIdx].y = Math.max(0, points[selIdx].y - step);
                if (e.key === 'ArrowDown')  points[selIdx].y = Math.min(100, points[selIdx].y + step);
                commitChange();
                return;
            }

            if ((e.key === 'Delete' || e.key === 'Backspace') && selIdx !== null && points.length > 2) {
                e.preventDefault();
                stopCRUD.remove('mesh', selIdx);
                return;
            }

            // Tab steps through the points, then leaves the pad as Tab does anywhere
            if (e.key === 'Tab' && points.length > 0) {
                const next = selIdx === null ? (e.shiftKey ? points.length - 1 : 0) : selIdx + (e.shiftKey ? -1 : 1);
                if (next >= 0 && next < points.length) e.preventDefault();
                window._selectedMeshPoint = next >= 0 && next < points.length ? next : null;
                commitChange({ push: false });
            }
        });
    }

    window._meshSpreadSliderActive = false;

    const meshBgColorInput = $('mesh-bg-color');
    if (meshBgColorInput) {
        meshBgColorInput.addEventListener('input', (e) => {
            const dm = getActiveDataMode();
            themeData[dm].gradientMeshBgColor = e.target.value;
            const sw = $('mesh-bg-swatch');
            if (sw) sw.style.background = e.target.value;
            commitChange({ push: false });
        });
        meshBgColorInput.addEventListener('change', () => pushState());
    }

    const toggleGradientBg = $('toggle-gradient-bg');
    if (toggleGradientBg) {
        dimGradientToggles(toggleGradientBg.checked);
        toggleGradientBg.addEventListener('change', (e) => {
            const dm = getActiveDataMode();
            themeData[dm].gradientEnabled = e.target.checked;
            if (e.target.checked) {
                if (themeData[dm].gradientType === 'mesh') {
                    if (!themeData[dm].gradientMeshPoints || themeData[dm].gradientMeshPoints.length < 2) {
                        themeData[dm].gradientMeshPoints = structuredClone(DEFAULT_MESH_POINTS);
                        themeData[dm].gradientMeshBgColor = themeData[dm].gradientMeshBgColor || DEFAULT_MODE_DATA.gradientMeshBgColor;
                    }
                } else if (!themeData[dm].gradientStops || themeData[dm].gradientStops.length < 2) {
                    themeData[dm].gradientStops = structuredClone(GRADIENT_PRESETS.midnight.stops);
                }
            }
            dimGradientToggles(e.target.checked);
            commitChange();
        });
    }

    const toggleGradientAnim = $('toggle-gradient-animation');
    if (toggleGradientAnim) toggleGradientAnim.addEventListener('change', (e) => {
        const dm = getActiveDataMode();
        themeData[dm].gradientAnimation = e.target.checked;
        commitChange();
    });

    const gradientSliders = [
        ['sl-gradient-angle', 'gradientAngle', 'val-gradient-angle', v => v + '°'],
        ['sl-gradient-intensity', 'gradientIntensity', 'val-gradient-intensity', v => v + '%'],
        ['sl-gradient-speed', 'gradientAnimationSpeed', 'val-gradient-speed', v => v + 's']
    ];
    gradientSliders.forEach(([sliderId, prop, valId, fmt]) => {
        const slider = $(sliderId);
        if (slider) {
            slider.addEventListener('input', () => {
                const dm = getActiveDataMode();
                themeData[dm][prop] = parseInt(slider.value);
                if ($(valId)) $(valId).innerText = fmt(slider.value);
                commitChange({ push: false });
            });
            slider.addEventListener('change', () => pushState());
        }
    });

    // === END GRADIENT BUILDER LOGIC ===

