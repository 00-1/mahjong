---
name: Use judgment when driving UIs — don't be a click-tool
description: When acting on screenshots, reason about what you see; recover from unexpected states using judgment rather than retrying scripts
type: feedback
originSessionId: c47cb2b5-120d-4520-bdd7-5ce5b91f658b
---
When you take a screenshot to inform the next action — at any point in any UI-driving task — you're not just a click executor. **Look at the snap and think.** Ask: is this the state I expected? If not:

- **Wrong screen?** Figure out where you are, navigate back to where you need to be.
- **Expected button missing?** Diagnose why — wrong tab, wrong realm, modal in the way, prompt waiting for input. Fix the underlying cause, then proceed.
- **Loading / mid-animation?** Re-snap once. If still loading after a couple retries, something's actually stuck.
- **Unexpected dialog or popup?** Read it. Decide whether to dismiss, accept, or back out — based on what it says, not on a default rule.
- **State changed since last snap?** (e.g. troop count went from 4/5 to 5/5 because a march arrived in between.) Recompute the plan with current state, don't blindly proceed with the old plan.

**Why:** UI state is dynamic and noisy. A scripted sequence of taps can't anticipate every popup, network glitch, animation hiccup, or game-state shift. The user expects you to use the visual context to make decisions in real time, the same way a human would.

**How to apply:** Treat each snap as an open-ended question ("what's on screen and what should I do next?"), not a checkbox ("did the previous step succeed?"). Be willing to deviate from a planned sequence. Narrate your reasoning briefly via `~/say` when you're recovering from something unexpected, so the user knows you're adapting and not stuck.
