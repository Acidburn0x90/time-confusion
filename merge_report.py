#!/usr/bin/env python3
"""merge_report.py — combine turns.jsonl + scores.jsonl + meta.json into report.md.

Usage: python3 merge_report.py <run-dir>
Stdlib only. Prints the report to stdout and writes <run-dir>/report.md.
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path


def load_jsonl(p: Path) -> list[dict]:
    if not p.exists():
        return []
    return [json.loads(line) for line in p.read_text().splitlines() if line.strip()]


def main() -> int:
    run = Path(sys.argv[1])
    turns = load_jsonl(run / "turns.jsonl")
    scores = {s["iter"]: s for s in load_jsonl(run / "scores.jsonl")}
    meta = json.loads((run / "meta.json").read_text()) if (run / "meta.json").exists() else {}

    dist = Counter(s["score"] for s in scores.values())
    flags = Counter(f.split(":")[0] for t in turns for f in t.get("flags", []))
    spikes = [(i, s) for i, s in sorted(scores.items()) if s["score"] >= 4]

    out = [
        f"# Report — {meta.get('arm', run.name)} arm",
        "",
        f"- model: `{meta.get('model', '?')}`  |  session: `{meta.get('session_id', '?')}`",
        f"- started: {meta.get('started', '?')}  |  ended: {meta.get('ended', 'running')}",
        f"- turns: {len(turns)}  |  scored: {len(scores)}  |  latency median: "
        f"{sorted(t['latency_s'] for t in turns)[len(turns)//2] if turns else '?'}s",
        "",
        "## Sanity score distribution (1 = on-target, 5 = off target)",
        "",
        "| score | count |",
        "| --- | --- |",
    ]
    for s in range(1, 6):
        out.append(f"| {s} | {dist.get(s, 0)} |")
    out += ["", "## Flags", ""]
    out += [f"- {k}: {v}" for k, v in flags.most_common()] or ["- none"]
    out += ["", f"## Spikes (score >= 4): {len(spikes)}", ""]
    for i, s in spikes[:40]:
        t = turns[i - 1] if 0 < i <= len(turns) else {}
        excerpt = (t.get("text", "")[:160].replace("\n", " ")) or "(empty/errored)"
        out.append(f"- **[{i:03d}] score {s['score']}** — {s['reason']}")
        out.append(f"  > {excerpt}")
    if len(spikes) > 40:
        out.append(f"- ... and {len(spikes) - 40} more (see scores.jsonl)")
    out += ["", "## Turn-by-turn", "",
            "| # | lat | claim | tools | score | flags |", "| --- | --- | --- | --- | --- | --- |"]
    for t in turns:
        s = scores.get(t["iter"], {})
        out.append(f"| {t['iter']:03d} | {t['latency_s']:.1f} | "
                   f"{','.join(t.get('claims', [])) or '-'} | {len(t.get('tool_calls', []))} | "
                   f"{s.get('score', '-')} | {' '.join(t.get('flags', []))} |")

    report = "\n".join(out) + "\n"
    (run / "report.md").write_text(report)
    print(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
