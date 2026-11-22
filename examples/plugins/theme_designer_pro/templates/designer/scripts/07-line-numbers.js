    // --- Line Number Gutter Engine ---
    function setupGutter(textarea) {
        if (textarea._lineGutter) return;
        const parent = textarea.parentElement;
        if (!parent.classList.contains('owui-code-body')) {
            const wrapper = document.createElement('div');
            wrapper.className = 'owui-code-body';
            parent.insertBefore(wrapper, textarea);
            const gutter = document.createElement('div');
            gutter.className = 'owui-line-numbers';
            wrapper.appendChild(gutter);
            wrapper.appendChild(textarea);
            textarea._lineGutter = gutter;
        }
        textarea.addEventListener('scroll', () => {
            textarea._lineGutter.scrollTop = textarea.scrollTop;
        });
    }

    function updateLineNumbers(textarea) {
        const gutter = textarea._lineGutter;
        if (!gutter) return;
        const lines = (textarea.value || '').split('\n');
        const count = Math.max(lines.length, 1);
        if (gutter._lastCount === count) {
            gutter.scrollTop = textarea.scrollTop;
            return;
        }
        gutter._lastCount = count;
        const nums = [];
        for (let i = 1; i <= count; i++) nums.push(i);
        gutter.textContent = nums.join('\n');
        gutter.scrollTop = textarea.scrollTop;
    }

    const bindEditor = (id, propKey) => {
        const editor = document.getElementById(id);
        if (!editor) return;

        setupGutter(editor);

        // The mode AND the text are captured when typed: switching modes
        // refills this editor with the other mode's text, which a timer
        // reading the editor when it fired then saved into the first mode
        const applyEdit = ({ dm, value }) => {
            themeData[dm][propKey] = value;
            activeThemeRef[dm] = null;
            if (propKey === 'canvasScript') activeCanvasRef[dm] = null;
            if (propKey === 'customCSS') activeCssRef[dm] = null;
            commitChange({ clearRef: false, push: false });
            pushStateSoon(editor, 800);
        };
        editor._flushEdit = () => {
            if (!editor._pendingEdit) return;
            clearTimeout(editor._timer);
            const edit = editor._pendingEdit;
            editor._pendingEdit = null;
            applyEdit(edit);
        };
        editor.addEventListener('input', (e) => {
            updateLineNumbers(editor);
            clearTimeout(editor._timer);
            const edit = { dm: getActiveDataMode(), value: e.target.value };
            // Typing in another mode before the last mode's edit was saved
            if (editor._pendingEdit && editor._pendingEdit.dm !== edit.dm) applyEdit(editor._pendingEdit);
            editor._pendingEdit = edit;
            editor._timer = setTimeout(() => {
                editor._pendingEdit = null;
                applyEdit(edit);
            }, 500);
        });

        // Tab inserts spaces until Escape releases it, so keyboard users can
        // still Tab out of the editor
        editor._tabTrapped = true;
        editor.addEventListener('keydown', function(e) {
            if (e.key === 'Escape') {
                this._tabTrapped = !this._tabTrapped;
                return;
            }
            if (e.key === 'Tab' && this._tabTrapped) {
                e.preventDefault();
                const start = this.selectionStart;
                const end = this.selectionEnd;
                this.value = this.value.substring(0, start) + "  " + this.value.substring(end);
                this.selectionStart = this.selectionEnd = start + 2;
                this.dispatchEvent(new Event('input'));
            }

            // Enter keeps the line's indent; after '{' it indents one level
            // more and adds the closing brace unless one already follows
            if (e.key === 'Enter') {
                e.preventDefault();
                const start = this.selectionStart;
                const val = this.value;
                const beforeCursor = val.substring(0, start);
                const afterCursor = val.substring(this.selectionEnd);

                const lines = beforeCursor.split(/\r?\n/);
                const lastLine = lines[lines.length - 1] || '';
                const indentMatch = lastLine.match(/^\s*/);
                const currentIndent = indentMatch ? indentMatch[0] : '';

                let insertText = '\n' + currentIndent;
                let newCursorPos = start + insertText.length;

                if (lastLine.trim().endsWith('{')) {
                    insertText += '  ';
                    newCursorPos = start + insertText.length;
                    if (!afterCursor.trim().startsWith('}')) {
                        insertText += '\n' + currentIndent + '}';
                    }
                }

                this.value = beforeCursor + insertText + afterCursor;
                this.selectionStart = this.selectionEnd = newCursorPos;
                this.dispatchEvent(new Event('input'));
            }

            const pairs = { '{': '}', '[': ']', '(': ')', '"': '"', "'": "'" };
            if (pairs[e.key] && this.selectionStart === this.selectionEnd) {
                e.preventDefault();
                const start = this.selectionStart;
                this.value = this.value.substring(0, start) + e.key + pairs[e.key] + this.value.substring(start);
                this.selectionStart = this.selectionEnd = start + 1;
                this.dispatchEvent(new Event('input'));
            }
        });

        updateLineNumbers(editor);
    };

    // The code blocks bindEditor did not take: the read-only CSS and JSON viewers
    function initLineNumbers() {
        document.querySelectorAll('.owui-code-block textarea').forEach(textarea => {
            if (textarea._lineGutter) return;
            setupGutter(textarea);
            textarea.addEventListener('input', () => updateLineNumbers(textarea));
            updateLineNumbers(textarea);
        });
    }

    bindEditor('custom-css-editor', 'customCSS');
    bindEditor('canvas-fx-editor', 'canvasScript');
    bindEditor('manual-overrides-editor', 'manualOverrides');
    initLineNumbers();

    function clearEditor(editorId, dataKey, extraRef, toastMsg) {
        flushPendingEdits();
        const el = $(editorId);
        if (el && el.value !== '') {
            const dm = getActiveDataMode();
            el.value = '';
            themeData[dm][dataKey] = '';
            activeThemeRef[dm] = null;
            if (extraRef) extraRef[dm] = null;
            commitChange({ clearRef: false });
            showToast(toastMsg);
        }
    }

    document.getElementById('clear-css-btn').addEventListener('click', () => clearEditor('custom-css-editor', 'customCSS', activeCssRef, 'Custom CSS Cleared'));

    const clearManualOverridesBtn = document.getElementById('clear-manual-overrides-btn');
    if (clearManualOverridesBtn) clearManualOverridesBtn.addEventListener('click', () => clearEditor('manual-overrides-editor', 'manualOverrides', null, 'Manual Overrides Cleared'));

    const clearCanvasBtn = document.getElementById('clear-canvas-btn');
    if (clearCanvasBtn) clearCanvasBtn.addEventListener('click', () => clearEditor('canvas-fx-editor', 'canvasScript', activeCanvasRef, 'Canvas Script Cleared'));

    function dimLabel(id, on) {
        const el = $(id);
        const label = el && el.closest('label');
        if (label) label.style.opacity = on ? '1' : '0.35';
    }

    [['toggle-palette-enabled', 'paletteEnabled'],['toggle-custom-css', 'customCssEnabled'],['toggle-auto-scope', 'autoScope'],['toggle-theme-auth', 'themeShowAuth'],['toggle-custom-auth', 'customCssShowAuth'],['toggle-canvas-auth', 'canvasShowAuth'],['toggle-manual-overrides', 'manualOverridesEnabled'],['toggle-gradient-auth', 'gradientShowAuth'],
     ...AUTH_ONLY.map(a => [a[3], a[0]])
    ].forEach(([id, key]) => {
        const el = $(id);
        if (el) el.addEventListener('change', (e) => {
            const dm = getActiveDataMode();
            themeData[dm][key] = e.target.checked;
            // Hidden from the sign-in pages, a part can't be shown only there
            const pair = AUTH_ONLY.find(a => a[1] === key);
            if (pair && !e.target.checked) themeData[dm][pair[0]] = false;
            if (id === 'toggle-palette-enabled') dimLabel('toggle-theme-auth', e.target.checked);
            if (id === 'toggle-custom-css') ['toggle-auto-scope', 'toggle-custom-auth'].forEach(did => dimLabel(did, e.target.checked));
            commitChange();
        });
    });

    const toggleCanvasFx = $('toggle-canvas-fx');
    if (toggleCanvasFx) {
        dimLabel('toggle-canvas-auth', toggleCanvasFx.checked);
        toggleCanvasFx.addEventListener('change', (e) => {
            flushPendingEdits();
            const dm = getActiveDataMode();
            themeData[dm].canvasEnabled = e.target.checked;
            if (e.target.checked && !themeData[dm].canvasScript) {
                themeData[dm].canvasScript = DEFAULT_CANVAS_SCRIPT;
                if ($('canvas-fx-editor')) $('canvas-fx-editor').value = DEFAULT_CANVAS_SCRIPT;
            }
            dimLabel('toggle-canvas-auth', e.target.checked);
            commitChange();
        });
    }

