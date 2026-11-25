    // --- AI Consultant ---
    // Describe a theme in words; a model on this instance answers with a hue,
    // chroma and lightness, which become the palette and, when the model
    // suggests one, a matching gradient. Ported from the Theme Designer Pro
    // Tool's apply_theme(), except that it changes only the palette and
    // gradient, so a mode's custom CSS and Canvas FX survive.
    const AiConsultant = (() => {
        const cfg = window.__THEME_PRO_CONFIG__ || {};
        let modal = null;

        function hslToHex(hue, sat, lit) {
            sat /= 100; lit /= 100;
            const f = n => {
                const k = (n + hue / 30) % 12;
                return lit - sat * Math.min(lit, 1 - lit) * Math.max(-1, Math.min(k - 3, 9 - k, 1));
            };
            const toHex = v => Math.round(v * 255).toString(16).padStart(2, '0');
            return '#' + toHex(f(0)) + toHex(f(8)) + toHex(f(4));
        }

        // The Tool's four-stop gradient for a hue.
        function gradientStops(hue) {
            return [
                { color: hslToHex(hue, 15, 4), position: 0 },
                { color: hslToHex(hue, 25, 12), position: 33 },
                { color: hslToHex(hue, 20, 7), position: 66 },
                { color: hslToHex(hue, 15, 4), position: 100 },
            ];
        }

        function apply(theme, modes) {
            const withGradient = theme.gradient && cfg.enableGradientBuilder !== false;
            modes.forEach(m => {
                const md = themeData[m];
                if (!md) return;
                md.h = theme.hue;
                md.c = theme.chroma;
                md.l = m === 'oled' ? 0 : theme.lightness;
                md.paletteEnabled = true;
                if (withGradient) {
                    md.gradientEnabled = true;
                    md.gradientType = 'linear';
                    md.gradientAngle = 135;
                    md.gradientStops = gradientStops(theme.hue);
                    md.gradientIntensity = 100;
                    activeGradientRef[m] = null;
                }
                activeThemeRef[m] = null;
            });
            commitChange({ clearRef: false });
            const name = theme.name || `H ${theme.hue}° C ${theme.chroma} L ${theme.lightness}`;
            if (withGradient && modes.some(m => themeData[m] && customCssHidesGradient(themeData[m]))) {
                showToast(`✨ ${name}: palette applied. The gradient is saved too, but your Custom CSS Snippet sets its own background, so it won't show. See the Gradient tab.`, 8000);
                return;
            }
            showToast(`✨ ${name}${withGradient ? ' — palette and gradient' : ' — palette'}. Fine-tune it below.`);
        }

        // Bumped by close(): an answer that lands after Cancel/Escape belongs to
        // a request the admin walked away from and must not repaint the theme.
        let requestSeq = 0;

        function close() {
            requestSeq++;
            if (modal) {
                hideModal(modal.id);
                const go = modal.querySelector('#ai-consult-go');
                if (go) go.disabled = false;
            }
        }

        function build() {
            modal = document.createElement('div');
            modal.className = 'modal-overlay';
            modal.id = 'ai-consult-modal';
            modal.setAttribute('role', 'dialog');
            modal.setAttribute('aria-modal', 'true');
            modal.setAttribute('aria-labelledby', 'ai-consult-title');
            modal.innerHTML =
                '<div class="control-group modal-panel modal-panel-info" style="text-align:left;">' +
                '<div class="section-title" id="ai-consult-title" style="margin-bottom:8px;">AI Consultant</div>' +
                '<p style="font-size:0.75rem;color:var(--text-muted);margin:0 0 14px;line-height:1.6;">Describe the theme you want, like “warm copper” or “calm ocean at night”. A model on this instance picks the colors, and you can fine-tune them after.</p>' +
                '<textarea id="ai-consult-input" class="modal-input" rows="3" maxlength="500" placeholder="A warm copper theme" style="resize:vertical;margin-bottom:12px;"></textarea>' +
                '<label class="toggle-label" style="margin-bottom:14px;"><input type="checkbox" class="cb-input" id="ai-consult-one-mode"> <span id="ai-consult-one-mode-label">Only the mode I\'m editing</span></label>' +
                '<div id="ai-consult-status" role="status" style="font-size:0.72rem;min-height:1.2em;margin-bottom:12px;color:var(--text-muted);"></div>' +
                '<div style="display:flex;gap:12px;"><button class="btn" id="ai-consult-cancel" style="flex:1;">Cancel</button>' +
                '<button class="btn btn-primary" id="ai-consult-go" style="flex:1;">Create theme</button></div>' +
                '</div>';
            document.body.appendChild(modal);
            modal.addEventListener('click', e => { if (e.target === modal) close(); });
            modal.addEventListener('keydown', e => {
                if (e.key === 'Escape') close();
                if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) submit();
            });
            modal.querySelector('#ai-consult-cancel').addEventListener('click', close);
            modal.querySelector('#ai-consult-go').addEventListener('click', submit);
        }

        function submit() {
            const input = modal.querySelector('#ai-consult-input');
            const status = modal.querySelector('#ai-consult-status');
            const go = modal.querySelector('#ai-consult-go');
            if (go.disabled) return;
            const description = input.value.trim();
            if (!description) { status.textContent = 'Describe the theme you want first.'; input.focus(); return; }
            const modes = modal.querySelector('#ai-consult-one-mode').checked ? [getActiveDataMode()] : MODES.slice();
            go.disabled = true;
            status.style.color = 'var(--text-muted)';
            status.textContent = 'Asking the model…';
            const seq = ++requestSeq;
            fetch('{ROUTE_BASE}/consult', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ description })
            }).then(r => r.json().catch(() => ({})).then(d => ({ ok: r.ok, d })))
                .then(({ ok, d }) => {
                    if (seq !== requestSeq) return;
                    go.disabled = false;
                    if (!ok) {
                        status.style.color = 'var(--color-danger)';
                        status.textContent = (d && d.error) || 'The AI Consultant could not answer.';
                        return;
                    }
                    status.textContent = '';
                    close();
                    apply(d, modes);
                })
                .catch(() => {
                    if (seq !== requestSeq) return;
                    go.disabled = false;
                    status.style.color = 'var(--color-danger)';
                    status.textContent = 'The server could not be reached.';
                });
        }

        function open() {
            if (!modal) build();
            const label = modal.querySelector('#ai-consult-one-mode-label');
            label.textContent = 'Only the ' + getActiveDataMode() + ' mode';
            modal.querySelector('#ai-consult-status').textContent = '';
            showModal(modal.id);
            modal.querySelector('#ai-consult-input').focus();
        }

        function init() {
            const btn = document.getElementById('ai-consult-btn');
            if (!btn) return;
            if (!cfg.enableAiConsultant) { btn.remove(); return; }
            btn.addEventListener('click', open);
        }

        return { init, apply };
    })();
    AiConsultant.init();

    // Custom Tooltip Engine
    const tooltipEl = document.createElement('div');
    tooltipEl.className = 'owui-tooltip';
    document.body.appendChild(tooltipEl);
    let activeTooltipTarget = null;
    // Rich-tooltip markup, keyed. Producers rebuild their whole list on every
    // render, so each one clears its own prefix first rather than growing forever.
    const _ttHtmlStore = new Map();
    function _ttRegister(key, html) { _ttHtmlStore.set(key, html); return key; }
    function _ttClearPrefix(prefix) {
        [..._ttHtmlStore.keys()].forEach(k => { if (k.startsWith(prefix)) _ttHtmlStore.delete(k); });
    }

    function showTooltip(el) {
        const target = el.closest('[data-tooltip], [data-tooltip-key]');
        if (!target) return;
        // Rich tooltips are looked up by key, never read back from an
        // attribute: the HTML parser decodes entities in attribute values, so
        // escaped markup would come back live and reach innerHTML
        const htmlContent = _ttHtmlStore.get(target.getAttribute('data-tooltip-key'));
        const text = htmlContent || target.getAttribute('data-tooltip');
        if (!text) return;

        clearTimeout(tooltipEl._richCleanup);
        activeTooltipTarget = target;
        if (htmlContent) {
            tooltipEl.innerHTML = htmlContent;
            tooltipEl.classList.add('rich');
        } else {
            tooltipEl.textContent = text;
            tooltipEl.classList.remove('rich');
        }
        tooltipEl.classList.add('visible');

        if (target.classList.contains('community-card')) {
            tooltipEl.classList.add('multiline');
        } else {
            tooltipEl.classList.remove('multiline');
        }

        const applyTooltipColor = (hex) => {
            tooltipEl.style.background = hex;
            tooltipEl.style.borderColor = 'rgba(255, 255, 255, 0.15)';
            tooltipEl.style.color = (getLuminance(hex) > 0.6) ? '#000000' : '#ffffff';
        };

        if (target.classList.contains('ramp-block')) {
            const hex = target.getAttribute('data-hex') || text.replace('Copy ', '');
            applyTooltipColor(hex);
        } else if (target.classList.contains('var-picker')) {
            const hex = target.value || text;
            applyTooltipColor(hex);
        } else {
            resetTooltipStyles(tooltipEl);
        }

        // Measured at the page's left edge: left where the last tooltip ended,
        // near the right edge it wraps narrower, and was placed for that size
        tooltipEl.style.left = '0px';
        const rect = target.getBoundingClientRect();
        const scrollTop = window.pageYOffset || document.documentElement.scrollTop || document.body.scrollTop || 0;
        const scrollLeft = window.pageXOffset || document.documentElement.scrollLeft || document.body.scrollLeft || 0;

        let top = rect.top + scrollTop - tooltipEl.offsetHeight - 8;
        let left = rect.left + scrollLeft + (rect.width / 2) - (tooltipEl.offsetWidth / 2);

        if (top < scrollTop) top = rect.bottom + scrollTop + 8;
        if (left < scrollLeft) left = scrollLeft + 8;
        if (left + tooltipEl.offsetWidth > window.innerWidth + scrollLeft) {
            left = window.innerWidth + scrollLeft - tooltipEl.offsetWidth - 8;
        }

        tooltipEl.style.top = top + 'px';
        tooltipEl.style.left = left + 'px';
    }
    document.body.addEventListener('mouseover', (e) => showTooltip(e.target));
    // Keyboard focus only: a click focuses too, and mousedown has just hidden it
    document.body.addEventListener('focusin', (e) => { if (e.target.matches(':focus-visible')) showTooltip(e.target); });
    // A control that changes its tooltip while showing it, as the sort button
    // does on Enter, gets no mousedown to hide the old text
    new MutationObserver((records) => {
        if (activeTooltipTarget && tooltipEl.classList.contains('visible') && records.some(r => r.target === activeTooltipTarget)) showTooltip(activeTooltipTarget);
    }).observe(document.body, { subtree: true, attributes: true, attributeFilter: ['data-tooltip'] });

    function scheduleTooltipCleanup() {
        clearTimeout(tooltipEl._richCleanup);
        tooltipEl._richCleanup = setTimeout(() => {
            tooltipEl.classList.remove('rich');
            resetTooltipStyles(tooltipEl);
        }, TIMING.tooltipFade);
    }

    function hideTooltipLeaving(e) {
        if (activeTooltipTarget && !activeTooltipTarget.contains(e.relatedTarget)) {
            tooltipEl.classList.remove('visible');
            activeTooltipTarget = null;
            scheduleTooltipCleanup();
        }
    }
    document.body.addEventListener('mouseout', hideTooltipLeaving);
    document.body.addEventListener('focusout', (e) => { if (activeTooltipTarget && activeTooltipTarget.contains(e.target)) hideTooltipLeaving(e); });

    document.body.addEventListener('mousedown', () => {
        tooltipEl.classList.remove('visible');
        scheduleTooltipCleanup();
    });

    const isModeMatch = (m1, m2) => !!m1 && !!m2 && modeSectionDiffs(m1, m2).length === 0;

    function getVariablesMap(config) {
        const vars = {};
        // Sanitized: this map becomes the palette block of the theme CSS that
        // is served to every user, and config can originate from an imported
        // or auto-updated third-party theme. See the CSS value sanitizers.
        const h = _cssNum(config.h, 0), c = _cssNum(config.c, 0) / 1000, l = _cssNum(config.l, 0) / 100;
        const ov = config.overrides || {};
        steps.forEach(step => {
            const computed = rampStepColor(step, h, c, l);
            const raw = ov[`--color-gray-${step}`];
            vars[`--color-gray-${step}`] = raw ? _cssTok(raw, computed) : computed;
        });
        return vars;
    }

    // Open WebUI's base scale from the palette. Its UI colours are base-*
    // utilities, each reading --app-base-0 to --app-base-1000 (src/tailwind.css
    // on dev after 0.13.4). The ramp gives 50 to 950; the ends follow it the
    // way Open WebUI mixes them from its two seeds, --app-bg and --app-fg: 0
    // is the light end, 1000 the dark one, and in Dark the dark end is the
    // background 60% toward black. The palette keeps its --color-gray-* names
    // in saved themes; those names are set here too, to the base scale, so
    // theme CSS that reads var(--color-gray-*) keeps the theme's colours.
    function baseScaleVars(vars, config, mode) {
        const h = _cssNum(config.h, 0), c = _cssNum(config.c, 0) / 1000, l = _cssNum(config.l, 0) / 100;
        const dark = mode === 'dark' || mode === 'oled';
        const end = (lightness) => `oklch(${Math.max(0, Math.min(1, lightness + (l - 0.20))).toFixed(3)} ${c.toFixed(3)} ${c === 0 ? 0 : h})`;
        const out = { '--app-base-0': end(1) };
        steps.forEach(step => { out[`--app-base-${step}`] = vars[`--color-gray-${step}`]; });
        out['--app-base-1000'] = dark ? `color-mix(in oklab, ${vars['--color-gray-900']}, black 60%)` : end(0);
        out['--app-bg'] = dark ? vars['--color-gray-900'] : out['--app-base-0'];
        out['--app-fg'] = dark ? out['--app-base-0'] : out['--app-base-1000'];
        steps.forEach(step => { out[`--color-gray-${step}`] = `var(--app-base-${step})`; });
        return out;
    }

    // A manual override can name a step the old way (--color-gray-900) or
    // the base scale's way (--app-base-900); both set the base scale.
    function baseStepName(name) { return name.replace(/^--color-gray-(\d+)$/, '--app-base-$1'); }
    function paletteStepKey(name) { return name.replace(/^--app-base-(\d+)$/, '--color-gray-$1'); }

    // A user's own Theme Colors (Settings > General) win over the palette:
    // Open WebUI sets them as --app-bg / --app-fg in <html>'s style
    // attribute, and the base scale is then mixed from them.
    function ownColorsYield(sel) {
        return sel.split(',').map(s => `${s.trim()}:not([style*="--app-bg"])`).join(', ');
    }

    function getDefaultColorForStep(mode, step) {
        return rampStepColor(step, DEFAULT_MODE_DATA.h, DEFAULT_MODE_DATA.c, defaultLightness(mode) / 100);
    }

    function isModeAtDefault(mode) {
        return themeData[mode].h === DEFAULT_MODE_DATA.h && themeData[mode].c === DEFAULT_MODE_DATA.c && themeData[mode].l === defaultLightness(mode);
    }

    function applyBaseColorsToMode(mode, h, c, l) {
        const dataMode = (mode === 'system') ? getActiveDataMode() : mode;
        if (!themeData[dataMode]) return;

        themeData[dataMode].h = h;
        themeData[dataMode].c = c;
        themeData[dataMode].l = l;
        // Wipe unlocked overrides so they fall back to the new slider values
        if (!themeData[dataMode].overrides) themeData[dataMode].overrides = {};
        if (!themeData[dataMode].locks) themeData[dataMode].locks = {};

        Object.keys(themeData[dataMode].overrides).forEach(varName => {
            if (!themeData[dataMode].locks[varName]) {
                delete themeData[dataMode].overrides[varName];
            }
        });
    }

    // A Dark or OLED palette is washed out when the designer's own text has to
    // turn dark to read on it (designerChromeColors)
    function detectWashedOut(dataMode, activeVars) {
        const light = dataMode === 'light' || dataMode === 'her';
        const chrome = light ? null : designerChromeColors(dataMode, activeVars);
        return {
            dark: !!(chrome && chrome.textIsDark),
            light: light && getEffectiveLightness(activeVars['--color-gray-50']) > 0.45
        };
    }

    // WCAG 2.1 AA: text 4.5:1, focus rings and other indicators 3:1
    const CHROME_TEXT_MIN = 4.5, CHROME_INDICATOR_MIN = 3;

    // The first candidate with at least min:1 against every background, or
    // the one closest to it
    function _firstContrasting(candidates, backgrounds, min) {
        let best = null;
        for (const hex of candidates) {
            if (!hex) continue;
            const ratio = Math.min(...backgrounds.map(bg => contrastRatio(hex, bg)));
            if (ratio >= min) return { hex, ratio };
            if (!best || ratio > best.ratio) best = { hex, ratio };
        }
        return best;
    }

    // The designer page's own text, muted text and accent, picked by measured
    // contrast against what they sit on: the page (--bg-deep, gray-900 in Dark
    // and OLED), the tinted panels over it and the dialogs (--bg-surface). Each
    // list starts with the colour the default palette gets, so a palette that
    // passes looks unchanged. No one colour reads on both a mid-gray page and
    // a lighter dialog, so the dialog surface and the panel tint follow the
    // text. null when the page colour only resolves in the live page (a var()
    // override): the designer then keeps its fixed colours.
    function designerChromeColors(dataMode, vars) {
        const dark = dataMode === 'dark' || dataMode === 'oled';
        const deep = _resolveReportColor(vars[dark ? '--color-gray-900' : '--color-gray-50']);
        if (!deep) return null;
        const own = step => _resolveReportColor(vars[`--color-gray-${step}`]);
        const LIGHT_TEXT = ['#fafafa', '#ffffff'], DARK_TEXT = ['#18181b', '#000000'];
        const main = _firstContrasting(dark ? [own(50), ...LIGHT_TEXT, ...DARK_TEXT] : [...DARK_TEXT, ...LIGHT_TEXT], [deep], CHROME_TEXT_MIN);
        const textIsDark = relativeLuminance(main.hex) < relativeLuminance(deep);
        const tint = textIsDark ? 'rgba(255, 255, 255, 0.55)' : 'rgba(0, 0, 0, 0.45)';
        const panel = _resolveReportColor(textIsDark ? `color-mix(in srgb, #ffffff 55%, ${deep})` : `color-mix(in srgb, #000000 45%, ${deep})`);
        const surface = _firstContrasting(dark ? [own(850), deep] : ['#ffffff', deep], [main.hex], CHROME_TEXT_MIN).hex;
        const elevated = dark ? _firstContrasting([own(800), surface], [main.hex], CHROME_TEXT_MIN).hex : null;
        const backgrounds = [deep, panel, surface].filter(Boolean);
        const muted = _firstContrasting([
            ...(dark && !textIsDark ? [own(400)] : []),
            ...(textIsDark ? ['#52525b', '#3f3f46', '#27272a'] : ['#a1a1aa', '#d4d4d8', '#e4e4e7']),
            main.hex
        ], backgrounds, CHROME_TEXT_MIN);
        const accents = ['#3b82f6', ...(textIsDark
            ? ['#2563eb', '#1d4ed8', '#1e40af', '#1e3a8a', '#172554']
            : ['#60a5fa', '#93c5fd', '#bfdbfe'])];
        // Text on the page and its panels (slider values, the open tab);
        // borders, rings and icons on the dialogs
        const page = [deep, panel].filter(Boolean);
        const minOn = (hex, bgs) => Math.min(...bgs.map(bg => contrastRatio(hex, bg)));
        let accent = _firstContrasting(accents.filter(hex => contrastRatio(hex, surface) >= CHROME_INDICATOR_MIN), page, CHROME_TEXT_MIN);
        if (!accent || accent.ratio < CHROME_TEXT_MIN) accent = _firstContrasting(accents, backgrounds, CHROME_INDICATOR_MIN);
        // The knob of a switch that is on sits on the accent
        const knob = _firstContrasting(['#ffffff', '#18181b'], [accent.hex], CHROME_INDICATOR_MIN);
        return {
            textIsDark, tint, backgrounds: { deep, panel, surface, elevated }, knob,
            textMain: { hex: main.hex, ratio: minOn(main.hex, [...backgrounds, elevated].filter(Boolean)) },
            textMuted: muted,
            accent: { hex: accent.hex, ratio: minOn(accent.hex, backgrounds), textRatio: minOn(accent.hex, page) }
        };
    }

    // Every --name: value declaration on one manual-override line, as
    // [{ name, value }]; the single parser behind both the shipped CSS and the
    // contrast report. Whole /* */ comments are dropped first and a line with
    // an unclosed one is rejected: !important appended after a trailing
    // comment loses to the palette, and an unclosed comment swallows every
    // rule after it, in the CSS every user receives.
    // Declarations are split on top-level semicolons only, so a data: URL's
    // ";base64," stays inside its url().
    function _overrideDecls(line) {
        let trimmed = String(line == null ? '' : line).trim();
        if (!trimmed || trimmed.startsWith('/*') || trimmed.startsWith('//') || trimmed.startsWith('*')) return [];
        if (!trimmed.startsWith('--')) return [];
        // Comments out, strings left as written ("/*" inside quotes is text)
        let clean = '', q = '';
        for (let i = 0; i < trimmed.length; i++) {
            const ch = trimmed[i];
            if (q) {
                clean += ch;
                if (ch === '\\' && i + 1 < trimmed.length) clean += trimmed[++i];
                else if (ch === q) q = '';
                continue;
            }
            if (ch === '"' || ch === "'") { q = ch; clean += ch; continue; }
            if (ch === '/' && trimmed[i + 1] === '*') {
                const end = trimmed.indexOf('*/', i + 2);
                if (end === -1) return [];
                clean += ' ';
                i = end + 1;
                continue;
            }
            if (ch === '*' && trimmed[i + 1] === '/') return [];
            clean += ch;
        }
        trimmed = clean.trim();
        // Block CSS scope breakout: reject lines containing braces, and lines
        // with an unclosed ( or [, which swallow every rule after them (a value
        // split over two lines leaves one on the first)
        if (/[{}]/.test(trimmed)) return [];
        if (!_parensBalanced(trimmed) ||
            !_parensBalanced(trimmed.replace(/[()]/g, '').replace(/\[/g, '(').replace(/\]/g, ')'))) return [];
        const parts = [];
        let depth = 0, quote = '', start = 0;
        for (let i = 0; i < trimmed.length; i++) {
            const ch = trimmed[i];
            if (quote) { if (ch === '\\') i++; else if (ch === quote) quote = ''; continue; }
            if (ch === '"' || ch === "'") quote = ch;
            else if (ch === '(' || ch === '[') depth++;
            else if (ch === ')' || ch === ']') depth--;
            else if (ch === ';' && depth === 0) { parts.push(trimmed.slice(start, i)); start = i + 1; }
        }
        if (quote) return [];
        parts.push(trimmed.slice(start));
        const out = [];
        parts.forEach(p => {
            p = p.trim();
            if (!p.startsWith('--')) return;
            const c = p.indexOf(':');
            if (c < 3) return;
            const name = p.slice(0, c).trim();
            // A value already marked !important would get it twice, which makes
            // the declaration invalid
            const value = p.slice(c + 1).trim().replace(/\s*!\s*important\s*$/i, '')
                // Neutralize marker comment sequences inside quoted values
                .replace(/\/\*\[(OWUI_|FX\])/g, '/* [$1');
            // A custom property name is an identifier: no quotes, comments
            // or punctuation that could carry a marker into the CSS
            if (/^--[\w\-\u0080-\uFFFF]+$/.test(name) && value) out.push({ name, value });
        });
        return out;
    }

    // The palette values that actually SHIP, which is what a contrast report has
    // to measure. getVariablesMap alone misses two things generateThemeSections
    // does:
    //   - paletteEnabled === false emits the mode's DEFAULT ramp, not the admin's
    //     h/c/l, so scoring the sliders would describe a palette nobody receives.
    //   - manual overrides are injected after the palette with !important, so
    //     they win outright: an --app-base-900 (or the old --color-gray-900)
    //     set there is the colour rated.
    function _shippedVars(config, dataMode) {
        let vars;
        if (config.paletteEnabled === false) {
            vars = {};
            steps.forEach(step => { vars[`--color-gray-${step}`] = getDefaultColorForStep(dataMode, step); });
        } else {
            vars = getVariablesMap(config);
        }
        let overridden = 0;
        if (config.manualOverridesEnabled && config.manualOverrides && config.manualOverrides.trim()) {
            config.manualOverrides.split('\n').forEach(line => {
                // Every declaration on the line, as the shipped CSS has them
                _overrideDecls(line).forEach(p => {
                    // hasOwnProperty, not `in`: only real palette steps, never an
                    // inherited key like __proto__ smuggled in through an override.
                    const key = paletteStepKey(p.name);
                    if (Object.prototype.hasOwnProperty.call(vars, key)) {
                        vars[key] = p.value;
                        overridden++;
                    }
                });
            });
        }
        return { vars, overridden, usingDefaults: config.paletteEnabled === false };
    }

    // The text/background pairs Open WebUI actually renders, expressed in the
    // gray steps the palette controls. These mirror the bg/text mapping in
    // generateThemeSections: dark & oled read text from the light end of the
    // ramp on dark backgrounds; light & her do the reverse. Body and sidebar are
    // the two backgrounds the generated CSS sets directly (bgBody / bgSidebar);
    // the elevated-surface row covers the steps Open WebUI's own components pull
    // from the ramp. Each row names its steps so the comparison is checkable
    // rather than something the admin has to take on trust.
    function _contrastPairs(dataMode) {
        const dark = (dataMode === 'dark' || dataMode === 'oled');
        const g = n => `--color-gray-${n}`;
        return [
            { label: 'Main text on background', fg: dark ? g(50) : g(950), bg: dark ? g(900) : g(50) },
            { label: 'Muted text on background', fg: dark ? g(400) : g(600), bg: dark ? g(900) : g(50) },
            { label: 'Main text on elevated surfaces', fg: dark ? g(50) : g(950), bg: dark ? g(850) : g(100) },
            { label: 'Main text on sidebar', fg: dark ? g(50) : g(950), bg: dark ? g(950) : g(50) },
        ];
    }

    // Report the palette's own contrast — the admin's colour choices, resolved
    // exactly as the ramp resolves them. It is deliberately measured against
    // the SOLID palette background: with a Canvas FX or gradient background
    // active the visible backdrop is an animation WCAG cannot score, and the
    // solid colour is the guaranteed fallback every user still sees.
    function renderContrastReport(config, dataMode, washedOut) {
        const el = $('contrast-report');
        if (!el) return;
        const shipped = _shippedVars(config, dataMode);
        const activeVars = shipped.vars;
        const pairs = _contrastPairs(dataMode);
        let passAA = 0, scored = 0, unknown = 0;
        const rows = pairs.map(p => {
            const fgHex = _resolveReportColor(activeVars[p.fg]);
            const bgHex = _resolveReportColor(activeVars[p.bg]);
            const ratio = (fgHex && bgHex) ? contrastRatio(fgHex, bgHex) : NaN;
            const v = contrastVerdict(ratio);
            const ok = isFinite(ratio);
            if (ok) { scored++; if (v.aa) passAA++; } else { unknown++; }
            const level = !ok ? 'Unknown' : v.aaa ? 'AAA' : v.aa ? 'AA' : v.aaLarge ? 'AA large' : 'Fail';
            const cls = !ok ? 'warn' : v.aa ? 'ok' : v.aaLarge ? 'warn' : 'bad';
            const ratioTxt = ok ? ratio.toFixed(2) + ':1' : '—';
            // An unresolved colour gets no swatch fill — showing it as black
            // would look like a measurement rather than a gap in one.
            const swatchStyle = (fgHex && bgHex)
                ? `background:${_cssTok(bgHex)};color:${_cssTok(fgHex)};`
                : 'background:transparent;color:var(--text-muted);';
            const stepOf = v => String(v).replace('--color-gray-', '');
            return `<div class="contrast-row">
                    <span class="contrast-swatch" style="${swatchStyle}">Aa</span>
                    <span class="contrast-label">${_esc(p.label)}<span class="contrast-steps">${_esc(stepOf(p.fg))} on ${_esc(stepOf(p.bg))}</span></span>
                    <span class="contrast-ratio">${_esc(ratioTxt)}</span>
                    <span class="contrast-badge contrast-${cls}">${_esc(level)}</span>
                </div>`;
        }).join('');
        const total = pairs.length;
        const allAA = scored > 0 && passAA === scored;
        let summaryCls, summaryTxt;
        if (scored === 0) {
            summaryCls = 'warn';
            summaryTxt = 'Contrast could not be measured';
        } else {
            summaryCls = allAA ? 'ok' : (passAA >= scored - 1 ? 'warn' : 'bad');
            summaryTxt = allAA
                ? (unknown ? `${scored} of ${total} pairs measured, all pass AA` : `All ${total} pairs pass AA`)
                : `${passAA}/${scored} measured pairs pass AA`;
        }
        const notes = [];
        if (shipped.usingDefaults) {
            notes.push('The palette is switched off for this mode, so the theme ships this mode’s default ramp. These ratings describe those defaults, not the sliders above.');
        }
        if (shipped.overridden) {
            notes.push(`${shipped.overridden} value${shipped.overridden > 1 ? 's' : ''} above come${shipped.overridden > 1 ? '' : 's'} from <b>Manual Variable Overrides</b>, which take priority over the palette — so ${shipped.overridden > 1 ? 'they are' : 'it is'} what users actually receive.`);
        }
        if (washedOut && (washedOut.dark || washedOut.light)) {
            notes.push('This palette is very washed out — the built-in contrast protection shifts text colour at runtime to keep it legible, so users may see better contrast than the palette alone scores here.');
        }
        if (unknown) {
            notes.push(`${unknown} pair${unknown > 1 ? 's use' : ' uses'} a colour that only resolves inside the live page — such as <code>var(--…)</code> — so ${unknown > 1 ? 'they' : 'it'} cannot be measured here.`);
        }
        const note = notes.length
            ? `<div class="contrast-note">${notes.join('<br><br>')}</div>`
            : '';
        el.innerHTML = `
            <div class="contrast-head">
                <span class="contrast-badge contrast-${summaryCls}">${_esc(summaryTxt)}</span>
                <span class="contrast-sub">WCAG contrast, solid background</span>
            </div>
            ${rows}
            ${note}`;
    }

    function updatePalette() {
        const dm = getActiveDataMode();
        const config = themeData[dm];

        ['h', 'c', 'l'].forEach(k => { if ($(`sl-${k}`)) $(`sl-${k}`).value = config[k]; });
        if ($('val-h')) $('val-h').innerText = config.h + '°';
        if ($('val-c')) $('val-c').innerText = (config.c / 1000).toFixed(2);
        if ($('val-l')) $('val-l').innerText = Math.round(config.l) + '%';

        const lNorm = config.l / 100;
        const preview = $('prev-main');
        if (preview) {
            preview.style.background = `oklch(${lNorm} ${config.c / 1000} ${config.h})`;
            preview.innerHTML = `<span style="color:${lNorm > 0.45 ? 'black' : 'white'}; font-size:10px; font-weight:bold; display:flex; justify-content:center; align-items:center; height:100%;">Aa</span>`;
        }

        const activeVars = getVariablesMap(config);
        // The ramp shows the generated palette, but the washout check reads
        // the values that actually ship (see forceLocalIframeTheme)
        const washedOut = detectWashedOut(dm, _shippedVars(config, dm).vars);
        document.body.classList.toggle('washed-out', washedOut.dark || washedOut.light);

        const gRamp = $('ramp-gray');
        if (gRamp) {
            gRamp.innerHTML = steps.map(s => {
                const rawVal = activeVars[`--color-gray-${s}`];
                const hex = oklchToHex(rawVal);
                let lVal = 0;
                if (rawVal.startsWith('oklch(')) lVal = _oklchL(rawVal);
                else if (rawVal.startsWith('#')) {
                    const r = parseInt(rawVal.slice(1,3), 16), g = parseInt(rawVal.slice(3,5), 16), b = parseInt(rawVal.slice(5,7), 16);
                    lVal = (r*0.299 + g*0.587 + b*0.114) / 255;
                }
                const textColor = lVal > 0.6 ? 'rgba(0,0,0,0.6)' : 'rgba(255,255,255,0.6)';
                return `<button type="button" class="plain-button ramp-block" data-hex="${hex}" style="background: ${rawVal}; color: ${textColor};" onclick="navigator.clipboard.writeText('${hex}').then(()=>showToast('Copied ${hex}'))" data-tooltip="Copy ${hex}" aria-label="Copy ${hex}">${s}</button>`;
            }).join('');
        }

        // Wrapped so a fault in the report can never take down the rest of
        // this repaint
        try { renderContrastReport(config, dm, washedOut); } catch (e) { console.warn('Theme Pro: contrast report failed', e); }

        const syncCheck = (id, val) => { const el = $(id); if (el) el.checked = val; };
        // Each editor is refilled only when its text changed: this runs on every
        // tick of a slider, and a Canvas FX script can be tens of KB
        const syncEditor = (id, text) => { const el = $(id); if (el && el.value !== text) { el.value = text; updateLineNumbers(el); } };
        syncEditor('custom-css-editor', config.customCSS || "");

        syncCheck('toggle-custom-css', config.customCssEnabled !== false);
        syncCheck('toggle-auto-scope', config.autoScope !== false);
        syncCheck('toggle-palette-enabled', !!config.paletteEnabled);
        syncCheck('toggle-theme-auth', config.themeShowAuth !== false);
        syncCheck('toggle-custom-auth', config.customCssShowAuth !== false);
        dimLabel('toggle-theme-auth', config.paletteEnabled);
        dimLabel('toggle-auto-scope', config.customCssEnabled !== false);
        dimLabel('toggle-custom-auth', config.customCssEnabled !== false);

        syncEditor('manual-overrides-editor', config.manualOverrides || "");

        syncCheck('toggle-manual-overrides', !!config.manualOverridesEnabled);

        syncEditor('canvas-fx-editor', config.canvasScript || "");

        syncCheck('toggle-canvas-fx', config.canvasEnabled === true);
        syncCheck('toggle-canvas-auth', config.canvasShowAuth !== false);
        dimLabel('toggle-canvas-auth', config.canvasEnabled);

        const workerBadge = $('canvas-worker-badge');
        const webglBadge = $('canvas-webgl-badge');
        const isActiveCanvas = config.canvasEnabled && config.canvasScript && config.canvasScript.trim() !== '';
        const scriptTags = getCanvasScriptTags(config.canvasScript);
        if (webglBadge) {
            webglBadge.style.display = (isActiveCanvas && scriptTags.webgl) ? 'inline-block' : 'none';
        }
        const contextBadge = $('canvas-context-badge');
        if (contextBadge) {
            contextBadge.style.display = (isActiveCanvas && scriptTags.context) ? 'inline-block' : 'none';
        }
        const themeBadge = $('canvas-theme-badge');
        if (themeBadge) {
            themeBadge.style.display = (isActiveCanvas && scriptTags.theme) ? 'inline-block' : 'none';
        }
        renderCanvasSettings();
        if (workerBadge) {
            if (isActiveCanvas) {
                workerBadge.style.display = 'inline-block';
                const hasOffscreen = typeof HTMLCanvasElement !== 'undefined' && !!HTMLCanvasElement.prototype.transferControlToOffscreen;
                if (scriptTags.isolated) {
                    workerBadge.innerText = hasOffscreen ? 'Isolated Frame' : "Won't Run (No OffscreenCanvas)";
                    workerBadge.style.color = hasOffscreen ? '#818cf8' : '#f87171';
                    workerBadge.style.backgroundColor = hasOffscreen ? 'rgba(129, 140, 248, 0.1)' : 'rgba(248, 113, 113, 0.1)';
                } else if (hasOffscreen) {
                    if (scriptTags.dom) {
                        workerBadge.innerText = 'Main Thread (DOM Access)';
                        workerBadge.style.color = '#60a5fa';
                        workerBadge.style.backgroundColor = 'rgba(96, 165, 250, 0.1)';
                    } else {
                        workerBadge.innerText = 'Background Worker';
                        workerBadge.style.color = '#10b981';
                        workerBadge.style.backgroundColor = 'rgba(16, 185, 129, 0.1)';
                    }
                } else {
                    workerBadge.innerText = 'Main Thread (Fallback)';
                    workerBadge.style.color = '#f59e0b';
                    workerBadge.style.backgroundColor = 'rgba(245, 158, 11, 0.1)';
                }
            } else {
                workerBadge.style.display = 'none';
            }
        }

        renderVariableGrid(config, activeVars);
        renderAccentGrid(config, dm);
        // The current mode's map is passed in so generateThemeSections doesn't
        // compute it again; the sections feed every consumer below
        const sections = generateThemeSections({ [dm]: activeVars });
        const css = assembleThemeCss(sections);
        updateCodeView(css);
        if (shouldInject) injectLive(css, sections);
        else forceLocalIframeTheme(sections);
        updateActiveHighlights();
        renderCanvasPresets();
        renderCssPresets();
        renderGradientTab();
        renderSurfacesTab();
        syncAuthOnlyToggles();
    }

    function updateActiveHighlights() {
        const dm = getActiveDataMode();
        // The card's gallery index, not its position on screen: with a search
        // or sort applied the two differ
        document.querySelectorAll('#snapshot-list .preset-btn').forEach(btn => {
            const i = parseInt(btn.dataset.index, 10);
            const isRef = activeThemeRef[dm] && activeThemeRef[dm].type === 'snapshot' && activeThemeRef[dm].id === i;
            btn.classList.toggle('active-theme', !!isRef);
        });

        // Highlight the resolved data mode when in System mode
        document.querySelectorAll('.mode-btn').forEach(btn => {
            const m = btn.dataset.mode;
            btn.classList.toggle('system-active', activeMode === 'system' && m !== 'system' && m === dm);
        });
    }

    function renderPresetGallery({ presets, galleryId, scrollAreaId, searchInputId, countWrapId, countId,
        sortVar, typeFilter = 'all', typeMatch = null, contentField, activeRefMap, loadFnName, emptyMsg, noResultsPrefix,
        actionFns: { rename, update, del, exp }, actionLabels }) {
        const gallery = $(galleryId);
        const scrollArea = $(scrollAreaId);
        if (!gallery || !scrollArea) return;
        const dm = getActiveDataMode();

        const countWrap = $(countWrapId);
        const countEl = $(countId);

        const searchInput = $(searchInputId);
        const searchQuery = (searchInput ? searchInput.value : '').trim().toLowerCase();
        const typeFiltering = typeFilter && typeFilter !== 'all' && typeof typeMatch === 'function';
        let filtered = presets.map((p, i) => ({ ...p, _origIndex: i }));
        if (searchQuery) {
            filtered = filtered.filter(p => (p.name || '').toLowerCase().includes(searchQuery));
        }
        if (typeFiltering) {
            filtered = filtered.filter(p => typeMatch(p[contentField], typeFilter));
        }
        if (sortVar !== 'default') {
            filtered.sort((a, b) => {
                const nameA = (a.name || '').toLowerCase();
                const nameB = (b.name || '').toLowerCase();
                return sortVar === 'asc' ? nameA.localeCompare(nameB) : nameB.localeCompare(nameA);
            });
        }

        if (countEl) countEl.innerText = (searchQuery || typeFiltering) ? filtered.length + '/' + presets.length : presets.length;
        if (countWrap) countWrap.style.display = presets.length > 0 ? 'inline' : 'none';

        scrollArea.style.display = 'block';
        if (filtered.length === 0) {
            gallery.style.display = 'block';
            const message = presets.length === 0 ? emptyMsg
                : searchQuery ? `${noResultsPrefix} &ldquo;${_esc(searchQuery)}&rdquo;`
                : `${noResultsPrefix} this filter`;
            setGalleryHtml(gallery, `<div class="empty-state">${message}</div>`);
            return;
        }
        gallery.style.display = 'grid';

        const enabledKey = contentField === 'script' ? 'canvasEnabled' : 'customCssEnabled';
        const modeContentKey = contentField === 'script' ? 'canvasScript' : 'customCSS';
        setGalleryHtml(gallery, filtered.map((p) => {
            const i = p._origIndex;
            const isActive = themeData[dm][enabledKey] && themeData[dm][modeContentKey] === p[contentField] && activeRefMap[dm] === i;
            const actions = `
            <button type="button" class="plain-button snapshot-action edit-snapshot" data-control="edit" onclick="event.stopPropagation(); ${rename}(${i})" data-tooltip="${actionLabels.rename}" aria-label="${actionLabels.rename}">✎</button>
            <button type="button" class="plain-button snapshot-action update-snapshot" data-control="update" onclick="event.stopPropagation(); ${update}(${i})" data-tooltip="${actionLabels.update}" aria-label="${actionLabels.update}">💾</button>
            <button type="button" class="plain-button snapshot-action delete-snapshot" data-control="delete" onclick="event.stopPropagation(); ${del}(${i})" data-tooltip="${actionLabels.del}" aria-label="${actionLabels.del}">×</button>
            <button type="button" class="plain-button snapshot-action export-snapshot" data-control="export" onclick="event.stopPropagation(); ${exp}(${i})" data-tooltip="${actionLabels.exp}" aria-label="${actionLabels.exp}">↓</button>
            `;
            return `
            <div class="preset-btn ${isActive ? 'active-theme' : ''}" style="padding: 12px 8px;" data-item="${i}" role="group" aria-label="${_escAttr(p.name)}">
                <button type="button" class="plain-button card-apply" data-control="apply" onclick="${loadFnName}(${i})" aria-label="Load ${_escAttr(p.name)}"></button>
                ${actions}
                <div class="preset-dots" style="background: var(--border); opacity: 0.5;"></div>
                <span style="font-size: 10px; width: 100%; overflow: hidden; text-overflow: ellipsis; text-align: center; white-space: nowrap; display: block;">${_esc(p.name)}</span>
                <div class="selected-check">✓</div>
            </div>
            `;
        }).join(''));
    }

    // A gallery's markup, written only when it changed: the galleries are
    // redrawn on every edit, and most edits (a palette slider) change nothing
    // in them. Every write to a gallery goes through here.
    function setGalleryHtml(gallery, html) {
        if (gallery._tdpHtml === html) return;
        setHtmlKeepingFocus(gallery, html);
        gallery._tdpHtml = html;
    }

    // Rebuilding a list from markup throws away the control that had focus,
    // and the one an open dialog gives focus back to on close. Both move to
    // the same control ([data-control]) of the same item ([data-item]) in the
    // new markup. When the list got shorter (a delete), they move to the
    // first control of the item now in that place.
    function setHtmlKeepingFocus(container, html) {
        const spot = (el) => {
            const item = el && el.dataset && el.dataset.control && el.closest('[data-item]');
            if (!item || !container.contains(item)) return null;
            const items = [...container.querySelectorAll('[data-item]')];
            return { item: item.dataset.item, at: items.indexOf(item), count: items.length, control: el.dataset.control };
        };
        const focused = spot(document.activeElement);
        const openers = openDialogs.map(d => ({ d, spot: spot(d.opener) })).filter(o => o.spot);
        container.innerHTML = html;
        const find = (was) => {
            const items = [...container.querySelectorAll('[data-item]')];
            const same = items.length >= was.count && items.find(i => i.dataset.item === was.item);
            const item = same || items[Math.min(was.at, items.length - 1)];
            if (!item) return null;
            return (same && item.querySelector(`[data-control="${was.control}"]`)) || item.querySelector('[data-control]');
        };
        if (focused) find(focused)?.focus({ preventScroll: true });
        openers.forEach(o => { o.d.opener = find(o.spot) || o.d.opener; });
    }

    // A Canvas FX script's capability badges, for the editor and the Preset
    // Gallery's type filter alike
    function getCanvasScriptTags(script) {
        const s = script || '';
        const code = s.replace(/\/\*[\s\S]*?\*\//g, '').replace(/(^|\s)\/\/.*$/gm, '$1');
        return {
            webgl: /getContext\s*\(\s*['"]webgl/.test(s),
            // The bootloader's tests: readsContext starts the context channel,
            // and `document` picks the main thread
            context: /['"`]context['"`]/.test(code),
            theme: /(?:case|===)\s*['"]theme['"]/.test(s),
            dom: /\bdocument\b/.test(code),
            // The bootloader's test for a script it runs in a sandboxed frame
            isolated: s.startsWith('/* tdp:isolated */'),
        };
    }

