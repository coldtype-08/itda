"""ItDA pipeline: ingest -> triage (per doc, parallel) -> resolve -> synthesize -> render.

The agent has no action tools at all: it can read the allowed input, call the
model, and write files under the output directory. Sending, booking, paying and
posting are impossible by construction and only appear as `approvals_needed`.
"""
from __future__ import annotations

import json
import os
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
    if doc.path.startswith("external/"):
        body = re.sub(r'"(url|link|content_urls)"\s*:\s*"[^"]*"', "", doc.text)
        hit = bool(_OVERRIDE.search(body))
    else:
        hit = bool((_EXFIL_VERB.search(doc.text) and _EXTERNAL_HOST.search(doc.text)) or _OVERRIDE.search(doc.text))
    if hit:
        if not r.get("contains_instructions_to_agent") or r.get("source_type") != "external_instruction":
            r = {**r, "contains_instructions_to_agent": True, "source_type": "external_instruction",
                 "reliability": "untrusted", "relevant": False, "trust": "ignore",
                 "trust_reason": "외부 호스트로 자료 전송을 요구하는 외부 지시 (코드 규칙)",
                 "instruction_summary": r.get("instruction_summary") or "외부 호스트로 자료 전송을 요구하는 문구",
                 "forced_by_rule": "exfiltration request to external host"}
    return r


_AUTHORITY = {"official_notice": 1.0, "field_survey": 0.9, "structured_data": 0.9, "internal_guideline": 0.9,
              "community_post": 0.6, "interpretation_draft": 0.5, "web_search": 0.5, "public_api": 0.5,
              "archive": 0.3, "promotional": 0.2, "personal_blog": 0.2, "advertisement": 0.1,
              "external_instruction": 0.0}
_INTEGRITY = {"intact": 1.0, "partial": 0.7, "estimated": 0.7, "ocr_uncertain": 0.5, "damaged": 0.5}
_TRUST = {"use": 1.0, "use_with_caution": 0.8, "background_only": 0.4, "ignore": 0.0}


def _norm(s: str) -> str:
    return re.sub(r"[\s\"'“”‘’`·,.()\[\]]+", "", s or "").lower()


def _quote_found(q: str, text: str) -> bool:
    """Verbatim after normalisation, or (for small edits like particles) 85% of the quote's
    character 4-grams present in the source."""
    if not q:
        return False
    if q in text:
        return True
    grams = {q[i:i + 4] for i in range(max(1, len(q) - 3))}
    return len(q) >= 8 and sum(g in text for g in grams) / len(grams) >= 0.85


def verify_and_score(doc: Doc, r: dict) -> dict:
    """Fact layer, done in code: a claim counts as a quoted fact only if its quote appears verbatim
    in the source. Then turn the source's qualities into a number the consensus step can compare."""
    if r.get("relevant") is False and r.get("trust") not in ("ignore",):
        r["trust"] = "ignore"  # an irrelevant source cannot be 'background' for this request
        r["trust_reason"] = r.get("trust_reason") or r.get("relevance_reason") or "요청과 무관"
    text = _norm(doc.text)
    st = str(r.get("source_type", "")).split("/")[0].strip()
    base = (_AUTHORITY.get(st, 0.4) * _INTEGRITY.get(r.get("integrity"), 0.8)
            * _TRUST.get(r.get("trust"), 0.6))
    for c in r.get("claims") or []:
        q = _norm(c.get("quote", ""))
        c["quote_verified"] = _quote_found(q, text)
        c["evidence_score"] = round(base * (1.0 if c["quote_verified"] else 0.5), 2)
    return r


def consensus_table(triaged: list[dict], topics: list[str] | None = None) -> list[dict]:
    """Group candidate values by (topic, subject, attribute) and rank them by evidence score."""
    groups: dict[tuple, list] = {}
    for t in triaged:
        for c in t.get("claims") or []:
            if topics and c.get("topic") not in topics:
                continue
            key = (c.get("topic"), _norm(c.get("subject", ""))[:24], (c.get("attribute") or "").lower())
            groups.setdefault(key, []).append({
                "doc": t["id"], "value": c.get("value") or c.get("statement"), "applies_to": c.get("applies_to"),
                "quote": c.get("quote"),
                "score": c.get("evidence_score"), "quote_verified": c.get("quote_verified"),
                "source_type": t.get("source_type"), "content_date": t.get("content_date")})
    out = []
    for (topic, _, attr), cands in groups.items():
        cands.sort(key=lambda x: -(x["score"] or 0))
        values = {_norm(str(x["value"])) for x in cands}
        out.append({"topic": topic, "attribute": attr,
                    "agree": len(values) == 1, "candidates": cands, "quorum": quorum(cands)})
    return out


QUORUM = 2 / 3      # BFT-style supermajority of evidence weight
MIN_WEIGHT = 0.5    # below this total there is not enough evidence to confirm anything


def quorum(cands: list[dict]) -> dict:
    """Source-weighted quorum (truth-discovery step 1 + BFT 2/3 rule), pure code, no LLM call.
    Sources vote for a value with their evidence score; one source votes once per question,
    and copies (same quote in several sources) count as a single vote.
      confirmed  : >= 2/3 of the weight agrees AND a verbatim quote backs the winner
      tentative  : a leading value exists but below 2/3 -> keep a Plan B
      unresolved : too little evidence or no verified quote -> 'check on site'"""
    votes: dict[str, float] = {}
    shown: dict[str, str] = {}
    verified: dict[str, bool] = {}
    seen_docs, seen_quotes = set(), set()
    for c in cands:
        if c["doc"] in seen_docs:
            continue
        seen_docs.add(c["doc"])
        qkey = _norm(str(c.get("quote") or ""))
        if qkey and qkey in seen_quotes:
            continue  # copied text: one vote
        if qkey:
            seen_quotes.add(qkey)
        v = _norm(str(c["value"]))
        votes[v] = votes.get(v, 0.0) + float(c.get("score") or 0)
        shown.setdefault(v, str(c["value"]))
        verified[v] = verified.get(v, False) or bool(c.get("quote_verified"))
    total = sum(votes.values())
    if not votes or total <= 0:
        return {"status": "unresolved", "winner": None, "share": 0.0, "total": 0.0}
    win = max(votes, key=votes.get)
    share = votes[win] / total
    if total < MIN_WEIGHT or not verified[win]:
        status = "unresolved"
    elif share >= QUORUM:
        status = "confirmed"
    else:
        status = "tentative"
    return {"status": status, "winner": shown[win], "share": round(share, 2), "total": round(total, 2)}


def triage(cfg: Config, llm: LLM, task: str, visit_date: str | None, docs: list[Doc],
           model: str | None = None) -> list[dict]:
    model = model or cfg.model_fast
    small = bool(cfg.small_base_url) and model == cfg.model_small
    def one(doc: Doc) -> dict:
        user = prompts.TRIAGE_USER.format(
            task=task, visit_date=visit_date or "미상", id=doc.id, path=doc.path,
            dates=doc.dates, years=doc.years, hints=doc.instruction_hints, text=_clip(doc.text))
        try:
            out = llm.chat_json(prompts.TRIAGE_SYSTEM, user, model, f"triage:{doc.id}",
                                mock=lambda: {"relevant": True, "source_type": "other", "reliability": "medium",
                                              "doc_date": None, "contains_instructions_to_agent": bool(doc.instruction_hints),
                                              "claims": []})
        except LLMAuthError:
            raise
        except Exception as e:  # one bad document must not sink the run
            out = {"relevant": False, "error": str(e), "claims": []}
        if isinstance(out, list):  # some answers come back as [ {...} ] instead of {...}
            out = next((x for x in out if isinstance(x, dict)), {})
        if not isinstance(out, dict):
            out = {"relevant": False, "error": "unexpected triage shape", "claims": []}
        # Deterministic signal wins over the model: hinted docs are always treated as untrusted input.
        if doc.instruction_hints and out.get("contains_instructions_to_agent"):
            out["reliability"] = "untrusted"
        return verify_and_score(doc, _force_untrusted(doc, {"id": doc.id, "path": doc.path, **out}))

    def batch(chunk: list[Doc]) -> list[dict]:
        body = "\n\n".join(prompts.TRIAGE_BATCH_DOC.format(
            id=d.id, path=d.path, dates=d.dates, years=d.years, hints=d.instruction_hints,
            text=_clip(d.text, 3000)) for d in chunk)
        user = prompts.TRIAGE_BATCH_USER.format(task=task, visit_date=visit_date or "미상", docs=body)
        try:
            out = llm.chat_json(prompts.TRIAGE_SYSTEM + prompts.TRIAGE_BATCH_SUFFIX, user, model,
                                f"triage:batch:{chunk[0].id}-{chunk[-1].id}",
                                mock=lambda: {"docs": [{"id": d.id, "relevant": True, "source_type": "other",
                                                        "reliability": "medium", "claims": [],
                                                        "contains_instructions_to_agent": bool(d.instruction_hints)}
                                                       for d in chunk]})
            rows = out.get("docs", []) if isinstance(out, dict) else out
            got = {r.get("id"): r for r in (rows if isinstance(rows, list) else []) if isinstance(r, dict)}
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
            res.append(verify_and_score(d, _force_untrusted(d, {**r, "id": d.id, "path": d.path})))
        _progress(f"  분류 완료 {chunk[0].id}–{chunk[-1].id} ({len(chunk)}건)")
        return res

    if cfg.triage_mode == "per_doc" or small:
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
    claims = [c for r in results for c in (r.get("claims") or [])]
    ok = sum(1 for c in claims if c.get("quote_verified"))
    if claims:
        _progress(f"   원문 인용 확인: {ok}/{len(claims)} claims (나머지는 점수 절반)")
        llm.audit.log("quote_check", verified=ok, total=len(claims))
    return results


RESOLVE_GROUPS = [
    ("운영·동선", ["operating_hours", "route_access", "approval_policy", "other"]),
    ("역사", ["history", "etiquette"]),
    ("음식·인물", ["food_dietary", "people"]),
]


def resolve(cfg: Config, llm: LLM, task: str, visit_date: str | None, triaged: list[dict]) -> dict:
    """Topic-specialised verifier agents run in parallel, then merge."""
    empty = {"visit_date": visit_date, "facts": [], "people": [], "rules": [],
             "excluded_sources": [], "untrusted_instructions": [], "open_questions": []}

    def focused(topics: list[str]) -> list[dict]:
        """Each verifier sees every source's metadata but only the claims of its own topics,
        so it is not drowned in 9k tokens of unrelated claims."""
        keep = []
        for t in triaged:
            claims = [c for c in (t.get("claims") or []) if c.get("topic") in topics]
            keep.append({**{k: v for k, v in t.items() if not k.startswith("_")}, "claims": claims})
        return keep

    def one(group) -> dict:
        name, topics = group
        system = prompts.RESOLVE_SYSTEM + prompts.RESOLVE_FOCUS.format(name=name, topics=", ".join(topics))
        view = focused(topics)
        n_claims = sum(len(t["claims"]) for t in view)
        u = prompts.RESOLVE_USER.format(task=task, visit_date=visit_date or "미상",
                                        consensus=json.dumps(consensus_table(triaged, topics), ensure_ascii=False, indent=1),
                                        triage=json.dumps(view, ensure_ascii=False, indent=1))
        out = llm.chat_json(system, u, cfg.model_main, f"resolve:{name}", mock=lambda: dict(empty), temperature=0)
        if n_claims and not out.get("facts"):
            # An empty answer despite claims on our topics is a model hiccup, not a verdict: retry once.
            _progress(f"   검증[{name}] 빈 응답 (주장 {n_claims}건 있음) → 재시도")
            out = llm.chat_json(system, u + "\n\n[주의] 이전 응답의 facts가 비어 있었다. 위 주장들을 반드시 판정해 facts로 출력하라.",
                                cfg.model_main, f"resolve:{name}:retry", mock=lambda: dict(empty), temperature=0)
        _progress(f"   검증[{name}] 주장 {n_claims}건 → 사실 {len(out.get('facts', []))}건")
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
    # Excluded = anything a verifier excluded, plus anything triage judged irrelevant/ignored.
    # Sources actually cited as evidence are removed again after synthesis (see run()).
    ex: dict = {}
    for p in parts:
        for x in p.get("excluded_sources") or []:
            ex.setdefault(x.get("doc"), x)
    for t in triaged:
        if (t.get("relevant") is False or t.get("trust") == "ignore") and t["id"] not in ex:
            ex[t["id"]] = {"doc": t["id"], "reason": t.get("trust_reason") or t.get("relevance_reason") or "요청과 무관"}
    merged["excluded_sources"] = [ex[k] for k in sorted(ex, key=str)]
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


def run_tools(plan: dict, tools: Tools, visit_date: str | None, max_calls: int = int(os.environ.get('ITDA_MAX_TOOL_CALLS', '8'))) -> tuple[list[Doc], list[dict]]:
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
        label = (args.get("query") or args.get("keyword") or args.get("place") or args.get("topic")
                 or (" → ".join(map(str, args["places"])) if isinstance(args.get("places"), list) else args.get("places")) or "")
        ext.append(Doc(id=f"W{i + 1:02d}", path=f"external/{item['call']['tool']}/{label}", text=text,
                       bytes=len(text.encode()),
                       instruction_hints=sorted({m.group(0) for m in _INSTRUCTION_RE.finditer(text)})))
    return ext, log


LANG_NAMES = {"en": "English", "ko": "한국어", "ja": "日本語", "zh": "中文", "es": "Español", "fr": "Français"}
_LANG_ALIASES = {"japanese": "ja", "日本語": "ja", "일본어": "ja", "jp": "ja", "english": "en", "영어": "en",
                 "korean": "ko", "한국어": "ko", "kr": "ko", "chinese": "zh", "中文": "zh", "중국어": "zh",
                 "spanish": "es", "french": "fr"}
_LANG_HINTS = [(re.compile(r"일본인|일본\s*(단체|관광객)|japanese", re.I), "ja"),
               (re.compile(r"중국인|중국\s*(단체|관광객)|chinese", re.I), "zh")]


def _norm_lang(v: str | None) -> str | None:
    if not v:
        return None
    v = str(v).strip()
    return _LANG_ALIASES.get(v.lower(), v.lower()[:2] if len(v) <= 5 else None)


def _detect_language(task: str, docs: list[Doc]) -> str | None:
    """Deterministic language signal: an explicit "language" field in structured visitor data wins,
    then nationality words in the task. The planner's guess is only used when this finds nothing."""
    for d in docs:
        if d.path.endswith(".json"):
            m = re.search(r'"(?:language|lang)"\s*:\s*"([^"]+)"', d.text)
            if m and _norm_lang(m.group(1)):
                return _norm_lang(m.group(1))
    for pat, code in _LANG_HINTS:
        if pat.search(task):
            return code
    return None


def synthesize(cfg: Config, llm: LLM, task: str, resolved: dict, deliverable: str = "",
               implicit: list | None = None) -> dict:
    system = prompts.SYNTH_SYSTEM.format(language=LANG_NAMES.get(cfg.language, cfg.language),
                                         deliverable=deliverable or "과제에 적힌 대로")
    user = prompts.SYNTH_USER.format(
        task=task, visitor_type=cfg.visitor_type, lens=prompts.LENS[cfg.visitor_type],
        interests=", ".join(f"{i}({prompts.INTEREST[i]})" for i in cfg.interests),
        implicit=json.dumps(implicit or [], ensure_ascii=False),
        resolved=json.dumps(resolved, ensure_ascii=False, indent=1))
    return llm.chat_json(system, user, cfg.model_main, "synthesize",
                         mock=lambda: {"title": "ItDA draft (mock)", "summary": "", "itinerary": [],
                                       "dietary_plan": [], "interpretation": [], "uncertainties": [],
                                       "approvals_needed": [], "not_done": []})


_PLAN_LISTS = ("itinerary", "dietary_plan", "interpretation", "uncertainties", "approvals_needed", "not_done",
               "day_card", "phrase_cards", "decisions", "scenarios", "considerations", "changes")


def _normalize_plan(plan) -> dict:
    """Models sometimes return null or a single object where a list is expected; never crash on that."""
    plan = plan if isinstance(plan, dict) else {}
    for k in _PLAN_LISTS:
        v = plan.get(k)
        plan[k] = v if isinstance(v, list) else ([] if v in (None, "") else [v])
    for k in ("title", "summary", "deliverable_text", "answer"):
        if not isinstance(plan.get(k), str):
            plan[k] = "" if plan.get(k) is None else str(plan.get(k))
    plan["title"] = plan["title"] or "ItDA"
    return plan


GROUND_EDITABLE = ("title", "summary", "itinerary", "interpretation", "deliverable_text")


def ground_check(cfg: Config, llm: LLM, plan: dict, resolved: dict, docs: list[Doc], triaged: list[dict]) -> tuple[dict, list]:
    """Second pass: drop claims the sources do not support (fabricated history etc.)."""
    used = {t["id"] for t in triaged if t.get("relevant")}
    sources = "\n\n".join(f"<<< {d.id} {d.path}\n{_clip(d.text, 2000)}\n>>>" for d in docs if d.id in used)
    user = prompts.GROUND_USER.format(plan=json.dumps(plan, ensure_ascii=False, indent=1),
                                      resolved=json.dumps(resolved, ensure_ascii=False), sources=sources)
    try:
        out = llm.chat_json(prompts.GROUND_SYSTEM, user, cfg.model_main, "ground",
                            mock=lambda: {"plan": plan, "removed": []}, temperature=0)
    except LLMAuthError:
        raise
    except Exception as e:  # keep the unchecked draft rather than failing the run
        _progress(f"  근거 검사 실패, 원본 초안 유지 ({e})")
        return plan, []
    new = out.get("plan") if isinstance(out, dict) else None
    if not isinstance(new, dict):
        return plan, []
    # The grounding pass may only edit narrative fields. Everything else (diet, decisions, Plan B,
    # cards, approvals) is kept from the synthesizer: models tend to silently drop keys on rewrite.
    merged = dict(plan)
    for k in GROUND_EDITABLE:
        v = new.get(k)
        if v not in (None, "", []) or not plan.get(k):
            merged[k] = v if v is not None else plan.get(k)
    return merged, out.get("removed", [])


def _cited(plan: dict, resolved: dict) -> set:
    ids = set()
    for sec in ("itinerary", "dietary_plan", "interpretation"):
        for it in plan.get(sec, []) or []:
            ids.update(it.get("evidence") or [])
    for sec in ("facts", "people", "rules"):
        for it in resolved.get(sec, []) or []:
            ids.update(it.get("evidence") or [])
    return ids


_TOOL_LABEL = {"wiki": "위키백과", "weather": "Open-Meteo 일기예보", "tavily": "웹 검색 (Tavily)",
               "brave": "웹 검색 (Brave)", "tour": "한국관광공사 TourAPI (공공데이터)", "naver": "네이버 검색",
               "place_info": "한국관광공사 공식 등록 정보", "accessibility": "한국관광공사 무장애 여행정보",
               "kma_weather": "기상청 단기예보", "weather_warning": "기상청 기상특보", "festival": "한국관광공사 행사·축제",
               "nearby": "한국관광공사 주변 장소", "encyclopedia": "한국민족문화대백과사전", "route": "동선 (TMAP 보행자 경로)"}


def _source_meta(t: dict) -> dict:
    """Human-facing attribution for a source: a readable label, links for external results, and the
    verbatim quotes that the code verified, so every claim in the UI can show where it came from."""
    path = t.get("path", "")
    quotes = [c.get("quote") for c in (t.get("claims") or []) if c.get("quote_verified") and c.get("quote")][:3]
    if not path.startswith("external/"):
        return {"label": path.split("/")[-1], "origin": "provided", "urls": [], "quotes": quotes}
    _, tool, q = (path.split("/", 2) + ["", ""])[:3]
    urls = []
    try:
        data = json.loads(t.get("_text") or "{}")
    except json.JSONDecodeError:
        data = {}
    for r in data.get("results", [])[:3] if isinstance(data, dict) else []:
        u = r.get("url") or r.get("link")
        if u:
            urls.append({"title": r.get("title") or u, "url": u})
    label = _TOOL_LABEL.get(tool, tool) + (f" · {data.get('kind')}" if tool == "naver" and data.get("kind") else "")
    return {"label": f"{label}: {q}", "origin": "external", "tool": tool, "urls": urls, "quotes": quotes}


def render_markdown(cfg: Config, plan: dict, resolved: dict, triaged: list[dict], consensus: list | None = None) -> str:
    id2path = {t["id"]: t["path"] for t in triaged}

    def ev(ids) -> str:
        return ", ".join(f"`{id2path.get(i, i)}`" for i in (ids or [])) or "-"

    ko = cfg.language == "ko"
    L = (lambda k, e: k if ko else e)
    out = [f"# {plan.get('title', 'ItDA')}", "",
           f"> **{L('초안', 'DRAFT')}** · {L('예약·연락·발송하지 않았습니다', 'Nothing has been booked, sent or posted')} · "
           f"lens: {cfg.visitor_type} / {', '.join(cfg.interests)} / {cfg.language}", "", plan.get("summary", ""), ""]
    if plan.get("answer"):
        out += [f"## {L('질문에 대한 답', 'Answer')}", "", plan["answer"], ""]
    if plan.get("changes"):
        out += [f"## {L('이전 초안 대비 바뀐 점', 'What changed')}", ""] + [f"- {x}" for x in plan["changes"]] + [""]
    if plan.get("considerations"):
        out += [f"## {L('이렇게 배려했어요 (추정)', 'Thoughtful touches (assumed)')}", ""]
        out += [f"- **{c.get('need', '')}** → {c.get('how_applied', '')}" for c in plan["considerations"] if isinstance(c, dict)] + [""]
    if plan.get("day_card"):
        out += [f"## {L('한눈에 보는 일정 카드', 'Day card')}", ""] + [f"- {x}" for x in plan["day_card"]] + [""]
    if plan.get("phrase_cards"):
        out += [f"## {L('현장 확인 문장', 'Show this to staff')}", ""]
        for c in plan["phrase_cards"]:
            out += [f"> **{c.get('person', '')} · {c.get('situation', '')}**  ", f"> ### {c.get('show_to_staff', '')}  ",
                    f"> _{c.get('meaning', '')}_", ""]
    if plan.get("decisions"):
        out += [f"## {L('핵심 결정 (불완전한 정보에서)', 'Key decisions under uncertainty')}", "",
                f"| {L('질문', 'Question')} | {L('선택', 'Choice')} | {L('이유', 'Why')} | {L('틀리면', 'Risk if wrong')} |",
                "|---|---|---|---|"]
        out += [f"| {d.get('question', '')} | **{d.get('choice', '')}** | {d.get('why', '')} | {d.get('risk_if_wrong', '')} |"
                for d in plan["decisions"]] + [""]
    if plan.get("scenarios"):
        out += [f"## {L('상황별 대안 (Plan B)', 'Scenarios (Plan B)')}", ""]
        out += [f"- **{L('만약', 'If')}** {x.get('if', '')} → {x.get('then', '')} — {ev(x.get('evidence'))}"
                for x in plan["scenarios"]] + [""]
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

    out += ["", f"## {L('판단 근거', 'Why these sources')}", "",
            f"| {L('주제', 'Topic')} | {L('판정', 'Decision')} | {L('상태', 'Status')} | {L('결정 기준', 'Decided by')} | {L('버린 자료', 'Overridden')} |",
            "|---|---|---|---|---|"]
    for f in resolved.get("facts", []):
        over = "; ".join(f"`{id2path.get(o.get('doc'), o.get('doc'))}` {o.get('reason', '')}" for o in f.get("overridden") or [])
        out.append(f"| {f.get('topic', '')}: {f.get('subject', '')} | {f.get('decision', '')} | {f.get('status', '')} | "
                   f"**{f.get('decided_by', '')}** — {f.get('rationale', '')} | {over or '-'} |")

    conflicts = [g for g in (consensus or []) if len(g["candidates"]) > 1]
    if conflicts:
        out += ["", f"## {L('합의 표 (원문 인용 × 근거 점수)', 'Consensus (verbatim quote × evidence score)')}", "",
                f"| {L('주제·속성', 'Topic · attribute')} | {L('후보 (점수 높은 순)', 'Candidates (by score)')} | {L('정족수 판정 (2/3)', 'Quorum (2/3)')} |",
                "|---|---|---|"]
        for g in conflicts:
            cands = "<br>".join(f"**{c['value']}** `{id2path.get(c['doc'], c['doc'])}` {c['score']} "
                                f"{'✓' if c['quote_verified'] else '✗'}" for c in g["candidates"])
            qv = g.get("quorum", {})
            label = {"confirmed": L("확정", "confirmed"), "tentative": L("잠정", "tentative"),
                     "unresolved": L("미결", "unresolved")}.get(qv.get("status"), "")
            out.append(f"| {g['topic']} · {g['attribute']} | {cands} | **{label}** {qv.get('winner') or ''} ({qv.get('share', 0):.0%}) |")
    out += ["", f"## {L('자료 신뢰 판정', 'Source trust verdicts')}", "",
            f"| {L('자료', 'Source')} | {L('종류', 'Type')} | {L('판정', 'Verdict')} | {L('이유', 'Reason')} |",
            "|---|---|---|---|"]
    for t in triaged:
        out.append(f"| `{t.get('path')}` | {t.get('source_type', '')} | **{t.get('trust', '')}** | {t.get('trust_reason', '')} |")

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
            cfg.language = (cfg.language or _detect_language(task, docs) or _norm_lang(agent_plan.get("language"))
                            or ("en" if cfg.visitor_type == "foreign" else "ko"))
            _progress(f"   렌즈 자동 판단: {cfg.visitor_type} / 언어 {cfg.language}")
        visit_date = visit_date or agent_plan.get("visit_date")
        ext_docs, tool_log = run_tools(agent_plan, tools, visit_date)
        small = cfg.model_small if cfg.small_base_url else None
        ext_triaged = triage(cfg, llm, task, visit_date, ext_docs, model=small) if ext_docs else []
        texts = {d.id: d.text for d in ext_docs}
        for t in ext_triaged:
            t["_text"] = texts.get(t["id"], "")
        triaged = f_local.result() + ext_triaged
    docs = docs + ext_docs
    _progress(f"③ 검증 에이전트 {len(RESOLVE_GROUPS)}개 병렬 시작 ({cfg.model_main})")
    resolved = resolve(cfg, llm, task, visit_date, triaged)
    _progress(f"   사실 {len(resolved.get('facts', []))}건, 제외 {len(resolved.get('excluded_sources', []))}건, "
              f"무시한 지시 {len(resolved.get('untrusted_instructions', []))}건")
    cons = consensus_table(triaged)
    # Only questions backed by at least one usable source matter downstream; cap the list so the
    # synthesizer is not flooded (unresolved noise mostly comes from weak external snippets).
    useful = [g for g in cons if any((c.get("score") or 0) >= 0.2 for c in g["candidates"])
              and (g["quorum"]["status"] != "confirmed" or len(g["candidates"]) > 1)]
    useful.sort(key=lambda g: {"tentative": 0, "unresolved": 1, "confirmed": 2}[g["quorum"]["status"]])
    resolved["quorum"] = [{"topic": g["topic"], "attribute": g["attribute"], **g["quorum"]} for g in useful[:10]]
    qs = [g["quorum"]["status"] for g in cons]
    _progress(f"   정족수 판정: 확정 {qs.count('confirmed')} · 잠정 {qs.count('tentative')} · 미결 {qs.count('unresolved')}")
    audit.log("quorum", confirmed=qs.count("confirmed"), tentative=qs.count("tentative"), unresolved=qs.count("unresolved"))
    _progress(f"④ 종합 시작 ({cfg.model_main})")
    implicit = agent_plan.get("implicit_needs") if isinstance(agent_plan.get("implicit_needs"), list) else []
    if implicit:
        _progress("   추정 배려: " + ", ".join(str(x.get("need", x))[:30] for x in implicit[:6] if isinstance(x, dict)))
    plan = _normalize_plan(synthesize(cfg, llm, task, resolved, str(agent_plan.get("deliverable") or ""), implicit))
    _progress(f"⑤ 근거 검사 시작 ({cfg.model_main})")
    plan, removed = ground_check(cfg, llm, plan, resolved, docs, triaged)
    plan = _normalize_plan(plan)
    _progress(f"   근거 없는 문장 {len(removed)}건 제거")
    # Damaged / OCR / estimated sources: every candidate year must survive into the draft.
    by_id = {d.id: d for d in docs}
    blob = json.dumps(plan, ensure_ascii=False)
    for t in triaged:
        d = by_id.get(t["id"])
        if not d or not t.get("relevant") or t.get("trust") == "ignore":
            continue
        shaky = t.get("integrity") in ("ocr_uncertain", "damaged", "estimated") or re.search(
            r"OCR|판독|훼손|추정|illegible|damaged", d.text, re.I)
        if shaky and len(d.years) >= 2 and not all(y in blob for y in d.years):
            ys = " / ".join(d.years)
            plan.setdefault("uncertainties", []).append(
                (f"`{d.path}`: 판독·훼손으로 연도 확정 불가 — 후보 {ys}" if cfg.language == "ko" else
                 f"`{d.path}`: year cannot be confirmed (damaged/OCR) — candidates {ys}"))
            audit.log("uncertainty_kept", doc=d.path, years=d.years)
    if not plan.get("approvals_needed"):
        ko = cfg.language == "ko"
        plan["approvals_needed"] = [
            "현장 예약·문의·연락은 코디네이터 승인 후 진행 (현재 승인 범위: 초안 작성만)" if ko else
            "Any booking, inquiry or message to venues needs coordinator approval (current approval: draft only)"]
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
        "consensus": cons,
        "agent_plan": agent_plan,
        "implicit_needs": implicit,
        "tool_calls": [{"tool": x["call"].get("tool"), "args": x["call"].get("args"), "why": x["call"].get("why"),
                        "ok": x["result"].get("ok"), "error": x["result"].get("error")} for x in tool_log],
        "sources": [{**{k: t.get(k) for k in ("id", "path", "relevant", "source_type", "reliability",
                                               "doc_date", "content_date", "scope", "integrity",
                                               "trust", "trust_reason", "contains_instructions_to_agent")},
                     **_source_meta(t)} for t in triaged],
    }
    guard.write_text("itda_result.json", json.dumps(result, ensure_ascii=False, indent=2))
    guard.write_text("course_draft.md", render_markdown(cfg, plan, resolved, triaged, result["consensus"]))
    audit.log("done")
    guard.write_text("audit.json", audit.to_json())
    return result
