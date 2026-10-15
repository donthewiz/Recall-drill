/* Exam tracker (v0.4). Real numbers; see recalldrill/ui/exam_tracker.py.
 *
 * Runs on Anki's deck screen only (Python adds this file to the deck browser's web view while
 * the flag is on). It reads the JSON block Python wrote, adds the status display inside each
 * listed row, and shows the hover card. It never touches the deck link, the gear or dragging.
 * Written as a plain script (no modules) and kept pure where it can be: placeCard() is
 * tested under node (tests/test_exam_tracker_ui.py), and so is slideFrom().
 */
(function (root) {
  'use strict';

  var SHOW_MS = 300; // pause before a hover card appears
  var HIDE_MS = 200; // pause before a card is dismissed after the mouse leaves
  // Motion, all in one place (handed to the CSS as variables on each card):
  // The opening copies the Redesign add-on's deck-name hover: the default `ease`, a small
  // drift, and a drift slower than the fade, so the card is still settling once it is visible.
  var FADE_MS = 400; // opening: opacity
  var SLIDE_MS = 600; // opening: the drift into place (longer than the fade)
  var CLOSE_MS = 150; // closing: opacity only
  var EASE = 'ease';
  var SLIDE_PX = 6; // the card starts this far from its place (direction: slideFrom)
  var SAMPLE_MS = 200; // keep mousemove samples this recent...
  var MAX_SAMPLES = 6; // ...and at most this many
  var MIN_MOVE = 4; // a cursor movement shorter than this counts as none
  var GAP = 6; // card to row when it opens below or above
  var SIDE_GAP = 10; // card to the table's right edge when it opens beside the list
  var MARGIN = 8; // keep this far inside the window
  var ARROW_EDGE = 16; // the pointer arrow stays this far from a card corner
  var PILL_OFFSET = 20; // below/above: the arrow aims this far right of the pill's left edge

  function clamp(v, lo, hi) {
    return Math.max(lo, Math.min(v, hi));
  }

  /* Where a card of `card` size goes for a row at `anchor` (all viewport pixels): `left` is the
   * status pill's left edge, `top`/`bottom` the row's, `right` the table's right edge.
   * 1. Beside the list: right of the table (sideGap), top level with the row, pulled onto screen.
   * 2. Else just below the row, left edge on the pill; above when below has no room.
   * 3. Else shifted left to stay visible. Never cut off.
   * `arrow` is the pointer arrow's offset along the card edge facing the row. */
  function placeCard(anchor, card, view, gap, margin, sideGap) {
    var side;
    var left;
    var top;
    var arrow;
    var edge = sideGap === undefined ? gap : sideGap;
    if (anchor.right + edge + card.width + margin <= view.width) {
      side = 'right';
      left = anchor.right + edge;
      top = clamp(anchor.top, margin, view.height - card.height - margin);
      top = Math.max(margin, top);
      arrow = clamp(
        (anchor.top + anchor.bottom) / 2 - top,
        ARROW_EDGE,
        Math.max(ARROW_EDGE, card.height - ARROW_EDGE)
      );
      return { left: left, top: top, side: side, arrow: arrow };
    }
    left = Math.max(margin, Math.min(anchor.left, view.width - card.width - margin));
    var below = anchor.bottom + gap;
    var above = anchor.top - gap - card.height;
    var roomBelow = view.height - margin - below;
    var roomAbove = anchor.top - gap - margin;
    if (card.height <= roomBelow) {
      side = 'below';
      top = below;
    } else if (card.height <= roomAbove) {
      side = 'above';
      top = above;
    } else {
      side = roomBelow >= roomAbove ? 'below' : 'above';
      top = side === 'below' ? below : above;
    }
    top = Math.max(margin, Math.min(top, view.height - card.height - margin));
    arrow = clamp(
      anchor.left + PILL_OFFSET - left,
      ARROW_EDGE,
      Math.max(ARROW_EDGE, card.width - ARROW_EDGE)
    );
    return { left: left, top: top, side: side, arrow: arrow };
  }

  /* The card's start offset {dx, dy} in px (it glides from there into place), from the cursor's
   * recent `samples` [{x, y, t}] and the card's `openSide` ('right', 'below' or 'above').
   * First-to-last vector, snapped to its dominant axis (ties go vertical); the card starts
   * SLIDE_PX opposite to the movement. Under MIN_MOVE px, or with fewer than 2 samples, the
   * default for the open side. No DOM. */
  function slideFrom(samples, openSide) {
    if (samples && samples.length >= 2) {
      var a = samples[0];
      var b = samples[samples.length - 1];
      var vx = b.x - a.x;
      var vy = b.y - a.y;
      if (Math.sqrt(vx * vx + vy * vy) >= MIN_MOVE) {
        if (Math.abs(vx) > Math.abs(vy)) return { dx: vx > 0 ? -SLIDE_PX : SLIDE_PX, dy: 0 };
        return { dx: 0, dy: vy > 0 ? -SLIDE_PX : SLIDE_PX };
      }
    }
    if (openSide === 'right') return { dx: -SLIDE_PX, dy: 0 };
    if (openSide === 'above') return { dx: 0, dy: SLIDE_PX };
    return { dx: 0, dy: -SLIDE_PX };
  }

  if (typeof module !== 'undefined' && module.exports) {
    module.exports = { placeCard: placeCard, slideFrom: slideFrom };
  }
  if (typeof document === 'undefined') return;

  var data = { decks: {}, pinned: null };
  var hoverCard = null; // {did, el}
  var pinCard = null; // {did, el}
  var pointerKey = null;
  var focusKey = null;
  var samples = []; // recent mousemove samples over the current row (cleared on leaving it)
  var showTimer = null;
  var hideTimer = null;

  function send(cmd) {
    if (typeof root.pycmd === 'function') root.pycmd(cmd);
  }

  function rowFor(did) {
    return document.getElementById(did);
  }

  function reducedMotion() {
    return !!(root.matchMedia && root.matchMedia('(prefers-reduced-motion: reduce)').matches);
  }

  function makeCard(did) {
    var wrap = document.createElement('div');
    wrap.innerHTML = data.decks[did].card; // built and escaped by Python
    var el = wrap.firstChild;
    el.setAttribute('data-did', did);
    el.style.setProperty('--rd-fade-ms', FADE_MS + 'ms');
    el.style.setProperty('--rd-slide-ms', SLIDE_MS + 'ms');
    el.style.setProperty('--rd-close-ms', CLOSE_MS + 'ms');
    el.style.setProperty('--rd-ease', EASE);
    document.body.appendChild(el); // invisible and click-through until .rd-in is added
    return el;
  }

  function place(did, el) {
    var row = rowFor(did);
    if (!row) return;
    var r = row.getBoundingClientRect();
    var table = row.closest('table');
    var t = table ? table.getBoundingClientRect() : r;
    var pill = row.querySelector('.rd-pill');
    var pl = pill ? pill.getBoundingClientRect().left : r.left + 16;
    var c = el.getBoundingClientRect();
    var view = {
      width: document.documentElement.clientWidth,
      height: document.documentElement.clientHeight
    };
    var p = placeCard(
      { left: pl, top: r.top, right: Math.max(t.right, r.right), bottom: r.bottom },
      { width: c.width, height: c.height },
      view,
      GAP,
      MARGIN,
      SIDE_GAP
    );
    el.style.left = p.left + 'px';
    el.style.top = p.top + 'px';
    el.style.setProperty('--rd-arrow', p.arrow + 'px');
    el.setAttribute('data-side', p.side);
    return p.side;
  }

  /* Opens the card: opacity, a slide from the cursor's direction (`moved` = use the samples;
   * pinning and keyboard focus use the open side's default). The CSS makes it
   * instant under reduced motion. */
  function reveal(el, side, moved) {
    var from = slideFrom(moved ? samples : [], side);
    el.style.setProperty('--rd-from-x', from.dx + 'px');
    el.style.setProperty('--rd-from-y', from.dy + 'px');
    void el.offsetWidth; // commit the hidden state so the transition runs
    el.classList.add('rd-in');
  }

  /* Fades the card out (opacity only) and removes it. It takes no clicks while it fades. */
  function dismiss(el) {
    el.classList.remove('rd-in');
    el.classList.add('rd-out');
    if (reducedMotion()) el.remove();
    else setTimeout(function () { el.remove(); }, CLOSE_MS);
  }

  function closeHover() {
    if (hoverCard) {
      dismiss(hoverCard.el);
      hoverCard = null;
    }
  }

  function closePin() {
    if (pinCard) {
      var pill = pillFor(pinCard.did);
      if (pill) pill.setAttribute('aria-pressed', 'false');
      dismiss(pinCard.el);
      pinCard = null;
    }
  }

  function pillFor(did) {
    var row = rowFor(did);
    return row ? row.querySelector('.rd-pill') : null;
  }

  function showHover(did, moved) {
    if (!data.decks[did] || !rowFor(did)) return;
    if (pinCard && pinCard.did === did) return;
    if (hoverCard && hoverCard.did === did) return;
    closeHover();
    hoverCard = { did: did, el: makeCard(did) };
    reveal(hoverCard.el, place(did, hoverCard.el), moved);
  }

  /* Shows the card at once (no show delay); a hover card already open becomes the pinned one. */
  function pin(did) {
    closePin();
    if (hoverCard && hoverCard.did === did) {
      pinCard = hoverCard;
      hoverCard = null;
      pinCard.el.classList.add('rd-pinned');
      place(did, pinCard.el);
    } else {
      closeHover();
      pinCard = { did: did, el: makeCard(did) };
      pinCard.el.classList.add('rd-pinned');
      reveal(pinCard.el, place(did, pinCard.el), false);
    }
    var pill = pillFor(did);
    if (pill) pill.setAttribute('aria-pressed', 'true');
  }

  function unpin(tellPython) {
    closePin();
    if (tellPython) send('rdet:unpin');
  }

  function activeKey() {
    return focusKey !== null ? focusKey : pointerKey;
  }

  function clearTimers() {
    clearTimeout(showTimer);
    clearTimeout(hideTimer);
    showTimer = null;
    hideTimer = null;
  }

  /* Called after any pointer or focus change. */
  function sync() {
    var key = activeKey();
    var shown = hoverCard ? hoverCard.did : null;
    if (key !== null && key === shown) {
      clearTimeout(hideTimer);
      hideTimer = null;
      clearTimeout(showTimer);
      showTimer = null;
      return;
    }
    if (shown !== null) {
      clearTimeout(hideTimer);
      hideTimer = setTimeout(function () {
        if (activeKey() !== (hoverCard && hoverCard.did)) closeHover();
      }, HIDE_MS);
    }
    clearTimeout(showTimer);
    showTimer = null;
    if (key !== null && !(pinCard && pinCard.did === key)) {
      showTimer = setTimeout(function () {
        if (activeKey() === key) showHover(key, focusKey === null);
      }, SHOW_MS);
    }
  }

  function keyOf(target) {
    if (!target || !target.closest) return null;
    var card = target.closest('.rd-card');
    if (card) return card.getAttribute('data-did');
    var row = target.closest('tr.deck');
    return row && data.decks[row.id] ? row.id : null;
  }

  function onOver(e) {
    var key = keyOf(e.target);
    if (key !== pointerKey) samples = []; // only what happened over the current row counts
    pointerKey = key;
    focusKey = null; // the pointer took over from the keyboard
    sync();
  }

  function onOut(e) {
    if (!e.relatedTarget) {
      pointerKey = null;
      samples = [];
      sync();
    }
  }

  function onMove(e) {
    if (pointerKey === null) return;
    var t = e.timeStamp || Date.now();
    samples.push({ x: e.clientX, y: e.clientY, t: t });
    while (samples.length > MAX_SAMPLES || (samples.length > 1 && t - samples[0].t > SAMPLE_MS)) {
      samples.shift();
    }
  }

  function onFocusIn(e) {
    var pill = e.target.closest && e.target.closest('.rd-pill');
    if (!pill) return;
    focusKey = keyOf(pill);
    clearTimers();
    if (focusKey !== null) showHover(focusKey, false);
  }

  function onFocusOut(e) {
    var pill = e.target.closest && e.target.closest('.rd-pill');
    if (!pill) return;
    focusKey = null;
    sync();
  }

  function onClick(e) {
    var pill = e.target.closest && e.target.closest('.rd-pill');
    if (!pill) return;
    var did = keyOf(pill);
    if (did === null) return;
    e.preventDefault();
    clearTimers(); // pinning is immediate: no pending show or hide
    if (pinCard && pinCard.did === did) {
      unpin(true);
      showHover(did, false);
    } else {
      pin(did);
      send('rdet:pin:' + did);
    }
  }

  function onKey(e) {
    if (e.key !== 'Escape') return;
    clearTimers();
    closeHover();
    if (pinCard) unpin(true);
  }

  function reposition() {
    if (hoverCard) closeHover();
    if (pinCard) place(pinCard.did, pinCard.el);
  }

  function init() {
    var node = document.getElementById('rd-exam-tracker-data');
    if (!node) return;
    try {
      data = JSON.parse(node.textContent || '{}');
    } catch (err) {
      return;
    }
    Object.keys(data.decks).forEach(function (did) {
      var row = rowFor(did);
      var cell = row && row.querySelector('td.decktd');
      if (cell) {
        cell.insertAdjacentHTML('beforeend', data.decks[did].row);
        row.classList.add('rd-has-et');
      } else delete data.decks[did];
    });
    document.addEventListener('mouseover', onOver);
    document.addEventListener('mouseout', onOut);
    document.addEventListener('mousemove', onMove);
    document.addEventListener('focusin', onFocusIn);
    document.addEventListener('focusout', onFocusOut);
    document.addEventListener('click', onClick);
    document.addEventListener('keydown', onKey);
    root.addEventListener('resize', reposition);
    root.addEventListener('scroll', reposition, true);
    if (data.pinned !== null && data.decks[data.pinned]) pin(String(data.pinned));
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
})(typeof window !== 'undefined' ? window : this);
