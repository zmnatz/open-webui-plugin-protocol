    // --- Open WebUI's own backgrounds ---
    // A person's Chat Background Image, or a model's or folder's own
    // background image, covers this theme's background in its chats. Each
    // slider sets how much of one shows while this theme is in use. Folders
    // belong to each person, so only a personal theme lists them.
    (function hiddenBackgroundsList() {
        const list = $('hidden-bg-list');
        const note = $('hidden-bg-note');
        if (!list || !note) return;
        const personal = (window.__THEME_PRO_CONFIG__ || {}).scope === 'me';
        note.textContent = personal
            ? "Your Chat Background Image, and models and folders with a background image of their own, cover this theme in their chats. Each slider sets that image's opacity while you use this theme: at 100% it shows as Open WebUI shows it, at 0% it's hidden. It applies in every mode."
            : "Each person's Chat Background Image, and models with a background image of their own, cover this theme in their chats. Each slider sets that image's opacity for everyone using the instance theme: at 100% it shows as Open WebUI shows it, at 0% it's hidden. It applies in every mode. Folders belong to each person, so each sets theirs in their own theme.";
        let found = null;
        let chatImage = null;

        function getJson(url) {
            const headers = { Accept: 'application/json' };
            if (authToken()) headers.Authorization = `Bearer ${authToken()}`;
            return fetch(url, { headers }).then(r => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json(); });
        }

        async function load() {
            const items = [];
            try {
                const settings = await getJson('/api/v1/users/user/settings');
                chatImage = (settings && settings.ui && settings.ui.backgroundImageUrl) || null;
            } catch (e) {}
            try {
                const res = await getJson('/api/models');
                (Array.isArray(res) ? res : res.data || []).forEach(m => {
                    const image = m && m.info && m.info.meta && m.info.meta.background_image_url;
                    if (image) items.push({ kind: 'models', id: m.id, name: m.name || m.id, image });
                });
            } catch (e) {}
            if (personal) {
                try {
                    // The folder list leaves out each folder's image, so each
                    // folder is read, a few at a time
                    const queue = (await getJson('/api/v1/folders/')).slice();
                    await Promise.all(Array.from({ length: 4 }, async () => {
                        while (queue.length) {
                            const f = queue.shift();
                            try {
                                const full = await getJson(`/api/v1/folders/${encodeURIComponent(f.id)}`);
                                const image = full && full.meta && full.meta.background_image_url;
                                if (image) items.push({ kind: 'folders', id: f.id, name: full.name || f.name || f.id, image });
                            } catch (e) {}
                        }
                    }));
                } catch (e) {}
            }
            found = items;
            render();
        }

        function shareOf(item) {
            if (item.kind === 'chat') return hiddenBackgrounds.chat;
            if (item.kind === 'auth') return hiddenBackgrounds.auth ? hiddenBackgrounds.auth.share : 100;
            if (item.kind === 'pages') return hiddenBackgrounds.pages ? hiddenBackgrounds.pages.share : 100;
            const shares = hiddenBackgrounds[item.kind];
            return Object.prototype.hasOwnProperty.call(shares, item.id) ? shares[item.id] : 100;
        }

        function kindLabel(item) {
            if (item.kind === 'auth') return item.image ? 'Before sign-in' : 'Before sign-in, none set';
            if (item.kind === 'pages') {
                const where = 'Workspace, Notes, Calendar, Channels and the other pages without a chat';
                const p = hiddenBackgrounds.pages;
                if (!p) return `${where}, none set`;
                if (p.source === 'chat') return `${where}, showing ${personal ? 'your' : "each person's own"} Chat Background Image`;
                return where;
            }
            if (item.kind === 'chat') return personal ? (item.image ? 'Interface setting' : 'Interface setting, none set') : "Each person's own";
            return (item.kind === 'models' ? 'Model' : 'Folder') + (item.image ? '' : ', no image now');
        }

        function row(item) {
            const el = document.createElement('div');
            el.className = 'hidden-bg-row';
            const thumb = document.createElement('span');
            thumb.className = 'hidden-bg-thumb';
            if (item.image) thumb.style.backgroundImage = `url("${String(item.image).replace(/["\\]/g, '\\$&')}")`;
            const name = document.createElement('span');
            name.className = 'hidden-bg-name';
            name.textContent = item.name;
            const kind = document.createElement('span');
            kind.className = 'hidden-bg-kind';
            kind.textContent = kindLabel(item);
            const share = shareOf(item);
            const slider = document.createElement('input');
            slider.type = 'range';
            slider.min = '0';
            slider.max = '100';
            slider.step = '5';
            slider.value = String(share);
            slider.className = 'hidden-bg-slider';
            slider.dataset.bgKind = item.kind;
            slider.dataset.bgId = item.id;
            slider.setAttribute('aria-label', `Opacity of ${item.name}`);
            if (item.kind === 'auth' && !item.image) slider.disabled = true;
            if (item.kind === 'pages' && !hiddenBackgrounds.pages) slider.disabled = true;
            const value = document.createElement('span');
            value.className = 'hidden-bg-val';
            value.textContent = `${share}%`;
            const text = document.createElement('span');
            text.className = 'hidden-bg-text';
            text.append(name, kind);
            const head = document.createElement('div');
            head.className = 'hidden-bg-head';
            head.append(thumb, text);
            const label = document.createElement('span');
            label.className = 'hidden-bg-label';
            label.textContent = 'Opacity';
            const controls = document.createElement('div');
            controls.className = 'hidden-bg-controls';
            controls.append(label, slider, value);
            el.append(head, controls);
            return el;
        }

        function authRow() {
            const a = hiddenBackgrounds.auth;
            const el = row({ kind: 'auth', id: 'auth', name: 'Sign-in page', image: a ? a.url : null });
            el.classList.add('is-auth');
            const actions = document.createElement('div');
            actions.className = 'hidden-bg-auth-actions';
            actions.innerHTML =
                '<button type="button" class="btn" data-auth="upload">Upload picture</button>' +
                '<input type="file" accept="image/png,image/jpeg,image/gif,image/webp" data-auth="file" hidden>' +
                '<input type="text" class="modal-input hidden-bg-auth-url" data-auth="url" placeholder="https://example.com/sign-in.jpg" aria-label="Sign-in picture address">' +
                '<button type="button" class="btn" data-auth="use">Use URL</button>' +
                (a ? '<button type="button" class="btn btn-danger" data-auth="remove">Remove</button>' : '') +
                '<span class="hidden-bg-auth-status" data-auth="status" role="status"></span>';
            if (a && !isAuthUpload(a)) actions.querySelector('[data-auth="url"]').value = a.url;
            el.append(actions);
            return el;
        }

        function pagesRow() {
            const p = hiddenBackgrounds.pages;
            const image = !p ? null : p.source === 'chat' ? chatImage : p.url;
            const el = row({ kind: 'pages', id: 'pages', name: 'Other pages', image });
            el.classList.add('is-auth');
            const actions = document.createElement('div');
            actions.className = 'hidden-bg-auth-actions';
            actions.innerHTML =
                `<button type="button" class="btn" data-pages="chat">${personal ? 'Use my Chat Background Image' : "Use each person's Chat Background Image"}</button>` +
                '<button type="button" class="btn" data-pages="upload">Upload picture</button>' +
                '<input type="file" accept="image/png,image/jpeg,image/gif,image/webp" data-pages="file" hidden>' +
                '<input type="text" class="modal-input hidden-bg-auth-url" data-pages="url" placeholder="https://example.com/background.jpg" aria-label="Other pages picture address">' +
                '<button type="button" class="btn" data-pages="use">Use URL</button>' +
                (p ? '<button type="button" class="btn btn-danger" data-pages="remove">Remove</button>' : '') +
                '<span class="hidden-bg-auth-status" data-pages="status" role="status"></span>';
            if (p && p.source === 'url' && !isPagesUpload(p)) actions.querySelector('[data-pages="url"]').value = p.url;
            el.append(actions);
            return el;
        }

        // An upload replaces the one file the published theme shows. It waits
        // on the library queue so a reload for another tab's save lets it finish.
        const DRAFT_UPLOAD_NOTE = 'Uploads replace the published picture at once. Publish first, then upload.';
        // A choice made while the upload waits wins: one before the upload
        // starts skips it, and one after deletes the file it wrote unless the
        // theme still shows an uploaded picture
        function queueUpload(kind, url, picked, status, apply) {
            const choice = ++_pictureChoice[kind];
            const headers = { 'Content-Type': picked.type || 'application/octet-stream' };
            if (authToken()) headers.Authorization = `Bearer ${authToken()}`;
            _libQueue = _libQueue.then(async () => {
                if (choice !== _pictureChoice[kind]) return;
                if (_draftMode) { status.textContent = DRAFT_UPLOAD_NOTE; return; }
                try {
                    const r = await fetch(url, { method: 'POST', headers, body: picked });
                    const j = await r.json().catch(() => ({}));
                    if (!r.ok || !authUrlOk(j.url)) throw new Error(j.error || `HTTP ${r.status}`);
                    if (choice === _pictureChoice[kind]) apply(j);
                    else if (!_draftMode && !(kind === 'auth' ? isAuthUpload(hiddenBackgrounds.auth) : isPagesUpload(hiddenBackgrounds.pages))) await deleteUpload(url);
                } catch (err) {
                    status.textContent = `Couldn't upload it: ${err.message || err}`;
                }
            });
        }

        function setPages(next) {
            hiddenBackgrounds = { ...hiddenBackgrounds, pages: next };
            commitChange({ clearRef: false, push: false });
            render();
        }

        function setAuth(next) {
            hiddenBackgrounds = { ...hiddenBackgrounds, auth: next };
            commitChange({ clearRef: false, push: false });
            render();
        }

        function render() {
            list.textContent = '';
            if (!found) {
                list.innerHTML = '<div class="hidden-bg-note">Looking for background images…</div>';
                return;
            }
            const items = found.slice().sort((a, b) => a.kind.localeCompare(b.kind) || a.name.localeCompare(b.name));
            // A changed one whose image is gone stays listed, so it can be set back
            ['models', 'folders'].forEach(kind => Object.keys(hiddenBackgrounds[kind]).forEach(id => {
                if (!items.some(i => i.kind === kind && i.id === id)) items.push({ kind, id, name: id, image: null });
            }));
            list.appendChild(row({ kind: 'chat', id: 'chat', name: 'Chat Background Image', image: chatImage }));
            list.appendChild(pagesRow());
            items.forEach(item => list.appendChild(row(item)));
            if (!personal) list.appendChild(authRow());
        }

        list.addEventListener('click', async (e) => {
            const btn = e.target.closest('button[data-auth]');
            if (!btn) return;
            const actions = btn.closest('.hidden-bg-auth-actions');
            const status = actions.querySelector('[data-auth="status"]');
            const keep = hiddenBackgrounds.auth ? hiddenBackgrounds.auth.share : 100;
            if (btn.dataset.auth === 'upload') {
                if (_draftMode) { status.textContent = DRAFT_UPLOAD_NOTE; return; }
                actions.querySelector('[data-auth="file"]').click();
            } else if (btn.dataset.auth === 'use') {
                const url = actions.querySelector('[data-auth="url"]').value.trim();
                if (!url.startsWith('https://') || !authUrlOk(url)) { status.textContent = 'Use an https:// address with no spaces, quotes or brackets.'; return; }
                dropAuthUpload(hiddenBackgrounds.auth);
                setAuth({ url, share: keep });
            } else if (btn.dataset.auth === 'remove') {
                dropAuthUpload(hiddenBackgrounds.auth);
                setAuth(null);
            }
        });
        // The picture chosen with a row's Upload picture, `kind` being its
        // data-auth or data-pages attribute
        function onPictureFile(kind, uploadUrl, apply) {
            list.addEventListener('change', async (e) => {
                const file = e.target.closest(`input[data-${kind}="file"]`);
                if (!file || !file.files || !file.files[0]) return;
                const status = file.closest('.hidden-bg-auth-actions').querySelector(`[data-${kind}="status"]`);
                const picked = file.files[0];
                file.value = '';
                if (_draftMode) { status.textContent = DRAFT_UPLOAD_NOTE; return; }
                if (picked.size > 5 * 1024 * 1024) { status.textContent = 'The picture is over 5 MB.'; return; }
                status.textContent = 'Uploading…';
                queueUpload(kind, uploadUrl(), picked, status, apply);
            });
        }
        onPictureFile('auth', () => '{ROUTE_BASE}/auth-background', (j) => setAuth({ url: j.url, share: hiddenBackgrounds.auth ? hiddenBackgrounds.auth.share : 100 }));
        list.addEventListener('click', (e) => {
            const btn = e.target.closest('button[data-pages]');
            if (!btn) return;
            const actions = btn.closest('.hidden-bg-auth-actions');
            const status = actions.querySelector('[data-pages="status"]');
            const keep = hiddenBackgrounds.pages ? hiddenBackgrounds.pages.share : 100;
            if (btn.dataset.pages === 'upload') {
                if (_draftMode) { status.textContent = DRAFT_UPLOAD_NOTE; return; }
                actions.querySelector('[data-pages="file"]').click();
            } else if (btn.dataset.pages === 'chat') {
                dropPagesUpload(hiddenBackgrounds.pages);
                setPages({ source: 'chat', share: keep });
            } else if (btn.dataset.pages === 'use') {
                const url = actions.querySelector('[data-pages="url"]').value.trim();
                if (!url.startsWith('https://') || !authUrlOk(url)) { status.textContent = 'Use an https:// address with no spaces, quotes or brackets.'; return; }
                dropPagesUpload(hiddenBackgrounds.pages);
                setPages({ source: 'url', url, share: keep });
            } else if (btn.dataset.pages === 'remove') {
                dropPagesUpload(hiddenBackgrounds.pages);
                setPages(null);
            }
        });
        onPictureFile('pages', pagesUploadUrl, (j) => setPages({ source: 'url', url: j.url, share: hiddenBackgrounds.pages ? hiddenBackgrounds.pages.share : 100 }));
        list.addEventListener('input', (e) => {
            const slider = e.target.closest('input[data-bg-kind]');
            if (slider) slider.nextElementSibling.textContent = `${slider.value}%`;
        });
        list.addEventListener('change', (e) => {
            const slider = e.target.closest('input[data-bg-kind]');
            if (!slider) return;
            const kind = slider.dataset.bgKind;
            const share = Number(slider.value);
            if (kind === 'auth') {
                if (hiddenBackgrounds.auth) setAuth({ ...hiddenBackgrounds.auth, share });
                return;
            }
            if (kind === 'pages') {
                if (hiddenBackgrounds.pages) setPages({ ...hiddenBackgrounds.pages, share });
                return;
            }
            if (kind === 'chat') {
                hiddenBackgrounds = { ...hiddenBackgrounds, chat: share };
            } else {
                const shares = { ...hiddenBackgrounds[kind] };
                if (share >= 100) delete shares[slider.dataset.bgId]; else shares[slider.dataset.bgId] = share;
                hiddenBackgrounds = { ...hiddenBackgrounds, [kind]: shares };
            }
            commitChange({ clearRef: false, push: false });
        });

        // One switch for every image: behind the Canvas FX animation, which
        // only does something in a mode that runs one
        const behindBox = $('hidden-bg-behind');
        const behindWhy = $('hidden-bg-behind-why');
        function syncBehind() {
            if (!behindBox) return;
            const mode = themeData[getActiveDataMode()] || {};
            const runs = (window.__THEME_PRO_CONFIG__ || {}).enableCanvasFx !== false && !!mode.canvasEnabled && !!mode.canvasScript;
            behindBox.checked = hiddenBackgrounds.behind;
            behindBox.disabled = !runs;
            behindBox.closest('label').classList.toggle('is-off', !runs);
            if (behindWhy) behindWhy.style.display = runs ? 'none' : '';
            const hint = $('hidden-bg-behind-hint');
            if (hint) hint.style.display = runs ? '' : 'none';
        }
        if (behindBox) {
            behindBox.addEventListener('change', () => {
                hiddenBackgrounds = { ...hiddenBackgrounds, behind: behindBox.checked };
                commitChange({ clearRef: false, push: false });
            });
            document.querySelector('.tab[data-tab="backgrounds"]')?.addEventListener('click', syncBehind);
            document.querySelectorAll('.mode-btn').forEach(b => b.addEventListener('click', () => setTimeout(syncBehind, 0)));
        }

        // One slider for Open WebUI's dimming layer over every image
        const dimBox = $('hidden-bg-dimming');
        const dimVal = $('hidden-bg-dimming-val');
        if (dimBox) {
            dimBox.value = String(hiddenBackgrounds.dimming);
            if (dimVal) dimVal.textContent = `${hiddenBackgrounds.dimming}%`;
            dimBox.addEventListener('input', () => { if (dimVal) dimVal.textContent = `${dimBox.value}%`; });
            dimBox.addEventListener('change', () => {
                hiddenBackgrounds = { ...hiddenBackgrounds, dimming: Number(dimBox.value) };
                commitChange({ clearRef: false, push: false });
            });
        }

        refreshBackgroundsUi = () => {
            if (dimBox) {
                dimBox.value = String(hiddenBackgrounds.dimming);
                if (dimVal) dimVal.textContent = `${hiddenBackgrounds.dimming}%`;
            }
            syncBehind();
            render();
        };

        render();
        load();
        syncBehind();
    })();

