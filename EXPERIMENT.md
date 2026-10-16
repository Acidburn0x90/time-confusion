# time-confusion

Experimental harness: repeated "What time is it?" questions against an OpenCode
session, two arms (noclock vs clock), live jev-scored sanity monitor.

- Entry point: `time_loop.py` (stdlib only; talk to the local OpenCode service
  via `opencode api`, never raw HTTP — the service requires auth).
- Session agents: builtin `build` + per-session permission matrices in
  `time_loop.py` (`PERMISSIONS`). Do not define custom agents — custom agents
  with deny-ALL permissions trip the free-tier 403 gate.
- Data: `runs/<utc>-<arm>/turns.jsonl` (live-appended), `meta.json`,
  `scores.jsonl` (monitor). `runs/` is gitignored.
- The `sandbox/` dir is the OpenCode session location; keep it empty of
  files so no accidental instruction injection contaminates sessions.
- Test: 3-turn smoke per arm (`--max-iter 3`) before any full run.
