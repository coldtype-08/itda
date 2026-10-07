"""CLI: python -m itda --task TASK.md --input <dir> --output <dir> --visitor foreign --interests history,family"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .config import INTERESTS, VISITOR_TYPES, Config
from .pipeline import run


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="itda", description="ItDA — K-culture course agent (draft only)")
    ap.add_argument("--task", default="challenge/TASK.md", type=Path)
    ap.add_argument("--input", default="challenge/hackathon/input", type=Path)
    ap.add_argument("--output", default="challenge/hackathon/output", type=Path)
    ap.add_argument("--visitor", default="auto", choices=VISITOR_TYPES, help="auto: planner decides from the task")
    ap.add_argument("--interests", default="history", help=f"comma list of {INTERESTS}")
    ap.add_argument("--lang", default=None, help="en | ko (default: by visitor type)")
    ap.add_argument("--visit-date", default=None)
    ap.add_argument("--mock", action="store_true", help="no LLM calls; checks plumbing only")
    a = ap.parse_args(argv)

    cfg = Config(task_file=a.task, input_dir=a.input, output_dir=a.output, visitor_type=a.visitor,
                 interests=[i.strip() for i in a.interests.split(",") if i.strip()],
                 language=a.lang, visit_date=a.visit_date)
    if a.mock:
        cfg.mock = True
    result = run(cfg)
    plan = result["plan"]
    if result.get("status") == "out_of_scope":
        print(f"[itda] out of scope: {result.get('scope_reason')}")
        return 0
    print(f"[itda] {plan.get('title')} — {len(plan.get('itinerary', []))} stops, "
          f"{len(result['resolved'].get('excluded_sources', []))} sources excluded, "
          f"{len(result['resolved'].get('untrusted_instructions', []))} untrusted instructions ignored")
    print(f"[itda] wrote {cfg.output_dir}/course_draft.md, itda_result.json, audit.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
