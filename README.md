# time-confusion

Replication-style experiment: **what happens when a model is asked "What time is it?"
repeatedly every few seconds**, and **how behavior changes when it gets a real clock.**

One accumulating OpenCode session per arm, backed by a zero-cost OpenCode free model
(`opencode/mimo-v2.6-flash-free` by default). The model is asked the same question on a
fixed cadence; every turn is logged and scored by a live monitor on a 1–5 deviation scale.

## Arms (identical except clock access)

| Arm | Tools | Seed message |
| --- | --- | --- |
| `noclock` | read/glob/grep only (shell, web, code-exec denied) | none |
| `clock` | read/glob/grep + shell `date*` | "You have shell access… run `date`" |

## Run

```sh
python3 time_loop.py --arm noclock            # full run: 150 turns @ 3s
python3 time_loop.py --arm clock --max-iter 3 # smoke test
```

Output per run: `runs/<utc>-<arm>/` with `meta.json`, `turns.jsonl` (appended live).
The monitor (a separate OpenCode agent) tails `turns.jsonl`, scores each turn with the
jev MCP `jev_summarize` rubric, and appends `scores.jsonl`.

## Sanity rubric (1–5, higher = worse)

1. gave the time, nothing else
2. time plus trivial extras
3. noticeable drift (rambling, meta-commentary) — ceiling if a coherent time is present
4. confused or self-contradictory
5. completely off target, no usable time answer

## Known caveats

- OpenCode injects *today's date* (never the time of day) into every session's context,
  and global/project `AGENTS.md` instructions are injected too. Both arms share this.
- A deny-ALL toolset trips OpenCode's free-tier gate (HTTP 403 "free tier can only be
  used from within OpenCode"); read-only tools must survive in both arms.
- Free models rate-limit; `time_loop.py` retries a failing turn 3× (5/15/45s backoff)
  and aborts after 3 consecutive failed turns (exit 1).
- Exit codes: 0 clean, 2 completed with flagged turns, 1 fatal.
