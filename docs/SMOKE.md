# Manual Smoke Checklist

Called for at the end of Part 4 of [`docs/V2-HANDOFF.md`](./V2-HANDOFF.md):
a hand-run pass over the things the automated suite (`npm test`) and the
trial-count harness (`npm run simulate`) don't cover — real browser timing,
localStorage round-trips across a page reload, and interaction sequences a
human actually clicks through. Run this before calling a release done;
`npm test` passing is necessary but not sufficient.

Each item names the concrete UI text/labels as they exist today, not as
originally spec'd — several changed shape across the phases (C1–C9, plus
the `MIN_WORDS_TO_CHUNK` tuning pass) that shipped since this checklist was
first written.

---

## 1. Start a fresh session

- [ ] From Setup, build or import a small deck with at least one **short**
      card (back ≤8 words — lands on the `full` stage directly, no
      chunking) and one **long** card (back >8 words — gets chunked; the
      typing-difficulty slider controls how many chunks).
- [ ] Click **Start session**. On the long card's first chunk, attempt 0 is
      a **presentation**: the chunk's full text is shown, the input is
      read-only with a "Press Enter to continue" placeholder, there's a
      **Read & Continue** badge, and the button reads **Continue** — not
      "Check answer". No "Show target" button (nothing to reveal).
- [ ] Press Enter/click Continue. The badge switches to **Blind Recall**
      and the input becomes typable with a generic "Type ... from memory..."
      placeholder. Type the chunk correctly — it should advance to the next
      chunk (or combining) immediately, regardless of what the "Blind
      typings required" slider is set to (that slider no longer paces
      individual chunks, only the final combination and short cards).
- [ ] On the short card, attempt 0 shows a **first-letter cue** instead (e.g.
      `T__ h____ p____ b____`) with a **First-Letter Cue** badge — not a
      presentation, since there's no chunk ladder for a short answer.
- [ ] The progress bar(s) move off 0% after the first correctly-completed
      chunk — they should not sit at 0% through the whole encode phase.

## 2. Mid-session refresh and resume

- [ ] Partway through encoding (some items `new`, some `encoding`, none
      `mastered` yet), reload the browser tab.
- [ ] Back on Setup, starting the same deck name should surface
      "Found a previous session for '\<name\>' with N of M items mastered"
      with the **correct** mastered count.
- [ ] Click **Resume session**. You should land back on the exact stage/
      streak state you left (e.g. still on the same chunk, same
      presentation-vs-blind state), not a restarted session.

## 3. Batch interstitial save-and-stop

- [ ] Use a deck with more cards than the configured batch size (e.g. 6
      cards at batch size 3, so there are 2 batches).
- [ ] Fully encode and cycle-master every card in batch 1. The
      **"Batch 1 of 2 complete!"** interstitial should appear with correct
      Mastered / Trials / Accuracy numbers for just that batch.
- [ ] Click **Save and stop**. DoneView should read "Session Saved" (not
      "Deck Mastered!", since batch 2 hasn't run).
- [ ] From Setup, resume that session. It should land directly back on the
      **same interstitial** — not re-run batch 1, and not skip ahead to
      DoneView.
- [ ] Click **Next batch**. Batch 2 should start its own encode phase,
      interleaving only its own cards.

## 4. Override on a wrong answer

- [ ] Deliberately type a wrong answer on a **blind** attempt (not a
      presentation — those can't be graded, so there's nothing to
      override) and check it. Feedback should show and **not**
      auto-advance — a **Continue** button and a **Count as correct**
      button both appear.
- [ ] Click **Count as correct** (or press `Ctrl+Enter`). The streak
      advances exactly as a genuine correct answer would, the session's
      `overrides` stat increments (visible in the footer once >0), and the
      trial moves on normally.

## 5. Reveal-then-type

- [ ] On a first-letter-cue or fully-blind attempt, press `Esc` or click
      **Show target**. The complete target text appears.
- [ ] Type the now-visible answer correctly and submit. The streak for
      that part resets to 0 (not counted as a miss), and the next attempt
      for that same part shows the cue again — it does not stay revealed
      or skip ahead.
- [ ] Repeat, but type something wrong after revealing. Same result: streak
      resets, no miss counted.
- [ ] On a **presentation** trial, confirm there is no "Show target" button
      and `Esc` does nothing — the chunk's text is already fully visible,
      so there's nothing to reveal.

## 6. Export TSV — **N/A, dropped from scope**

C6 (Anki handoff export) was cut from v2's scope on 2026-09-20 — see the
struck section in `docs/V2-HANDOFF.md`. There is no export feature in the
app to smoke-test. Left here, marked N/A, so this checklist still mirrors
the doc's original list item-for-item.

## 7. 100-card deck performance sanity check

- [ ] Import or generate a 100-card deck with a mix of short (≤8 word) and
      long (>8 word) backs, so both the `full` stage and the chunk ladder
      are exercised.
- [ ] Start a session and play through several trials of a chunked card
      (presentation → chunk → chunk → ... → combine → remediate if you miss
      one on purpose).
- [ ] Watch for input lag or dropped keystrokes on typing, and stutter on
      **Check answer** / **Continue** clicks — `persistState` serializes
      the entire 100-item array to localStorage on every single state
      change, which is the likely culprit if something feels slow.
- [ ] If it stutters: debounce `SessionView.tsx`'s `persistState` write
      (e.g. coalesce with a short `setTimeout`/`requestIdleCallback` instead
      of writing synchronously on every `sessionState` change) rather than
      reducing how often state updates — the state itself needs to stay
      real-time for the UI.

## 8. Edit the current card mid-session

Test deck (normal punctuation mode; repeat the equivalent-change step on a
copy with **Punctuation must match** on):

```
Tachycardia :: fast heart rate
-itis :: inflammation
Menieres disease :: inner ear disorder causing vertigo tinnitus and hearing loss over time
Hypertension :: blood pressure that stays above the normal range
Before surgery :: pre op
```

- [ ] **Edit card** (pencil, left of End session) is enabled on a blind
      attempt, on a presentation beat, and while **Continue** is showing
      after a wrong answer or a cycle verdict; it's disabled during an
      auto-advance dwell (e.g. the "Part learned!" flash).
- [ ] The editor shows the card's **full** front and back, even mid-chunk.
      Save is disabled while either field is empty.
- [ ] Inside the editor, `Esc` cancels (does not trigger Show target) and
      plain `Enter` does not check an answer; `Ctrl+Enter` saves.
- [ ] **Prompt-only edit** mid-encode on a short card: the prompt updates;
      status dot and cue level are unchanged.
- [ ] **Real answer change** on the long card mid-combine: the card restarts
      at a presentation beat with the new text. Attempts/misses unchanged.
- [ ] **Equivalent change** (`Menieres` → `Ménière's`): progress kept. On the
      strict copy, `pre op` → `pre-op` restarts the card.
- [ ] **Cycle-phase real change**: that card goes back to encoding; the
      other cards' dots don't regress; the session still finishes normally.
- [ ] **Reveal rule**: open Edit before typing an answer, then Cancel. The
      card shows as revealed and the next correct answer doesn't build the
      streak ("Revealed — streak reset for this part.").
- [ ] **Write-back**: End session → Back to Setup → the deck editor shows the
      new text; reload → the deck library shows it; Save in the deck editor
      doesn't revert it.
- [ ] **Resume**: edit, reload mid-session, Resume → edited text.
- [ ] **Folder practice**: an edit works in-session, shows "Saved for this
      session only.", and the source deck is unchanged.
