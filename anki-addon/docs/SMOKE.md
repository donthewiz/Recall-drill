# Recall Drill add-on: manual smoke check

Run in Anki 26.08.1 with the dev junction (`docs/DECISIONS.md`, "Dev install"), on Don's real collection. Nothing in this check writes to the collection; step 11 confirms it. Phase 7 extends this list.

Phase 3b (drill window, setup panel, entry points).

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
- [ ] 10. Finish both batches and the Final check, missing one card on purpose. The Done screen lists it under **Missed in final check**; **Hand off** is there but disabled ("coming next"); **Drill these cards again** runs just that card.
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

## Also worth a look

- [ ] Night mode (Preferences → Theme → Dark) while a drill window is open: the card and the diff colors follow.
- [ ] Switch profile with a drill window open: it saves and closes, no error.
- [ ] A deck with nothing eligible: Start is disabled and says why.
