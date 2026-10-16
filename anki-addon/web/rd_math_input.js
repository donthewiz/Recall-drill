/* Recall Drill: the math answer field and its palette (v0.6).
 *
 * Loaded with MathLive (web/mathlive/) into the drill window's second web view. The page's
 * HTML comes from recalldrill/math_input.py. Everything here is offline: no sounds, no virtual
 * keyboard, no menu, fonts from this add-on's own folder.
 *
 * Python talks to this page with window.rdMath.* (evals) and hears back through pycmd:
 *   rd:math:<latex>   the field's value, on every change and before every command below
 *   rd:enter | rd:ctrl-enter | rd:reveal | rd:edit | rd:replay | rd:extra   the drill's keys
 */
(function () {
  "use strict";

  var script = document.currentScript;
  var base = script && script.src ? script.src.slice(0, script.src.lastIndexOf("/") + 1) : "";
  var mf = null;
  var mounted = false;
  var sent = null;
  var pending = { readOnly: false, placeholder: "" };

  function bridge(cmd) {
    if (typeof pycmd === "function") {
      pycmd(cmd);
    }
  }

  function latex() {
    try {
      return mf ? mf.getValue("latex") : "";
    } catch (e) {
      return "";
    }
  }

  function push(force) {
    var v = latex();
    if (force || v !== sent) {
      sent = v;
      bridge("rd:math:" + v);
    }
  }

  function apply() {
    if (!mf) {
      return;
    }
    mf.readOnly = !!pending.readOnly;
    mf.setAttribute("placeholder", pending.placeholder || "");
    document.getElementById("rd-pad").classList.toggle("rd-pad-off", !!pending.readOnly);
    var buttons = document.querySelectorAll("#rd-pad button");
    for (var i = 0; i < buttons.length; i++) {
      buttons[i].disabled = !!pending.readOnly;
    }
  }

  function press(button) {
    if (!mf || pending.readOnly) {
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
    push(false);
  }

  var KEYS = { Enter: "rd:enter", Escape: "rd:reveal" };

  // Before the page's <math-field> is parsed (MathLive starts loading its fonts as soon as the
  // element exists): fonts from this add-on's own folder, no sounds, nothing from the network.
  (function () {
    var M = (window.MathLive && window.MathLive.MathfieldElement) || window.MathfieldElement;
    if (M) {
      M.fontsDirectory = base + "mathlive/fonts";
      M.soundsDirectory = null;
      M.keypressSound = null;
      M.plonkSound = null;
    }
  })();

  function onKey(e) {
    var cmd = null;
    var mod = e.ctrlKey || e.metaKey;
    if (e.key === "Enter") {
      cmd = mod ? "rd:ctrl-enter" : KEYS.Enter;
    } else if (e.key === "Escape") {
      cmd = KEYS.Escape;
    } else if (mod && (e.key === "e" || e.key === "E")) {
      cmd = "rd:edit";
    } else if (mod && (e.key === "r" || e.key === "R")) {
      cmd = "rd:replay";
    } else if (mod && (e.key === "i" || e.key === "I")) {
      cmd = "rd:extra";
    }
    if (cmd === null) {
      return;
    }
    // Before MathLive (and Anki's own Escape handler) see it: the drill's keys always win.
    e.preventDefault();
    e.stopPropagation();
    push(true);
    bridge(cmd);
  }

  function init() {
    mf = document.getElementById("rd-mf");
    mf.smartFence = false;
    mf.smartMode = false;
    mf.smartSuperscript = false; // x^10 keeps both digits in the exponent; the arrow leaves it
    mf.mathVirtualKeyboardPolicy = "manual";
    mf.addEventListener("input", function () {
      push(false);
    });
    var pad = document.getElementById("rd-pad");
    // Clicking a palette button must not take the focus (and the caret) from the field.
    pad.addEventListener("mousedown", function (e) {
      e.preventDefault();
    });
    pad.addEventListener("click", function (e) {
      var t = e.target;
      while (t && t !== pad && t.tagName !== "BUTTON") {
        t = t.parentNode;
      }
      if (t && t.tagName === "BUTTON") {
        press(t);
      }
    });
    apply();
    // MathLive mounts asynchronously: focus (and lock) again once it is ready.
    if (mounted && !pending.readOnly) {
      mf.focus();
      // MathLive hands the caret to its hidden input a frame later.
      window.requestAnimationFrame(function () {
        if (!pending.readOnly) {
          mf.focus();
        }
      });
    }
  }

  // MathLive mounts the field while the page is still being parsed, before init() runs.
  document.addEventListener(
    "mount",
    function () {
      mounted = true;
      if (mf) {
        apply();
        if (!pending.readOnly) {
          mf.focus();
        }
      }
    },
    true
  );
  window.addEventListener("keydown", onKey, true);
  document.addEventListener("DOMContentLoaded", init);

  window.rdMath = {
    ready: function () {
      return mounted;
    },
    value: latex,
    /* {readOnly, placeholder, night}: called on every render of the drill window. */
    configure: function (opts) {
      pending.readOnly = !!opts.readOnly;
      pending.placeholder = opts.placeholder || "";
      document.documentElement.classList.toggle("night-mode", !!opts.night);
      apply();
    },
    clear: function () {
      if (mf) {
        mf.setValue("");
      }
      push(true);
    },
    focus: function () {
      if (mf) {
        mf.focus();
      }
    },
    set: function (value) {
      if (mf) {
        mf.setValue(value);
      }
      push(true);
    },
  };
})();
