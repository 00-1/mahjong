---
name: Announce via ~/say BEFORE any phone test or tap-sending action
description: Always voice-announce before running a test that will touch the phone, so the user can intervene if they're using it
type: feedback
originSessionId: c47cb2b5-120d-4520-bdd7-5ce5b91f658b
---
Before running ANY action that taps, swipes, or otherwise drives the phone (gather flow, exploration, calibration, even a single test tap), call `~/say "<short announcement>"` FIRST so the user — who may be using the phone manually — can interrupt before you start.

**Why:** the phone is shared. The user may be playing PNC, taking a screenshot, reading a notification, etc. A surprise tap from the agent can dismiss their dialog, send unintended input, or interfere with their flow. Verbal announcement gives them a one-second window to say "wait" before the action lands.

**How to apply:**
- At the start of every PNC run / test / exploration: `~/say "<short — what I'm about to do>"`. Example: `~/say "starting gather maintenance pass"`, `~/say "running search panel setup test"`, `~/say "checking arcane barrier"`.
- One announcement per session of work is enough — narrating each tap inside a known flow is fine via the existing terse-narration rule, but the *first* action that touches the phone needs an explicit heads-up.
- The exception: read-only `dumpsys`/`adb devices`/`adb exec-out screencap` calls don't need an announcement (they don't affect what the user is doing). Anything that issues `input tap`, `input swipe`, `monkey`, or `am start` does.
- Also applies when an autonomous cron fires — its prompt should start with `~/say "auto-run starting"` so the user is alerted that the agent is about to act.
