    // --- Theme Update System ---
    const MANIFEST_URL = 'https://raw.githubusercontent.com/silentoplayz/theme-designer-pro-presets/main/manifest.json';
    // The Enable Theme Update Checks valve: off, no update request is made.
    const UPDATE_CHECKS = (window.__THEME_PRO_CONFIG__ || {}).enableThemeUpdateChecks !== false;

    // The one URL rewriter: the host this returns is the host the allowlist
    // checks and the host fetched, so a rewrite rule anywhere else would fetch
    // from a host the admin never listed.
    function toRawGitHub(url) {
        if (!url) return url;
        if (typeof url !== 'string') return '';
        const ghBlob = url.match(/^https?:\/\/github\.com\/([^/]+)\/([^/]+)\/blob\/(.+)$/);
        if (ghBlob) return `https://raw.githubusercontent.com/${ghBlob[1]}/${ghBlob[2]}/${ghBlob[3]}`;
        const ghRaw = url.match(/^https?:\/\/github\.com\/([^/]+)\/([^/]+)\/raw\/(.+)$/);
        if (ghRaw) return `https://raw.githubusercontent.com/${ghRaw[1]}/${ghRaw[2]}/${ghRaw[3]}`;
        // gist.github.com/user/id/raw/... already serves raw; a bare gist needs /raw
        const gist = url.match(/^https?:\/\/gist\.github\.com\/([^/]+)\/([a-f0-9]+)\/?$/);
        if (gist) return `https://gist.githubusercontent.com/${gist[1]}/${gist[2]}/raw`;
        return url;
    }

    // Every remote fetch caps its response, or one hostile updateUrl could hang
    // or OOM the admin tab during a "Check for Updates" sweep of the library.
    const MAX_REMOTE_BYTES = 2 * 1024 * 1024;
    // "Install All" and a bundle pasted into an import ship every theme in one
    // document, so they get their own ceiling.
    const MAX_BUNDLE_BYTES = 16 * 1024 * 1024;
    // A host that takes the connection and never answers, or stops halfway,
    // would otherwise leave "Check for Updates" or an import spinning for
    // good. It bounds the wait for the headers and then each gap between
    // chunks, not the whole download, so a slow link still gets a bundle.
    const REMOTE_TIMEOUT_MS = 15000;

    async function readCappedText(res, cap, onChunk) {
        const asMb = n => (n / 1024 / 1024).toFixed(1);
        const declared = parseInt(res.headers.get('content-length') || '0', 10);
        if (declared > cap) throw new Error(`Response too large (${asMb(declared)}MB). Maximum is ${asMb(cap)}MB.`);
        if (!res.body) return '';
        // content-length is optional and can lie, so the bytes are counted as
        // they arrive and the download is dropped at the cap, not after it
        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        let bytes = 0, text = '';
        for (;;) {
            const { done, value } = await reader.read();
            if (done) return text + decoder.decode();
            onChunk();
            bytes += value.byteLength;
            if (bytes > cap) throw new Error(`Response too large (over ${asMb(cap)}MB).`);
            text += decoder.decode(value, { stream: true });
        }
    }

    // Every remote read: the allowlist on the rewritten URL, the host about to
    // be contacted, and again after a redirect, then the time limit and the
    // byte cap.
    async function fetchRemoteText(url, cap = MAX_REMOTE_BYTES) {
        const fetchUrl = toRawGitHub(url);
        assertImportHostAllowed(fetchUrl);
        const host = new URL(fetchUrl, window.location.origin).hostname;
        const ctrl = new AbortController();
        let answered = false, timer;
        const arm = () => {
            clearTimeout(timer);
            timer = setTimeout(() => ctrl.abort(new DOMException('', 'TimeoutError')), REMOTE_TIMEOUT_MS);
        };
        arm();
        try {
            const res = await fetch(fetchUrl, { signal: ctrl.signal });
            answered = true;
            arm();
            // fetch follows redirects, so the check above only proves the FIRST
            // host was allowed. An allowlisted host answering 302 would otherwise
            // deliver a payload from anywhere.
            if (res.redirected) assertImportHostAllowed(res.url);
            if (!res.ok) throw new Error(`HTTP ${res.status}${res.statusText ? ': ' + res.statusText : ''}`);
            return await readCappedText(res, cap, arm);
        } catch (e) {
            if (e && e.name === 'TimeoutError') {
                const secs = REMOTE_TIMEOUT_MS / 1000;
                throw new Error(answered ? `${host} stopped sending for ${secs} seconds.` : `${host} didn't answer within ${secs} seconds.`);
            }
            throw e;
        } finally {
            clearTimeout(timer);
            // Releases the connection on every early exit (a refused redirect,
            // an HTTP error, the cap) instead of leaving the body downloading
            ctrl.abort();
        }
    }

    // Theme Pro's own manifest, catalog and bundle endpoints still go through the
    // allowlist. They are third-party hosts from the instance's point of view:
    // the manifest supplies the updateUrls the update flow then follows, and
    // "Install All" installs whole theme bodies straight from the bundle. An
    // admin who restricts imports to an internal mirror expects that to stop the
    // outbound traffic too, not just the manual button.
    async function fetchGatedJson(url, cap) {
        return JSON.parse(await fetchRemoteText(url, cap));
    }

    // Dotted numbers, with an optional leading "v" and a pre-release tag
    // ("1.2.0-beta.1") that sorts before its release, as in semver. A part
    // that isn't a number counts as 0 instead of making every comparison fail.
    const semverCompare = (a, b) => {
        const parse = (v) => {
            const m = String(v || '0.0.0').trim().replace(/^v/i, '').split('+')[0].match(/^([^-]*)(?:-(.*))?$/);
            return { nums: m[1].split('.').map(n => parseInt(n, 10) || 0), pre: m[2] || '' };
        };
        const pa = parse(a), pb = parse(b);
        for (let i = 0; i < Math.max(pa.nums.length, pb.nums.length); i++) {
            const diff = (pa.nums[i] || 0) - (pb.nums[i] || 0);
            if (diff !== 0) return diff;
        }
        if (pa.pre === pb.pre) return 0;
        if (!pa.pre) return 1;
        if (!pb.pre) return -1;
        const xa = pa.pre.split('.'), xb = pb.pre.split('.');
        for (let i = 0; i < Math.max(xa.length, xb.length); i++) {
            if (xa[i] === undefined) return -1;
            if (xb[i] === undefined) return 1;
            const na = /^\d+$/.test(xa[i]), nb = /^\d+$/.test(xb[i]);
            if (na && nb) { const d = Number(xa[i]) - Number(xb[i]); if (d) return d; }
            else if (na !== nb) return na ? -1 : 1;
            else if (xa[i] !== xb[i]) return xa[i] < xb[i] ? -1 : 1;
        }
        return 0;
    };

    async function fetchManifest() {
        try {
            const data = await fetchGatedJson(MANIFEST_URL);
            if (data.manifestVersion && data.themes) return data;
            return null;
        } catch { return null; }
    }

    async function checkThemeUpdate(index) {
        if (!UPDATE_CHECKS) return null;
        const snapshots = getSnapshots();
        const snap = snapshots[index];
        if (!snap || !snap.updateUrl) return null;

        try {
            const remote = await fetchThemeData(snap.updateUrl);
            const localVer = snap.version || '0.0.0';
            const remoteVer = remote.version || '0.0.0';

            if (semverCompare(remoteVer, localVer) > 0) {
                if (isUpdateIgnored(snap.updateUrl, localVer, remoteVer)) return null; // user dismissed this transition
                return { index, local: snap, remote, localVersion: localVer, remoteVersion: remoteVer };
            }
            return null; // up to date
        } catch(e) {
            console.error(`Update check failed for "${snap.name}":`, e);
            return { index, error: e.message, local: snap };
        }
    }

    async function checkUpdatesViaManifest(snapshots) {
        if (!UPDATE_CHECKS) return null;
        const manifest = await fetchManifest();
        if (!manifest) return null; // manifest unavailable, caller should fall back

        const manifestByUrl = new Map();
        for (const entry of Object.values(manifest.themes)) {
            manifestByUrl.set(toRawGitHub(entry.updateUrl), entry);
            manifestByUrl.set(entry.updateUrl, entry);
        }

        const results = [];
        const unmatched = []; // indices not found in manifest

        for (let i = 0; i < snapshots.length; i++) {
            const snap = snapshots[i];
            if (!snap.updateUrl) continue;

            const rawLocal = toRawGitHub(snap.updateUrl);
            const manifestEntry = manifestByUrl.get(rawLocal) || manifestByUrl.get(snap.updateUrl);

            if (!manifestEntry) {
                // Not in manifest — will need per-theme fallback
                unmatched.push(i);
                continue;
            }

            const localVer = snap.version || '0.0.0';
            const remoteVer = manifestEntry.version || '0.0.0';

            if (semverCompare(remoteVer, localVer) > 0) {
                if (isUpdateIgnored(snap.updateUrl, localVer, remoteVer)) {
                    results.push(null); // user dismissed this transition
                } else {
                    // Update available — but we don't have the full theme data yet.
                    // Store the updateUrl so we can fetch it when user clicks "Update".
                    results.push({
                        index: i,
                        local: snap,
                        remote: null, // will be fetched on-demand
                        remoteUpdateUrl: manifestEntry.updateUrl,
                        localVersion: localVer,
                        remoteVersion: remoteVer,
                        viaManifest: true
                    });
                }
            } else {
                results.push(null); // up to date
            }
        }

        return { results, unmatched };
    }

    // The host gate for every remote theme fetch, including the ones the admin
    // doesn't type a URL for (community installs, update checks): an admin who
    // restricts imports to their own host expects an installed theme not to
    // pull new code from a third party either.
    //
    // Checked AFTER toRawGitHub(), so the host tested is the host contacted,
    // and again on res.url after a redirect: fetch follows redirects, and an
    // allowlisted host answering 302 was seen delivering a payload from an
    // arbitrary origin. An unparseable URL is refused rather than fetched.
    function assertImportHostAllowed(rawUrl) {
        const allow = ((window.__THEME_PRO_CONFIG__ || {}).allowedImportDomains || [])
            // URL.hostname is always lowercased by the parser, so an admin who
            // types "Raw.GithubUserContent.com" would otherwise block every
            // import with a misleading "not in the allowed list" error.
            .map(d => String(d || '').trim().toLowerCase()).filter(Boolean);
        if (!allow.length) return;  // Empty valve = no restriction, as documented
        let hostname;
        try { hostname = new URL(rawUrl, window.location.origin).hostname.toLowerCase(); }
        catch (e) { throw new Error('Invalid URL'); }
        const ok = allow.some(d => hostname === d || hostname.endsWith('.' + d));
        if (!ok) throw new Error(`Domain "${hostname}" is not in the allowed import list. Allowed: ${allow.join(', ')}`);
    }

    async function fetchThemeData(updateUrl) {
        const remote = await fetchGatedJson(updateUrl);
        if (!remote.dark || !remote.light) throw new Error('Invalid theme format');
        return remote;
    }

    window.applyManifestUpdate = async function(index, updateUrl, opts) {
        try {
            showToast('Downloading theme update...');
            const remote = await fetchThemeData(updateUrl);
            // applyThemeUpdate asks for the confirmation, for every update path
            return applyThemeUpdate(index, remote, opts);
        } catch(e) {
            showToast(`Error: ${e.message}`);
            return false;
        }
    };

