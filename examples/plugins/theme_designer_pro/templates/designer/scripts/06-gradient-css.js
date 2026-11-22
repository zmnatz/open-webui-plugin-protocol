    // === Gradient CSS Helpers ===
    function hexToRgba(hex, alpha) {
        const tok = _cssTok(hex, '#000000');
        let h = tok.replace('#', '');
        if (h.length === 3) h = h.split('').map(c => c + c).join('');
        // rgb(), oklch() and named colors have no hex channels to read (they
        // gave rgba(NaN, ...), which the browser drops); let it mix them
        if (!/^[0-9a-fA-F]{6}$/.test(h)) return `color-mix(in srgb, ${tok} ${Math.round(alpha * 100)}%, transparent)`;
        const [r, g, b] = parseHex(h);
        return `rgba(${r}, ${g}, ${b}, ${alpha})`;
    }

    function getDarkestStop(stops) {
        if (!stops || stops.length === 0) return '#000000';
        let darkest = stops[0].color;
        let minLum = Infinity;
        stops.forEach(s => {
            // getLuminance reads six hex digits, so #000 or rgb() would read as
            // NaN and never win; resolve every stop to #rrggbb first
            const hex = _resolveReportColor(s.color);
            if (!hex) return;
            const lum = getLuminance(hex);
            if (lum < minLum) { minLum = lum; darkest = s.color; }
        });
        return darkest;
    }

    function adjustHexIntensity(hex, intensity) {
        // Stop colors come straight from theme data, so they can be any
        // value. Intensity only means anything for hex; everything else
        // passes through, sanitized by _cssTok.
        const tok = _cssTok(hex, '#000000');
        let h = tok.replace('#', '');
        if (h.length === 3) h = h.split('').map(c => c + c).join('');
        if (!/^[0-9a-fA-F]{6}$/.test(h)) return tok;
        let [r, g, b] = parseHex(h);
        const factor = _cssNum(intensity, 100) / 100;
        r = Math.max(0, Math.min(255, Math.round(128 + (r - 128) * factor)));
        g = Math.max(0, Math.min(255, Math.round(128 + (g - 128) * factor)));
        b = Math.max(0, Math.min(255, Math.round(128 + (b - 128) * factor)));
        return '#' + [r, g, b].map(c => c.toString(16).padStart(2, '0')).join('');
    }

    // The bounds validateModeData enforces, so a value that skipped
    // validation still renders within the slider's range
    function gradientSpeed(modeData) {
        const [lo, hi] = _MODE_NUM_BOUNDS.gradientAnimationSpeed;
        return _num(modeData.gradientAnimationSpeed, lo, hi, DEFAULT_MODE_DATA.gradientAnimationSpeed);
    }

    function gradientAnimationCss(modeData) {
        if (!modeData.gradientAnimation) return { animCss: '', keyframesCss: '' };
        return {
            animCss: `  background-size: 300% 300% !important;\n  animation: owui-gradient-shift ${gradientSpeed(modeData)}s ease infinite !important;`,
            keyframesCss: `\n@keyframes owui-gradient-shift {\n  0% { background-position: 0% 50%; }\n  50% { background-position: 100% 50%; }\n  100% { background-position: 0% 50%; }\n}\n`
        };
    }

    function buildGradientStructuralCss({ selector, baseColor, animCss, keyframesCss, comment, bodyBg }) {
        const sidebarRgba = hexToRgba(baseColor, 0.75);
        const sidebarBlur = 'blur(12px)';
        const overlayFrom = hexToRgba(baseColor, 0.7);
        const overlayTo = hexToRgba(baseColor, 0.35);
        return `\n/*[OWUI_GRADIENT_START]*/\n/* ${comment} */\n${selector} body {\n${bodyBg}\n  background-attachment: fixed !important;\n${animCss}\n}\n${selector} body::before { content: none !important; display: none !important; }\n${selector} #chat-container .bg-linear-to-t:not(.bg-cover + div) {\n  background-image: linear-gradient(to top, ${overlayFrom}, ${overlayTo}) !important;\n}\n${selector} #sidebar:not(.h-full) { /*[FX]*/\n  background-color: ${sidebarRgba} !important;\n  backdrop-filter: ${sidebarBlur} !important;\n}\n${selector} #sidebar :is(.sidebar-bg-gradient-to-t, .sidebar-bg-gradient-to-b) {\n  --tw-gradient-from: ${sidebarRgba} !important;\n}\n${selector} #navbar-bg-gradient-to-b {\n  --tw-gradient-from: ${hexToRgba(baseColor, 0.9)} !important;\n  --tw-gradient-via: ${hexToRgba(baseColor, 0.5)} !important;\n}\n${keyframesCss}/*[OWUI_GRADIENT_END]*/\n`;
    }

    function buildGradientCss(modeData, selector) {
        if (!modeData.gradientEnabled) return '';
        const def = DEFAULT_MODE_DATA;

        const gType = modeData.gradientType || def.gradientType;
        const intensity = _cssNum(modeData.gradientIntensity, def.gradientIntensity);

        // === MESH GRADIENT ===
        if (gType === 'mesh') {
            const points = modeData.gradientMeshPoints || [];
            if (points.length < 2) return '';
            // bgColor bypasses adjustHexIntensity (which would normalize it via
            // hex parsing), so it needs sanitizing on its own; the geometry
            // fields are interpolated raw. All of it can come from an imported
            // theme and lands in instance-wide CSS.
            const bgColor = _cssTok(modeData.gradientMeshBgColor, def.gradientMeshBgColor);
            const meshLayers = points.map(p => {
                const c = adjustHexIntensity(p.color, intensity);
                return `radial-gradient(at ${_cssNum(p.x, 50)}% ${_cssNum(p.y, 50)}%, ${c} 0%, transparent ${_cssNum(p.spread, 50)}%)`;
            }).join(', ');
            return buildGradientStructuralCss({
                selector, baseColor: bgColor, ...gradientAnimationCss(modeData),
                comment: 'Mesh Gradient Background',
                bodyBg: `  background-color: ${bgColor} !important;\n  background-image: ${meshLayers} !important;`
            });
        }

        if (!modeData.gradientStops || modeData.gradientStops.length < 2) return '';

        const sortedStops = [...modeData.gradientStops].sort((a, b) => a.position - b.position);
        // adjustHexIntensity sanitizes the stop colors; positions and the
        // shape and size keywords need it here, since they can come from an
        // imported theme too
        const stopsStr = sortedStops
            .map(s => `${adjustHexIntensity(s.color, intensity)} ${_cssNum(s.position, 0)}%`)
            .join(', ');

        let gradientFunc;
        const angle = _cssNum(modeData.gradientAngle, def.gradientAngle);
        if (gType === 'radial') {
            const rShape = _cssTok(modeData.gradientRadialShape, def.gradientRadialShape);
            const rSize = _cssTok(modeData.gradientRadialSize, def.gradientRadialSize);
            const rPosX = _cssNum(modeData.gradientRadialPosX, def.gradientRadialPosX);
            const rPosY = _cssNum(modeData.gradientRadialPosY, def.gradientRadialPosY);
            gradientFunc = `radial-gradient(${rShape} ${rSize} at ${rPosX}% ${rPosY}%, ${stopsStr})`;
        } else if (gType === 'conic') {
            gradientFunc = `conic-gradient(from ${angle}deg, ${stopsStr})`;
        } else {
            gradientFunc = `linear-gradient(${angle}deg, ${stopsStr})`;
        }

        return buildGradientStructuralCss({
            selector, baseColor: getDarkestStop(sortedStops), ...gradientAnimationCss(modeData),
            comment: 'System Gradient Background',
            bodyBg: `  background-image: ${gradientFunc} !important;`
        });
    }

    // The flat CSS (the CSS viewer, /theme.css, localStorage cache). Each
    // section carries its own /*[OWUI_*]*/ markers, so concatenation is enough.
    // 'extra' holds the server's valve-appended rules and is empty here.
    function assembleThemeCss(s) {
        return s.vars + s.structural + s.gradient + s.custom + (s.extra || '');
    }

    function generateCoreCSS(varsCache) {
        return assembleThemeCss(generateThemeSections(varsCache));
    }

    // Generate the theme CSS as structured sections { vars, structural, gradient, custom }.
    // Consumers pick the sections they need instead of regex-slicing the flat blob:
    // the designer page uses vars+custom, the iframe self-theme uses vars only, and
    // the bootloader assembles auth-page CSS from the server-delivered copy.
    function generateThemeSections(varsCache) {
        // varsCache: optional { modeId: varsMap } — pre-computed vars from updatePalette()
        // to avoid recomputing getVariablesMap() for the active mode.

        // Open WebUI's grey utilities, and the elements whose class list
        // starts with one of them: first class, or any later one
        const GREY_UTILS = ['bg-gray-', 'dark:bg-gray-', 'bg-base-', 'dark:bg-base-'];
        const PANEL_UTILS = ['bg-white', ...GREY_UTILS];
        const withUtilClass = (elements, ex, utils) => utils.flatMap(u => elements.flatMap(el =>
            [`${el}[class^="${u}"]${ex}`, `${el}[class*=" ${u}"]${ex}`])).join(', ');

        // The Surfaces tab. Off: nothing, and the instance's Sidebar and
        // Overlay Transparency settings apply. On: these rules, which outrank
        // those settings' rules through the :not() of three IDs no element
        // has (specificity only, it matches everything).
        const buildSurfaceCss = (modeData, scope, dark) => {
            if (!modeData.surfacesEnabled) return '';
            const at = scope + ':not(#tdp-surface#tdp-surface#tdp-surface)';
            const num = (k) => _num(modeData[k], 0, k.endsWith('Blur') ? 40 : 100, DEFAULT_MODE_DATA[k]);
            const fill = (c, o) => o >= 100 ? c : `color-mix(in srgb, ${c} ${o}%, transparent)`;
            const glass = (b) => b > 0 ? `blur(${b}px) saturate(1.2)` : 'none';
            const decl = (bg, b) => `background-color: ${bg} !important; backdrop-filter: ${glass(b)} !important; -webkit-backdrop-filter: ${glass(b)} !important;`;
            const color = (key) => SURFACE_LAYERS.find(l => l.key === key).color[dark ? 0 : 1];
            const pex = ':not(.app):not(.modal):not(#theme-designer-container):not([id^="owui-"]):not([style*="display: contents"]):not(script):not(style)';
            const iex = ':not(button):not(a):not(input):not(select):not(label):not(span):not(svg):not(img):not(.modal *)';
            const tokens = withUtilClass(['div'], iex, PANEL_UTILS);
            // Notes, the calendar, workspace and other pages open as tabs in
            // the side panel; there they are a page, not a panel
            const pageTab = '[id^="chat-panel-page%3A"]';
            const onPage = `:not(#sidebar *):not(#messages-container *):not(#message-input-container *):not(#controls-container *:not(${pageTab} *)):not(#auth-page *)`;
            // Below 768px the Tabs drawer is a dialog outside .app
            const onPages = (sel, tail = '') => `${at} .app :where(${sel})${tail}, ${at} #controls-container ${pageTab} :where(${sel})${tail}`;
            const so = num('surfaceSidebarOpacity');
            let css = `/* --- Surfaces --- */\n`;
            css += `${at} #sidebar:not(.h-full) { ${decl(fill(color('Sidebar'), so), num('surfaceSidebarBlur'))} }\n`;
            css += `${at} #sidebar .sidebar-bg-gradient-to-t, ${at} #sidebar .sidebar-bg-gradient-to-b { display: ${so >= 100 ? 'block' : 'none'} !important; }\n`;
            css += `${at} #message-input-container { ${decl(fill(color('Composer'), num('surfaceComposerOpacity')), num('surfaceComposerBlur'))} }\n`;
            // From 768px each tab, alone or in a split, is the page or chat it
            // shows. Below that the fill goes to the Tabs drawer, whose own
            // solid panel clears so the fill shows.
            const panel = decl(fill(color('Panel'), num('surfacePanelOpacity')), num('surfacePanelBlur'));
            css += `${at} #controls-container:not(.absolute) { ${panel} }\n`;
            css += `${at} :has(> div > #controls-container:not(.absolute)) { background-color: transparent !important; }\n`;
            // Rounded panels on a page stay solid under the background
            // clearing; at 100% and no blur they keep Open WebUI's own look.
            // A chat's messages, the sidebar, the message input and the side
            // panel have their own layers or stay as they are.
            const co = num('surfaceCardsOpacity'), cb = num('surfaceCardsBlur');
            if (co < 100 || cb > 0) {
                // A group of buttons, such as the split Create button, keeps its look
                const cex = ':not(button):not(a):not(input):not(select):not(label):not(span):not(svg):not(img):not(:has(> button:first-child))' + onPage;
                const cards = withUtilClass(['div[class*="rounded"]'], cex, PANEL_UTILS);
                css += `${onPages(cards)} { ${decl(fill(color('Cards'), co), cb)} }\n`;
                // Cards that light up under the pointer still do
                css += `${onPages(cards, '[class*="hover:bg-"]:hover')} { background-color: ${fill(color('Cards'), Math.min(100, co + 10))} !important; }\n`;
            }
            // Grey buttons and button groups on a page, at 100% and no blur
            // Open WebUI's own. Switches show on and off by their fill. Black
            // and white action buttons (Save, Send) can carry grey classes
            // too; their text gives them away: white in Light mode, dark in Dark.
            const bo = num('surfaceButtonsOpacity'), bb = num('surfaceButtonsBlur');
            if (bo < 100 || bb > 0) {
                const bex = '[class*="rounded"]:not([role="switch"]):not([role="checkbox"])' +
                    ':not([class^="text-white"]):not([class*=" text-white"]):not([class*="dark:text-black"]):not([class*="dark:text-gray-9"]):not([class*="dark:text-gray-8"]):not([class*="dark:text-base-9"]):not([class*="dark:text-base-8"])' + onPage;
                const btn = withUtilClass(['button', 'div:has(> button:first-child)'], bex, GREY_UTILS);
                css += `${onPages(btn)} { ${decl(fill(color('Buttons'), bo), bb)} }\n`;
                css += `${onPages(btn, '[class*="hover:bg-"]:hover')} { background-color: ${fill(color('Buttons'), Math.min(100, bo + 15))} !important; }\n`;
            }
            css += `${at} .app-dropdown-menu, ${at} .tippy-box, ${at} [data-sonner-toast], ${at} body > div${pex} :where(${tokens}) { ${decl(fill(color('Menu'), num('surfaceMenuOpacity')), num('surfaceMenuBlur'))} }\n`;
            css += `${at} .modal > div:where([class*="bg-white"], [class*="bg-gray-"], [class*="bg-base-"]) { ${decl(fill(color('Dialog'), num('surfaceDialogOpacity')), num('surfaceDialogBlur'))} }\n`;
            // Overlay Transparency also tints the pieces inside a dialog; hand
            // them back to Open WebUI's own classes, which sit in a cascade layer
            const inner = withUtilClass(['div'], '', PANEL_UTILS);
            css += `${at} .modal > div :where(${inner}) { background-color: revert-layer !important; backdrop-filter: revert-layer !important; -webkit-backdrop-filter: revert-layer !important; }\n`;
            css += `${at} .modal { ${decl(`rgb(0 0 0 / ${num('surfaceBackdropOpacity')}%)`, num('surfaceBackdropBlur'))} }\n`;
            const fo = num('surfaceFadeOpacity');
            css += `${at} #navbar-bg-gradient-to-b { display: ${fo > 0 ? 'block' : 'none'} !important; opacity: ${fo / 100} !important; }\n`;
            return css;
        };

        const getBgRules = (mode, selector, bgBody, bgSidebar) => {
            // Your own message bubble stays: cleared, its text floats on the canvas.
            // Rounded controls (the message input, pill buttons) and everything
            // inside the message input keep their fill too: they hide almost
            // none of the canvas, so clearing them only changed their look.
            const gEx = ':not(button):not(a):not(input):not(select):not(label):not(span):not(.chat-user *)' +
                ':not([class*="rounded"]):not(#message-input-container *)';
            const gWhere = withUtilClass([''], gEx, GREY_UTILS);
            const config = themeData[mode];
            const hasCanvas = config.canvasEnabled && config.canvasScript && config.canvasScript.trim();
            const hasGradient = config.gradientEnabled && (
                (config.gradientType === 'mesh' && config.gradientMeshPoints && config.gradientMeshPoints.length >= 2) ||
                (config.gradientType !== 'mesh' && config.gradientStops && config.gradientStops.length >= 2)
            );
            if (hasCanvas || hasGradient) {
                // The code block header is the one sticky element with content
                // scrolling under it; cleared, its label sits on top of the code.
                // A file tab's code editor paints its own --editor-bg.
                // The marker names the backgrounds the clearing is for, so the
                // bootloader and the Enable Canvas FX valve can drop it where
                // none of them shows.
                const clear = 'OWUI_CLEAR_' + [hasCanvas && 'CANVAS', hasGradient && 'GRADIENT'].filter(Boolean).join('_');
                return `
${selector} body { background-color: var(${bgBody}) !important; }
/*[${clear}_START]*/
${hasCanvas ? `${selector} #owui-theme-bg-color { background-color: transparent !important; }` : ''}
${selector} .app, ${selector} #theme-designer-container, ${selector} #auth-container { background-color: transparent !important; background-image: none !important; position: relative; }
${selector} .app > div, ${selector} #theme-designer-container > *, ${selector} #auth-page > div, ${selector} main { background-color: transparent !important; background-image: none !important; }
${selector} .app :where(${gWhere}) { background-color: transparent !important; background-image: none !important; }
${selector} #theme-designer-container :where(${gWhere}) { background-color: transparent !important; background-image: none !important; }
${selector} #auth-page :where(${gWhere}):where(:not(#auth-login-card *)) { background-color: transparent !important; background-image: none !important; }
${selector} .app :where(nav, .sticky:not([class*="bg-black"]), [class*="bg-gradient"]:not(.sidebar-bg-gradient-to-t):not(.sidebar-bg-gradient-to-b), [class*="bg-linear-to"]:not(.bg-cover + div):not(.sidebar-bg-gradient-to-t):not(.sidebar-bg-gradient-to-b):not(#navbar-bg-gradient-to-b)) { background-color: transparent !important; background-image: none !important; }
${selector} .app .file-code-editor { --editor-bg: transparent !important; }
/*[${clear}_END]*/
${selector} #sidebar:not(.h-full) { /*[FX]*/ background-color: var(${bgSidebar}) !important; }
`;
            } else {
                return `
${selector} body { background-color: var(${bgBody}) !important; }
${selector} #sidebar:not(.h-full) { /*[FX]*/ background-color: var(${bgSidebar}) !important; }
`;
            }
        };

        // System mode follows the OS through @media (prefers-color-scheme)
        const wrapSystemMedia = (modeId, contentFn) => {
            if (modeId !== 'dark' && modeId !== 'light') return '';
            const inner = contentFn('html[data-theme="system"], :root[data-theme="system"]');
            if (!inner || !inner.trim()) return '';
            return `@media (prefers-color-scheme: ${modeId}) {\n${inner}\n}\n`;
        };

        // 'scope' is 'sel' as one compound selector, for use in front of a
        // descendant: a selector list there only scopes its last entry and
        // styles <html> itself with the rest. Its specificity equals the
        // data-theme entry that matched descendants before, so precedence
        // against theme custom CSS is unchanged.
        const modes =[
            { id: 'light', name: 'LIGHT MODE', sel: ':root:not(.dark):not(.her):not([data-theme="dark"]):not([data-theme="oled-dark"]):not([data-theme="her"])', scope: ':root:not(.dark):not(.her):not([data-theme="dark"]):not([data-theme="oled-dark"]):not([data-theme="her"])', bgBody: '--color-gray-50', bgSidebar: '--color-gray-50' },
            { id: 'dark', name: 'DARK MODE', sel: 'html.dark:not([data-theme="oled-dark"]), html[data-theme="dark"]', scope: ':is(html[data-theme="dark"], html:where(.dark:not([data-theme="oled-dark"])))', bgBody: '--color-gray-900', bgSidebar: '--color-gray-950' },
            { id: 'oled', name: 'OLED DARK MODE', sel: 'html.dark[data-theme="oled-dark"], html[data-theme="oled-dark"]', scope: 'html[data-theme="oled-dark"]', bgBody: '--color-gray-900', bgSidebar: '--color-gray-950' },
            { id: 'her', name: 'HER MODE', sel: 'html.her, html[data-theme="her"]', scope: ':is(html[data-theme="her"], html:where(.her))', bgBody: '--color-gray-50', bgSidebar: '--color-gray-50' }
        ];

        const formatOverrideLine = (line, indent = '  ') => {
            return _overrideDecls(line).map(d => `${indent}${d.name}: ${d.value} !important;\n`).join('');
        };

        let varsCss = `/*[OWUI_VARS_START]*/\n`;
        modes.forEach(m => {
            const modeTag = m.id.toUpperCase();
            const modeData = themeData[m.id];

            // Palette off still emits the mode's defaults, so OLED keeps its
            // darker greys (l=0) and the others match Open WebUI's @theme
            let vars;
            if (modeData.paletteEnabled === false) {
                vars = {};
                steps.forEach(step => {
                    vars[`--color-gray-${step}`] = getDefaultColorForStep(m.id, step);
                });
            } else {
                vars = (varsCache && varsCache[m.id]) || getVariablesMap(modeData);
            }
            // The accents, palette on or off, so theme CSS can always use them
            vars = { ...vars, ...accentVars(modeData, m.id) };

            varsCss += `/*[OWUI_PAL_${modeTag}_START]*/\n`;
            varsCss += `/* --- ${m.name} VARIABLES --- */\n${m.sel} {\n`;
            Object.entries(vars).forEach(([k, v]) => { varsCss += `  ${k}: ${v} !important;\n`; });
            varsCss += `}\n`;
            varsCss += wrapSystemMedia(m.id, (sel) => {
                let inner = `  ${sel} {\n`;
                Object.entries(vars).forEach(([k, v]) => { inner += `    ${k}: ${v} !important;\n`; });
                inner += `  }`;
                return inner;
            });
            varsCss += `\n/*[OWUI_PAL_${modeTag}_END]*/\n`;

            // After the palette, so the overrides win
            if (modeData.manualOverrides && modeData.manualOverrides.trim() && !!modeData.manualOverridesEnabled) {
                const lines = modeData.manualOverrides.split('\n');
                varsCss += `/* --- ${m.name} MANUAL OVERRIDES --- */\n${m.sel} {\n`;
                lines.forEach(line => { varsCss += formatOverrideLine(line); });
                varsCss += `}\n`;
                varsCss += wrapSystemMedia(m.id, (sel) => {
                    let inner = `  ${sel} {\n`;
                    lines.forEach(line => { inner += formatOverrideLine(line, '    '); });
                    inner += `  }`;
                    return inner;
                });
                varsCss += `\n`;
            }
        });
        varsCss += `/*[OWUI_VARS_END]*/\n\n`;

        let structuralCss = `/*[OWUI_STRUCTURAL_START]*/\n`;
        let gradientCss = '';
        let customCss = '';
        modes.forEach(m => {
            const modeData = themeData[m.id];

            structuralCss += `/* --- ${m.name} Background Overrides --- */\n`;
            structuralCss += getBgRules(m.id, m.scope, m.bgBody, m.bgSidebar);
            structuralCss += wrapSystemMedia(m.id, () => getBgRules(m.id, 'html[data-theme="system"]', m.bgBody, m.bgSidebar));
            const darkMode = m.id === 'dark' || m.id === 'oled';
            structuralCss += buildSurfaceCss(modeData, m.scope, darkMode);
            structuralCss += wrapSystemMedia(m.id, () => buildSurfaceCss(modeData, 'html[data-theme="system"]', darkMode));

            gradientCss += buildGradientCss(modeData, m.scope);
            gradientCss += wrapSystemMedia(m.id, () => buildGradientCss(modeData, ':root[data-theme="system"]'));
            customCss += buildCustomCss(modeData, m.sel);
            customCss += wrapSystemMedia(m.id, () => buildCustomCss(modeData, 'html[data-theme="system"]'));
        });
        structuralCss += `/*[OWUI_STRUCTURAL_END]*/\n`;

        return { vars: varsCss, structural: structuralCss, gradient: gradientCss, custom: customCss };
    }

    // The CSS viewer (the header's CSS button) refreshes only while it's open
    function updateCodeView(preGeneratedCss) {
        const viewer = document.getElementById('css-view-modal');
        if (!viewer || viewer.style.display !== 'flex') return;
        let rawCss = preGeneratedCss || generateCoreCSS();
        if (document.getElementById('toggle-minify-css')?.checked) rawCss = minifyCss(rawCss);
        const rawTextarea = document.getElementById('raw-css');
        if (rawTextarea) { rawTextarea.value = rawCss; updateLineNumbers(rawTextarea); }
    }
    document.getElementById('toggle-minify-css')?.addEventListener('change', () => updateCodeView());
    document.getElementById('css-view-btn')?.addEventListener('click', () => { showModal('css-view-modal'); updateCodeView(); });
    document.getElementById('css-close-btn')?.addEventListener('click', () => hideModal('css-view-modal'));
    
    function forceLocalIframeTheme(sections) {
        const dm = getActiveDataMode();
        const config = themeData[dm];
        // Shipped values, not the raw palette: manual overrides land in the
        // same vars section this page is themed from, so one can light up the
        // background while the palette still reads dark
        const shippedVars = _shippedVars(config, dm).vars;
        const washedOut = detectWashedOut(dm, shippedVars);
        // Measured for the mode being edited, so only that mode's block below
        // takes them; the other keeps the fixed fallbacks
        const chrome = designerChromeColors(dm, shippedVars);
        const isDark = dm === 'dark' || dm === 'oled';
        const dc = isDark ? chrome : null, lc = isDark ? null : chrome;

        const darkTextMain = dc ? dc.textMain.hex : "var(--color-gray-50, #fafafa)";
        const darkTextMuted = dc ? dc.textMuted.hex : "var(--color-gray-400, #a1a1aa)";
        const darkBorder = washedOut.dark ? "rgba(0,0,0,0.2)" : "var(--color-gray-800, oklch(0.26 0 0))";
        const darkBgSurface = dc ? dc.backgrounds.surface : "var(--color-gray-850, oklch(0.23 0 0))";
        const darkBgElevated = dc ? dc.backgrounds.elevated : "var(--color-gray-800, oklch(0.26 0 0))";

        const lightTextMain = lc ? lc.textMain.hex : washedOut.light ? "#18181b" : "var(--color-gray-950, #09090b)";
        const lightTextMuted = lc ? lc.textMuted.hex : washedOut.light ? "#52525b" : "var(--color-gray-600, #52525b)";
        const lightBorder = washedOut.light ? "rgba(0,0,0,0.2)" : "var(--color-gray-200, #e4e4e7)";
        const lightBgElevated = washedOut.light ? "rgba(0,0,0,0.05)" : "var(--color-gray-100, #f4f4f5)";
        const lightBgSurface = lc ? lc.backgrounds.surface : "#ffffff";
        // Fallbacks are the stylesheet's own --accent, --accent-knob and --panel-tint
        const chromeAccentVars = c => c ? `--accent: ${c.accent.hex} !important; --accent-knob: ${c.knob.hex} !important; --panel-tint: ${c.tint} !important;` : '';
        
        // Vars only: the structural, gradient and custom sections target Open
        // WebUI's layout, not this page's
        let iframeCss = (sections || generateThemeSections()).vars;

        // The gradient's body rule, re-targeted to this page's body
        let toolGradientCss = '';
        let toolNeedsTransparentContainer = false;
        try {
            if (config && config.canvasEnabled && config.canvasScript && config.canvasScript.trim()) {
                toolNeedsTransparentContainer = true;
            }
            if (config && config.gradientEnabled) {
                toolNeedsTransparentContainer = true;
                const gradCss = buildGradientCss(config, '');
                const bodyMatch = gradCss.match(/body\s*\{([^}]*background-image[^}]*)\}/);
                if (bodyMatch) {
                    toolGradientCss = `body#tool-body { ${bodyMatch[1]} }`;
                }
            }
        } catch(e) { console.warn('[Theme Pro] Gradient preview error:', e); }

        iframeCss += `
            /* Iframe Self-Theming Overrides */
            html#tool-html, body#tool-body { background-color: var(--bg-deep) !important; }
            ${toolGradientCss}
            ${toolNeedsTransparentContainer ? `
            /* Canvas FX / Gradient: make wrapper transparent so body-level visuals show through */
            #theme-designer-container {
                background: transparent !important;
                isolation: auto !important;
            }
            /* Translucent panels so background effects bleed through */
            #tab-lch .control-group,
            #tab-bg .control-group,
            #tab-backgrounds .control-group,
            #tab-surfaces .control-group,
            #tab-lch .var-item {
                background: var(--panel-tint) !important;
                backdrop-filter: blur(16px) !important;
                -webkit-backdrop-filter: blur(16px) !important;
            }
            ` : ''}
            
            body#tool-body {
                --bg-deep: var(--color-gray-900, oklch(0.20 0 0)) !important;
                --bg-surface: ${darkBgSurface} !important;
                --bg-elevated: ${darkBgElevated} !important;
                --border: ${darkBorder} !important;
                --text-main: ${darkTextMain} !important;
                --text-muted: ${darkTextMuted} !important;
                ${chromeAccentVars(dc)}
            }
            body#tool-body.light-mode {
                --bg-deep: var(--color-gray-50, #f4f4f5) !important;
                --bg-surface: ${lightBgSurface} !important;
                --bg-elevated: ${lightBgElevated} !important;
                --border: ${lightBorder} !important;
                --text-main: ${lightTextMain} !important;
                --text-muted: ${lightTextMuted} !important;
                ${chromeAccentVars(lc)}
            }
        `;
        
        const oldIframeStyle = document.getElementById('iframe-live-theme');
        if (oldIframeStyle) oldIframeStyle.remove();
        const iframeStyle = document.createElement('style');
        iframeStyle.id = 'iframe-live-theme';
        iframeStyle.textContent = iframeCss;
        document.head.appendChild(iframeStyle);
        
        const html = document.documentElement;
        const osDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
        
        if (activeMode === 'system') {
            html.setAttribute('data-theme', 'system');
            applyModeToElement(html, osDark ? 'dark' : 'light');
            // applyModeToElement set the OS mode's data-theme
            html.setAttribute('data-theme', 'system');
        } else {
            applyModeToElement(html, activeMode);
        }

        const isLightUI = (activeMode === 'light' || activeMode === 'her' || (activeMode === 'system' && !osDark));
        document.body.classList.toggle('light-mode', isLightUI);
        document.body.classList.toggle('washed-out', washedOut.dark || washedOut.light);
    }

    function syncParentNativeMode(mode) {
        try {
            const html = document.documentElement;
            if (mode === 'system') {
                html.classList.remove('dark', 'light', 'her');
                html.setAttribute('data-theme', 'system');
            } else {
                applyModeToElement(html, mode);
            }
            // A draft previews the mode in this tab only, never in other tabs
            // or the admin's live session
            if (!_draftMode) {
                localStorage.setItem('theme', MODE_CONFIG[mode]?.dataTheme || mode);
            }
        } catch(e) { console.warn('Theme Pro:', e); }
    }

    // The theme as this page holds it. Saves send this, never a copy read
    // back from storage, whose write can fail (a full or blocked storage)
    // and leave an older theme there.
    function themeStateStr() {
        return JSON.stringify({
            ...themeData,
            _activeThemeRef: activeThemeRef,
            _activeCanvasRef: activeCanvasRef,
            _activeCssRef: activeCssRef,
            _activeGradientRef: activeGradientRef,
            ...(hasHiddenBackgrounds(hiddenBackgrounds) ? { _hiddenBackgrounds: hiddenBackgrounds } : {})
        });
    }

    function injectLive(preGeneratedCss, sections) {
        const s = sections || generateThemeSections();
        const css = preGeneratedCss || assembleThemeCss(s);
        try {
            let liveStyle = document.getElementById('owui-dev-live-theme');
            if (shouldInject) {
                if (!liveStyle) {
                    liveStyle = document.createElement('style');
                    liveStyle.id = 'owui-dev-live-theme';
                    document.head.appendChild(liveStyle);
                }
                // The structural and gradient sections target body, .app and
                // #theme-designer-container, which collide with the designer's
                // own layout; this page previews the gradient through
                // iframe-live-theme instead. Storage and the server still get
                // the full CSS below.
                if (window.__THEME_DESIGNER__ || document.getElementById('theme-designer-container')) {
                    liveStyle.textContent = s.vars + s.custom;
                } else {
                    liveStyle.textContent = css;
                }
                // Live mode leaves the cross-tab css_cache write to the POST
                // response in syncToServer(): the server returns the
                // valve-postprocessed CSS, and the raw CSS here would make other
                // tabs' 'storage' listeners apply opaque /*[FX]*/ sidebar rules
                // for a couple of seconds until the SSE refetch. A draft writes
                // now, since Storage routes it to this tab's sessionStorage.
                if (_draftMode) Storage.setRaw('css_cache', css);
                const stateStr = themeStateStr();
                Storage.setRaw('theme', stateStr);
                // Handed straight to the sync: re-read from localStorage when
                // the debounce fires, another tab's write-through could have
                // replaced it with the server's previous state
                syncToServer(css, s, stateStr);

                const pTheme = localStorage.getItem('theme');
                if (pTheme && document.documentElement.getAttribute('data-theme') !== pTheme) {
                    document.documentElement.setAttribute('data-theme', pTheme);
                }

                if (!document.getElementById('owui-theme-bootloader')) {
                    try {
                        // The designer manages its state directly; the
                        // bootloader's server fetch would race syncToServer
                        if (document.getElementById('theme-designer-container')) {
                            window.__THEME_DESIGNER__ = true;
                        }
                        const bootScript = document.createElement('script');
                        bootScript.id = 'owui-theme-bootloader';
                        const nonceScript = document.querySelector('script[nonce]');
                        if (nonceScript && nonceScript.nonce) bootScript.setAttribute('nonce', nonceScript.nonce);
                        bootScript.textContent = document.getElementById('bootloader-src').textContent;
                        document.head.appendChild(bootScript);
                    } catch(e) { console.warn('[Theme Pro] Could not inject bootloader dynamically:', e); }
                }

                // The state rides in the event, so the bootloader's initCanvas()
                // sees the current script even in a draft, whose sessionStorage
                // its normal read path cannot see
                try {
                    window.dispatchEvent(new CustomEvent('owui-theme-updated', { detail: { state: stateStr, css: css } }));
                } catch(e) { console.warn('Theme Pro:', e); }
            } else if (liveStyle) {
                liveStyle.remove();
            }
        } catch (e) { console.warn('Theme Pro:', e); }
        forceLocalIframeTheme(s);
    }

    // History entries leave the Backgrounds tab out, and a Live reset deletes
    // its uploaded pictures, so Undo of a reset says what it leaves as it is
    function resetBackgrounds() {
        const had = hiddenBackgrounds;
        const authDropped = dropAuthUpload(had.auth);
        const pagesDropped = dropPagesUpload(had.pages);
        hiddenBackgrounds = readHiddenBackgrounds(null);
        refreshBackgroundsUi();
        if (!hasHiddenBackgrounds(had)) return null;
        if (!authDropped && !pagesDropped) return 'Undone. The Backgrounds tab stays reset.';
        return _draftMode
            ? 'Undone. The Backgrounds tab stays reset, and Publish deletes its picture.'
            : 'Undone. The Backgrounds tab stays reset, and its deleted picture can\u2019t come back.';
    }
    function noteUndo(note) {
        if (note) historyStack[historyIndex].undoNote = note;
    }

    function defaultLightness(mode) {
        return mode === 'oled' ? 0 : 20;
    }

    function resetActiveMode(silent = false, saveBackup = false) {
        flushPendingEdits();
        if (!silent && saveBackup) {
            const snapshots = getSnapshots();
            shiftThemeRefs(1);
            snapshots.unshift({
                name: `Backup: Pre-Reset`,
                dark: structuredClone(themeData.dark),
                oled: structuredClone(themeData.oled),
                light: structuredClone(themeData.light),
                her: structuredClone(themeData.her)
            });
            saveSnapshots(snapshots);
        }

        const dm = getActiveDataMode();
        themeData[dm] = createDefaultModeData({ l: defaultLightness(dm) });
        activeThemeRef[dm] = null;
        activeCanvasRef[dm] = null;
        activeCssRef[dm] = null;
        activeGradientRef[dm] = null;
        // The Backgrounds tab has one set of settings for every mode
        const undoNote = resetBackgrounds();
        commitChange({ clearRef: false, snapshots: true });
        noteUndo(undoNote);
        if (!silent) {
            showToast(`${activeMode.charAt(0).toUpperCase() + activeMode.slice(1)} Mode Reset${saveBackup ? ' (Backup Saved)' : ''}.`);
        }
    }

    function nuclearReset(silent = false, saveBackup = false) {
        flushPendingEdits();
        forgetPendingSaves();
        if (!silent && saveBackup) {
            const snapshots = getSnapshots();
            snapshots.unshift({
                name: `Backup: Global Reset`,
                dark: structuredClone(themeData.dark),
                oled: structuredClone(themeData.oled),
                light: structuredClone(themeData.light),
                her: structuredClone(themeData.her)
            });
            saveSnapshots(snapshots);
            // The live refs are cleared below, but undo entries still hold positions
            shiftThemeRefs(1);
        }
        
        shouldInject = true;
        themeData = {
            dark: createDefaultModeData(),
            oled: createDefaultModeData({ l: 0 }),
            light: createDefaultModeData(),
            her: createDefaultModeData()
        };
        activeThemeRef = { dark: null, oled: null, light: null, her: null };
        activeCanvasRef = { dark: null, oled: null, light: null, her: null };
        activeCssRef = { dark: null, oled: null, light: null, her: null };
        activeGradientRef = { dark: null, oled: null, light: null, her: null };
        const undoNote = resetBackgrounds();
        try {
            if (!_draftMode) {
                try {
                    localStorage.removeItem('owui_dev_theme_v1');
                    localStorage.removeItem('owui_dev_theme_v1_css');
                    const el = document.getElementById('owui-dev-live-theme');
                    if (el) el.remove();
                } catch(e) { console.warn('Theme Pro:', e); }
                syncParentNativeMode(activeMode);
            } else {
                // A draft leaves localStorage to the live theme
                const el = document.getElementById('owui-dev-live-theme');
                if (el) el.remove();
            }
            commitChange({ clearRef: false, snapshots: true });
            noteUndo(undoNote);
            if (!silent) showToast(saveBackup ? "All Modes Reset (Backup Saved)." : "All Modes Reset.");
        } catch (e) { console.warn('Theme Pro:', e); }
    }
    
    // Double-click on a base color slider
    window.resetSlider = (key) => {
        const dm = getActiveDataMode();
        const defaults = { h: DEFAULT_MODE_DATA.h, c: DEFAULT_MODE_DATA.c, l: defaultLightness(dm) };
        if (defaults[key] !== undefined) {
            document.getElementById(`sl-${key}`).value = defaults[key];
            document.getElementById(`sl-${key}`).dispatchEvent(new Event('input'));
        }
    };

    /* --- EVENT LISTENERS --- */
    const getActiveDataMode = () => {
        if (activeMode === 'system') {
            return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
        }
        return activeMode;
    };

    // Each mode's classes and data-theme on <html>
    const MODE_CONFIG = {
        dark:   { add: 'dark',  remove: ['light', 'her'], dataTheme: 'dark' },
        oled:   { add: 'dark',  remove: ['light', 'her'], dataTheme: 'oled-dark' },
        her:    { add: 'her',   remove: ['dark', 'light'], dataTheme: 'her' },
        light:  { add: 'light', remove: ['dark', 'her'],  dataTheme: 'light' },
        system: { add: null,    remove: ['dark', 'light', 'her'], dataTheme: 'system' },
    };

    function applyModeToElement(el, mode) {
        const cfg = MODE_CONFIG[mode] || MODE_CONFIG.dark;
        if (cfg.add) el.classList.add(cfg.add);
        cfg.remove.forEach(c => el.classList.remove(c));
        el.setAttribute('data-theme', cfg.dataTheme);
    }

    document.querySelectorAll('.mode-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            document.querySelectorAll('.mode-btn').forEach(b => { b.classList.remove('active'); b.setAttribute('aria-checked', 'false'); });
            btn.classList.add('active');
            btn.setAttribute('aria-checked', 'true');
            activeMode = btn.dataset.mode;
            
            syncParentNativeMode(activeMode);
            updatePalette();
            renderSnapshots();
        });
    });

    window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => {
        if (activeMode === 'system') {
            updatePalette();
            renderSnapshots();
        }
    });
    ['h', 'c', 'l'].forEach(key => {
        const slider = document.getElementById(`sl-${key}`);
        
        slider.addEventListener('input', (e) => {
            const dm = getActiveDataMode();
            applyBaseColorsToMode(activeMode, 
                key === 'h' ? parseFloat(e.target.value) : themeData[dm].h,
                key === 'c' ? parseFloat(e.target.value) : themeData[dm].c,
                key === 'l' ? parseFloat(e.target.value) : themeData[dm].l
            );
            commitChange({ push: false });
        });
        
        slider.addEventListener('change', () => pushState());
        
        // One step per wheel notch
        slider.addEventListener('wheel', (e) => {
            e.preventDefault();
            slider.value = parseFloat(slider.value) + (e.deltaY < 0 ? 1 : -1);
            slider.dispatchEvent(new Event('input'));
            // The wheel doesn't fire 'change'
            pushStateSoon(slider, 400);
        });
    });

    function resetBaseColors(dm) {
        themeData[dm].h = DEFAULT_MODE_DATA.h;
        themeData[dm].c = DEFAULT_MODE_DATA.c;
        themeData[dm].l = defaultLightness(dm);
    }

    document.getElementById('lock-all-btn').addEventListener('click', () => {
        const dm = getActiveDataMode();
        const vars = getVariablesMap(themeData[dm]);
        if (!themeData[dm].locks) themeData[dm].locks = {};
        if (!themeData[dm].overrides) themeData[dm].overrides = {};
        
        Object.keys(vars).forEach(k => {
            themeData[dm].locks[k] = true;
            themeData[dm].overrides[k] = vars[k];
        });
        commitChange({ clearRef: false });
        showToast("Locked all variables");
    });

    document.getElementById('unlock-all-btn').addEventListener('click', () => {
        const dm = getActiveDataMode();
        const vars = getVariablesMap(themeData[dm]);
        if (!themeData[dm].locks) themeData[dm].locks = {};
        
        Object.keys(vars).forEach(k => {
            themeData[dm].locks[k] = false;
        });
        commitChange({ clearRef: false });
        showToast("Unlocked all variables");
    });

    document.getElementById('reset-all-btn').addEventListener('click', () => {
        const dm = getActiveDataMode();
        const vars = getVariablesMap(themeData[dm]);
        const locks = themeData[dm].locks || {};
        const overrides = themeData[dm].overrides || {};
        
        const varKeys = Object.keys(vars);
        const lockedCount = varKeys.filter(k => locks[k] === true).length;
        
        if (lockedCount === varKeys.length) {
            showModal('reset-all-confirm-modal');
            return;
        }
        
        let resetCount = 0;
        varKeys.forEach(k => {
            if (!locks[k]) {
                if (overrides[k] !== undefined) {
                    delete overrides[k];
                    resetCount++;
                }
            }
        });
        
        resetBaseColors(dm);
        
        commitChange({ clearRef: false });
        if (resetCount > 0) {
            showToast(`Reset active mode base & ${resetCount} unlocked overrides to defaults`);
        } else {
            showToast("Reset active mode base to defaults");
        }
    });

    document.getElementById('confirm-reset-all-confirm-btn').addEventListener('click', () => {
        const dm = getActiveDataMode();
        const vars = getVariablesMap(themeData[dm]);
        const locks = themeData[dm].locks || {};
        const overrides = themeData[dm].overrides || {};
        
        Object.keys(vars).forEach(k => {
            locks[k] = false;
            delete overrides[k];
        });
        
        resetBaseColors(dm);
        
        hideModal('reset-all-confirm-modal');
        commitChange({ clearRef: false });
        showToast("Unlocked and reset all variables to defaults");
    });

    // Performance Optimization: Debounce IDE-Grade Behaviors
