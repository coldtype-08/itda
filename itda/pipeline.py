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
from .ingest import _INSTRUCTION_RE, Doc, load_docs
from .llm import LLM, LLMAuthError
from .tools import Tools


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


_EXFIL_VERB = re.compile(r"업로드|전송|보내|메일로|공유하|upload|send|e-?mail|forward|share|(?<![a-z])post(?![a-z])|exfil", re.I)
_OVERRIDE = re.compile(r"ignore\s+(all\s+|the\s+)?(previous|prior|above)\s+instructions|(이전|위의?|기존)\s*(지시|지침|규칙)[을를]?\s*무시", re.I)
# ASCII-only boundaries: Hangul counts as a word char, so "\b" fails on "domain.example에".
_EXTERNAL_HOST = re.compile(r"(?<![a-z0-9-])[a-z0-9-]+(?:\.[a-z0-9-]+)*\.(?:example|com|net|io|org|kr|co|xyz|site)(?![a-z0-9-])", re.I)


def _force_untrusted(doc: Doc, r: dict) -> dict:
    """Code-level rule, independent of the model: a document that asks for data to be sent to an
    external host is an injection, whatever the model called it."""
    if (_EXFIL_VERB.search(doc.text) and _EXTERNAL_HOST.search(doc.text)) or _OVERRIDE.search(doc.text):
        if not r.get("contains_instructions_to_agent") or r.get("source_type") != "external_instruction":
            r = {**r, "contains_instructions_to_agent": True, "source_type": "external_instruction",
                 "reliability": "untrusted", "relevant": False,
                 "instruction_summary": r.get("instruction_summary") or "외부 호스트로 자료 전송을 요구하는 문구",
                 "forced_by_rule": "exfiltration request to external host"}
    return r


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
        return _force_untrusted(doc, {"id": doc.id, "path": doc.path, **out})

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
            res.append(_force_untrusted(d, {**r, "id": d.id, "path": d.path}))
        _progress(f"  분류 완료 {chunk[0].id}–{chunk[-1].id} ({len(chunk)}건)")
        return res

    if cfg.triage_mode == "per_doc":
        with ThreadPoolExecutor(max_workers=cfg.concurrency) as pool:
            results = list(pool.map(one, docs))
    else:
        # Small batches (≤5 docs or ~4k chars) run in parallel: 20 docs ≈ 4 concurrent calls.
        chunks, cur, size = [], [], 0
        for d in docs:
            if cur and (len(cur) >= 5 or size + len(d.text) > 4000):
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


RESOLVE_GROUPS = [
    ("운영·동선", ["operating_hours", "route_access", "approval_policy", "other"]),
    ("역사", ["history", "etiquette"]),
    ("음식·인물", ["food_dietary", "people"]),
]


def resolve(cfg: Config, llm: LLM, task: str, visit_date: str | None, triaged: list[dict]) -> dict:
    """Topic-specialised verifier agents run in parallel, then merge."""
    user = prompts.RESOLVE_USER.format(
        task=task, visit_date=visit_date or "미상",
        triage=json.dumps(triaged, ensure_ascii=False, indent=1))
    empty = {"visit_date": visit_date, "facts": [], "people": [], "rules": [],
             "excluded_sources": [], "untrusted_instructions": [], "open_questions": []}

    def one(group) -> dict:
        name, topics = group
        system = prompts.RESOLVE_SYSTEM + prompts.RESOLVE_FOCUS.format(name=name, topics=", ".join(topics))
        out = llm.chat_json(system, user, cfg.model_main, f"resolve:{name}", mock=lambda: dict(empty))
        _progress(f"   검증[{name}] 사실 {len(out.get('facts', []))}건")
        return out

    with ThreadPoolExecutor(max_workers=len(RESOLVE_GROUPS)) as pool:
        parts = list(pool.map(one, RESOLVE_GROUPS))

    merged = dict(empty)
    merged["visit_date"] = next((p.get("visit_date") for p in parts if p.get("visit_date")), visit_date)
    for key in ("facts", "people", "rules", "open_questions"):
        merged[key] = [x for p in parts for x in (p.get(key) or [])]
    by_doc = {}
    for p in parts:
        for x in p.get("untrusted_instructions") or []:
            by_doc.setdefault(x.get("doc"), x)
    for t in triaged:  # anything triage flagged is always reported, even if verifiers forgot it
        if t.get("contains_instructions_to_agent") and t["id"] not in by_doc:
            by_doc[t["id"]] = {"doc": t["id"], "summary": t.get("instruction_summary", "")}
    merged["untrusted_instructions"] = list(by_doc.values())
    # A source is excluded only if every verifier excluded it.
    excluded_sets = [{x.get("doc"): x for x in (p.get("excluded_sources") or [])} for p in parts]
    common = set.intersection(*(set(e) for e in excluded_sets)) if excluded_sets else set()
    merged["excluded_sources"] = [excluded_sets[0][d] for d in sorted(common)]
    return merged


def plan_agent(cfg: Config, llm: LLM, task: str, docs: list[Doc], tools: Tools) -> dict:
    avail = tools.available()
    tool_desc = "\n".join(f"- {k}: {v} 인자 {prompts.TOOL_ARGS[k]}" for k, v in avail.items())
    listing = "\n".join(f"- {d.path}: {d.text[:150].replace(chr(10), ' ')}" for d in docs)
    lens = "auto (과제와 자료에서 판단)" if cfg.visitor_type == "auto" else cfg.visitor_type
    user = prompts.PLAN_USER.format(task=task, visitor_type=lens, interests=", ".join(cfg.interests),
                                    language=cfg.language or "auto", tools=tool_desc, docs=listing)
    try:
        return llm.chat_json(prompts.PLAN_SYSTEM, user, cfg.model_main, "plan",
                             mock=lambda: {"goal": "mock", "places": [], "checks": [], "tool_calls": [
                                 {"tool": "wiki", "args": {"query": "조선", "lang": "ko"}, "why": "mock"},
                                 {"tool": "send_email", "args": {}, "why": "should be blocked"}]})
    except LLMAuthError:
        raise
    except Exception as e:
        _progress(f"  계획 실패, 로컬 자료만 사용 ({e})")
        return {"goal": task[:200], "tool_calls": [], "error": str(e)}


def run_tools(plan: dict, tools: Tools, visit_date: str | None, max_calls: int = 6) -> tuple[list[Doc], list[dict]]:
    calls = [c for c in (plan.get("tool_calls") or []) if isinstance(c, dict)][:max_calls]
    for c in calls:
        if c.get("tool") == "weather":
            c.setdefault("args", {}).setdefault("date", visit_date)

    def one(c: dict) -> dict:
        args = c.get("args") if isinstance(c.get("args"), dict) else {}
        r = tools.call(str(c.get("tool")), **args)
        mark = "✓" if r.get("ok") else "✗"
        _progress(f"   도구 {mark} {c.get('tool')} {json.dumps(args, ensure_ascii=False)[:80]}"
                  + ("" if r.get("ok") else f" → {r.get('error')}"))
        return {"call": c, "result": r}

    with ThreadPoolExecutor(max_workers=4) as pool:
        log = list(pool.map(one, calls))
    ext = []
    for i, item in enumerate(x for x in log if x["result"].get("ok")):
        text = json.dumps(item["result"], ensure_ascii=False)[:4000]
        args = item["call"].get("args") or {}
        label = args.get("query") or args.get("keyword") or args.get("place") or ""
        ext.append(Doc(id=f"W{i + 1:02d}", path=f"external/{item['call']['tool']}/{label}", text=text,
                       bytes=len(text.encode()),
                       instruction_hints=sorted({m.group(0) for m in _INSTRUCTION_RE.finditer(text)})))
    return ext, log


LANG_NAMES = {"en": "English", "ko": "한국어", "ja": "日本語", "zh": "中文", "es": "Español", "fr": "Français"}


def synthesize(cfg: Config, llm: LLM, task: str, resolved: dict, deliverable: str = "") -> dict:
    system = prompts.SYNTH_SYSTEM.format(language=LANG_NAMES.get(cfg.language, cfg.language),
                                         deliverable=deliverable or "과제에 적힌 대로")
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
           f"lens: {cfg.visitor_type} / {', '.join(cfg.interests)} / {cfg.language}", "", plan.get("summary", ""), ""]
    if (plan.get("deliverable_text") or "").strip():
        out += [f"## {L('요청 결과물', 'Deliverable')}", "", plan["deliverable_text"].strip(), ""]

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

    tools = Tools(audit)
    _progress(f"① 수집: 로컬 문서 {len(docs)}개, 방문일 {visit_date}, 렌즈 {cfg.visitor_type}/{','.join(cfg.interests)}")
    _progress(f"② 계획 에이전트 + 로컬 분류 병렬 시작 (도구: {', '.join(tools.available())})")
    with ThreadPoolExecutor(max_workers=2) as pool:
        f_local = pool.submit(triage, cfg, llm, task, visit_date, docs)
        agent_plan = plan_agent(cfg, llm, task, docs, tools)
        _progress(f"   계획: {agent_plan.get('goal', '')[:80]} / 도구 호출 {len(agent_plan.get('tool_calls') or [])}건")
        if cfg.visitor_type == "auto":
            vt = agent_plan.get("visitor_type")
            cfg.visitor_type = vt if vt in ("foreign", "korean") else "foreign"
            cfg.language = cfg.language or str(agent_plan.get("language") or ("en" if cfg.visitor_type == "foreign" else "ko"))[:5]
            _progress(f"   렌즈 자동 판단: {cfg.visitor_type} / 언어 {cfg.language}")
        visit_date = visit_date or agent_plan.get("visit_date")
        ext_docs, tool_log = run_tools(agent_plan, tools, visit_date)
        ext_triaged = triage(cfg, llm, task, visit_date, ext_docs) if ext_docs else []
        triaged = f_local.result() + ext_triaged
    docs = docs + ext_docs
    _progress(f"③ 검증 에이전트 {len(RESOLVE_GROUPS)}개 병렬 시작 ({cfg.model_main})")
    resolved = resolve(cfg, llm, task, visit_date, triaged)
    _progress(f"   사실 {len(resolved.get('facts', []))}건, 제외 {len(resolved.get('excluded_sources', []))}건, "
              f"무시한 지시 {len(resolved.get('untrusted_instructions', []))}건")
    _progress(f"④ 종합 시작 ({cfg.model_main})")
    plan = synthesize(cfg, llm, task, resolved, str(agent_plan.get("deliverable") or ""))
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
        "agent_plan": agent_plan,
        "tool_calls": [{"tool": x["call"].get("tool"), "args": x["call"].get("args"), "why": x["call"].get("why"),
                        "ok": x["result"].get("ok"), "error": x["result"].get("error")} for x in tool_log],
        "sources": [{k: t.get(k) for k in ("id", "path", "relevant", "source_type", "reliability",
                                            "doc_date", "contains_instructions_to_agent")} for t in triaged],
    }
    guard.write_text("itda_result.json", json.dumps(result, ensure_ascii=False, indent=2))
    guard.write_text("course_draft.md", render_markdown(cfg, plan, resolved, triaged))
    audit.log("done")
    guard.write_text("audit.json", audit.to_json())
    return result
