# Path library

A "path" is any sequence of taps/swipes the agent has to perform that's:
- Repeatable
- Doesn't require LLM judgment
- Can be expressed as a script

Goal: minimize LLM-in-the-loop time. Every wasteful LLM round-trip is a
candidate to script. Every scripted path that fails is a candidate to
improve.

## How this directory works

- `INDEX.md` — every known path, with status (`scripted` / `todo`),
  the script that owns it (if any), and any notes.
- `TODO.md` — paths we haven't scripted yet, with priority + sketch
  of approach.
- `failures.jsonl` — append-only log of scripted-path failures. Format:
  `{ts, path, script, run_id, failure_reason, expected, observed}`.
  When a script returns its `needs_llm` exit code (or otherwise
  fails), it should append a record here. Periodic review surfaces
  scripts that need patching.

## When to add an entry

### Paths to ADD to TODO.md

When you (the LLM agent) find yourself doing something repetitive that
isn't yet scripted, add an entry. Examples:

- "Every time the level ends I have to dismiss a rewards popup by
  tapping at (~610, ~1800). Could be scripted."
- "I keep finding the new wireless-debugging port by reading off the
  screen. Could be auto-detected via mDNS."

### Paths to MARK as scripted

When you write or update a script that handles a path, update its
entry in `INDEX.md` with the script's location.

### Failures to LOG

When a script returns `exit code 1` with `needs_llm`, append a record
to `failures.jsonl`. Include enough info to diagnose: which step
failed, what state was observed vs expected. Offline review of the
log surfaces script weak points.

## Conventions for scripted paths

1. **Calibration once, run many.** First-time setup may need user-provided
   coords; save them to `data/<script>_config.json` with a
   `calibrated_resolution`. On subsequent runs, scale coords to the
   current device.
2. **Verify state after each step.** Use `detect_screen` or a
   path-specific check. If verification fails, exit non-zero with a
   `needs_llm` event so the agent knows to take over.
3. **Log every event in jsonl format.** stdout + (optional) file. Makes
   review trivial.
4. **Prefer vision over hardcoded coords** when the target shifts
   (e.g., Continue button y varies by scroll position).
5. **Idempotent if possible.** Running the script twice in a row
   shouldn't break state.

## Workflow

1. Agent runs scripts. When LLM intervention is needed, log a
   failures.jsonl entry.
2. Periodically run `scripts/review_paths.py` to summarize: which
   paths failed most often, what reasons, which `needs_llm` events
   recurred.
3. Patch the scripts based on patterns OR add a TODO if the failure
   reveals a new path that wasn't previously known.

## Currently scripted

See `INDEX.md`.

## Currently un-scripted

See `TODO.md`.
