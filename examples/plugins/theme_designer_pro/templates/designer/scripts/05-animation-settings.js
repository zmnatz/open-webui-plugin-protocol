    // ---- Animation settings ----
    // A script's CONFIG object, or the constants at its top, read as sliders,
    // switches and colors (the same parser as the website's Studio). A change
    // rewrites that one value in the script, exactly like typing it in the
    // editor, so Undo, the gallery and the live canvas all see an edit.

    const NUM = '-?(?:\\d+\\.?\\d*|\\.\\d+)(?:e-?\\d+)?';
    const LIT = `(${NUM}|true|false|'#(?:[0-9a-fA-F]{6}|[0-9a-fA-F]{3})'|"#(?:[0-9a-fA-F]{6}|[0-9a-fA-F]{3})")`;
    const OBJ_ENTRY = new RegExp(`^(\\s*([A-Za-z_$][\\w$]*)\\s*:\\s*)${LIT}(\\s*(?:,|$).*)$`);
    const INLINE_ENTRY = new RegExp(`([A-Za-z_$][\\w$]*)\\s*:\\s*${LIT}(?=\\s*[,}])`, 'g');
    const CONST_ENTRY = new RegExp(`^((?:const|let|var)\\s+([A-Z][A-Z0-9_]*)\\s*=\\s*)${LIT}(\\s*;.*)$`);
    const SECTION = /^\s*\/\/\s*[-─═=]{2,}\s*(.*?)\s*[-─═=]*\s*$/;
    const MAX_SETTINGS = 80;

    function labelOf(key) {
      const words = key.includes('_') ? key.toLowerCase().split('_') : key.replace(/([a-z0-9])([A-Z])/g, '$1 $2').toLowerCase().split(' ');
      const text = words.filter(Boolean).join(' ');
      return text.charAt(0).toUpperCase() + text.slice(1);
    }

    // A range stated in the comment wins; otherwise one sized to the default
    function numberRange(v, comment) {
      const int = Number.isInteger(v);
      const r = comment.match(/(-?\d*\.?\d+)\s*(?:-|–|—|to|\.\.)\s*(-?\d*\.?\d+)/);
      let min, max;
      if (r && Number(r[1]) < Number(r[2])) { min = Number(r[1]); max = Number(r[2]); }
      else if (v < 0) { min = v * 3; max = -v * 3; }
      else if (v === 0) { min = 0; max = 1; }
      else if (!int && v <= 1) { min = 0; max = 1; }
      else { min = 0; max = int ? Math.max(4, Math.ceil(v * 3)) : Number((v * 3).toPrecision(2)); }
      min = Math.min(min, v);
      max = Math.max(max, v);
      const whole = int && Number.isInteger(min) && Number.isInteger(max);
      const step = whole ? 1 : Math.pow(10, Math.floor(Math.log10((max - min) / 100)));
      return { min, max, step };
    }

    // at: where the value starts in its line, so a change replaces only it
    function settingOf(line, at, key, raw, rest, section) {
      const comment = ((rest.match(/\/\/\s*(.*)$/) || [])[1] || '').trim();
      const e = { line, at, len: raw.length, key, section, hint: comment, label: labelOf(key) };
      if (raw === 'true' || raw === 'false') {
        e.kind = 'bool';
        e.value = raw === 'true';
      } else if (/^['"]#/.test(raw)) {
        e.kind = 'color';
        e.quote = raw[0];
        const hex = raw.slice(2, -1);
        e.value = '#' + (hex.length === 3 ? hex.split('').map((ch) => ch + ch).join('') : hex).toLowerCase();
      } else {
        e.kind = 'number';
        e.value = Number(raw);
        Object.assign(e, numberRange(e.value, comment));
      }
      return e;
    }

    function parseSettings(src) {
      const lines = String(src || '').split('\n');
      const out = [];
      let section = '';
      const start = lines.findIndex((x) => /^\s*(?:const|let|var)\s+(?:CONFIG|CFG)\s*=\s*\{/.test(x));
      if (start >= 0 && /\}\s*;?\s*(?:\/\/.*)?$/.test(lines[start])) {
        // The whole object on one line
        let m;
        INLINE_ENTRY.lastIndex = 0;
        while ((m = INLINE_ENTRY.exec(lines[start])) && out.length < MAX_SETTINGS) {
          out.push(settingOf(start, m.index + m[0].length - m[2].length, m[1], m[2], '', ''));
        }
      } else if (start >= 0) {
        let depth = 0;
        for (let i = start; i < lines.length && out.length < MAX_SETTINGS; i++) {
          if (i > start && depth === 1) {
            const sec = lines[i].match(SECTION);
            if (sec && sec[1]) section = sec[1];
            const m = lines[i].match(OBJ_ENTRY);
            if (m) out.push(settingOf(i, m[1].length, m[2], m[3], m[4], section));
          }
          // Brackets outside comments and strings set what belongs to CONFIG itself
          const code = lines[i].replace(/(['"`])(?:\\.|(?!\1).)*\1/g, '').replace(/\/\/.*$/, '');
          depth += (code.match(/[{[]/g) || []).length - (code.match(/[}\]]/g) || []).length;
          if (i > start && depth <= 0) break;
        }
      } else {
        // The other common layout: constants above the first function
        for (let i = 0; i < lines.length && out.length < MAX_SETTINGS; i++) {
          if (/^\s*(?:function|class|async\s+function|self\.onmessage|onmessage)\b/.test(lines[i])) break;
          const sec = lines[i].match(SECTION);
          if (sec && sec[1]) section = sec[1];
          const m = lines[i].match(CONST_ENTRY);
          if (m) out.push(settingOf(i, m[1].length, m[2], m[3], m[4], section));
        }
      }
      return out;
    }

    // Only parsed settings, with values of the right kind, are ever written
    function applySettings(src, cfg) {
      if (!cfg || !Object.keys(cfg).length) return src;
      const lines = src.split('\n');
      // Right to left, so an edit never moves a value still to be edited
      parseSettings(src).sort((x, y) => x.line - y.line || y.at - x.at).forEach((e) => {
        if (!Object.prototype.hasOwnProperty.call(cfg, e.key)) return;
        const v = cfg[e.key];
        // A value left at its default keeps the line exactly as written
        if (v === e.value) return;
        let lit = null;
        if (e.kind === 'bool' && typeof v === 'boolean') lit = v ? 'true' : 'false';
        else if (e.kind === 'color' && /^#[0-9a-f]{6}$/i.test(v)) lit = e.quote + v.toLowerCase() + e.quote;
        else if (e.kind === 'number' && typeof v === 'number' && isFinite(v)) lit = String(Number(v.toFixed(6)));
        if (lit !== null) lines[e.line] = lines[e.line].slice(0, e.at) + lit + lines[e.line].slice(e.at + e.len);
      });
      return lines.join('\n');
    }

    function fmtNum(v, step) {
        const d = step >= 1 ? 0 : Math.min(4, Math.ceil(-Math.log10(step)));
        return Number(v).toFixed(d);
    }

    // var, not let: updatePalette() can run before this point at startup,
    // and nothing renders until the whole script has run
    var _canvasSettingsKey = null, _canvasSettingsReady = false;
    function renderCanvasSettings() {
        const box = $('canvas-settings');
        if (!box || !_canvasSettingsReady) return;
        const dm = getActiveDataMode();
        const script = (themeData[dm] && themeData[dm].canvasScript) || '';
        const key = dm + '\n' + script;
        // Palette edits run this on every frame; rebuild only when the script changed
        if (key === _canvasSettingsKey) return;
        _canvasSettingsKey = key;
        const list = script.trim() ? parseSettings(script) : [];
        box.style.display = list.length ? '' : 'none';
        let section = null;
        $('canvas-settings-body').innerHTML = list.map((e) => {
            const head = e.section && e.section !== section ? `<div class="fx-set-section">${_esc(e.section)}</div>` : '';
            section = e.section;
            const hint = e.hint ? `<span class="fx-set-hint">${_esc(e.hint)}</span>` : '';
            const dataKey = _escAttr(e.key);
            if (e.kind === 'bool') {
                return head + `<label class="fx-set-toggle"><input type="checkbox" class="cb-input" data-key="${dataKey}" ${e.value ? 'checked' : ''}><span class="fx-set-text"><span>${_esc(e.label)}</span>${hint}</span></label>`;
            }
            if (e.kind === 'color') {
                return head + `<label class="fx-set-color"><input type="color" data-key="${dataKey}" value="${_escAttr(e.value)}"><span class="fx-set-text"><span>${_esc(e.label)}</span>${hint}</span></label>`;
            }
            return head + `<div class="slider-row"><label><span>${_esc(e.label)}</span> <span class="slider-val">${fmtNum(e.value, e.step)}</span></label>${hint}` +
                `<input type="range" data-key="${dataKey}" min="${e.min}" max="${e.max}" step="${e.step}" value="${e.value}" aria-label="${_escAttr(e.label)}"></div>`;
        }).join('');
        syncCanvasSettingsReset();
    }

    // The script as it was before its first setting change, per mode, so Reset
    // can bring it back. Any other change to the script (typing, loading a
    // preset, Undo) means it no longer applies.
    var _canvasSettingsBase = {};
    function canvasSettingsBase(dm) {
        const b = _canvasSettingsBase[dm];
        return b && b.current === themeData[dm].canvasScript ? b : null;
    }

    function syncCanvasSettingsReset() {
        const dm = getActiveDataMode();
        const list = parseSettings(themeData[dm].canvasScript || '');
        const b = canvasSettingsBase(dm);
        let changed = 0;
        if (b) {
            const before = {};
            parseSettings(b.script).forEach((e) => { before[e.key] = e.value; });
            changed = list.filter((e) => e.key in before && before[e.key] !== e.value).length;
        }
        $('canvas-settings-count').textContent = !list.length ? '' : changed ? `(${list.length} \u00b7 ${changed} changed)` : `(${list.length})`;
        $('canvas-settings-reset').disabled = !changed;
    }

    function canvasSettingFor(key) {
        return parseSettings(themeData[getActiveDataMode()].canvasScript || '').find((e) => e.key === key);
    }

    $('canvas-settings-body').addEventListener('input', (e) => {
        const t = e.target;
        if (t.type !== 'range') return;
        const s = canvasSettingFor(t.dataset.key);
        const out = t.closest('.slider-row').querySelector('.slider-val');
        if (s && out) out.textContent = fmtNum(t.value, s.step);
    });

    $('canvas-settings-body').addEventListener('change', (e) => {
        const t = e.target;
        const s = t.dataset.key && canvasSettingFor(t.dataset.key);
        if (!s) return;
        const value = s.kind === 'bool' ? t.checked : s.kind === 'color' ? t.value.toLowerCase() : Number(t.value);
        const dm = getActiveDataMode();
        const typedKey = _canvasSettingsKey;
        flushPendingEdits();
        // Text the editor still held rebuilt the panel, and this control with it
        const rebuilt = _canvasSettingsKey !== typedKey;
        const prev = themeData[dm].canvasScript || '';
        const next = applySettings(prev, { [s.key]: value });
        if (next === prev) return;
        const b = canvasSettingsBase(dm) || (_canvasSettingsBase[dm] = { script: prev, ref: activeCanvasRef[dm] });
        b.current = next;
        themeData[dm].canvasScript = next;
        activeThemeRef[dm] = null;
        activeCanvasRef[dm] = null;
        // The panel already shows this value, so keep it (and its focus) as it is
        if (!rebuilt) _canvasSettingsKey = dm + '\n' + next;
        commitChange({ clearRef: false });
        if (rebuilt) {
            const again = [].find.call($('canvas-settings-body').querySelectorAll('[data-key]'), el => el.dataset.key === s.key);
            if (again) again.focus();
        }
        syncCanvasSettingsReset();
    });

    $('canvas-settings-reset').addEventListener('click', () => {
        flushPendingEdits();
        const dm = getActiveDataMode();
        const b = canvasSettingsBase(dm);
        if (!b) return;
        delete _canvasSettingsBase[dm];
        themeData[dm].canvasScript = b.script;
        activeThemeRef[dm] = null;
        // Back to the exact script, so a gallery preset it came from is active again
        activeCanvasRef[dm] = b.ref || null;
        commitChange({ clearRef: false });
        showToast('Animation Settings Reset');
    });

    // getActiveDataMode() and others are declared further down, so the first
    // render waits until this whole script has run
    queueMicrotask(() => {
        _canvasSettingsReady = true;
        renderCanvasSettings();
    });

    function renderCanvasPresets() {
        renderPresetGallery({
            presets: CANVAS_PRESETS, galleryId: 'canvas-preset-gallery', scrollAreaId: 'canvas-preset-scroll',
            searchInputId: 'canvas-search-input', countWrapId: 'canvas-count-wrap', countId: 'canvas-count',
            sortVar: typeof activeCanvasSort !== 'undefined' ? activeCanvasSort : 'default',
            typeFilter: typeof activeCanvasTypeFilter !== 'undefined' ? activeCanvasTypeFilter : 'all',
            typeMatch: (script, f) => !!getCanvasScriptTags(script)[f],
            contentField: 'script', activeRefMap: activeCanvasRef, loadFnName: 'loadCanvasPreset',
            emptyMsg: 'Your saved animations will appear here.',
            noResultsPrefix: 'No scripts match',
            actionFns: { rename: 'requestCanvasRename', update: 'updateCanvasSnapshot', del: 'requestCanvasDelete', exp: 'exportCanvasSnapshot' },
            actionLabels: { rename: 'Rename animation', update: 'Overwrite with editor script', del: 'Delete preset', exp: 'Export script' }
        });
    }

    function renderCssPresets() {
        renderPresetGallery({
            presets: CSS_PRESETS, galleryId: 'css-preset-gallery', scrollAreaId: 'css-preset-scroll',
            searchInputId: 'css-search-input', countWrapId: 'css-count-wrap', countId: 'css-count',
            sortVar: typeof activeCssSort !== 'undefined' ? activeCssSort : 'default',
            contentField: 'code', activeRefMap: activeCssRef, loadFnName: 'loadCssPreset',
            emptyMsg: 'Your saved CSS snippets will appear here.',
            noResultsPrefix: 'No snippets match',
            actionFns: { rename: 'requestCssRename', update: 'updateCssSnapshot', del: 'requestCssDelete', exp: 'exportCssSnapshot' },
            actionLabels: { rename: 'Rename snippet', update: 'Overwrite with editor code', del: 'Delete snippet', exp: 'Export CSS' }
        });
    }

    function loadPreset(type, index) {
        flushPendingEdits();
        const isCanvas = type === 'canvas';
        const presets = isCanvas ? CANVAS_PRESETS : CSS_PRESETS;
        const p = presets[index];
        if (!p) return;
        const dm = getActiveDataMode();
        if (isCanvas) {
            themeData[dm].canvasEnabled = true;
            themeData[dm].canvasScript = p.script;
            if ($('canvas-fx-editor')) $('canvas-fx-editor').value = p.script;
            activeCanvasRef[dm] = index;
        } else {
            themeData[dm].customCssEnabled = true;
            themeData[dm].customCSS = p.code;
            if ($('custom-css-editor')) $('custom-css-editor').value = p.code;
            activeCssRef[dm] = index;
        }
        commitChange();
        showToast('Loaded ' + p.name);
    }
    window.loadCanvasPreset = (index) => loadPreset('canvas', index);
    window.loadCssPreset = (index) => loadPreset('css', index);

    // The colors the grid shows now, which a lock pins
    let _lastActiveVars = {};

    // The grid is rebuilt on every palette change, so its listeners sit on
    // the container
    function setupVariableGridDelegation() {
        const grid = document.getElementById('variable-grid');
        if (!grid) return;

        // Live while dragging; the undo point lands on change
        grid.addEventListener('input', (e) => {
            const picker = e.target.closest('.var-picker');
            if (!picker) return;
            const dm = getActiveDataMode();
            const varName = picker.dataset.var;
            themeData[dm].overrides[varName] = picker.value;
            themeData[dm].locks[varName] = true;
            commitChange({ clearRef: false, push: false });
        });

        grid.addEventListener('change', (e) => {
            if (!e.target.closest('.var-picker')) return;
            pushState();
        });

        grid.addEventListener('click', (e) => {
            const lock = e.target.closest('.var-lock');
            if (lock) {
                const dm = getActiveDataMode();
                const varName = lock.dataset.var;
                const isLocked = (themeData[dm].locks || {})[varName];

                if (isLocked) {
                    themeData[dm].locks[varName] = false;
                } else {
                    themeData[dm].locks[varName] = true;
                    themeData[dm].overrides[varName] = _lastActiveVars[varName];
                }
                commitChange({ clearRef: false });
                return;
            }

            const reset = e.target.closest('.var-reset');
            if (reset) {
                const varName = reset.dataset.var;
                const dm = getActiveDataMode();

                if (themeData[dm].locks) {
                    themeData[dm].locks[varName] = false;
                }
                if (themeData[dm].overrides) {
                    if (isModeAtDefault(dm)) {
                        delete themeData[dm].overrides[varName];
                    } else {
                        const step = parseInt(varName.split('-').pop());
                        themeData[dm].overrides[varName] = getDefaultColorForStep(dm, step);
                    }
                }

                commitChange({ clearRef: false });
                showToast(`Reset ${varName.split('-').pop()} to default`);
            }
        });
    }

    // The Accent Colors row: one swatch per accent, showing the color in use.
    // An automatic one follows the hue and chroma and says Auto; a picked one
    // is pinned like a locked variable until ⟲ sets it back to automatic.
    // Built once and updated in place, so a picker in use is never replaced.
    function renderAccentGrid(config, dataMode) {
        const grid = $('accent-grid');
        if (!grid) return;
        if (grid.childElementCount !== ACCENT_FIELDS.length) {
            grid.innerHTML = ACCENT_FIELDS.map(a => `
            <div class="var-item" data-accent-item="${a.key}">
                <button type="button" class="plain-button var-name" data-copy-accent="${a.cssVar}" style="font-size: 0.6rem;" data-tooltip="Copy var(${a.cssVar})" aria-label="Copy var(${a.cssVar})">${a.label}</button>
                <div class="var-controls">
                    <button type="button" class="plain-button var-reset" data-accent="${a.key}" data-tooltip="Back to automatic" aria-label="Set ${a.label} back to automatic">⟲</button>
                    <div class="var-picker-wrap">
                        <span class="var-picker-aa"></span>
                        <input type="color" class="var-picker" data-accent="${a.key}" aria-label="${a.label} color">
                    </div>
                </div>
            </div>`).join('');
        }
        const vars = accentVars(config, dataMode);
        let custom = 0;
        ACCENT_FIELDS.forEach(a => {
            const item = grid.querySelector(`[data-accent-item="${a.key}"]`);
            if (!item) return;
            const set = _accentHex(config[a.key]);
            if (set) custom++;
            const hex = set || oklchToHex(vars[a.cssVar]);
            item.classList.toggle('is-locked', !!set);
            const reset = item.querySelector('.var-reset');
            reset.style.visibility = set ? '' : 'hidden';
            const aa = item.querySelector('.var-picker-aa');
            aa.textContent = set ? '' : 'Auto';
            aa.style.color = getEffectiveLightness(hex) > 0.45 ? 'rgba(0,0,0,0.7)' : 'rgba(255,255,255,0.8)';
            const picker = item.querySelector('.var-picker');
            if (picker !== document.activeElement || !set) picker.value = hex;
            picker.dataset.tooltip = set ? hex.toUpperCase() : `Automatic: ${hex.toUpperCase()}`;
        });
        const val = $('val-accents');
        if (val) val.innerText = custom ? `${custom} set` : 'Auto';
    }

    function setupAccentGridDelegation() {
        const grid = $('accent-grid');
        if (!grid) return;
        // Live while dragging, like the variable pickers; the undo point
        // lands on change
        grid.addEventListener('input', (e) => {
            const picker = e.target.closest('.var-picker[data-accent]');
            if (!picker) return;
            themeData[getActiveDataMode()][picker.dataset.accent] = _accentHex(picker.value);
            commitChange({ clearRef: false, push: false });
        });
        grid.addEventListener('change', (e) => {
            if (!e.target.closest('.var-picker[data-accent]')) return;
            pushState();
        });
        grid.addEventListener('click', (e) => {
            const reset = e.target.closest('.var-reset[data-accent]');
            if (reset) {
                themeData[getActiveDataMode()][reset.dataset.accent] = '';
                commitChange({ clearRef: false });
                const a = ACCENT_FIELDS.find(f => f.key === reset.dataset.accent);
                showToast(`${a ? a.label : 'Accent'} is automatic again`);
                return;
            }
            const name = e.target.closest('[data-copy-accent]');
            if (name) {
                const text = `var(${name.dataset.copyAccent})`;
                navigator.clipboard.writeText(text).then(() => showToast(`Copied ${text}`));
            }
        });
    }

    // Double-click on the row's label
    function resetAccents() {
        const dm = getActiveDataMode();
        if (ACCENT_FIELDS.every(({ key }) => !_accentHex(themeData[dm][key]))) return;
        ACCENT_FIELDS.forEach(({ key }) => { themeData[dm][key] = ''; });
        commitChange({ clearRef: false });
        showToast('Accents are automatic again');
    }

    function renderVariableGrid(config, activeVars) {
        const grid = document.getElementById('variable-grid');
        if (!grid) return;

        _lastActiveVars = activeVars;
        // Not under a color picker in use: rebuilding replaced it mid-drag,
        // which closed it and lost its change event (and the undo point).
        // The grid catches up on the next change once focus moves on.
        const activeEl = document.activeElement;
        if (activeEl && activeEl.classList && activeEl.classList.contains('var-picker') && grid.contains(activeEl)) return;

        setHtmlKeepingFocus(grid, Object.entries(activeVars).map(([name, val]) => {
            const isLocked = (config.locks || {})[name] === true;
            const hex = oklchToHex(val);
            return `
            <div class="var-item ${isLocked ? 'is-locked' : ''}" data-item="${name}">
                <button type="button" class="plain-button var-name" data-control="copy" style="font-size: 0.6rem; cursor: pointer;" 
                      onmouseover="this.style.color='var(--accent)'" 
                      onmouseout="this.style.color='var(--text-muted)'" 
                      onclick="navigator.clipboard.writeText('${baseStepName(name)}: ${hex};').then(()=>showToast('Copied ${baseStepName(name)}: ${hex};'))" 
                      data-tooltip="Copy ${baseStepName(name)}: ${hex};" aria-label="Copy ${baseStepName(name)}: ${hex};">
                    ${name.split('-').pop()}
                </button>
                <div class="var-controls">
                    <button type="button" class="plain-button var-lock" data-control="lock" data-var="${name}" data-tooltip="${isLocked ? 'Unlock variable' : 'Lock current color'}" aria-label="Lock ${name}" aria-pressed="${isLocked}">
                        ${isLocked ? ICONS.lockClosed : ICONS.lockOpen}
                    </button>
                    <button type="button" class="plain-button var-reset" data-control="reset" data-var="${name}" data-tooltip="Reset variable to default" aria-label="Reset ${name} to default">
                        ⟲
                    </button>
                    <div class="var-picker-wrap">
                        <span class="var-picker-aa" style="color:${getEffectiveLightness(hex) > 0.45 ? 'rgba(0,0,0,0.7)' : 'rgba(255,255,255,0.8)'}">Aa</span>
                        <input type="color" class="var-picker" data-var="${name}" value="${hex}" data-tooltip="${hex.toUpperCase()}" aria-label="${name} color">
                    </div>
                </div>
            </div>`;
        }).join(''));
    }

    // One scratch canvas for every oklchToHex call, not 26 new ones per commit
    const _hexCanvas = document.createElement('canvas');
    _hexCanvas.width = 1; _hexCanvas.height = 1;
    const _hexCtx = _hexCanvas.getContext('2d');
    // Resolved-colour memo. oklchToHex sits on the palette repaint path, which
    // runs on every colour-picker drag frame, and getImageData() forces a
    // GPU→CPU readback. The ramp resolves 12 steps per frame and the contrast
    // report reads back several of those same values, so a shared memo makes the
    // report's lookups free instead of adding readbacks. Bounded: a hue drag
    // produces a fresh set of values every frame, so this must not grow forever.
    const _hexMemo = new Map();
    const _HEX_MEMO_MAX = 512;

    function _memoHex(key, compute) {
        const hit = _hexMemo.get(key);
        if (hit !== undefined) return hit;   // null is a real cached value
        const val = compute();
        if (_hexMemo.size >= _HEX_MEMO_MAX) _hexMemo.clear();
        _hexMemo.set(key, val);
        return val;
    }

    // #rgb, #rgba, #rrggbb and #rrggbbaa → #rrggbb, alpha dropped as
    // oklchToHex drops it. parseHex() slices fixed offsets, so any other form
    // would parse to NaN and every consumer of it would read as unknown.
    function _expandHex(h) {
        if (/^#[0-9a-fA-F]{3,4}$/.test(h)) return '#' + h.slice(1, 4).split('').map(c => c + c).join('');
        if (/^#(?:[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$/.test(h)) return h.slice(0, 7);
        return h;
    }

    function oklchToHex(str) {
        if (str.startsWith('#')) return _expandHex(str);
        return _memoHex(str, () => {
            // clearRect first: on the reused canvas a translucent value would
            // composite over the previous call's pixel and resolve differently
            // depending on call order
            _hexCtx.clearRect(0, 0, 1, 1);
            _hexCtx.fillStyle = '#000000'; _hexCtx.fillStyle = str;
            _hexCtx.fillRect(0, 0, 1, 1);
            const data = _hexCtx.getImageData(0, 0, 1, 1).data;
            return "#" +[data[0], data[1], data[2]].map(x => x.toString(16).padStart(2, '0')).join('');
        });
    }

    // Resolve for the contrast report: the hex, or null when this browser cannot
    // resolve the value on its own. _cssTok allows var(), which never resolves
    // on a detached canvas, and fillStyle ignores a value it cannot parse, so a
    // single read would score it as the black baseline (a false Fail). A value
    // that parsed reads back the same after two different sentinels; one that
    // did not tracks whichever sentinel preceded it.
    function _resolveReportColor(str) {
        if (!str || typeof str !== 'string') return null;
        if (/^#(?:[0-9a-fA-F]{3,4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$/.test(str)) return _expandHex(str);
        return _memoHex('probe ' + str, () => {
            _hexCtx.fillStyle = '#000000'; _hexCtx.fillStyle = str;
            const first = _hexCtx.fillStyle;
            _hexCtx.fillStyle = '#ffffff'; _hexCtx.fillStyle = str;
            if (first !== _hexCtx.fillStyle) return null;
            return oklchToHex(str);
        });
    }

    // Lightness of an oklch() value on the 0-1 scale; CSS also allows a
    // percentage ("oklch(14.5% 0 0)"), which parseFloat alone read as 14.5.
    function _oklchL(colorStr) {
        const tok = colorStr.replace(/^oklch\(\s*/, '').split(/[\s/)]/)[0];
        const v = parseFloat(tok);
        return tok.endsWith('%') ? v / 100 : v;
    }

    function getEffectiveLightness(colorStr) {
        if (!colorStr) return 0.20;
        if (colorStr.startsWith('oklch(')) {
            return _oklchL(colorStr);
        } else if (colorStr.startsWith('#')) {
            return getLuminance(colorStr);
        }
        return 0.20;
    }

    // What CSS rewrites must leave alone: escapes, comments, strings and url
    // tokens, where :root or html is text, not a selector
    const CSS_OPAQUE_TOKEN = /\\[\s\S]|\/\*[\s\S]*?(?:\*\/|$)|"(?:[^"\\\n]|\\[\s\S])*(?:"|(?=\n)|$)|'(?:[^'\\\n]|\\[\s\S])*(?:'|(?=\n)|$)|\burl\((?![ \t\n]*["'])[^)]*\)?/gi;

    // css with rewrite() applied only outside those tokens
    function rewriteSelectors(css, rewrite) {
        const kept = [];
        // A U+0001 of the CSS's own becomes a space, not nothing: dropped, it
        // joined u\u0001rl( into url(
        const masked = css.replace(/\u0001/g, ' ').replace(CSS_OPAQUE_TOKEN, t => '\u0001' + (kept.push(t) - 1) + '\u0001');
        return rewrite(masked).replace(/\u0001(\d+)\u0001/g, (m, i) => kept[i]);
    }

    function buildCustomCss(modeData, selector) {
        if (!modeData.customCSS || modeData.customCssEnabled === false) return '';
        // Sanitize: neutralize any marker comment sequences to prevent
        // spoofing the /*[OWUI_*]*/ markers used for auth-page CSS stripping
        const cssText = modeData.customCSS.replace(/\/\*\[OWUI_/g, '/* [OWUI_');
        if (modeData.autoScope) {
            const { keyframes, cleanedCss } = extractKeyframes(cssText);
            // :root and html both mean the page root, which the scope
            // selector already is; nested as descendants they'd never match
            const scoped = rewriteSelectors(cleanedCss, c => c.replace(/:root/gi, '&')
                .replace(/(^|[\s,{};(])html(?=[\s.,:\[#{>+~)]|$)/gim, '$1&'));
            return `\n/*[OWUI_CUSTOM_START]*/\n/* Custom CSS (Auto-Scoped) */\n${selector} {\n${scoped}\n}\n${keyframes}\n/*[OWUI_CUSTOM_END]*/\n`;
        }
        const scoped = rewriteSelectors(cssText, c => c.replace(/:root/gi, `:is(${selector})`));
        return `\n/*[OWUI_CUSTOM_START]*/\n/* Custom CSS (Raw) */\n${scoped}\n/*[OWUI_CUSTOM_END]*/\n`;
    }

    function extractKeyframes(css) {
        let keyframes = '';
        let cleanedCss = css;
        // Scan a copy with comments, strings and escapes blanked to spaces
        // (same length, so indices line up): a "@keyframes" or brace inside a
        // comment is not CSS, \{ opens no block and \" no string. An
        // unbalanced block (still being typed, or a bare mention) ends the
        // scan and stays where it is.
        let shadow = css.replace(CSS_OPAQUE_TOKEN, m => ' '.repeat(m.length));
        let from = 0;
        let startIndex = shadow.indexOf('@keyframes', from);

        while (startIndex !== -1) {
            let openBraces = 0;
            let i = startIndex;
            let started = false;
            let end = -1;
            while (i < shadow.length) {
                if (shadow[i] === '{') { openBraces++; started = true; }
                else if (shadow[i] === '}') { openBraces--; }

                i++;
                if (started && openBraces === 0) { end = i; break; }
            }
            if (end === -1) break;
            keyframes += cleanedCss.substring(startIndex, end) + '\n';
            // A space where the block was: joined, the text around it made
            // new tokens, such as u@keyframes a{}rl( becoming url(
            cleanedCss = cleanedCss.substring(0, startIndex) + ' ' + cleanedCss.substring(end);
            shadow = shadow.substring(0, startIndex) + ' ' + shadow.substring(end);
            from = startIndex;
            startIndex = shadow.indexOf('@keyframes', from);
        }
        return { keyframes, cleanedCss };
    }

