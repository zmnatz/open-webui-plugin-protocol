// Page Banners: shows the banners from Admin Panel > Settings > General > Banners in every chat.
// A variant of Better Banners by Classic298 (BSD-3-Clause, see NOTICE.md in the repository root).
// This file is the body of a script, not a whole one: owpp wraps it in its own function (strict mode, with a
// try/catch) and fills in the config below from the valves (function.py, asset_vars). It is not Python.
if (window.__owuiPageBanners) return;
window.__owuiPageBanners = true;

var CFG = __CONFIG__;
var COLLAPSED_KEY = 'owui-page-banners:collapsed';
// Open WebUI's own key, so dismissals carry over in both directions.
var DISMISSED_KEY = 'dismissedBannerIds';
var FRAME = '42["' + CFG.event + '"';
var SYNC_SPREAD_MS = 2000;
var COLLAPSE_MS = 240;
var LEAVE_MS = 200;
var STAGGER_MS = 45;
var LEVEL_ORDER = ['success', 'info', 'warning', 'error'];
var ICONS = {
  info: '<circle cx="12" cy="12" r="9"/><path d="M12 11v5"/><path d="M12 8h.01"/>',
  success: '<circle cx="12" cy="12" r="9"/><path d="m8.5 12.5 2.5 2.5 4.5-5"/>',
  warning: '<path d="M10.3 4.2 2.6 17.6a2 2 0 0 0 1.7 3h15.4a2 2 0 0 0 1.7-3L13.7 4.2a2 2 0 0 0-3.4 0Z"/><path d="M12 10v4"/><path d="M12 17h.01"/>',
  error: '<circle cx="12" cy="12" r="9"/><path d="m9.5 9.5 5 5"/><path d="m14.5 9.5-5 5"/>'
};
var CHEVRON = '<path d="m6 9 6 6 6-6"/>';
var CLOSE = '<path d="M6 6l12 12"/><path d="M18 6 6 18"/>';
var MEGAPHONE = '<path d="m3 11 18-5v12L3 14v-3z"/><path d="M11.6 16.8a3 3 0 1 1-5.8-1.6"/>';

var banners = [];
var root = null;
var placeQueued = false;
var lastRenderKey = '';
var collapseTimer = null;
var anchored = false;
var inflight = false;
var syncAgain = false;
var syncTimer = null;
var lastToken = null;

function token() {
  try { return localStorage.getItem('token') || ''; } catch (e) { return ''; }
}

function readJson(key, fallback) {
  try {
    var value = JSON.parse(localStorage.getItem(key) || 'null');
    return value && typeof value === 'object' ? value : fallback;
  } catch (e) {
    return fallback;
  }
}

function writeJson(key, value) {
  try { localStorage.setItem(key, JSON.stringify(value)); } catch (e) {}
}

function svg(paths) {
  return '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' + paths + '</svg>';
}

// Same lookup as Open WebUI's resolveLocalizedString: exact locale, then its base language.
function localized(banner, field) {
  var lang = (document.documentElement.getAttribute('lang') || '').trim();
  var base = lang.split('-')[0];
  var candidates = base && base !== lang ? [lang, base] : lang ? [lang] : [];
  for (var i = 0; i < candidates.length; i++) {
    var entry = banner.i18n && banner.i18n[candidates[i]];
    var value = entry && entry[field];
    if (typeof value === 'string' && value.trim()) return value;
  }
  return typeof banner[field] === 'string' ? banner[field] : '';
}

function fingerprint(banner) {
  var text = JSON.stringify([banner.type, banner.title || '', banner.content, banner.i18n || null]);
  var hash = 5381;
  for (var i = 0; i < text.length; i++) hash = ((hash << 5) + hash + text.charCodeAt(i)) | 0;
  return (hash >>> 0).toString(36);
}

function isSafeUrl(url) {
  return /^(https?:\/\/|mailto:|\/(?!\/))/i.test(url);
}

function appendLink(target, href, label) {
  var link = document.createElement('a');
  link.href = href;
  link.target = '_blank';
  link.rel = 'noopener noreferrer';
  link.textContent = label;
  target.appendChild(link);
}

function appendInline(target, text) {
  var pattern = /\*\*([^*]+)\*\*|\*([^*\s][^*]*)\*|`([^`]+)`|\[([^\]]+)\]\(((?:[^()\s]|\([^()\s]*\))+)\)|https?:\/\/[^\s<>"']+/g;
  var last = 0;
  var match;
  while ((match = pattern.exec(text))) {
    var raw = match[0];
    var isBareUrl = /^https?:/.test(raw);
    if (isBareUrl) {
      raw = raw.replace(/[.,;:!?]+$/, '');
      while (raw.slice(-1) === ')' && raw.split('(').length < raw.split(')').length) raw = raw.slice(0, -1);
      pattern.lastIndex = match.index + raw.length;
    }
    if (match.index > last) target.appendChild(document.createTextNode(text.slice(last, match.index)));
    var bold = match[1];
    var italic = match[2];
    if (bold || italic) {
      var emphasis = document.createElement(bold ? 'strong' : 'em');
      appendInline(emphasis, bold || italic);
      target.appendChild(emphasis);
    } else if (match[3]) {
      var code = document.createElement('code');
      code.textContent = match[3];
      target.appendChild(code);
    } else if (match[4]) {
      if (isSafeUrl(match[5])) appendLink(target, match[5], match[4]);
      else target.appendChild(document.createTextNode(match[4]));
    } else {
      appendLink(target, raw, raw);
    }
    last = match.index + raw.length;
  }
  if (last < text.length) target.appendChild(document.createTextNode(text.slice(last)));
}

var HTML_TAGS = /^(A|ABBR|B|BLOCKQUOTE|BR|CODE|DEL|DETAILS|DIV|EM|H[1-6]|HR|I|IMG|LI|MARK|OL|P|PRE|S|SMALL|SPAN|STRONG|SUB|SUMMARY|SUP|TABLE|TBODY|TD|TH|THEAD|TR|U|UL)$/;
var HTML_DROPPED = /^(SCRIPT|STYLE|IFRAME|OBJECT|EMBED|TEMPLATE|NOSCRIPT|SVG|MATH|FORM|INPUT|BUTTON|TEXTAREA|SELECT|LINK|META|BASE)$/;

// Same idea as Open WebUI's DOMPurify pass: keep formatting and inline styles, drop anything that can run or load code.
function appendSafeHtml(target, source) {
  Array.prototype.forEach.call(source.childNodes, function (node) {
    if (node.nodeType === 3) {
      target.appendChild(document.createTextNode(node.nodeValue));
      return;
    }
    if (node.nodeType !== 1 || HTML_DROPPED.test(node.tagName)) return;
    if (!HTML_TAGS.test(node.tagName)) {
      appendSafeHtml(target, node);
      return;
    }
    var clean = document.createElement(node.tagName.toLowerCase());
    var style = node.getAttribute('style');
    if (style && !/url\s*\(|expression|javascript:/i.test(style)) clean.setAttribute('style', style);
    ['title', 'class', 'colspan', 'rowspan', 'alt', 'width', 'height'].forEach(function (name) {
      if (node.hasAttribute(name)) clean.setAttribute(name, node.getAttribute(name));
    });
    if (node.tagName === 'A') {
      var href = node.getAttribute('href') || '';
      if (isSafeUrl(href)) {
        clean.href = href;
        clean.target = '_blank';
        clean.rel = 'noopener noreferrer';
      }
    }
    if (node.tagName === 'IMG') {
      var src = node.getAttribute('src') || '';
      if (!/^https?:\/\//i.test(src)) return;
      clean.src = src;
    }
    appendSafeHtml(clean, node);
    target.appendChild(clean);
  });
}

function renderContent(target, text) {
  // Like Open WebUI, banners written in HTML render as HTML, with line breaks kept.
  if (/<[a-z][^>]*>/i.test(text)) {
    var parsed = new DOMParser().parseFromString(String(text).replace(/\r?\n/g, '<br>'), 'text/html');
    appendSafeHtml(target, parsed.body);
  } else {
    renderMarkdown(target, text);
  }
}

function renderMarkdown(target, text) {
  var list = null;
  var needsBreak = false;
  String(text).replace(/\r\n/g, '\n').split('\n').forEach(function (line) {
    var item = /^\s*(?:[-*+]|(\d+)[.)])\s+(.*)$/.exec(line);
    if (item) {
      var listTag = item[1] ? 'OL' : 'UL';
      if (!list || list.tagName !== listTag) {
        list = document.createElement(listTag);
        target.appendChild(list);
      }
      var li = document.createElement('li');
      appendInline(li, item[2]);
      list.appendChild(li);
      needsBreak = false;
      return;
    }
    list = null;
    if (needsBreak) target.appendChild(document.createElement('br'));
    var heading = /^\s*#{1,6}\s+(.*)$/.exec(line);
    if (heading) {
      var strong = document.createElement('strong');
      appendInline(strong, heading[1]);
      target.appendChild(strong);
    } else {
      appendInline(target, line);
    }
    needsBreak = true;
  });
}

function dismissedIds() {
  var ids = readJson(DISMISSED_KEY, []);
  return Array.isArray(ids) ? ids : [];
}

function collapsedMap() {
  return readJson(COLLAPSED_KEY, {});
}

function visibleBanners() {
  var dismissed = dismissedIds();
  return banners.filter(function (banner) {
    return dismissed.indexOf(banner.id) === -1;
  });
}

function anchor() {
  var chatNav = document.querySelector('#new-chat-button ~ nav');
  if (!chatNav) return null;
  var pane = document.getElementById('chat-pane');
  var inChat = pane && (pane.querySelector('#chat-conversation') || location.pathname.lastIndexOf('/c/', 0) === 0);
  if (!inChat) return null;
  if (CFG.position === 'top') {
    // In the page flow, so the chat moves down instead of hiding under the banners.
    return { parent: pane, before: pane.firstChild === root ? root.nextSibling : pane.firstChild };
  }
  var input = document.getElementById('message-input-container');
  var form = input && input.closest('form');
  return form && form.parentNode ? { parent: form.parentNode, before: form } : null;
}

function ensureRoot() {
  if (root) return;
  root = document.createElement('div');
  root.id = 'owui-page-banners';
  root.setAttribute('role', 'region');
  root.setAttribute('aria-label', 'Announcements');
  root.dataset.position = CFG.position;
  root.style.setProperty('--opb-max-height', CFG.maxHeight + 'px');
}

function place() {
  placeQueued = false;
  var current = token();
  if (current !== lastToken) {
    lastToken = current;
    sync();
  }
  var target = root && root.childNodes.length ? anchor() : null;
  // Pick up dismissals made in Open WebUI's own banners in this tab.
  if (target && !anchored) render();
  anchored = Boolean(target);
  if (!target || !root.childNodes.length) {
    if (root && root.parentNode) {
      root.parentNode.removeChild(root);
      root.querySelectorAll('.opb-enter').forEach(function (element) { element.classList.remove('opb-enter'); });
    }
    return;
  }
  var misplaced = root.parentNode !== target.parent || (target.before && root.nextSibling !== target.before);
  if (misplaced) target.parent.insertBefore(root, target.before);
}

function schedulePlace() {
  if (placeQueued) return;
  placeQueued = true;
  requestAnimationFrame(place);
}

function isCollapsed(visible) {
  var map = collapsedMap();
  return visible.length > 0 && visible.every(function (banner) {
    return map[banner.id] === fingerprint(banner);
  });
}

function staggerFromPill(elements) {
  elements.forEach(function (element, index) {
    var distance = CFG.position === 'top' ? index : elements.length - 1 - index;
    element.style.setProperty('--opb-delay', distance * STAGGER_MS + 'ms');
  });
}

function replayAnimation(element, className) {
  element.classList.remove('opb-enter', 'opb-absorb', 'opb-release');
  void element.offsetHeight;
  element.classList.add(className);
  element.addEventListener('animationend', function () { element.classList.remove(className); }, { once: true });
}

function collapseAll() {
  var visible = visibleBanners();
  if (!visible.length) return;
  var pill = root.querySelector('.opb-pill');
  clearTimeout(collapseTimer);
  var map = {};
  visible.forEach(function (banner) { map[banner.id] = fingerprint(banner); });
  writeJson(COLLAPSED_KEY, map);
  lastRenderKey = renderKey(visible, true);
  updatePill(pill, visible, true);
  var elements = root.querySelectorAll('.opb-banner');
  staggerFromPill(elements);
  // Keep the target height of an expand still running, so reversing it again opens fully.
  var heights = Array.prototype.map.call(elements, function (element) {
    return element.style.height || element.offsetHeight + 'px';
  });
  elements.forEach(function (element, index) {
    element.classList.remove('opb-enter');
    element.style.height = heights[index];
    element.classList.add('opb-collapsing');
  });
  void root.offsetHeight;
  elements.forEach(function (element) { element.classList.add('opb-collapsed'); });
  collapseTimer = setTimeout(function () {
    elements.forEach(function (element) { element.remove(); });
    replayAnimation(pill, 'opb-absorb');
  }, COLLAPSE_MS + (elements.length - 1) * STAGGER_MS);
}

function expandAll() {
  var visible = visibleBanners();
  if (!visible.length) return;
  var pill = root.querySelector('.opb-pill');
  clearTimeout(collapseTimer);
  writeJson(COLLAPSED_KEY, {});
  lastRenderKey = renderKey(visible, false);
  updatePill(pill, visible, false);
  replayAnimation(pill, 'opb-release');
  var elements = root.querySelectorAll('.opb-banner');
  if (!elements.length) {
    elements = visible.map(bannerElement);
    if (CFG.position === 'top') pill.after.apply(pill, elements);
    else pill.before.apply(pill, elements);
    var heights = elements.map(function (element) { return element.offsetHeight + 'px'; });
    elements.forEach(function (element, index) {
      element.style.height = heights[index];
      element.classList.add('opb-collapsed');
    });
    void root.offsetHeight;
  }
  staggerFromPill(elements);
  elements.forEach(function (element) {
    element.classList.add('opb-collapsing');
    element.classList.remove('opb-collapsed');
  });
  collapseTimer = setTimeout(function () {
    elements.forEach(function (element) {
      element.classList.remove('opb-collapsing');
      element.style.height = '';
    });
  }, COLLAPSE_MS + (elements.length - 1) * STAGGER_MS);
}

function dismiss(banner, element) {
  var remaining = banners.map(function (b) { return b.id; });
  var ids = [banner.id].concat(dismissedIds()).filter(function (id) {
    return remaining.indexOf(id) !== -1;
  });
  writeJson(DISMISSED_KEY, ids);
  // Start the fade from wherever a running entrance left it.
  element.style.opacity = getComputedStyle(element).opacity;
  element.classList.remove('opb-enter');
  element.classList.add('opb-leave');
  setTimeout(function () {
    element.remove();
    var visible = visibleBanners();
    if (visible.length) {
      var pill = root.querySelector('.opb-pill');
      var collapsed = pill.getAttribute('aria-expanded') !== 'true';
      lastRenderKey = renderKey(visible, collapsed);
      updatePill(pill, visible, collapsed);
    } else if (!root.querySelector('.opb-banner')) {
      // Wait for any other banner still fading out before clearing the stack.
      render();
    }
    schedulePlace();
  }, LEAVE_MS);
}

function button(className, paths, label) {
  var el = document.createElement('button');
  el.type = 'button';
  el.className = 'opb-button ' + className;
  el.setAttribute('aria-label', label);
  el.title = label;
  el.innerHTML = svg(paths);
  return el;
}

function bannerLevel(banner) {
  return ICONS[banner.type] ? banner.type : 'info';
}

function bannerElement(banner) {
  var level = bannerLevel(banner);
  var element = document.createElement('div');
  element.className = 'opb-banner opb-' + level;
  element.dataset.id = banner.id;

  var icon = document.createElement('span');
  icon.className = 'opb-icon';
  icon.innerHTML = svg(ICONS[level]);
  element.appendChild(icon);

  var body = document.createElement('div');
  body.className = 'opb-body';
  var title = localized(banner, 'title').trim();
  if (title) {
    var heading = document.createElement('div');
    heading.className = 'opb-title';
    heading.textContent = title;
    body.appendChild(heading);
  }
  var content = document.createElement('div');
  content.className = 'opb-content';
  renderContent(content, localized(banner, 'content'));
  body.appendChild(content);
  element.appendChild(body);

  if (banner.dismissible) {
    var actions = document.createElement('div');
    actions.className = 'opb-actions';
    var close = button('opb-close', CLOSE, 'Dismiss');
    close.addEventListener('click', function () { dismiss(banner, element); });
    actions.appendChild(close);
    element.appendChild(actions);
  }
  return element;
}

function updatePill(pill, visible, collapsed) {
  var pillLevel = visible.map(bannerLevel).reduce(function (highest, level) {
    return LEVEL_ORDER.indexOf(level) > LEVEL_ORDER.indexOf(highest) ? level : highest;
  });
  var label = (collapsed ? 'Expand all (' : 'Collapse all (') + visible.length + ')';
  LEVEL_ORDER.forEach(function (level) { pill.classList.remove('opb-' + level); });
  pill.classList.add('opb-' + pillLevel);
  pill.setAttribute('aria-label', label);
  pill.setAttribute('aria-expanded', String(!collapsed));
  pill.title = label;
  pill.querySelector('.opb-count').textContent = visible.length;
}

function pillElement(visible, collapsed) {
  var pill = document.createElement('button');
  pill.type = 'button';
  pill.className = 'opb-pill';
  pill.innerHTML = '<span class="opb-dot"></span>' + svg(MEGAPHONE) + '<span class="opb-count"></span>' +
    '<span class="opb-chevron">' + svg(CHEVRON) + '</span>';
  updatePill(pill, visible, collapsed);
  pill.addEventListener('click', function () {
    if (pill.getAttribute('aria-expanded') === 'true') collapseAll();
    else expandAll();
  });
  return pill;
}

function renderKey(visible, collapsed) {
  return JSON.stringify([collapsed, document.documentElement.getAttribute('lang'), visible]);
}

function render() {
  ensureRoot();
  var visible = visibleBanners();
  var collapsed = isCollapsed(visible);
  // Skip identical re-renders so a routine sync does not replay the entrance animation.
  var key = renderKey(visible, collapsed);
  if (key === lastRenderKey) return;
  lastRenderKey = key;
  // Forget an old collapse once the stack is open, or dismissing the banner that reopened it re-collapses it.
  if (visible.length && !collapsed) writeJson(COLLAPSED_KEY, {});
  var elements = collapsed ? [] : visible.map(bannerElement);
  staggerFromPill(elements);
  if (visible.length) {
    var pill = pillElement(visible, collapsed);
    if (CFG.position === 'top') elements.unshift(pill);
    else elements.push(pill);
  }
  elements.forEach(function (element) {
    element.classList.add('opb-enter');
    element.addEventListener('animationend', function () { element.classList.remove('opb-enter'); });
  });
  root.replaceChildren.apply(root, elements);
  schedulePlace();
}

function sync() {
  if (syncTimer) {
    clearTimeout(syncTimer);
    syncTimer = null;
  }
  var auth = token();
  if (!auth) {
    banners = [];
    render();
    return;
  }
  if (inflight) {
    syncAgain = true;
    return;
  }
  inflight = true;
  fetch('/api/v1/configs/banners', {
    headers: { Authorization: 'Bearer ' + auth },
    cache: 'no-store'
  })
    .then(function (res) { return res.ok ? res.json() : null; })
    .then(function (data) {
      if (!Array.isArray(data)) return;
      banners = data;
      render();
    })
    .catch(function () {})
    .then(function () {
      inflight = false;
      if (syncAgain) {
        syncAgain = false;
        sync();
      }
    });
}

// Spread over a short window so an edit does not hit the server with every tab at once.
function scheduleSync() {
  if (syncTimer) return;
  syncTimer = setTimeout(function () {
    syncTimer = null;
    sync();
  }, Math.floor(Math.random() * SYNC_SPREAD_MS));
}

function onFrame(evt) {
  var raw = evt.data;
  if (typeof raw === 'string' && raw.lastIndexOf(FRAME, 0) === 0) scheduleSync();
}

// Plugins get no handle on the app's socket, so hook WebSocket to hear the change signal.
function hookSocket() {
  var proto = window.WebSocket.prototype;
  var listen = proto.addEventListener;
  var connectedBefore = false;

  function watch(ws) {
    if (String(ws.url).indexOf('socket.io') === -1) return;
    listen.call(ws, 'message', onFrame);
    // The first connection comes with the page load, which already fetched.
    listen.call(ws, 'open', function () {
      if (connectedBefore) scheduleSync();
      connectedBefore = true;
    });
  }

  // engine.io sets onmessage right after onopen, before the socket connects.
  var desc = Object.getOwnPropertyDescriptor(proto, 'onmessage');
  Object.defineProperty(proto, 'onmessage', {
    configurable: true,
    enumerable: desc.enumerable,
    get: desc.get,
    set: function (fn) {
      watch(this);
      desc.set.call(this, fn);
    }
  });
}

function start() {
  lastToken = token();
  sync();
  new MutationObserver(schedulePlace).observe(document.body, { childList: true, subtree: true });
  new MutationObserver(function () { if (banners.length) render(); })
    .observe(document.documentElement, { attributes: true, attributeFilter: ['lang'] });
  document.addEventListener('visibilitychange', function () {
    if (!document.hidden) scheduleSync();
  });
  window.addEventListener('storage', function (evt) {
    if (evt.key === DISMISSED_KEY || evt.key === COLLAPSED_KEY) render();
  });
  if (CFG.resync > 0) {
    setInterval(function () { if (!document.hidden) sync(); }, CFG.resync * 1000);
  }
}

hookSocket();
start();
