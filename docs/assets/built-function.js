// An example's built function in a popup: a link to the file, and the code with the copy button
// the site's code blocks have. "Get the built function" is an ordinary link to that file (tools/build_docs.py), so it
// still leads to the code without this script.
(() => {
  const el = (tag, props, ...kids) => {
    const node = Object.assign(document.createElement(tag), props);
    node.append(...kids);
    return node;
  };

  const show = async (url) => {
    const close = el("button", { type: "button", className: "md-button" }, "Close");
    const code = el("code", {}, "Loading…");
    const pre = el("pre", {}, code);
    // The dialog has no padding of its own, so a click that lands on it is one outside the box.
    const dialog = el("dialog", { className: "owpp-popup md-typeset" },
      el("div", {},
        el("div", { className: "owpp-bar" }, el("strong", {}, url.split("/").pop()), close),
        el("p", {}, "The file, also for Import from URL: ", el("a", { href: url }, url)),
        el("div", { className: "highlight" }, pre)));
    close.onclick = () => dialog.close();
    dialog.onclick = (event) => { if (event.target === dialog) dialog.close(); };
    dialog.onclose = () => dialog.remove();
    document.body.append(dialog);
    dialog.showModal();

    let text;
    try {
      const response = await fetch(url);
      if (!response.ok) throw new Error("HTTP " + response.status);
      text = await response.text();
    } catch (error) {
      code.textContent = "Could not load the code (" + error.message + "). Open the link above.";
      return;
    }
    code.textContent = text;
    pre.prepend(copyButton(text));
  };

  // The theme's markup, for its look. The theme copies for the blocks it finds on loading only,
  // and says so behind a dialog, so this button does both itself.
  const copyButton = (text) => {
    const button = el("button", { type: "button", className: "md-code__button", title: "Copy to clipboard" });
    button.dataset.mdType = "copy";
    button.setAttribute("aria-label", button.title);
    const status = el("span", { className: "owpp-status" });
    status.setAttribute("role", "status");
    button.onclick = async () => {
      try {
        await navigator.clipboard.writeText(text);
        status.textContent = "Copied";
      } catch (error) {
        status.textContent = "Copy failed";
      }
      setTimeout(() => { status.textContent = ""; }, 2000);
    };
    return el("nav", { className: "md-code__nav" }, status, button);
  };

  document.addEventListener("click", (event) => {
    const link = event.target.closest("a.owpp-built");
    // A click meant to open the file elsewhere (new tab, download) is left to the browser.
    if (!link || event.button || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    event.preventDefault();
    show(link.href);
  });
})();
