---
name: Terse narration during phone-control tasks via ~/say
description: During PNC / adb UI work, narrate each meaningful step with a short ~/say call; skip raw command output; end by returning to Termux
type: feedback
originSessionId: c47cb2b5-120d-4520-bdd7-5ce5b91f658b
---
When the phone is foregrounded on another app (e.g. PNC) and the user can't see the Termux conversation, narrate progress directly via `~/say "<short message>"` — don't rely on Stop hooks. The Stop hook has been removed; `~/say` is the canonical narration channel.

**Why:** The user listens via TTS while watching the phone. The Stop hook only fires once per turn, often reads stale text due to transcript flush races, and can't narrate mid-turn — so it was removed. Direct `~/say` calls give clean, in-context narration tied to the actual step.

**How to apply (baked-in PNC / phone-UI process):**
1. Narrate each meaningful step with one short `~/say` call before/after the action ("tapping search", "level five furnace selected", "march one sent"). One short sentence, not a paragraph.
2. Skip narration for trivial chained calls or raw stdout — only narrate things you'd actually want to *tell* the user.
3. Don't narrate command syntax, file paths, or internal reasoning — only user-relevant progress.
4. When the test/sequence finishes, bring Termux back to the foreground (`adb shell am start -n com.termux/.app.TermuxActivity`) and `~/say` a short "done" / status line so the user knows the run ended.
5. `~/say` is fire-and-forget (detached via setsid + paplay); chain with `sleep N &&` if a message must follow another action, or call before the action when it's narrating intent.
6. **Narrate problems too.** When something goes wrong — wrong screen, missing button, unexpected dialog, tap apparently misfired, app backgrounded itself, recovery action needed — call `~/say` to tell the user what you're seeing and what you're doing about it. Do NOT report problems only in chat text the user can't see while watching the phone. Examples: `~/say "p n c lost focus, relaunching"`, `~/say "wrong realm, recovering"`, `~/say "tap missed, trying again"`. Same brevity rule applies — one short sentence.
7. **Don't rely on chat text being heard.** The user often has eyes on the phone, not the Termux conversation. Anything you write *only* as chat text is invisible to them in that moment. Rule of thumb during phone-UI work: **for every meaningful chat-text update, also send a short `~/say` version of the same point.** It's cheap (fire-and-forget), and it prevents the user from having to ask "what just happened?" because they didn't see the chat. The chat-text version can be longer/more detailed; the `~/say` version is the one-sentence essence.
