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

  function render(v) {
    if (!root) {
      root = document.getElementById("mp-root");
    }
    var y = window.scrollY;
    readonly = {};
    (v.readonly || []).forEach(function (id) {
      readonly[id] = true;
    });
    document.documentElement.classList.toggle("night-mode", !!v.night);
    root.innerHTML = v.html;
    var fields = v.fields || {};
    var mfs = root.querySelectorAll("math-field");
    for (var i = 0; i < mfs.length; i++) {
      wireField(mfs[i], fields[mfs[i].getAttribute("data-id")] || "");
    }
    var texts = v.texts || {};
    Object.keys(texts).forEach(function (id) {
      var el = textEl(id);
      if (el && "value" in el) {
        el.value = texts[id];
      }
    });
    typeset();
    window.scrollTo(0, y);
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
