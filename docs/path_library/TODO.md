# Path candidates — to be scripted

Things the agent currently has to do via LLM judgment that look scriptable.
Add entries when you find yourself doing repetitive nav/interaction tasks.

Entry format:

```
## <path name>

**Symptom**: what the agent currently has to do
**Trigger**: when this comes up
**Approach**: rough idea for how a script would handle it
**Priority**: high / med / low
**Blocker**: anything that prevents scripting (no calibration data, missing
            screenshots, etc.)
```

---

## Win-state recovery (level cleared → next level)

**Symptom**: when a level is cleared, a "Level Complete" popup appears with
rewards and a "Continue" button. Currently the LLM has to dismiss this
and navigate back to the level list to start the next level.

**Trigger**: autoplay returns exit code 0 (won)

**Approach**: similar to `restart.py` but for the win flow. Tap somewhere
to dismiss the rewards popup, navigate back to the Arcane Puzzle level
list (probably already there), find the next level's Continue button,
tap.

**Priority**: high — every won level currently costs an LLM context
cycle for navigation.

**Blocker**: no calibration screenshots of the win/rewards popup yet.
Capture one during the next successful run.

---

## ADB port-rotation auto-recovery

**Symptom**: when the wireless debugging port rotates (after reboot or
WD toggle), the agent has to ask the user for the new port.

**Trigger**: autoplay/session returns setup_error with "adb device unreachable"

**Approach**: scan a port range and try `adb pair` / `adb connect` until
one succeeds. Or use mDNS if available. Termux's adb doesn't support
mdns natively but we could shell out via `dns-sd` on macOS or write a
small mdns-browser helper.

**Priority**: med — user gets disconnected several times per session
in practice.

**Blocker**: complex on Android — no standard mDNS browser available
without rooting / extra packages.

---

## Lock-screen / battery-saver wake

**Symptom**: phone locks during long idle gaps. Agent currently can't
unlock (PIN/pattern blocked from adb). User has to physically unlock.

**Trigger**: autoplay returns adb_disconnected after long idle, OR
screencap returns lock-screen image.

**Approach**: fully unscriptable while a PIN is set. Workaround: agent
keeps the screen continuously awake via `keyevent 224` every 30s.
Already implemented in `docs/_session_artifacts/phone_helpers/screen_keepalive.sh`.

**Priority**: low (workaround in place)

**Blocker**: rooted phone or no PIN required.

---

## Detect "Use Discard or Withdraw" Tip modal automatically

**Symptom**: currently `restart.py` assumes we're at the Tip modal when
called. If we're actually at some other state (e.g., the LLM tapped
something unexpected), it taps the wrong thing.

**Trigger**: scripted restart flow about to begin

**Approach**: `restart.py` should pre-flight verify it's at the modal
via screen detection. Could template-match the modal's distinctive
features (the "Tip" header, two-button layout) or use OCR.

**Priority**: med — would prevent restart.py from misfiring.

**Blocker**: no saved screenshot of the Tip modal yet.

---

## In-game settings / pause menu navigation

**Symptom**: occasionally the user/agent might need to access settings
(e.g., to change sound, or quit a level mid-game). Currently fully
LLM-driven.

**Trigger**: rare — only when something needs configuring

**Approach**: deferred. Low priority since the play loop doesn't need it.

**Priority**: low
