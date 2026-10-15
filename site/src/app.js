/* Terminal prompt: wires the slash input to the DOM. Logic lives in
   filter.js (SkillFilter); this file only handles events and rendering.
   The buffer always starts with "/" (pre-typed, undeletable); the rest is
   typed freely and ranked by SkillFilter.search. */
(function () {
  "use strict";
  var F = window.SkillFilter;
  var dataEl = document.getElementById("skill-data");
  var input = document.getElementById("cmd");
  if (!F || !dataEl || !input) return;

  var items = JSON.parse(dataEl.textContent);

  var term = document.getElementById("term");
  var echo = document.getElementById("echo");
  var hint = document.getElementById("hint");
  var menu = document.getElementById("menu");
  var status = document.getElementById("status");
  var idleHint = hint.textContent;

  var buffer = "/";
  var state = F.search(buffer, items);
  var active = -1;
  var open = false; // menu shows only once the user engages the prompt
  var composing = false; // IME composition: never touch value/caret mid-word

  function setBuffer(next, engage) {
    buffer = F.normalize(next);
    if (!composing) {
      if (input.value !== buffer) input.value = buffer;
      caretToEnd();
    }
    state = F.search(buffer, items);
    active = state.mode === "results" || state.mode === "suggest" ? 0 : -1;
    if (engage) open = true;
    render(true);
  }

  function caretToEnd() {
    try { input.setSelectionRange(input.value.length, input.value.length); } catch (e) { /* not focused */ }
  }

  function option(entry, idx) {
    var li = document.createElement("li");
    li.id = "opt-" + idx;
    li.setAttribute("role", "option");
    li.setAttribute("aria-selected", idx === active ? "true" : "false");
    var nm = document.createElement("span");
    nm.className = "nm";
    nm.textContent = "/" + entry.name;
    var kd = document.createElement("span");
    kd.className = "kd";
    kd.textContent = entry.kind;
    var ds = document.createElement("span");
    ds.className = "ds";
    ds.textContent = entry.summary;
    li.appendChild(nm);
    li.appendChild(kd);
    li.appendChild(ds);
    li.addEventListener("click", function () { go(entry.name); });
    return li;
  }

  function render(announce) {
    echo.textContent = buffer;
    if (state.exact) { hint.textContent = "↵ to open"; hint.hidden = false; }
    else { hint.textContent = idleHint; hint.hidden = buffer !== "/"; }
    menu.textContent = "";
    var note = F.noMatchText(state);
    if (note) {
      var p = document.createElement("li");
      p.className = "note";
      p.setAttribute("role", "presentation");
      p.setAttribute("aria-hidden", "true"); // the live region reads it
      p.textContent = note;
      menu.appendChild(p);
    }
    state.options.forEach(function (entry, idx) { menu.appendChild(option(entry, idx)); });
    var shown = open && (state.options.length > 0 || !!note);
    menu.hidden = !shown;
    input.setAttribute("aria-expanded", shown && state.options.length ? "true" : "false");
    if (shown && active >= 0) input.setAttribute("aria-activedescendant", "opt-" + active);
    else input.removeAttribute("aria-activedescendant");
    if (announce) status.textContent = open ? F.statusText(state) : "";
  }

  function move(delta) {
    var n = state.options.length;
    if (!n) return;
    open = true;
    active = active < 0 ? (delta > 0 ? 0 : n - 1) : (active + delta + n) % n;
    render(false);
    var el = document.getElementById("opt-" + active);
    if (el && el.scrollIntoView) el.scrollIntoView({ block: "nearest" });
  }

  function close() {
    open = false;
    render(true);
  }

  function go(name) {
    var base = (document.body && document.body.getAttribute("data-base")) || "";
    window.location.assign(base + "/" + encodeURIComponent(name));
  }

  // Clicks in the menu never take focus from the prompt (no blur-close).
  menu.addEventListener("mousedown", function (e) { e.preventDefault(); });

  // Source of truth for every edit (typing, Android IME keyCode 229, paste,
  // autofill, cut): normalise so the leading "/" can never be removed.
  input.addEventListener("input", function () {
    setBuffer(input.value, true);
  });
  // IME: search live while composing, fix up the value once it commits.
  input.addEventListener("compositionstart", function () { composing = true; });
  input.addEventListener("compositionend", function () {
    composing = false;
    setBuffer(input.value, true);
  });

  input.addEventListener("keydown", function (e) {
    if (e.keyCode === 229 || e.isComposing) return;
    switch (e.key) {
      case "Tab":
        if (e.shiftKey || e.altKey || e.ctrlKey || e.metaKey || !open) return;
        var c = F.complete(buffer, state, active);
        if (c !== null) { e.preventDefault(); setBuffer(c, true); }
        // Nothing to fill: let Tab move focus (no keyboard trap).
        return;
      case "ArrowDown":
        if (state.options.length) { e.preventDefault(); move(1); }
        return;
      case "ArrowUp":
        if (state.options.length) { e.preventDefault(); move(-1); }
        return;
      case "Enter":
        e.preventDefault();
        var name = open ? F.resolve(state, active) : null;
        if (name) go(name);
        else if (!open) { open = true; render(true); }
        return;
      case "Escape":
        if (buffer !== "/") { e.preventDefault(); setBuffer("/", false); close(); }
        else if (open) { e.preventDefault(); close(); }
        return;
      case "Backspace":
        if (buffer === "/" && input.selectionStart === input.selectionEnd) e.preventDefault();
        return;
      case "/":
        // "/" on the bare prompt shows everything (nothing to type: it is there).
        if (buffer === "/") { e.preventDefault(); open = true; render(true); }
        return;
      case "ArrowLeft":
      case "Home":
        e.preventDefault(); // caret stays at the end
        return;
    }
  });

  input.addEventListener("focus", function () {
    if (input.value !== buffer) input.value = buffer;
    caretToEnd();
  });
  // Leaving the prompt closes the menu (option clicks keep focus: mousedown is cancelled).
  input.addEventListener("blur", function () { if (open) close(); });

  // Tap/click in the terminal (home: the bottom dock) focuses the input.
  term.addEventListener("click", function (e) {
    if (e.target.closest && e.target.closest("a, li[role=option], .note")) return;
    input.focus();
    if (!open) { open = true; render(true); }
  });

  // "/" anywhere on the page jumps into the terminal.
  document.addEventListener("keydown", function (e) {
    if (e.key !== "/" || e.ctrlKey || e.metaKey || e.altKey) return;
    var t = document.activeElement;
    if (t === input || (t && (t.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName)))) return;
    e.preventDefault();
    input.focus();
    setBuffer("/", true);
  });

  input.value = buffer;
  render(false);
  // Home autofocuses on desktop; detail pages opt out (data-autofocus="false").
  var home = input.getAttribute("data-autofocus") !== "false";
  var finePointer = window.matchMedia && window.matchMedia("(pointer: fine)").matches;
  if (home && finePointer) input.focus({ preventScroll: true });

  // Home on desktop: a click on empty space hands focus back to the prompt,
  // like a terminal. Links, options and text selections are left alone.
  if (home && finePointer) {
    document.addEventListener("click", function (e) {
      if (e.target.closest && e.target.closest("a, button, input, li[role=option], .note")) return;
      var sel = window.getSelection && window.getSelection();
      if (sel && String(sel)) return;
      input.focus({ preventScroll: true });
    });
  }

  // Intro (html.intro, set by an inline head script): any key or click ends it.
  // The listener never cancels the event, so a first "/" still lands.
  var root = document.documentElement;
  if (root.classList.contains("intro")) {
    var endIntro = function () {
      root.classList.remove("intro");
      document.removeEventListener("keydown", endIntro, true);
      document.removeEventListener("pointerdown", endIntro, true);
    };
    document.addEventListener("keydown", endIntro, true);
    document.addEventListener("pointerdown", endIntro, true);
    setTimeout(endIntro, 1500);
  }
})();
