/* Terminal home: wires the locked slash input to the DOM. Logic lives in
   filter.js (SkillFilter); this file only handles events and rendering. */
(function () {
  "use strict";
  var F = window.SkillFilter;
  var dataEl = document.getElementById("skill-data");
  var input = document.getElementById("cmd");
  if (!F || !dataEl || !input) return;

  var items = JSON.parse(dataEl.textContent);
  var names = items.map(function (i) { return i.name; });
  var byName = {};
  items.forEach(function (i) { byName[i.name] = i; });

  var term = document.getElementById("term");
  var echo = document.getElementById("echo");
  var hint = document.getElementById("hint");
  var menu = document.getElementById("menu");
  var status = document.getElementById("status");

  var buffer = "";
  var current = [];
  var active = -1;

  function setBuffer(next) {
    buffer = next;
    if (input.value !== buffer) input.value = buffer;
    caretToEnd();
    current = F.matches(buffer, names);
    active = current.length ? 0 : -1;
    render(true);
  }

  function caretToEnd() {
    try { input.setSelectionRange(buffer.length, buffer.length); } catch (e) { /* not focused */ }
  }

  function render(announce) {
    echo.textContent = buffer;
    hint.hidden = buffer !== "";
    menu.textContent = "";
    current.forEach(function (name, idx) {
      var li = document.createElement("li");
      li.id = "opt-" + idx;
      li.setAttribute("role", "option");
      li.setAttribute("aria-selected", idx === active ? "true" : "false");
      var nm = document.createElement("span");
      nm.className = "nm";
      nm.textContent = "/" + name;
      var ds = document.createElement("span");
      ds.className = "ds";
      ds.textContent = byName[name].summary;
      li.appendChild(nm);
      li.appendChild(ds);
      li.addEventListener("mousedown", function (e) { e.preventDefault(); });
      li.addEventListener("click", function () { go(name); });
      menu.appendChild(li);
    });
    var open = current.length > 0;
    menu.hidden = !open;
    input.setAttribute("aria-expanded", open ? "true" : "false");
    if (active >= 0) input.setAttribute("aria-activedescendant", "opt-" + active);
    else input.removeAttribute("aria-activedescendant");
    if (announce) {
      status.textContent = buffer === "" ? "" :
        current.length + (current.length === 1 ? " matching command" : " matching commands");
    }
  }

  function move(delta) {
    if (!current.length) return;
    active = (active + delta + current.length) % current.length;
    render(false);
    var el = document.getElementById("opt-" + active);
    if (el && el.scrollIntoView) el.scrollIntoView({ block: "nearest" });
  }

  function go(name) {
    var base = (document.body && document.body.getAttribute("data-base")) || "";
    window.location.assign(base + "/" + encodeURIComponent(name));
  }

  // Block invalid insertions before they land (desktop + most mobile).
  input.addEventListener("beforeinput", function (e) {
    if (e.isComposing || /Composition/.test(e.inputType || "")) return;
    if (/^insert/.test(e.inputType || "") && typeof e.data === "string") {
      if (F.accept(buffer, e.data, names) === null) e.preventDefault();
    }
  });

  // Source of truth: roll back anything invalid (Android IME keyCode 229,
  // paste, autofill), accept anything that keeps the buffer valid.
  input.addEventListener("input", function () {
    var v = input.value;
    if (v !== buffer && F.isValid(v, names)) setBuffer(v);
    else { input.value = buffer; caretToEnd(); }
  });

  input.addEventListener("keydown", function (e) {
    if (e.keyCode === 229 || e.isComposing) return;
    switch (e.key) {
      case "Tab":
        if (e.shiftKey || e.altKey || e.ctrlKey || e.metaKey) return;
        var c = F.complete(buffer, names);
        if (c !== null) { e.preventDefault(); setBuffer(c); }
        // No completion: let Tab move focus (no keyboard trap).
        return;
      case "ArrowDown":
        if (current.length) { e.preventDefault(); move(1); }
        return;
      case "ArrowUp":
        if (current.length) { e.preventDefault(); move(-1); }
        return;
      case "Enter":
        e.preventDefault();
        var name = F.resolve(buffer, names, active);
        if (name) go(name);
        return;
      case "Escape":
        if (buffer !== "") { e.preventDefault(); setBuffer(""); }
        return;
      case "ArrowLeft":
      case "Home":
        e.preventDefault(); // caret stays at the end
        return;
    }
  });

  input.addEventListener("focus", caretToEnd);

  // Tap/click anywhere in the terminal focuses the input (opens phone keyboard).
  term.addEventListener("click", function (e) {
    if (e.target.closest && e.target.closest("a, li[role=option]")) return;
    input.focus();
  });

  // "/" anywhere on the page jumps into the terminal.
  document.addEventListener("keydown", function (e) {
    if (e.key !== "/" || e.ctrlKey || e.metaKey || e.altKey) return;
    var t = document.activeElement;
    if (t === input || (t && (t.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName)))) return;
    e.preventDefault();
    input.focus();
    if (buffer === "") setBuffer("/");
  });

  render(false);
  // Home autofocuses on desktop; detail pages opt out (data-autofocus="false").
  if (input.getAttribute("data-autofocus") !== "false" &&
      window.matchMedia && window.matchMedia("(pointer: fine)").matches) {
    input.focus({ preventScroll: true });
  }
})();
