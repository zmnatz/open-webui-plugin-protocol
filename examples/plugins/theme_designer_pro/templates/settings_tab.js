(function () {
    'use strict';
    if (window.__owuiTdpSettingsTab) return;
    window.__owuiTdpSettingsTab = true;

    var ROUTE = '__THEME_ROUTE__';
    var LABEL = 'Theme Designer Pro';
    // Each tab's own name, short like the dialog's other tabs.
    var TAB_LABEL = 'Themes';
    // The Personal tab edits the signed-in user's own theme, the Admin tab the
    // instance theme. Each sits after Interface in its section.
    var SPECS = [];
    if (__TAB_PERSONAL__) SPECS.push({ key: 'personal', panelId: 'tab-theme-designer', after: 'tab-interface', admin: false, src: ROUTE + '?embed=settings&scope=me', title: LABEL + ', my theme' });
    if (__TAB_ADMIN__) SPECS.push({ key: 'admin', panelId: 'tab-admin-theme-designer', after: 'tab-admin-interface', admin: true, src: ROUTE + '?embed=settings', title: LABEL });
    // Words the dialog's search box finds these tabs by.
    var KEYWORDS = 'themes designer pro colors colours palette css canvas fx gradient appearance';
    // Heroicons' swatch.
    var ICON = '<svg class="size-3.5" aria-hidden="true" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M4.098 19.902a3.75 3.75 0 0 0 5.304 0l6.401-6.402M6.75 21A3.75 3.75 0 0 1 3 17.25V4.125C3 3.504 3.504 3 4.125 3h5.25c.621 0 1.125.504 1.125 1.125v4.072M6.75 21a3.75 3.75 0 0 0 3.75-3.75V8.197M6.75 21h13.125c.621 0 1.125-.504 1.125-1.125v-5.25c0-.621-.504-1.125-1.125-1.125h-4.072M10.5 8.197l2.88-2.88c.438-.439 1.15-.439 1.59 0l3.712 3.713c.44.44.44 1.152 0 1.59l-2.879 2.88M6.75 17.25h.008v.008H6.75v-.008Z"/></svg>';
    var STYLE = [
        '.tdp-settings-panel{display:none;position:relative;flex:1 1 auto;min-height:0;flex-direction:column}',
        '[data-tdp-open="personal"]>.tdp-settings-panel[data-tdp-key="personal"],[data-tdp-open="admin"]>.tdp-settings-panel[data-tdp-key="admin"]{display:flex}',
        '[data-tdp-open]>:not(.tdp-settings-panel){display:none!important}',
        '.tdp-settings-panel iframe{flex:1 1 auto;width:100%;min-height:0;border:0;border-radius:.75rem;background:transparent}',
        '.tdp-settings-loading{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;font-size:.75rem;color:var(--color-base-500,#9b9b9b);pointer-events:none}',
        // The tab whose theme this page shows
        '.tdp-theme-dot{width:6px;height:6px;margin-left:auto;flex-shrink:0;border-radius:9999px;background:#22c55e}',
        // A ring for the instance theme, where the Admin tab isn't there to show it
        '.tdp-theme-dot.tdp-theme-dot-instance{background:transparent;box-shadow:inset 0 0 0 1.5px #22c55e}',
        // The dialog's own tab keeps its selected look while ours is open; drop it.
        '#settings-tabs-container[data-tdp-active] [data-tdp-was]{font-weight:400;color:var(--color-base-600,#676767);background:transparent}',
        'html.dark #settings-tabs-container[data-tdp-active] [data-tdp-was]{color:var(--color-base-400,#b4b4b4)}'
    ].join('');
    // tabButtonClass in SettingsModal.svelte, read from the dialog's own tabs when it has them.
    var activeClass = 'flex items-center gap-1.5 h-7 px-2 md:w-full shrink-0 rounded-lg text-xs text-left transition-colors duration-75 font-medium text-gray-900 dark:text-white bg-gray-50 dark:bg-white/[0.04]';
    var inactiveClass = 'flex items-center gap-1.5 h-7 px-2 md:w-full shrink-0 rounded-lg text-xs text-left transition-colors duration-75 text-gray-600 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-300';
    var classesRead = false;
    var scheduled = false;

    function ensureStyle() {
        if (document.getElementById('owui-tdp-settings-style')) return;
        var style = document.createElement('style');
        style.id = 'owui-tdp-settings-style';
        style.textContent = STYLE;
        document.head.appendChild(style);
    }

    function nativeTabs(nav) {
        return nav.querySelectorAll('button[role="tab"]:not(.tdp-settings-tab)');
    }

    function readClasses(nav) {
        if (classesRead) return;
        var tabs = nativeTabs(nav);
        var active = null, inactive = null;
        for (var i = 0; i < tabs.length; i++) {
            if (tabs[i].hasAttribute('data-tdp-was')) continue;
            if (tabs[i].getAttribute('aria-selected') === 'true') active = active || tabs[i].className;
            else inactive = inactive || tabs[i].className;
        }
        if (active && inactive) {
            activeClass = active;
            inactiveClass = inactive;
            classesRead = true;
        }
    }

    function searchText(nav) {
        var input = nav.querySelector('#search-input-settings-modal');
        return input ? input.value.trim().toLowerCase() : '';
    }

    function matches(query) {
        return query.split(/\s+/).every(function (word) { return KEYWORDS.indexOf(word) !== -1; });
    }

    // After its section's Interface tab; while searching, after the last tab
    // of its section the search left, or last in the list when it left none.
    function anchorFor(nav, spec) {
        var query = searchText(nav);
        if (query && !matches(query)) return null;
        var after = nav.querySelector('button[role="tab"][aria-controls="' + spec.after + '"]');
        if (after) return after;
        if (!query) return null;
        var section = [].filter.call(nativeTabs(nav), function (tab) {
            return (tab.getAttribute('aria-controls') || '').indexOf('tab-admin-') === 0 ? spec.admin : !spec.admin;
        });
        if (section.length) return section[section.length - 1];
        // An admin tab never shows for someone the dialog gives no admin tabs.
        return spec.admin && !nav.querySelector('button[role="tab"][aria-controls^="tab-admin-"]') && !nav.__tdpAdminSeen ? null : nav.querySelector('.tabs');
    }

    // The key of the tab of ours that is open, or ''.
    function openKey(nav) {
        return nav.getAttribute('data-tdp-active') || '';
    }

    function makeTab(spec) {
        var tab = document.createElement('button');
        tab.type = 'button';
        tab.setAttribute('role', 'tab');
        tab.setAttribute('aria-controls', spec.panelId);
        tab.setAttribute('data-tdp-key', spec.key);
        tab.innerHTML = ICON + '<span>' + TAB_LABEL + '</span>';
        tab.addEventListener('click', function () {
            var nav = document.getElementById('settings-tabs-container');
            if (nav) open(nav, spec);
        });
        return tab;
    }

    function makePanel(spec) {
        var panel = document.createElement('div');
        panel.className = 'tdp-settings-panel';
        panel.id = spec.panelId;
        panel.setAttribute('data-tdp-key', spec.key);
        panel.setAttribute('role', 'tabpanel');
        var loading = document.createElement('div');
        loading.className = 'tdp-settings-loading';
        loading.textContent = 'Loading ' + LABEL + '…';
        var frame = document.createElement('iframe');
        frame.title = spec.title;
        frame.src = spec.src;
        frame.setAttribute('allow', 'clipboard-read; clipboard-write');
        frame.addEventListener('load', function () { loading.remove(); }, { once: true });
        panel.appendChild(loading);
        panel.appendChild(frame);
        return panel;
    }

    // A panel stays in the dialog once loaded, hidden while another tab is
    // open, so coming back is instant and keeps the designer where you left it.
    function open(nav, spec) {
        var host = nav.nextElementSibling;
        if (!host || openKey(nav) === spec.key) return;
        readClasses(nav);
        // Switching between our two tabs keeps the dialog's tab marked as the
        // one to go back to.
        if (!openKey(nav)) {
            var tabs = nativeTabs(nav);
            for (var i = 0; i < tabs.length; i++) {
                if (tabs[i].getAttribute('aria-selected') === 'true') {
                    tabs[i].setAttribute('aria-selected', 'false');
                    tabs[i].setAttribute('data-tdp-was', '');
                }
            }
        }
        if (!host.querySelector(':scope > .tdp-settings-panel[data-tdp-key="' + spec.key + '"]')) host.appendChild(makePanel(spec));
        host.setAttribute('data-tdp-open', spec.key);
        nav.setAttribute('data-tdp-active', spec.key);
        render();
    }

    // `clicked` is the dialog tab that closed ours; picking the tab that was
    // open before does not change the dialog's choice, so give it back its state.
    function close(nav, clicked) {
        var host = nav.nextElementSibling;
        if (host) host.removeAttribute('data-tdp-open');
        nav.removeAttribute('data-tdp-active');
        var was = nav.querySelectorAll('[data-tdp-was]');
        for (var i = 0; i < was.length; i++) {
            was[i].removeAttribute('data-tdp-was');
            if (was[i] === clicked) was[i].setAttribute('aria-selected', 'true');
        }
        render();
    }

    function watch(nav) {
        if (nav.__tdpWatched) return;
        nav.__tdpWatched = true;
        nav.addEventListener('click', function (evt) {
            var tab = evt.target.closest && evt.target.closest('button[role="tab"]');
            if (tab && !tab.classList.contains('tdp-settings-tab') && openKey(nav)) close(nav, tab);
        }, true);
        nav.addEventListener('input', schedule);
        // The search box filters the dialog's tab list
        new MutationObserver(schedule).observe(nav, { childList: true, subtree: true });
        // The dialog picked another tab on its own, as the search box's Enter does.
        new MutationObserver(function () {
            if (!openKey(nav)) return;
            var tabs = nativeTabs(nav);
            for (var i = 0; i < tabs.length; i++) {
                if (tabs[i].getAttribute('aria-selected') === 'true' && !tabs[i].hasAttribute('data-tdp-was')) {
                    close(nav, null);
                    return;
                }
            }
        }).observe(nav, { attributes: true, attributeFilter: ['aria-selected'], subtree: true });
    }

    // Theme Designer Pro was turned off while this page was open: take the tabs
    // and the designers away, and give the dialog back the tab it had open.
    function withdraw(nav) {
        if (openKey(nav)) close(nav, nav.querySelector('[data-tdp-was]'));
        var host = nav.nextElementSibling;
        if (host) [].forEach.call(host.querySelectorAll(':scope > .tdp-settings-panel'), function (panel) { panel.remove(); });
        [].forEach.call(nav.querySelectorAll('.tdp-settings-tab'), function (tab) { tab.remove(); });
    }

    function place(nav, spec) {
        var anchor = anchorFor(nav, spec);
        var tab = nav.querySelector('.tdp-settings-tab[data-tdp-key="' + spec.key + '"]');
        if (!anchor) {
            if (tab) tab.remove();
            return;
        }
        if (!tab) tab = makeTab(spec);
        var isOpen = openKey(nav) === spec.key;
        var className = (isOpen ? activeClass : inactiveClass) + ' tdp-settings-tab';
        if (tab.className !== className) tab.className = className;
        tab.setAttribute('aria-selected', isOpen ? 'true' : 'false');
        if (anchor.classList.contains('tabs')) {
            // Already at the end among our own tabs: with two of ours anchored
            // here, each moved itself after the other on every render, and
            // each move was a mutation that scheduled the next render
            var atEnd = tab.parentElement === anchor;
            for (var next = tab.nextElementSibling; atEnd && next; next = next.nextElementSibling) {
                if (!next.classList.contains('tdp-settings-tab')) atEnd = false;
            }
            if (!atEnd) anchor.appendChild(tab);
        } else if (anchor.nextElementSibling !== tab) {
            anchor.after(tab);
        }
    }

    // Which theme is on screen isn't obvious from the list: a dot marks the
    // tab whose theme this page shows, from the loader's
    // window.__owuiThemeSource, and the tooltips say what's in use. A user
    // without the Admin tab gets a ring on their own tab for the instance
    // theme, so they can tell it from a theme of their own.
    function markInUse(nav, tab, spec) {
        var source = window.__owuiThemeSource || '';
        var own = spec.key === 'personal' ? 'personal' : 'instance';
        var adminTab = !!nav.querySelector('.tdp-settings-tab[data-tdp-key="admin"]');
        var mark = source === own ? 'own'
            : (own === 'personal' && source === 'instance' && !adminTab ? 'instance' : '');
        var dot = tab.querySelector('.tdp-theme-dot');
        if (mark && !dot) {
            dot = document.createElement('span');
            dot.setAttribute('aria-hidden', 'true');
            tab.appendChild(dot);
        } else if (!mark && dot) {
            dot.remove();
            dot = null;
        }
        if (dot) {
            var dotClass = 'tdp-theme-dot' + (mark === 'instance' ? ' tdp-theme-dot-instance' : '');
            if (dot.className !== dotClass) dot.className = dotClass;
        }
        var hint = '';
        if (mark === 'own') hint = own === 'personal' ? 'In use: your own theme' : 'In use: the instance theme';
        else if (mark === 'instance') hint = 'In use: the instance theme, set by an admin. Saving your own theme here replaces it for you';
        else if (own === 'instance' && source === 'personal') hint = 'Your own theme, under Basics, replaces this one for you';
        // aria-description: screen readers hear it with the tab's name
        ['title', 'aria-description'].forEach(function (attr) {
            if ((tab.getAttribute(attr) || '') === hint) return;
            if (hint) tab.setAttribute(attr, hint);
            else tab.removeAttribute(attr);
        });
    }

    function render() {
        scheduled = false;
        var nav = document.getElementById('settings-tabs-container');
        if (!nav) return;
        if (window.__owuiThemeFunctionOff) {
            withdraw(nav);
            return;
        }
        // Remembered so a search that hides every admin tab keeps ours for an admin.
        if (nav.querySelector('button[role="tab"][aria-controls^="tab-admin-"]')) nav.__tdpAdminSeen = true;
        ensureStyle();
        watch(nav);
        readClasses(nav);
        SPECS.forEach(function (spec) { place(nav, spec); });
        // After placing both, since a tab's mark depends on the other being there
        SPECS.forEach(function (spec) {
            var tab = nav.querySelector('.tdp-settings-tab[data-tdp-key="' + spec.key + '"]');
            if (tab) markInUse(nav, tab, spec);
        });
    }

    function schedule() {
        if (scheduled) return;
        scheduled = true;
        requestAnimationFrame(render);
    }

    function start() {
        // Open WebUI's Modal appends the Settings dialog to <body> itself, so
        // <body>'s own children say when it opens, and a chat's streamed
        // tokens schedule nothing
        new MutationObserver(schedule).observe(document.body, { childList: true });
        window.addEventListener('owui-theme-function-state', schedule);
        window.addEventListener('owui-theme-source', schedule);
        schedule();
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', start, { once: true });
    } else {
        start();
    }
})();
