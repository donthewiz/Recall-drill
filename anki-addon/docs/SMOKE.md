# Recall Drill add-on: manual smoke check

Run in Anki 26.08.1 with the dev junction (`docs/DECISIONS.md`, "Dev install"), on Don's real collection. Phase 7 extends this list.

Phase 3b (drill window, setup panel, entry points): nothing in steps 1–13 writes to the collection; step 11 confirms it. Phase 4 (the handoff) is below: **its handoffs are real**.

## Setup

- [ ] 1. Restart Anki. In the deck list, the gear menu on **Medical Terminology › 3 - Skeletal System** has **Recall Drill this deck**. (Also there: Tools → **Recall Drill…**, and a **Recall Drill** button at the bottom of the deck's overview screen.)
- [ ] 2. The setup panel shows about 368 eligible cards (184 notes × 2), mostly *suspended new*.
  - [ ] Set the template filter to **Reverse** only: the sibling warning goes to 0.
  - [ ] Set **Max cards** to 6.
  - [ ] Press **Use terminology settings**, then set **Cards per batch** to 3.

## Drilling

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

## Save, resume and finish

- [ ] 9. Click the window's X → **Save**. Quit Anki, reopen it, and Recall Drill this deck again: the panel offers **Resume**, and Resume lands on the same card.
- [ ] 10. Finish both batches and the Final check, missing one card on purpose. The Done screen lists it under **Missed in final check**; **Hand off** is there (don't press it yet: Phase 4 below); **Drill these cards again** runs just that card.
- [ ] 11. Back in the Browser, the 6 cards are **still suspended and untagged**. Nothing was written to the collection.

## An anki-cards deck

- [ ] 12. Open the setup panel and use **Search…** with `"deck:Human A&P::Lecture 2::Bones and Bone Tissue Chapter 6" tag:rd::drill::A1`, max cards 5:
  - [ ] the cards come in Layer order, and cloze fronts show `[...]` or the hint;
  - [ ] after a full answer, the long `Extra` shows with its formatting (italics, any image), and the session pauses so you can read it;
  - [ ] long answers (over 8 words) go through chunks, then chaining.

  Finish, or save and stop. Nothing is written to Anki.

## Image occlusion cards

- [ ] 13. **Search…** `"deck:Human A&P::Lecture 2::Bones and Bone Tissue Chapter 6" "note:Image Occlusion (anki-medical-cards)"`, max cards 3:
  - [ ] the figure shows (media loads), with the **red box visible** on the structure being asked;
  - [ ] the header line, the whole figure and the cue are visible **without scrolling**, and the answer box is on screen;
  - [ ] no hint is added;
  - [ ] type the label (e.g. `osteon`). On feedback, the verdict and diff are at the top, then the cue, then the back of the card **in place of** the question figure (one figure, that region revealed, its label), then the Extra only once;
  - [ ] the next card starts scrolled to the top.

## Phase 4: hand off to Anki

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

## Also worth a look

- [ ] Night mode (Preferences → Theme → Dark) while a drill window is open: the card and the diff colors follow.
- [ ] Switch profile with a drill window open: it saves and closes, no error.
- [ ] A deck with nothing eligible: Start is disabled and says why.
