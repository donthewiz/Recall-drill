/* Exam tracker hover test (v0.4 step 1). FAKE numbers; see recalldrill/ui/exam_tracker_demo.py.
 *
 * Runs on Anki's deck screen only (Python adds this file to the deck browser's web view while
 * the flag is on). It reads the JSON block Python wrote, adds the status display inside each
 * listed row, and shows the hover card. It never touches the deck link, the gear or dragging.
 * Written as a plain script (no modules) and kept pure where it can be: placeCard() is
 * tested under node (tests/test_exam_tracker_js.py).
 */
(function (root) {
  'use strict';

  var SHOW_MS = 250;
  var HIDE_MS = 200;
  var GAP = 6;
  var MARGIN = 8;

  /* Where a card of `card` size goes for a row at `anchor` (all viewport pixels).
   * Below the row when it fits above the window's bottom edge, else above it, else on the side
   * with more room, pulled inside the window. Shifted left when too wide; never cut off. */
  function placeCard(anchor, card, view, gap, margin) {
    var maxLeft = view.width - card.width - margin;
    var left = Math.max(margin, Math.min(anchor.left, maxLeft));
    var below = anchor.bottom + gap;
    var above = anchor.top - gap - card.height;
    var roomBelow = view.height - margin - below;
    var roomAbove = anchor.top - gap - margin;
    var side;
    var top;
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
    return { left: left, top: top, side: side };
  }

  if (typeof module !== 'undefined' && module.exports) {
    module.exports = { placeCard: placeCard };
  }
  if (typeof document === 'undefined') return;

  var data = { decks: {}, pinned: null };
  var hoverCard = null; // {did, el}
  var pinCard = null; // {did, el}
  var pointerKey = null;
  var focusKey = null;
  var showTimer = null;
  var hideTimer = null;

  function send(cmd) {
    if (typeof root.pycmd === 'function') root.pycmd(cmd);
  }

  function rowFor(did) {
    return document.getElementById(did);
  }

  function makeCard(did) {
    var wrap = document.createElement('div');
    wrap.innerHTML = data.decks[did].card; // built and escaped by Python
    var el = wrap.firstChild;
    el.setAttribute('data-did', did);
    el.style.visibility = 'hidden';
    document.body.appendChild(el);
    return el;
  }

  function place(did, el) {
    var row = rowFor(did);
    if (!row) return;
    var r = row.getBoundingClientRect();
    var c = el.getBoundingClientRect();
    var view = {
      width: document.documentElement.clientWidth,
      height: document.documentElement.clientHeight
    };
    var p = placeCard(
      { left: r.left + 16, top: r.top, right: r.right, bottom: r.bottom },
      { width: c.width, height: c.height },
      view,
      GAP,
      MARGIN
    );
    el.style.left = p.left + 'px';
    el.style.top = p.top + 'px';
    el.setAttribute('data-side', p.side);
    el.style.visibility = 'visible';
  }

  function closeHover() {
    if (hoverCard) {
      hoverCard.el.remove();
      hoverCard = null;
    }
  }

  function closePin() {
    if (pinCard) {
      var pill = pillFor(pinCard.did);
      if (pill) pill.setAttribute('aria-pressed', 'false');
      pinCard.el.remove();
      pinCard = null;
    }
  }

  function pillFor(did) {
    var row = rowFor(did);
    return row ? row.querySelector('.rd-pill') : null;
  }

  function showHover(did) {
    if (!data.decks[did] || !rowFor(did)) return;
    if (pinCard && pinCard.did === did) return;
    if (hoverCard && hoverCard.did === did) return;
    closeHover();
    hoverCard = { did: did, el: makeCard(did) };
    place(did, hoverCard.el);
  }

  function pin(did) {
    closeHover();
    closePin();
    pinCard = { did: did, el: makeCard(did) };
    pinCard.el.classList.add('rd-pinned');
    place(did, pinCard.el);
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
        if (activeKey() === key) showHover(key);
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
    pointerKey = keyOf(e.target);
    focusKey = null; // the pointer took over from the keyboard
    sync();
  }

  function onOut(e) {
    if (!e.relatedTarget) {
      pointerKey = null;
      sync();
    }
  }

  function onFocusIn(e) {
    var pill = e.target.closest && e.target.closest('.rd-pill');
    if (!pill) return;
    focusKey = keyOf(pill);
    clearTimers();
    if (focusKey !== null) showHover(focusKey);
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
    if (pinCard && pinCard.did === did) {
      unpin(true);
      showHover(did);
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
      if (cell) cell.insertAdjacentHTML('beforeend', data.decks[did].row);
      else delete data.decks[did];
    });
    document.addEventListener('mouseover', onOver);
    document.addEventListener('mouseout', onOut);
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
