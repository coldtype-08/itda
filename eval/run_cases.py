"""Run ItDA on every variant case in eval/cases/ and score it against that case's checks.json.

These cases use different people, places, languages and traps than the practice task, to
catch rules that only work for the practice set.
    python3 eval/run_cases.py [case_name ...] [--mock]
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CASES = ROOT / "eval" / "cases"
args = [a for a in sys.argv[1:] if not a.startswith("--")]
mock = "--mock" in sys.argv


def score(case: Path, out: Path) -> tuple[int, int]:
    res = json.loads((out / "itda_result.json").read_text())
    audit = json.loads((out / "audit.json").read_text())
    md = (out / "course_draft.md").read_text()
    plan, resolved = res["plan"], res["resolved"]
    id2path = {s["id"]: s["path"] for s in res["sources"]}
    text = {
        "md": md,
        "itinerary": json.dumps(plan.get("itinerary", []), ensure_ascii=False),
        "interp": json.dumps(plan.get("interpretation", []), ensure_ascii=False),
        "diet": json.dumps(plan.get("dietary_plan", []), ensure_ascii=False),
        "untrusted": " ".join(id2path.get(x.get("doc"), str(x.get("doc")))
                              for x in resolved.get("untrusted_instructions", [])),
    }
    input_root = str((case / "input").resolve())
    ok_n = 0
    checks = json.loads((case / "checks.json").read_text())
    for c in checks:
        w = c["where"]
        if w == "audit_reads_outside_input":
            ok = all(e["kind"] != "file_read" or e["path"].startswith(input_root) or e["path"].endswith("TASK.md")
                     for e in audit)
        elif w == "approvals_nonempty":
            ok = bool(plan.get("approvals_needed"))
        else:
            t = text[w]
            ok = True
            if "must" in c:
                ok &= bool(re.search(c["must"], t, re.I))
            for pat in c.get("must_all", []):
                ok &= bool(re.search(pat, t, re.I))
            if "must_not" in c:
                ok &= not re.search(c["must_not"], t, re.I)
        ok_n += ok
        print(("  ✅ " if ok else "  ❌ ") + c["name"])
    return ok_n, len(checks)


total = [0, 0]
for case in sorted(p for p in CASES.iterdir() if p.is_dir() and (not args or p.name in args)):
    out = ROOT / "out" / "cases" / case.name
    print(f"\n=== {case.name} ===")
    t0 = time.time()
    cmd = [sys.executable, "-m", "itda", "--task", str(case / "TASK.md"), "--input", str(case / "input"),
           "--output", str(out), "--visitor", "auto", "--interests", "history,family"] + (["--mock"] if mock else [])
    r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stderr[-1500:])
        continue
    got, n = score(case, out)
    total[0] += got
    total[1] += n
    print(f"  → {got}/{n}  ({time.time() - t0:.0f}s)  draft: {out / 'course_draft.md'}")
print(f"\nTOTAL {total[0]}/{total[1]}")
