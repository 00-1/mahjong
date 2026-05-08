# Game navigation: home → Arcane Puzzle level

The puzzle is buried inside an Events menu. The agent needs to navigate
this flow before it can call `agent.py decide` on a real puzzle screen.

## Steps

The five screenshots in this directory document the path. They're named
in chronological order (01 = first step the agent sees, 05 = arrived at
the level list).

### 1. `01_home.jpg` — game home screen

City view, with various UI elements. **Tap the small fireworks / event
banner in the top-right** (red circle in the reference screenshot). It's
the small panel with a countdown timer next to it. That opens the Event
Center.

### 2. `02.jpg` — Event Center / Daily Event tab

Tap the **Festival Event** tab (red circle on the screenshot). Three
tabs total: Daily Event | Festival Event | Coming soon.

### 3. `03.jpg` — Festival Event list, scroll to "Arcane Puzzle"

Scroll the list down. Tap the **Arcane Puzzle** entry near the bottom
(red circle).

### 4. `04.jpg` — Arcane Puzzle level list, scroll down

Levels 1-7 are visible at top, all completed (checkmark icons). Scroll
down to reach your current level (red arrow points down).

### 5. `05.jpg` — find level, tap **Continue**

The current in-progress level (level 8 in the example) has a yellow
**Continue** button (red circle) and a grey **Restart** button. Tap
**Continue** to enter the level. (Tap **Restart** to start a fresh run
of the same level — useful for retries.)

After step 5, the Arcane Puzzle gameplay screen loads — that's the state
the rest of the toolkit assumes. Call `agent.py start-run --level N`
where N is the level you just continued / restarted, and proceed with
the play loop.

## Notes for the agent

- **Detecting the level**: easiest is to read it directly from the level
  list (the row label text "Level 8" etc.), but you can also OCR the
  "Level N" header on the gameplay screen to verify.
- **Continue vs Restart**: Restart resets progress on that level (useful
  if you want a fresh structure for testing). Continue resumes from where
  you left off.
- **Animations / popups**: between screens there may be load spinners or
  reward popups. The agent should wait for them to clear before tapping.
- **Returning home after a level**: typically a back button (top-left) or
  a "leave level" prompt. After end-run, the agent navigates back to step
  4 to choose the next level.

