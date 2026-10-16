#!/usr/bin/env python3
"""time_loop.py — repeated "What time is it?" experiment against an OpenCode session.

Asks the same time question every N seconds into ONE accumulating OpenCode
session backed by a zero-cost OpenCode free model, under one of two permission
arms (the only difference between arms):

  noclock  read-only, time-blind tools (shell/web/code-exec all denied)
  clock    same as noclock, plus the shell `date` command allowed

Arm clock receives one seeded first message telling it about `date`.
Each turn is appended immediately to turns.jsonl so a live monitor can tail it.

stdlib only. Talks to the local OpenCode background service via `opencode api`.
Exit codes: 0 = completed clean, 2 = completed with flagged turns, 1 = fatal.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path

PROJECT = Path(__file__).resolve().parent

# Last-matching-rule-wins. Both arms keep read/glob/grep so the request keeps a
# non-empty standard toolset — a deny-ALL toolset trips OpenCode's free-tier
# gate ("free tier can only be used from within OpenCode", HTTP 403).
PERMISSIONS_BASE = [
    {"action": "*", "resource": "*", "effect": "deny"},
    {"action": "read", "resource": "*", "effect": "allow"},
    {"action": "glob", "resource": "*", "effect": "allow"},
    {"action": "grep", "resource": "*", "effect": "allow"},
]
PERMISSIONS = {
    "noclock": PERMISSIONS_BASE,
    "clock": PERMISSIONS_BASE + [{"action": "shell", "resource": "date*", "effect": "allow"}],
}

CLOCK_SEED = (
    "You have shell access. Whenever you are asked about the current time, "
    "run the `date` command to get the real time before answering."
)

TIME_RE = re.compile(r"\b(\d{1,2}[:.]\d{2}(?:\s*[AaPp]\.?[Mm]\.?)?)\b")
CONFUSION_KEYWORDS = [
    "confus", "disorient", "no clock", "don't have", "do not have",
    "cannot access", "can't access", "unsure", "uncertain", "apolog",
    "sorry", "lost", "doesn't make sense", "strange", "weird",
]


def oc_api(method: str, path: str, body: dict | None = None,
           params: dict[str, str] | None = None, timeout: int = 180) -> dict:
    """Call the local OpenCode service via the auth-aware `opencode api` CLI."""
    cmd = ["opencode", "api", method.lower(), path]
    for k, v in (params or {}).items():
        cmd += ["--param", f"{k}={v}"]
    if body is not None:
        cmd += ["--data", json.dumps(body)]
    proc = subprocess.run(cmd, capture_output=True, text=True,
                          timeout=timeout, cwd=PROJECT)
    out = proc.stdout.strip()
    try:
        parsed = json.loads(out) if out else {}
    except json.JSONDecodeError:
        raise RuntimeError(f"non-JSON response (rc={proc.returncode}): {out[:300]} {proc.stderr[:200]}")
    if proc.returncode != 0 or ("_tag" in parsed and parsed.get("_tag") != "SessionInfo"):
        raise ApiError(f"rc={proc.returncode} body={json.dumps(parsed)[:400]}")
    return parsed


class ApiError(RuntimeError):
    pass


def now_iso() -> str:
    return dt.datetime.now().astimezone().isoformat(timespec="milliseconds")


def extract_claims(text: str) -> list[str]:
    return TIME_RE.findall(text)


def repetition_ratio(text: str) -> float:
    grams = [text[i:i + 4] for i in range(max(0, len(text) - 3))]
    if not grams:
        return 0.0
    return Counter(grams).most_common(1)[0][1] / len(grams)


def turn_flags(text: str, prev_claim: str | None, claim: str | None,
               prev_len: int) -> list[str]:
    flags = []
    low = text.lower()
    hits = [kw for kw in CONFUSION_KEYWORDS if kw in low]
    if hits:
        flags.append("keyword:" + ",".join(hits[:3]))
    rep = repetition_ratio(text)
    if rep > 0.15:
        flags.append(f"repetition:{rep:.2f}")
    if prev_len and len(text) > prev_len * 4 and len(text) > 400:
        flags.append("len_spike")
    if claim is None and len(text) > 20:
        flags.append("no_time_claim")
    if prev_claim and claim and prev_claim != claim:
        flags.append(f"claim_changed:{prev_claim}->{claim}")
    return flags


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--arm", choices=("noclock", "clock"), required=True)
    ap.add_argument("--model", default="opencode/mimo-v2.6-flash-free")
    ap.add_argument("--interval", type=float, default=3.0)
    ap.add_argument("--max-iter", type=int, default=150)
    ap.add_argument("--call-timeout", type=int, default=180)
    ap.add_argument("--out", default=None, help="output dir (default runs/<utc>-<arm>)")
    ap.add_argument("--prompt", default="What time is it?")
    args = ap.parse_args()

    provider, model_id = args.model.split("/", 1)
    out_dir = Path(args.out) if args.out else (
        PROJECT / "runs" / f"{dt.datetime.now(dt.timezone.utc):%Y%m%dT%H%M%SZ}-{args.arm}")
    out_dir.mkdir(parents=True, exist_ok=True)
    turns_path = out_dir / "turns.jsonl"

    # 1. Create the session
    sess_body = {
        "title": f"time-confusion-{args.arm}",
        "agent": "build",
        "location": {"directory": str(PROJECT / "sandbox")},
        "model": {"providerID": provider, "id": model_id},
        "permissions": PERMISSIONS[args.arm],
    }
    sid = oc_api("post", "/api/session", sess_body)["data"]["id"]
    meta = {
        "arm": args.arm, "model": args.model, "session_id": sid,
        "interval": args.interval, "max_iter": args.max_iter,
        "prompt": args.prompt, "seed": CLOCK_SEED if args.arm == "clock" else None,
        "permissions": PERMISSIONS[args.arm], "started": now_iso(),
        "note": ("OpenCode injects today's DATE into session context, never the "
                 "time of day; arm noclock still cannot know the clock."),
    }
    (out_dir / "meta.json").write_text(json.dumps(meta, indent=2))
    print(f"session={sid} arm={args.arm} model={args.model} out={out_dir}", flush=True)

    def send(text: str, timeout: int | None = None) -> None:
        oc_api("post", f"/api/session/{sid}/prompt", {"text": text}, timeout=timeout or args.call_timeout)
        oc_api("post", f"/api/experimental/session/{sid}/wait", timeout=timeout or args.call_timeout)

    # Seeded first turn (clock arm only)
    if args.arm == "clock":
        send(CLOCK_SEED, timeout=args.call_timeout)

    seen_ids: set[str] = set()
    all_flagged = 0
    consecutive_failures = 0
    prev_claim = prev_len = None

    def fetch_new_assistant() -> list[dict]:
        msgs = oc_api("get", f"/api/session/{sid}/message",
                      params={"type": "assistant", "order": "desc", "limit": "20"},
                      timeout=60)["data"]
        fresh = [m for m in msgs if m["id"] not in seen_ids]
        for m in msgs:
            seen_ids.add(m["id"])
        return list(reversed(fresh))

    try:
        for i in range(1, args.max_iter + 1):
            t_start = time.monotonic()
            rec: dict = {"iter": i, "t_start": now_iso(), "prompt": args.prompt,
                         "attempts": []}
            success = False
            for attempt in range(1, 4):
                try:
                    send(args.prompt)
                    success = True
                    break
                except (ApiError, subprocess.TimeoutExpired, RuntimeError) as e:
                    rec["attempts"].append({"attempt": attempt, "error": str(e)[:300]})
                    time.sleep(5 * attempt)
            rec["t_end"] = now_iso()
            rec["latency_s"] = round(time.monotonic() - t_start, 2)

            if success:
                parts = fetch_new_assistant()
                texts, tools, outcomes, errors = [], [], [], []
                for m in parts:
                    if m.get("outcome"):
                        outcomes.append(m["outcome"])
                    if m.get("error"):
                        errors.append(str(m["error"].get("message", m["error"]))[:300])
                    for c in m.get("content") or []:
                        if c.get("type") == "text" and c.get("text"):
                            texts.append(c["text"])
                        elif c.get("type") == "tool":
                            tools.append({"name": c.get("name"),
                                          "state": (c.get("state") or {}).get("status")})
                text = "\n".join(texts)
                claims = extract_claims(text)
                claim = claims[-1].replace(".", ":",) if claims else None
                rec.update({
                    "ground_truth_send": rec["t_start"], "ground_truth_recv": rec["t_end"],
                    "texts": texts, "text": text, "tool_calls": tools,
                    "outcomes": outcomes, "errors": errors,
                    "claims": claims,
                    "flags": turn_flags(text, prev_claim, claim, prev_len),
                })
                prev_claim, prev_len = claim or prev_claim, len(text)
                consecutive_failures = 0
                if rec["flags"]:
                    all_flagged += 1
                print(f"[{i:03d}] {rec['latency_s']:>6.1f}s  claim={claim or '-':<8} "
                      f"tools={len(tools)}  {' '.join(rec['flags'])}", flush=True)
            else:
                rec.update({"texts": [], "text": "", "tool_calls": [], "outcomes": [],
                            "errors": ["turn failed after 3 attempts"], "claims": [],
                            "flags": ["turn_failed"]})
                all_flagged += 1
                consecutive_failures += 1
                print(f"[{i:03d}] TURN FAILED after 3 attempts", file=sys.stderr, flush=True)

            with turns_path.open("a") as f:
                f.write(json.dumps(rec) + "\n")

            if consecutive_failures >= 3:
                meta["ended"] = now_iso()
                meta["abort"] = "3 consecutive turn failures"
                (out_dir / "meta.json").write_text(json.dumps(meta, indent=2))
                print("ABORT: 3 consecutive turn failures", file=sys.stderr)
                return 1

            # start-to-start cadence
            remaining = args.interval - (time.monotonic() - t_start)
            if remaining > 0:
                time.sleep(remaining)
    except KeyboardInterrupt:
        meta["ended"] = now_iso()
        meta["abort"] = "keyboard interrupt"
        (out_dir / "meta.json").write_text(json.dumps(meta, indent=2))
        return 1

    meta["ended"] = now_iso()
    meta["flagged_turns"] = all_flagged
    (out_dir / "meta.json").write_text(json.dumps(meta, indent=2))
    print(f"DONE {args.max_iter} turns, {all_flagged} flagged -> {out_dir}", flush=True)
    return 2 if all_flagged else 0


if __name__ == "__main__":
    sys.exit(main())
