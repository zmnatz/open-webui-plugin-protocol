(function () {
    'use strict';
    if (window.__owuiTdpAdminPage) return;
    window.__owuiTdpAdminPage = true;

    // The instance designer as a page of the Admin Panel, in its top bar
    // between Functions and Settings. The bar only renders for admins.
    var SRC = '__THEME_ROUTE__?embed=admin';
    var LABEL = 'Themes';
    // The bar's links carry these while they aren't the open page.
    // Open WebUI's UI greys are text-base-* after 0.13.4 (text-gray-* through 0.13.4);
    // the bar's own dimmed links say which this instance uses.
    var DIM_GRAY = ['text-gray-300', 'dark:text-gray-600', 'hover:text-gray-700', 'dark:hover:text-white'];
    var DIM_BASE = ['text-base-300', 'dark:text-base-600', 'hover:text-base-700', 'dark:hover:text-white'];
    var DIM = DIM_GRAY;
    function pickDim(row) {
        if (row.querySelector('a[class*="text-base-"]')) DIM = DIM_BASE;
        else if (row.querySelector('a[class*="text-gray-"]')) DIM = DIM_GRAY;
    }
    var STYLE = [
        '[data-tdp-admin-open]>:not(.tdp-admin-page){display:none!important}',
        '.tdp-admin-page{display:none;position:relative;height:100%;min-height:0;flex-direction:column;padding:0 .625rem .5rem}',
        '[data-tdp-admin-open]>.tdp-admin-page{display:flex}',
        '.tdp-admin-page iframe{flex:1 1 auto;width:100%;min-height:0;border:0;border-radius:.75rem;background:transparent}',
        '.tdp-admin-loading{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;font-size:.75rem;color:var(--color-gray-500,#9b9b9b);pointer-events:none}'
    ].join('');
    var openPath = null;
    var scheduled = false;
    var observer = new MutationObserver(schedule);
    var observed = null;

    // The bar's row once it's there; until then the page, since the Admin
    // Panel's layout renders only after its own onMount
    function observe(target, options) {
        if (observed === target) return;
        observer.disconnect();
        observed = target;
        if (target) observer.observe(target, options);
    }

    function onAdminPath() {
        return /^\/admin(\/|$)/.test(location.pathname);
    }

    // Back from a new chat into the Admin Panel: Open WebUI's chat tabs
    // replace the address with / before the panel renders, so the panel is
    // looked for over the next 10 seconds whatever the address says
    var lookUntil = 0;
    function onPopstate() {
        if (onAdminPath()) {
            lookUntil = Date.now() + 10000;
            setTimeout(schedule, 10000);
        }
        schedule();
    }

    function ensureStyle() {
        if (document.getElementById('owui-tdp-admin-page-style')) return;
        var style = document.createElement('style');
        style.id = 'owui-tdp-admin-page-style';
        style.textContent = STYLE;
        document.head.appendChild(style);
    }

    function bar() {
        var settings = document.querySelector('nav a[href="/admin/settings"]');
        if (!settings || !settings.parentElement.querySelector('a[href="/admin/evaluations"]')) return null;
        pickDim(settings.parentElement);
        return { row: settings.parentElement, settings: settings, host: settings.closest('nav').nextElementSibling };
    }

    function setDim(el, dim) {
        DIM.forEach(function (c) { el.classList.toggle(c, dim); });
    }

    function makeLink(b) {
        var link = document.createElement('a');
        link.className = b.settings.className;
        link.classList.add('tdp-admin-page-link');
        link.href = '#theme-designer';
        link.draggable = false;
        link.textContent = LABEL;
        link.addEventListener('click', function (evt) {
            evt.preventDefault();
            open(bar());
        });
        return link;
    }

    function makePage() {
        var page = document.createElement('div');
        page.className = 'tdp-admin-page';
        var loading = document.createElement('div');
        loading.className = 'tdp-admin-loading';
        loading.textContent = 'Loading Theme Designer Pro…';
        var frame = document.createElement('iframe');
        frame.src = SRC;
        frame.title = 'Theme Designer Pro';
        frame.setAttribute('allow', 'clipboard-read; clipboard-write');
        frame.addEventListener('load', function () { loading.remove(); }, { once: true });
        page.appendChild(loading);
        page.appendChild(frame);
        return page;
    }

    function open(b) {
        if (!b || !b.host) return;
        if (!b.host.querySelector(':scope > .tdp-admin-page')) b.host.appendChild(makePage());
        b.host.setAttribute('data-tdp-admin-open', '');
        openPath = location.pathname;
        render();
    }

    function close(b) {
        openPath = null;
        if (b && b.host) b.host.removeAttribute('data-tdp-admin-open');
    }

    // Give the bar's own links back the look they had.
    function undim(b) {
        [].forEach.call(b.row.querySelectorAll('a[data-tdp-dimmed]'), function (a) {
            a.removeAttribute('data-tdp-dimmed');
            setDim(a, false);
        });
    }

    // Turned off while this page was open: take the link and the page away.
    function withdraw(b) {
        close(b);
        undim(b);
        var link = b.row.querySelector('.tdp-admin-page-link');
        if (link) link.remove();
        var page = b.host && b.host.querySelector(':scope > .tdp-admin-page');
        if (page) page.remove();
    }

    function watch(b) {
        if (b.row.__tdpWatched) return;
        b.row.__tdpWatched = true;
        // Another page of the bar closes ours; Settings opens a dialog over it.
        b.row.addEventListener('click', function (evt) {
            var a = evt.target.closest && evt.target.closest('a');
            if (a && !a.classList.contains('tdp-admin-page-link') && a.getAttribute('href') !== '/admin/settings') {
                close(bar());
                render();
            }
        }, true);
    }

    function render() {
        scheduled = false;
        var b = bar();
        // Leaving the Admin Panel closes the page too, or coming back to
        // the same address showed our link as current over the real page
        if (!b) {
            openPath = null;
            observe(onAdminPath() || Date.now() < lookUntil ? document.body : null, { childList: true, subtree: true });
            return;
        }
        observe(b.row, { childList: true });
        if (window.__owuiThemeFunctionOff) {
            withdraw(b);
            return;
        }
        // Navigating elsewhere in the Admin Panel closes the page, and so
        // does a rebuilt layout that no longer holds it open.
        if (openPath && (location.pathname !== openPath || (b.host && !b.host.hasAttribute('data-tdp-admin-open')))) {
            openPath = null;
            if (b.host) b.host.removeAttribute('data-tdp-admin-open');
        }
        ensureStyle();
        watch(b);
        var link = b.row.querySelector('.tdp-admin-page-link');
        if (!link) link = makeLink(b);
        if (link.nextElementSibling !== b.settings) b.row.insertBefore(link, b.settings);
        var isOpen = !!openPath;
        setDim(link, !isOpen);
        link.setAttribute('aria-current', isOpen ? 'page' : 'false');
        // While ours is open, the route's own link stops looking selected.
        if (!isOpen) {
            undim(b);
            return;
        }
        [].forEach.call(b.row.querySelectorAll('a:not(.tdp-admin-page-link)'), function (a) {
            if (!DIM.every(function (c) { return a.classList.contains(c); })) {
                a.setAttribute('data-tdp-dimmed', '');
                setDim(a, true);
            }
        });
    }

    function schedule() {
        if (scheduled) return;
        scheduled = true;
        requestAnimationFrame(render);
    }

    function start() {
        window.addEventListener('owui-theme-function-state', schedule);
        window.addEventListener('owui-tdp-route', schedule);
        window.addEventListener('popstate', onPopstate);
        schedule();
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', start, { once: true });
    } else {
        start();
    }
})();
