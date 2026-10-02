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
- [ ] **Short card, 2nd rep:** answer wrong on a short card's 2nd try, then
      **Count as correct**. The streak reads 2 of 3 (not 1), and the Misses
      count doesn't go up.
- [ ] **First combination on a long card:** answer the first 2-part
      combination wrong, then **Count as correct**. It moves on to the whole
      answer — no "isolating…" and no Precision Repair.
- [ ] **Review:** on a card's second review try, answer wrong, then **Count
      as correct**. It says **Mastered** and doesn't come back in that review.
- [ ] **Final check:** answer one wrong, then **Count as correct**. That card
      doesn't come back in the pass, and the end screen doesn't list it as
      missed.
- [ ] **After a reveal:** press `Esc` (Show target) and submit. There is no
      **Count as correct** button.
- [ ] **Edit + override:** answer wrong, open **Edit card**, fix a typo in
      the back (wording only), save, then **Count as correct**. The fix
      sticks and the card moves on.

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

## 9. Within-session spacing (2026-09-24)

Paste-in deck (normal deck, batch size 5, cycle order Shuffled, 3 reps):

```
Tachycardia :: fast heart rate
Bradycardia :: slow heart rate
-itis :: inflammation
-osis :: abnormal condition
-emia :: blood condition
Hypertension :: blood pressure that stays above the normal range for a long time
```

**After Phase 1 (cycle reinsertion gap):**

- [ ] In the batch's cycle, a card that shows "Correct — will test once more
      later" doesn't come back until every other unmastered card in that
      pass has been shown.
- [ ] The very last card of the batch still repeats immediately. That's
      expected until Phase 3's Final check.

**After Phase 2 (rep rotation):**

- [ ] During encoding, after "1 of 3 streaks" the next card is a **different**
      card, while more than one card is still encoding.
- [ ] After a wrong answer, the same card comes back.
- [ ] On the long card (6th line, in batch 2), each chunk's "Read & Continue"
      is followed directly by typing that chunk — the presentation/blind pair
      never gets split apart by the rotation.
- [ ] The status counts (attempts/misses) look normal.

**After Phase 3 (Final check):**

- [ ] After batch 2's cycle finishes, a **Final check** runs over all 6 cards
      in shuffled order, with no cues (blank input, no first-letter hint) and
      the phase line reading "Final check • k of 6".
- [ ] Miss one on purpose: it returns at the end of the Final check (not the
      cycle's short gap), and DoneView lists it under **"Missed in final
      check"** with its front/back and miss count.
- [ ] **End session** mid-Final-check, then **Resume**: you land back in the
      Final check, already-answered cards aren't re-asked, and the card that
      was on screen when you ended is still among the ones left to go.
- [ ] Finish the Final check: the saved session is cleared (Start shows no
      resume prompt for this deck), and DoneView's stats reflect the whole
      session, Final check included.

**After chain contiguity (2026-09-26):**

Deck (batch 5, 3 reps):

```
Tachycardia :: fast heart rate
Hypertension :: blood pressure that stays above the normal range for a long time
-itis :: inflammation
```

- [ ] On the Hypertension card, every part, every combination, and any
      weak-spot drill run back to back without switching cards. The first
      switch to another card comes after the first correct answer on the
      whole answer.

**After resume position (2026-09-26):**

Run on a clean `npm run dev`, not the installed app. Deck (batch 5, 3 reps):

```
Tachycardia :: fast heart rate
-itis :: inflammation
Hypertension :: blood pressure that stays above the normal range for a long time
Bradycardia :: slow heart rate
```

- [ ] Start. On Hypertension, get a combination wrong on purpose so it says
      "isolating…". Answer the isolated part correctly once.
- [ ] Press **End session**, go back, and resume. The first card is
      Hypertension, same isolated part (label **Precision Repair**) — not
      Tachycardia.
- [ ] Repeat with a browser refresh (F5) instead of End session, while
      Hypertension is on its 2nd part. Resume → still Hypertension, same
      part.
- [ ] Resume an old save (made before this change): it opens as it did
      before (first unfinished card), no errors.

## 10. Session review: reveals, trouble spots, history, drill again (2026-09-30)

Two-card deck is enough (e.g. `Tachy :: fast heart rate`, `itis :: inflammation`),
blind typings at 1.

- [ ] On the first card, press **Show target** (Esc), type the answer, check it.
      The session footer shows **Reveals: 1**.
- [ ] Get `itis` wrong once in the review cycle and once in the Final check.
- [ ] On **Deck Mastered!**: the line under the stats reads e.g.
      "2 misses • 1 reveal — answers typed after a reveal don't count toward
      accuracy", and Accuracy is (attempts − misses − reveals) / attempts
      (11 attempts, 2 misses, 1 reveal → 73%).
- [ ] **Where you struggled** lists `itis` first (misses + final-check miss),
      then the revealed card. On a long card that went through **Precision
      Repair**, the part that broke shows as a highlighted chip.
- [ ] **Drill this card again** (under Missed in final check) starts a
      session over just the missed card, titled "<deck> (missed cards)". It
      does not add a deck to the library.
- [ ] In devtools, `localStorage['session-history:<deck-slug>']` has one
      entry with per-card `words`, `chunks`, `attempts`, `misses`,
      `reveals`, `finalMisses`, `hardSpans`. **Export all decks** includes
      it under each deck's `history`.

---

## 11. Anki add-on

Manual checks for the Anki add-on (`anki-addon/`), phases 3b to 7, run in Anki 26.08.1 with the dev junction (`anki-addon/docs/DECISIONS.md`, "Dev install") on a real collection. The automated suite (`pytest anki-addon/tests`) can't open Anki's windows or hooks, so these cover them. Steps 14–20 and 23 make **real handoffs**: Edit → Undo "Recall Drill handoff" reverts each one. Steps 1–13 write nothing to the collection; step 11 confirms it.

### Setup

- [ ] 1. Restart Anki. In the deck list, the gear menu on **Medical Terminology › 3 - Skeletal System** has **Recall Drill this deck**. (Also there: Tools → **Recall Drill…**, and a **Recall Drill** button at the bottom of the deck's overview screen.)
- [ ] 2. The setup panel shows about 368 eligible cards (184 notes × 2), mostly *suspended new*.
  - [ ] Set the template filter to **Reverse** only: the sibling warning goes to 0.
  - [ ] Set **Max cards** to 6.
  - [ ] Press **Use terminology settings**, then set **Cards per batch** to 3.

### Drilling

- [ ] 3. **Start.** The front shows the meaning, with any hint, and the first trial shows the first-letter cue.
- [ ] 4. Type one answer right, one with a stray space or wrong case (still exact), and one wrong. The diff shows missed words in red; the card flashes green or red.
- [ ] 5. On the wrong one, press **Ctrl+Enter**: it counts as correct, and the stats line shows an override.
- [ ] 6. Press **Esc** on a card: the target shows, the window stays open, and the stats count a reveal, not a miss.
- [ ] 7. After a correct full answer, the term's audio plays. **Ctrl+R** replays it.
- [ ] 8. **Ctrl+E** opens the Browser on that card (the card selected, its editor showing).
  - [ ] Add a word to the meaning (`BackText`, the front) and close the Browser. The new front shows **without** a restart.
  - [ ] Change the term (`FrontText`, the answer) and close the Browser. The card **restarts** with the new answer.
  - [ ] Undo both edits in the Browser afterwards.
  - [ ] Optional: open the Browser first, then Ctrl+E (it's reused), edit, and press **Done editing** in the drill window instead of closing the Browser.

### Save, resume and finish

- [ ] 9. Click the window's X → **Save**. Quit Anki, reopen it, and Recall Drill this deck again: the panel offers **Resume**, and Resume lands on the same card.
- [ ] 10. Finish both batches and the Final check, missing one card on purpose. The Done screen lists it under **Missed in final check**; **Hand off** is there (don't press it yet: Phase 4 below); **Drill these cards again** runs just that card.
- [ ] 11. Back in the Browser, the 6 cards are **still suspended and untagged**. Nothing was written to the collection.

### An anki-cards deck

- [ ] 12. Open the setup panel and use **Search…** with `"deck:Human A&P::Lecture 2::Bones and Bone Tissue Chapter 6" tag:rd::drill::A1`, max cards 5:
  - [ ] the cards come in Layer order, and cloze fronts show `[...]` or the hint;
  - [ ] after a full answer, the long `Extra` shows with its formatting (italics, any image), and the session pauses so you can read it;
  - [ ] long answers (over 8 words) go through chunks, then chaining.

  Finish, or save and stop. Nothing is written to Anki.

### Image occlusion cards

- [ ] 13. **Search…** `"deck:Human A&P::Lecture 2::Bones and Bone Tissue Chapter 6" "note:Image Occlusion (anki-medical-cards)"`, max cards 3:
  - [ ] the figure shows (media loads), with the **red box visible** on the structure being asked;
  - [ ] the header line, the whole figure and the cue are visible **without scrolling**, and the answer box is on screen;
  - [ ] no hint is added;
  - [ ] type the label (e.g. `osteon`). On feedback, the verdict and diff are at the top, then the cue, then the back of the card **in place of** the question figure (one figure, that region revealed, its label), then the Extra only once;
  - [ ] the next card starts scrolled to the top.

### Phase 4: hand off to Anki

These handoffs are **real**: the cards show up in your Anki reviews tomorrow. Edit → Undo reverts each one.

- [ ] 14. **Recall Drill this deck** on **Medical Terminology › 3 - Skeletal System**: the banner shows **Hand off finished session** for the 6-card Reverse session from step 10.
- [ ] 15. Click it. The dialog shows:
  - [ ] 6 cards, "stay new, front of the queue, available from Sat Oct 3, 4:00 AM" (the date and time of Anki's next day; handoff B);
  - [ ] Siblings: 6 (their Normal cards);
  - [ ] Tags: +7 / −0 (rd::drilled +6, rd::final-miss +1), with your own counts;
  - [ ] tomorrow's new cards and reviews for Medical Terminology, and any amber warning.
- [ ] 16. **Hand off**: "Handed off. Edit → Undo "Recall Drill handoff" reverts it." Then, in the Browser:
  - [ ] `tag:rd::drilled` finds exactly those 6 notes; the card missed in the Final check also has `rd::final-miss`;
  - [ ] `tag:rd::drilled is:buried` finds 12 cards (the 6 Reverse cards and their 6 Normal siblings), all new, none suspended, first when sorted by Due (Reverse 0–5, then Normal).
- [ ] 17. **Edit → Undo "Recall Drill handoff"**: all 12 are suspended and untagged again. Then **Edit → Redo** (Ctrl+Shift+Z) to hand off again. The banner doesn't come back after an undo: the session's save was deleted on success.
- [ ] 18. **Tomorrow**: those cards come first in your Med Term new cards.
- [ ] 19. Tools → **Recall Drill: my rd::hard cards** opens the panel scoped to `tag:rd::hard` (empty if nothing reached 3 misses + reveals; that's fine). Tools → **Recall Drill: filtered deck for rd::hard** opens Anki's filtered-deck dialog with `tag:rd::hard` filled in; close it without building.
- [ ] 20. **anki-cards deck:** **Search…** `"deck:General Psychology::Psychology Ch7" tag:rd::drill::A`, max **5**. Drill to the end, then **Hand off**:
  - [ ] those 5 new cards are buried and at the front of the Ch7 new queue;
  - [ ] their `rd::drill::A`, `Part::*` and `Layer::*` tags are still there, with `rd::drilled` added.

### Phase 5: tuning report and holdout

- [ ] 21. Tools → **Recall Drill: tuning report**. The header counts your sessions; the cards of the Phase 4 handoffs show as outcomes, or as pending if not reviewed yet. The confound warning is there.
- [ ] 22. Groups under 30 say "n too small", and no Apply button shows. That's expected for weeks. **Copy as CSV** pastes one row per card.
- [ ] 23. The card section says "Holdout: off" with **Holdout %** at 0 (the default). Set it to 15: K appears and changes as you change the %. Start a new Med Term session; reopening the panel shows 15 again (saved for the deck). The panel said "Holdout: K cards skip the drill and go to Anki as new cards (measurement control)." After the handoff, `tag:rd::holdout` finds them: unsuspended, buried until tomorrow, queued right after the drilled cards, and absent from the next session's selection (the panel counts them as left out).

### Phase 6: difficulty and pacing

- [ ] 24. Open the panel on a deck with reviewed cards (a Human A&P lecture deck). The card section shows "Difficulty-adjusted: X cards +1 rep, Y cards −1 rep, Z cards chunk earlier. New cards (N): no FSRS data, unchanged." and, if any, "Stable: K cards skipped". On Med Term (all new) X, Y and Z are 0.
- [ ] 25. Drill 3 lapsed or leech cards: a `+1` card needs one more correct full answer than "Blind typings required" ("1 of 4 streaks" at 3).
- [ ] 26. Med Term Ch 3, **Pacing**: tick **Pace to a target date**, pick the exam date, Mon–Fri. "Today: N cards" ≈ remaining ÷ weekdays left. Drill time says **no estimate yet** until 3 timed sessions in the deck, then your pace. Anki minutes come from the **FSRS simulator** with a peak day once the deck has 50 learning and 50 review ratings of yours (else the small print says why). No "about N–M min" cold-start figure and no "How familiar…" picker anywhere. **Use N as max cards** fills it in.
- [ ] 27. Compare the panel's Anki minutes for tomorrow with the deck options → FSRS → **Simulator** for the same deck: same ballpark.

### Phase 7: panel polish and packaging

- [ ] 28. Open Recall Drill on Med Term Ch 3 and scroll the panel with the mouse wheel over the spin boxes and drop-downs: **no value changes**. Click a spin box, then wheel: it changes. Set **Cards per batch** back to **3** and **Save settings**.
- [ ] 29. The drill time row reads "Next N cards: no estimate yet (needs 3 timed sessions)", and the pacing small print reads as plain sentences (for example "Anki time: no estimate yet. The FSRS simulator needs 50 learning and 50 review ratings of yours in this deck (you have 0 and 0); with fewer it would use Anki's default answer times.").
- [ ] 30. **Install test in a throwaway Anki folder** (your real profile and the dev junction aren't touched). Build the package: `anki-addon\.venv\Scripts\python anki-addon\build.py` (clean git tree). Quit Anki, then start it against a throwaway base folder: `"%LOCALAPPDATA%\Programs\Anki\anki.exe" -b C:\temp\anki-rd-test`.
  - [ ] Tools → Add-ons → **Install from file** → the `.ankiaddon`; quit and start again with the same `-b` command. Tools → **Recall Drill** (no "(dev)": that suffix only shows when running from `recall_drill_dev`) → the About box says `Recall Drill 0.1.0`.
  - [ ] Add 4 Basic cards in a new deck, suspend them, and run **Recall Drill this deck** → drill to the end → **Hand off**. In the Browser: tagged `rd::drilled`, new, buried, first in the new queue. Then Edit → Undo.
  - [ ] Quit, then delete `C:\temp\anki-rd-test`.
- [ ] 31. **Switching your real Anki from the dev junction to the package** (only when you want to; the junction keeps working):
  - [ ] Tools → Add-ons → **Recall Drill (dev)** → **Config**: copy the JSON somewhere (accepted tuning lives there). Quit Anki.
  - [ ] Copy `anki-addon\user_files\profiles` somewhere safe (sessions, history, settings, hints, mappings, pacing).
  - [ ] Remove the junction: `rmdir "%APPDATA%\Anki2\addons21\recall_drill_dev"`. `rmdir`, never `del /s`.
  - [ ] Start Anki, install the `.ankiaddon`, quit, copy the saved `profiles` folder into `%APPDATA%\Anki2\addons21\recall_drill\user_files\`, start Anki again, and paste back any config values that differ from the defaults.
  - [ ] The setup panel on Med Term shows your target date, the handed-off count and any pending session, as before.

### Also worth a look

- [ ] Night mode (Preferences → Theme → Dark) while a drill window is open: the card and the diff colors follow.
- [ ] Switch profile with a drill window open: it saves and closes, no error.
- [ ] A deck with nothing eligible: Start is disabled and says why.
