/* Math Path: the page every window shows (v0.1).
 *
 * Python owns the state and sends the whole screen as HTML with mp.render({...}). This file only
 * draws it, types the math with MathJax (Anki's own, or MathLive's static renderer when MathJax is
 * not there, so a page never shows raw LaTeX), keeps the math fields' contents, and reports what
 * the learner does through pycmd as mp:<kind>:<args> (math_path/pages.py lists them).
 *
 * Everything here is offline: no sounds, no virtual keyboard, no menu, fonts from this add-on's own
 * folder. The palette buttons never take the focus from the field being typed in.
 */
(function () {
  "use strict";

  var script = document.currentScript;
  var base = script && script.src ? script.src.slice(0, script.src.lastIndexOf("/") + 1) : "";
  var root = null;
  var active = ""; // id of the math field (or text box) that last had the focus
  var readonly = {};

  function bridge(cmd) {
    if (typeof pycmd === "function") {
      pycmd(cmd);
    }
  }

  // Before any <math-field> is parsed: fonts from this add-on's own folder, no sounds.
  (function () {
    var M = (window.MathLive && window.MathLive.MathfieldElement) || window.MathfieldElement;
    if (M) {
      M.fontsDirectory = base + "mathlive/fonts";
      M.soundsDirectory = null;
      M.keypressSound = null;
      M.plonkSound = null;
    }
  })();

  function fieldEl(id) {
    return root ? root.querySelector('math-field[data-id="' + id + '"]') : null;
  }

  function textEl(id) {
    return root ? root.querySelector('[data-id="' + id + '"]:not(math-field)') : null;
  }

  function currentId() {
    var a = document.activeElement;
    if (a && a.getAttribute && a.getAttribute("data-id")) {
      return a.getAttribute("data-id");
    }
    var host = a && a.closest ? a.closest("math-field") : null;
    return host ? host.getAttribute("data-id") : "";
  }

  function latexOf(mf) {
    try {
      return mf.getValue("latex");
    } catch (e) {
      return "";
    }
  }

  function wireField(mf, value) {
    mf.smartFence = false;
    mf.smartMode = false;
    mf.smartSuperscript = false; // x^10 keeps both digits in the exponent; the arrow leaves it
    mf.mathVirtualKeyboardPolicy = "manual";
    var id = mf.getAttribute("data-id");
    mf.readOnly = !!readonly[id];
    if (value) {
      try {
        mf.setValue(value, { silenceNotifications: true });
      } catch (e) {
        mf.value = value;
      }
    }
    mf.addEventListener("input", function () {
      bridge("mp:field:" + id + ":" + latexOf(mf));
    });
    mf.addEventListener("focusin", function () {
      active = id;
      bridge("mp:focus:" + id);
    });
  }

  function typeset() {
    if (!root) {
      return;
    }
    var mj = window.MathJax;
    if (mj && mj.typesetPromise) {
      var go = function () {
        mj.typesetPromise([root]).catch(function () {});
      };
      if (mj.startup && mj.startup.promise) {
        mj.startup.promise.then(go).catch(function () {});
      } else {
        go();
      }
      return;
    }
    var ML = window.MathLive;
    if (ML && ML.renderMathInElement) {
      try {
        ML.renderMathInElement(root, {
          TeX: { delimiters: { inline: [["\\(", "\\)"]], display: [] }, processEnvironments: false },
          renderAccessibleContent: "",
        });
      } catch (e) {
        /* leave the text as it is */
      }
    }
  }

  function focusId(id) {
    if (!id) {
      return;
    }
    var mf = fieldEl(id);
    if (mf) {
      mf.focus();
      window.requestAnimationFrame(function () {
        if (!readonly[id]) {
          mf.focus();
        }
      });
      return;
    }
    var t = textEl(id);
    if (t && t.focus) {
      t.focus();
    }
  }

  // Put the new screen in place without ever taking `el` (the focused field) out of the page:
  // walk from the root down to it, and at each level swap in the new siblings around the one node
  // on the path. False when the new screen has no element in the same place (then rebuild).
  function morphAround(el, html) {
    var tpl = document.createElement("template");
    tpl.innerHTML = html;
    var id = el.getAttribute("data-id");
    var twin = tpl.content.querySelector('[data-id="' + id + '"]');
    if (!twin || twin.tagName !== el.tagName) {
      return false;
    }
    var livePath = [];
    var newPath = [];
    for (var a = el; a && a !== root; a = a.parentNode) livePath.unshift(a);
    for (var b = twin; b && b !== tpl.content; b = b.parentNode) newPath.unshift(b);
    if (livePath.length !== newPath.length) {
      return false;
    }
    for (var d = 0; d < livePath.length; d++) {
      if (livePath[d].tagName !== newPath[d].tagName) {
        return false;
      }
    }
    var liveParent = root;
    var newParent = tpl.content;
    for (var i = 0; i < livePath.length; i++) {
      var keep = livePath[i];
      var repl = newPath[i];
      // everything in liveParent except `keep` is replaced by repl's siblings, in order
      var before = [];
      var after = [];
      var seen = false;
      var kids = Array.prototype.slice.call(newParent.childNodes);
      for (var k = 0; k < kids.length; k++) {
        if (kids[k] === repl) { seen = true; continue; }
        (seen ? after : before).push(kids[k]);
      }
      var old = Array.prototype.slice.call(liveParent.childNodes);
      for (var o = 0; o < old.length; o++) {
        if (old[o] !== keep) liveParent.removeChild(old[o]);
      }
      for (var x = 0; x < before.length; x++) liveParent.insertBefore(before[x], keep);
      for (var y = 0; y < after.length; y++) liveParent.appendChild(after[y]);
      if (i < livePath.length - 1) {
        // sync the kept ancestor's attributes with the new one
        var at;
        for (at = keep.attributes.length - 1; at >= 0; at--) {
          var n = keep.attributes[at].name;
          if (!repl.hasAttribute(n)) keep.removeAttribute(n);
        }
        for (at = 0; at < repl.attributes.length; at++) {
          keep.setAttribute(repl.attributes[at].name, repl.attributes[at].value);
        }
      }
      liveParent = keep;
      newParent = repl;
    }
    if (el.tagName === "INPUT") {
      el.className = twin.className;
      el.readOnly = twin.hasAttribute("readonly");
    }
    return true;
  }

  // v.keep: a redraw after a focus/field/text message. The live fields and text boxes stay the
  // same elements (their value, caret and listeners survive); Python's copy of their value may be
  // a keystroke behind, so it is not written back. The field that had the focus gets it back
  // synchronously, before any key event can arrive.
  function render(v) {
    if (!root) {
      root = document.getElementById("mp-root");
    }
    var kept = {};
    var had = "";
    if (v.keep) {
      had = currentId();
      var live = root.querySelectorAll("math-field[data-id], input[data-id]");
      for (var k = 0; k < live.length; k++) {
        kept[live[k].getAttribute("data-id")] = live[k];
      }
    }
    var oldMain = root.querySelector(".mp-main");
    var y = oldMain ? oldMain.scrollTop : 0;
    readonly = {};
    (v.readonly || []).forEach(function (id) {
      readonly[id] = true;
    });
    document.documentElement.classList.toggle("night-mode", !!v.night);
    var pinned = v.keep && had && kept[had] ? kept[had] : null;
    if (!pinned || !morphAround(pinned, v.html)) {
      root.innerHTML = v.html;
    }
    var fields = v.fields || {};
    var mfs = root.querySelectorAll("math-field");
    for (var i = 0; i < mfs.length; i++) {
      var mid = mfs[i].getAttribute("data-id");
      var oldMf = kept[mid];
      if (oldMf && oldMf.tagName === "MATH-FIELD") {
        if (mfs[i] !== oldMf) mfs[i].replaceWith(oldMf);
        oldMf.readOnly = !!readonly[mid];
      } else {
        delete kept[mid];
        wireField(mfs[i], fields[mid] || "");
      }
    }
    var ins = root.querySelectorAll("input[data-id]");
    for (var j = 0; j < ins.length; j++) {
      var iid = ins[j].getAttribute("data-id");
      var oldIn = kept[iid];
      if (oldIn && oldIn.tagName === "INPUT") {
        if (ins[j] !== oldIn) {
          oldIn.className = ins[j].className;
          oldIn.readOnly = ins[j].hasAttribute("readonly");
          ins[j].replaceWith(oldIn);
        }
      } else {
        delete kept[iid];
      }
    }
    var texts = v.texts || {};
    Object.keys(texts).forEach(function (id) {
      var el = textEl(id);
      if (el && "value" in el && !kept[id]) {
        el.value = texts[id];
      }
    });
    typeset();
    var newMain = root.querySelector(".mp-main");
    if (newMain) {
      newMain.scrollTop = y;
    }
    if (v.keep) {
      var back = had ? fieldEl(had) || textEl(had) : null;
      if (back && currentId() !== had) {
        back.focus();
      }
      return;
    }
    var want = v.focus || active;
    if (want && (fieldEl(want) || textEl(want))) {
      focusId(want);
    }
  }

  function press(button) {
    var id = active && fieldEl(active) ? active : "";
    if (!id) {
      var first = root.querySelector("math-field:not([data-ro])");
      id = first ? first.getAttribute("data-id") : "";
    }
    var mf = id ? fieldEl(id) : null;
    if (!mf || readonly[id]) {
      return;
    }
    var op = button.getAttribute("data-op");
    var arg = button.getAttribute("data-arg");
    if (op === "insert") {
      mf.insert(arg, { focus: true, feedback: false });
    } else if (op === "command") {
      mf.executeCommand(arg);
    }
    mf.focus();
    bridge("mp:field:" + id + ":" + latexOf(mf));
  }

  function up(el, pred) {
    while (el && el !== document.body) {
      if (pred(el)) {
        return el;
      }
      el = el.parentNode;
    }
    return null;
  }

  document.addEventListener("mousedown", function (e) {
    // A palette button must not take the focus (and the caret) from the field.
    if (up(e.target, function (n) { return n.classList && n.classList.contains("mp-padbtn"); })) {
      e.preventDefault();
    }
  });

  document.addEventListener("click", function (e) {
    var pad = up(e.target, function (n) { return n.classList && n.classList.contains("mp-padbtn"); });
    if (pad) {
      press(pad);
      return;
    }
    var el = up(e.target, function (n) { return n.getAttribute && n.getAttribute("data-act"); });
    if (el && !el.disabled && el.getAttribute("aria-disabled") !== "true") {
      var arg = el.getAttribute("data-arg");
      bridge("mp:act:" + el.getAttribute("data-act") + (arg === null ? "" : ":" + arg));
    }
  });

  document.addEventListener("input", function (e) {
    var t = e.target;
    if (t && t.getAttribute && t.getAttribute("data-id") && t.tagName === "INPUT") {
      bridge("mp:text:" + t.getAttribute("data-id") + ":" + t.value);
    }
  });

  document.addEventListener("change", function (e) {
    var t = e.target;
    if (t && t.tagName === "SELECT" && t.getAttribute("data-id")) {
      bridge("mp:select:" + t.getAttribute("data-id") + ":" + t.value);
    }
  });

  document.addEventListener("focusin", function (e) {
    var t = e.target;
    if (t && t.tagName === "INPUT" && t.getAttribute("data-id")) {
      active = t.getAttribute("data-id");
      bridge("mp:focus:" + active);
    }
  });

  // The window's keys win over MathLive's and Anki's: Enter checks or goes on, Esc closes help.
  window.addEventListener(
    "keydown",
    function (e) {
      var cmd = null;
      var mod = e.ctrlKey || e.metaKey;
      if (e.key === "Enter") {
        cmd = mod ? "mp:ctrl-enter:" : "mp:enter:" + currentId();
      } else if (e.key === "Escape") {
        cmd = "mp:esc:";
      }
      if (cmd === null) {
        return;
      }
      e.preventDefault();
      e.stopPropagation();
      var id = currentId();
      var mf = id ? fieldEl(id) : null;
      if (mf) {
        bridge("mp:field:" + id + ":" + latexOf(mf));
      }
      bridge(cmd);
    },
    true
  );

  window.mp = {
    render: render,
    ready: function () {
      return !!root;
    },
    fieldValue: function (id) {
      var mf = fieldEl(id);
      return mf ? latexOf(mf) : "";
    },
    setField: function (id, latex) {
      var mf = fieldEl(id);
      if (mf) {
        mf.setValue(latex);
        bridge("mp:field:" + id + ":" + latexOf(mf));
      }
    },
    focus: focusId,
  };
})();
