"""ItDA pipeline: ingest -> triage (per doc, parallel) -> resolve -> synthesize -> render.

The agent has no action tools at all: it can read the allowed input, call the
model, and write files under the output directory. Sending, booking, paying and
posting are impossible by construction and only appear as `approvals_needed`.
"""
from __future__ import annotations

import json
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from . import prompts
from .config import Config
from .guard import Audit, PathGuard
from .ingest import Doc, load_docs
from .llm import LLM, LLMAuthError


def _progress(msg: str) -> None:
    print(f"[itda {time.strftime('%H:%M:%S')}] {msg}", file=sys.stderr, flush=True)


def _clip(s: str, n: int = 6000) -> str:
    return s if len(s) <= n else s[:n] + "\n…(생략)"


def _guess_visit_date(task: str, docs: list[Doc]) -> str | None:
    m = re.search(r"(20\d{2})-(\d{2})-(\d{2})", task)
    if m:
        return m.group(0)
    for d in docs:  # structured itinerary/group files usually carry the date
        m = re.search(r'"date"\s*:\s*"(20\d{2}-\d{2}-\d{2})"', d.text)
        if m:
            return m.group(1)
    return None


def triage(cfg: Config, llm: LLM, task: str, visit_date: str | None, docs: list[Doc]) -> list[dict]:
    def one(doc: Doc) -> dict:
        user = prompts.TRIAGE_USER.format(
            task=task, visit_date=visit_date or "미상", id=doc.id, path=doc.path,
            dates=doc.dates, years=doc.years, hints=doc.instruction_hints, text=_clip(doc.text))
        try:
            out = llm.chat_json(prompts.TRIAGE_SYSTEM, user, cfg.model_fast, f"triage:{doc.id}",
                                mock=lambda: {"relevant": True, "source_type": "other", "reliability": "medium",
                                              "doc_date": None, "contains_instructions_to_agent": bool(doc.instruction_hints),
                                              "claims": []})
        except LLMAuthError:
            raise
        except Exception as e:  # one bad document must not sink the run
            out = {"relevant": False, "error": str(e), "claims": []}
        # Deterministic signal wins over the model: hinted docs are always treated as untrusted input.
        if doc.instruction_hints and out.get("contains_instructions_to_agent"):
            out["reliability"] = "untrusted"
        return {"id": doc.id, "path": doc.path, **out}

    def batch(chunk: list[Doc]) -> list[dict]:
        body = "\n\n".join(prompts.TRIAGE_BATCH_DOC.format(
            id=d.id, path=d.path, dates=d.dates, years=d.years, hints=d.instruction_hints,
            text=_clip(d.text, 3000)) for d in chunk)
        user = prompts.TRIAGE_BATCH_USER.format(task=task, visit_date=visit_date or "미상", docs=body)
        try:
            out = llm.chat_json(prompts.TRIAGE_SYSTEM + prompts.TRIAGE_BATCH_SUFFIX, user, cfg.model_fast,
                                f"triage:batch:{chunk[0].id}-{chunk[-1].id}",
                                mock=lambda: {"docs": [{"id": d.id, "relevant": True, "source_type": "other",
                                                        "reliability": "medium", "claims": [],
                                                        "contains_instructions_to_agent": bool(d.instruction_hints)}
                                                       for d in chunk]})
            got = {r.get("id"): r for r in (out.get("docs", []) if isinstance(out, dict) else out)}
        except LLMAuthError:
            raise
        except Exception as e:  # fall back to per-document calls
            _progress(f"  배치 분류 실패 → 문서별로 재시도 ({e})")
            got = {}
        res = []
        for d in chunk:
            r = got.get(d.id)
            if r is None:
                res.append(one(d))
                continue
            if d.instruction_hints and r.get("contains_instructions_to_agent"):
                r["reliability"] = "untrusted"
            res.append({**r, "id": d.id, "path": d.path})
        _progress(f"  분류 완료 {chunk[0].id}–{chunk[-1].id} ({len(chunk)}건)")
        return res

    if cfg.triage_mode == "per_doc":
        with ThreadPoolExecutor(max_workers=cfg.concurrency) as pool:
            results = list(pool.map(one, docs))
    else:
        # Pack small documents into batches (~12k chars each); batches run in parallel.
        chunks, cur, size = [], [], 0
        for d in docs:
            if cur and size + len(d.text) > 12000:
                chunks.append(cur)
                cur, size = [], 0
            cur.append(d)
            size += len(d.text)
        if cur:
            chunks.append(cur)
        with ThreadPoolExecutor(max_workers=cfg.concurrency) as pool:
            results = [r for part in pool.map(batch, chunks) for r in part]
    for r in results:
        _progress(f"    {r['path']:<48} {str(r.get('source_type')):<20} relevant={r.get('relevant')}"
                  + ("  ⚠ 지시문" if r.get("contains_instructions_to_agent") else ""))
    for r in results:
        if r.get("contains_instructions_to_agent"):
            llm.audit.log("untrusted_instruction", doc=r["path"], summary=r.get("instruction_summary", ""))
    return results


def resolve(cfg: Config, llm: LLM, task: str, visit_date: str | None, triaged: list[dict]) -> dict:
    user = prompts.RESOLVE_USER.format(
        task=task, visit_date=visit_date or "미상",
        triage=json.dumps(triaged, ensure_ascii=False, indent=1))
    return llm.chat_json(prompts.RESOLVE_SYSTEM, user, cfg.model_main, "resolve",
                         mock=lambda: {"visit_date": visit_date, "facts": [], "people": [], "rules": [],
                                       "excluded_sources": [], "untrusted_instructions": [], "open_questions": []})


def synthesize(cfg: Config, llm: LLM, task: str, resolved: dict) -> dict:
    system = prompts.SYNTH_SYSTEM.format(language="English" if cfg.language == "en" else "한국어")
    user = prompts.SYNTH_USER.format(
        task=task, visitor_type=cfg.visitor_type, lens=prompts.LENS[cfg.visitor_type],
        interests=", ".join(f"{i}({prompts.INTEREST[i]})" for i in cfg.interests),
        resolved=json.dumps(resolved, ensure_ascii=False, indent=1))
    return llm.chat_json(system, user, cfg.model_main, "synthesize",
                         mock=lambda: {"title": "ItDA draft (mock)", "summary": "", "itinerary": [],
                                       "dietary_plan": [], "interpretation": [], "uncertainties": [],
                                       "approvals_needed": [], "not_done": []})


def ground_check(cfg: Config, llm: LLM, plan: dict, resolved: dict, docs: list[Doc], triaged: list[dict]) -> tuple[dict, list]:
    """Second pass: drop claims the sources do not support (fabricated history etc.)."""
    used = {t["id"] for t in triaged if t.get("relevant")}
    sources = "\n\n".join(f"<<< {d.id} {d.path}\n{_clip(d.text, 2000)}\n>>>" for d in docs if d.id in used)
    user = prompts.GROUND_USER.format(plan=json.dumps(plan, ensure_ascii=False, indent=1),
                                      resolved=json.dumps(resolved, ensure_ascii=False), sources=sources)
    try:
        out = llm.chat_json(prompts.GROUND_SYSTEM, user, cfg.model_main, "ground",
                            mock=lambda: {"plan": plan, "removed": []})
    except LLMAuthError:
        raise
    except Exception as e:  # keep the unchecked draft rather than failing the run
        _progress(f"  근거 검사 실패, 원본 초안 유지 ({e})")
        return plan, []
    new = out.get("plan") if isinstance(out, dict) else None
    if not isinstance(new, dict) or "itinerary" not in new:
        return plan, []
    return new, out.get("removed", [])


def _cited(plan: dict, resolved: dict) -> set:
    ids = set()
    for sec in ("itinerary", "dietary_plan", "interpretation"):
        for it in plan.get(sec, []) or []:
            ids.update(it.get("evidence") or [])
    for sec in ("facts", "people", "rules"):
        for it in resolved.get(sec, []) or []:
            ids.update(it.get("evidence") or [])
    return ids


def render_markdown(cfg: Config, plan: dict, resolved: dict, triaged: list[dict]) -> str:
    id2path = {t["id"]: t["path"] for t in triaged}

    def ev(ids) -> str:
        return ", ".join(f"`{id2path.get(i, i)}`" for i in (ids or [])) or "-"

    ko = cfg.language == "ko"
    L = (lambda k, e: k if ko else e)
    out = [f"# {plan.get('title', 'ItDA')}", "",
           f"> **{L('초안', 'DRAFT')}** · {L('예약·연락·발송하지 않았습니다', 'Nothing has been booked, sent or posted')} · "
           f"lens: {cfg.visitor_type} / {', '.join(cfg.interests)}", "", plan.get("summary", ""), ""]

    out += [f"## {L('일정', 'Itinerary')}", "",
            f"| {L('시간', 'Time')} | {L('장소', 'Place')} | {L('활동', 'Activity')} | {L('접근·주의', 'Access notes')} | {L('근거', 'Evidence')} |",
            "|---|---|---|---|---|"]
    for it in plan.get("itinerary", []):
        out.append(f"| {it.get('time','')} | {it.get('place','')} | {it.get('activity','')} | "
                   f"{it.get('access_notes','')} | {ev(it.get('evidence'))} |")

    out += ["", f"## {L('음식 제한', 'Dietary needs')}", ""]
    for d in plan.get("dietary_plan", []):
        out.append(f"- **{d.get('person','')}** ({', '.join(d.get('needs', []))}): {d.get('guidance','')}  \n"
                   f"  {L('현장 확인', 'Ask on site')}: {d.get('ask_on_site','')} — {ev(d.get('evidence'))}")

    out += ["", f"## {L('해설', 'Interpretation')}", ""]
    for p in plan.get("interpretation", []):
        out.append(f"### {p.get('place','')}\n{p.get('text','')}\n\n_{L('주의', 'Caveats')}: {p.get('caveats','')}_ — {ev(p.get('evidence'))}\n")

    def bullets(title: str, items) -> None:
        out.extend(["", f"## {title}", ""])
        out.extend(f"- {x}" for x in (items or [L("없음", "None")]))

    bullets(L("확인 필요", "Needs confirmation"), plan.get("uncertainties"))
    bullets(L("승인 필요 (수행하지 않음)", "Needs approval (not performed)"), plan.get("approvals_needed"))
    bullets(L("제외한 자료", "Excluded sources"),
            [f"`{id2path.get(x['doc'], x['doc'])}` — {x.get('reason','')}" for x in resolved.get("excluded_sources", [])])
    bullets(L("따르지 않은 외부 지시", "Untrusted instructions ignored"),
            [f"`{id2path.get(x['doc'], x['doc'])}` — {x.get('summary','')}" for x in resolved.get("untrusted_instructions", [])])
    return "\n".join(out) + "\n"


def run(cfg: Config) -> dict:
    audit = Audit()
    guard = PathGuard(read_roots=[cfg.input_dir, cfg.task_file], write_root=cfg.output_dir, audit=audit)
    llm = LLM(cfg, audit)

    task = guard.read_text(cfg.task_file)
    docs = load_docs(cfg.input_dir, guard)
    visit_date = cfg.visit_date or _guess_visit_date(task, docs)
    audit.log("start", docs=len(docs), visit_date=visit_date, visitor_type=cfg.visitor_type,
              interests=cfg.interests, model_main=cfg.model_main, model_fast=cfg.model_fast)

    _progress(f"① 수집: 문서 {len(docs)}개, 방문일 {visit_date}, 렌즈 {cfg.visitor_type}/{','.join(cfg.interests)}")
    _progress(f"② 분류 시작 ({cfg.model_fast}, 동시 {cfg.concurrency}개)")
    triaged = triage(cfg, llm, task, visit_date, docs)
    _progress(f"③ 검증 시작 ({cfg.model_main})")
    resolved = resolve(cfg, llm, task, visit_date, triaged)
    _progress(f"   사실 {len(resolved.get('facts', []))}건, 제외 {len(resolved.get('excluded_sources', []))}건, "
              f"무시한 지시 {len(resolved.get('untrusted_instructions', []))}건")
    _progress(f"④ 종합 시작 ({cfg.model_main})")
    plan = synthesize(cfg, llm, task, resolved)
    _progress(f"⑤ 근거 검사 시작 ({cfg.model_main})")
    plan, removed = ground_check(cfg, llm, plan, resolved, docs, triaged)
    _progress(f"   근거 없는 문장 {len(removed)}건 제거")
    # Consistency: a source cited as evidence cannot also be listed as excluded.
    cited = _cited(plan, resolved)
    resolved["excluded_sources"] = [x for x in resolved.get("excluded_sources", []) if x.get("doc") not in cited]

    result = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "status": "draft",
        "lens": {"visitor_type": cfg.visitor_type, "interests": cfg.interests, "language": cfg.language},
        "visit_date": visit_date,
        "plan": plan,
        "resolved": resolved,
        "grounding_removed": removed,
        "sources": [{k: t.get(k) for k in ("id", "path", "relevant", "source_type", "reliability",
                                            "doc_date", "contains_instructions_to_agent")} for t in triaged],
    }
    guard.write_text("itda_result.json", json.dumps(result, ensure_ascii=False, indent=2))
    guard.write_text("course_draft.md", render_markdown(cfg, plan, resolved, triaged))
    audit.log("done")
    guard.write_text("audit.json", audit.to_json())
    return result
