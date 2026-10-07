"""Minimal demo UI (stdlib only): pick a lens, run the agent, watch progress, read results.

    python3 -m itda.web                      # agent runs on this host
    ITDA_RUNNER=sandbox SANDBOX=itda-hack python3 -m itda.web   # agent runs inside OpenShell

Open http://<host>:8501
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .config import INTERESTS, VISITOR_TYPES

ROOT = Path(__file__).resolve().parent.parent
RUNS = ROOT / "out" / "web_runs"
JOBS: dict[str, dict] = {}
LOCK = threading.Lock()


def _live_inputs(job_dir: Path, req: dict) -> tuple[Path, Path]:
    """Live mode: the user's own request becomes TASK.md, and their companions/conditions become a
    structured visitor profile, so the same pipeline (trust checks, consensus, Plan B) runs on real
    places with real API data instead of the challenge folder."""
    task_dir, inp = job_dir / "task", job_dir / "input" / "request"
    task_dir.mkdir(parents=True, exist_ok=True)
    inp.mkdir(parents=True, exist_ok=True)
    date = (req.get("date") or "").strip()[:10]
    text = (req.get("request") or "").strip()[:2000]
    (task_dir / "TASK.md").write_text(
        "# 요청 (사용자 직접 입력)\n" + text + (f"\n\n방문일: {date}" if date else "") +
        "\n\n실제 장소에 대한 요청이다. 도구로 운영시간·휴무일·최근 소식·날씨를 확인하고, "
        "확인되지 않은 정보는 '방문 전 확인'으로 남긴다. 예약·연락·결제는 하지 않는다.\n", encoding="utf-8")
    profile = {"group": "사용자 입력", "date": date or None, "visitor_type": req.get("visitor"),
               "companions_and_needs": (req.get("companions") or "").strip()[:1000],
               "approval": "draft_only", "source": "user_input (this request only)"}
    (inp / "visitor_profile.json").write_text(json.dumps(profile, ensure_ascii=False, indent=1), encoding="utf-8")
    return task_dir / "TASK.md", job_dir / "input"


def _start(visitor: str, interests: list[str], req: dict | None = None) -> str:
    job = uuid.uuid4().hex[:8]
    out = RUNS / job
    out.mkdir(parents=True, exist_ok=True)
    args = ["--visitor", visitor, "--interests", ",".join(interests)]
    extra_env = {}
    if req and req.get("mode") == "live":
        task, inp = _live_inputs(RUNS / f"{job}_in", req)
        args += ["--task", str(task), "--input", str(inp)]
        extra_env = {"TASK_FILE": str(task), "INPUT_DIR": str(inp)}
    if os.environ.get("ITDA_RUNNER") == "sandbox":
        sb_args = [a for a in args if a not in ("--task", "--input") and a not in extra_env.values()]
        cmd = ["sh", "scripts/sandbox_run.sh", *sb_args]
        env = {**os.environ, "OUT_DIR": str(out), **extra_env}
    else:
        cmd = [sys.executable, "-m", "itda", *args, "--output", str(out)]
        env = dict(os.environ)
    JOBS[job] = {"lines": [f"$ {' '.join(cmd)}"], "done": False, "ok": None, "out": str(out), "t0": time.time()}

    def worker() -> None:
        p = subprocess.Popen(cmd, cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                             text=True, bufsize=1)
        for line in p.stdout:  # type: ignore[union-attr]
            JOBS[job]["lines"].append(line.rstrip())
        JOBS[job].update(done=True, ok=p.wait() == 0)

    threading.Thread(target=worker, daemon=True).start()
    return job


def _result(job: str) -> dict:
    out = Path(JOBS[job]["out"])
    found = {p.name: p for p in out.rglob("*") if p.is_file()}
    data: dict = {}
    for name, key in (("itda_result.json", "result"), ("audit.json", "audit")):
        if name in found:
            data[key] = json.loads(found[name].read_text())
    if "course_draft.md" in found:
        data["markdown"] = found["course_draft.md"].read_text()
    return data


class Handler(BaseHTTPRequestHandler):
    def _send(self, code: int, body: bytes, ctype: str = "application/json") -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype + "; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code: int = 200) -> None:
        self._send(code, json.dumps(obj, ensure_ascii=False).encode())

    def log_message(self, *a) -> None:  # quiet
        pass

    def _authorized(self, q: dict) -> bool:
        """Optional shared token (ITDA_WEB_TOKEN) for a publicly tunnelled demo: open the page once
        with ?t=<token>; a cookie carries it afterwards. Without the env var the UI is open."""
        tok = os.environ.get("ITDA_WEB_TOKEN")
        return not tok or q.get("t") == tok or f"itda_t={tok}" in (self.headers.get("Cookie") or "")

    def do_GET(self) -> None:
        u = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        if not self._authorized(q):
            return self._send(401, "<p>접근 토큰이 필요합니다: 공유받은 링크(?t=...)로 접속하세요.</p>".encode(), "text/html")
        if u.path in ("/", "/index.html"):
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            if os.environ.get("ITDA_WEB_TOKEN"):
                self.send_header("Set-Cookie", f"itda_t={os.environ['ITDA_WEB_TOKEN']}; Path=/; HttpOnly; SameSite=Lax")
            body = PAGE.encode()
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif u.path == "/status" and q.get("job") in JOBS:
            j = JOBS[q["job"]]
            self._json({"lines": j["lines"][-200:], "done": j["done"], "ok": j["ok"],
                        "elapsed": round(time.time() - j["t0"])})
        elif u.path == "/result" and q.get("job") in JOBS:
            self._json(_result(q["job"]))
        else:
            self._json({"error": "not found"}, 404)

    def do_POST(self) -> None:
        if not self._authorized({}):
            return self._json({"error": "unauthorized"}, 401)
        if urlparse(self.path).path != "/run":
            return self._json({"error": "not found"}, 404)
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0)) or b"{}"))
        visitor = body.get("visitor")
        interests = [i for i in body.get("interests", []) if i in INTERESTS]
        if visitor not in VISITOR_TYPES or not interests:  # whitelist: nothing user-supplied reaches the shell
            return self._json({"error": "invalid lens"}, 400)
        if body.get("mode") == "live" and len((body.get("request") or "").strip()) < 5:
            return self._json({"error": "요청 내용을 적어 주세요"}, 400)
        with LOCK:
            if any(not j["done"] for j in JOBS.values()):
                return self._json({"error": "a run is already in progress"}, 409)
            self._json({"job": _start(visitor, interests, body)})


PAGE = r"""<!doctype html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>잇다 ItDA</title>
<link rel="preconnect" href="https://fonts.googleapis.com"><link href="https://fonts.googleapis.com/css2?family=Noto+Serif+KR:wght@600;700&family=Noto+Sans+KR:wght@400;500;700&display=swap" rel="stylesheet">
<style>
:root{--bg:#f6f2e9;--paper:#fffdf8;--card:#fff;--fg:#1d1b18;--mut:#6f685d;--line:#e4dccd;--acc:#b23a2b;--acc2:#1f6f6b;--gold:#c99a2e;--ok:#2f6f4f;--warn:#a5631a;--bad:#a32d2d;--chip:#f1ebdf}
@media (prefers-color-scheme:dark){:root{--bg:#141311;--paper:#1b1a17;--card:#211f1c;--fg:#ece6dc;--mut:#a59d90;--line:#36322c;--acc:#e0806b;--acc2:#6fc2bb;--gold:#e0b65a;--ok:#7cc4a0;--warn:#e5a65a;--bad:#f09595;--chip:#2a2723}}
*{box-sizing:border-box}html,body{margin:0;background:var(--bg);color:var(--fg);font:16px/1.65 "Noto Sans KR",-apple-system,"Apple SD Gothic Neo",sans-serif}
main{max-width:880px;margin:0 auto;padding:20px 16px 80px}
.brand{display:flex;align-items:baseline;gap:10px;flex-wrap:wrap}.brand h1{font:700 30px/1.2 "Noto Serif KR",serif;margin:0}
.brand .en{color:var(--acc);font-weight:700;letter-spacing:.08em}.tag-line{color:var(--mut);margin:4px 0 18px}
h2{font:700 20px/1.3 "Noto Serif KR",serif;margin:30px 0 12px}h3{margin:0 0 4px;font-size:17px}
.card{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:16px 18px;margin:12px 0}
.panel{background:var(--paper);border:1px solid var(--line);border-radius:18px;padding:18px}
.seg{display:flex;background:var(--chip);border-radius:12px;padding:4px;gap:4px;margin-bottom:14px;flex-wrap:wrap}
.seg button{flex:1;min-width:140px;border:0;background:transparent;color:var(--fg);padding:10px;border-radius:9px;font:inherit;cursor:pointer}
.seg button.on{background:var(--card);box-shadow:0 1px 3px rgba(0,0,0,.08);font-weight:700}
.lbl{font-weight:700;margin:12px 0 6px}.chips{display:flex;gap:8px;flex-wrap:wrap}
.chip{border:1px solid var(--line);background:var(--card);color:var(--fg);border-radius:999px;padding:8px 14px;cursor:pointer;font:inherit}
.chip.on{border-color:var(--acc);background:color-mix(in srgb,var(--acc) 10%,var(--card));color:var(--acc);font-weight:700}
textarea,input[type=date]{width:100%;font:inherit;padding:10px 12px;border-radius:10px;border:1px solid var(--line);background:var(--card);color:var(--fg)}
.go{width:100%;margin-top:16px;background:var(--acc);color:#fff;border:0;border-radius:12px;padding:14px;font:700 17px "Noto Sans KR",sans-serif;cursor:pointer}
.go:disabled{opacity:.55;cursor:wait}.mut{color:var(--mut)}.small{font-size:13px}
.steps{display:flex;gap:6px;margin:16px 0 4px}.steps div{flex:1;height:6px;border-radius:3px;background:var(--line)}.steps div.on{background:var(--acc2)}
.tabs{display:flex;gap:18px;border-bottom:1px solid var(--line);margin:28px 0 4px}.tabs button{border:0;background:none;color:var(--mut);font:700 15px inherit;padding:10px 0;cursor:pointer;border-bottom:3px solid transparent}
.tabs button.on{color:var(--fg);border-color:var(--acc)}
.hero{background:linear-gradient(135deg,color-mix(in srgb,var(--acc) 8%,var(--paper)),var(--paper));border:1px solid var(--line);border-radius:18px;padding:20px}
.hero h2{margin:0 0 8px;font-size:23px}.badges{display:flex;gap:6px;flex-wrap:wrap;margin:8px 0}
.b{font-size:12.5px;border-radius:999px;padding:3px 10px;background:var(--chip);color:var(--mut)}.b.r{background:color-mix(in srgb,var(--acc) 14%,var(--card));color:var(--acc)}.b.g{background:color-mix(in srgb,var(--ok) 14%,var(--card));color:var(--ok)}
.trust{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin-top:12px}.trust div{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:10px;text-align:center}.trust b{display:block;font-size:22px;color:var(--acc2)}
.phone{max-width:380px;margin:0 auto;background:var(--fg);color:var(--paper);border-radius:28px;padding:22px 20px;box-shadow:0 10px 30px rgba(0,0,0,.18)}
.phone ul{margin:0;padding-left:18px}.phone li{margin:6px 0}.phone .t{font:700 15px "Noto Serif KR",serif;color:var(--gold);margin-bottom:8px}
.tl{position:relative;margin-left:8px;border-left:2px solid var(--line);padding-left:18px}.tl .it{position:relative;margin:0 0 16px}
.tl .it:before{content:"";position:absolute;left:-26px;top:6px;width:12px;height:12px;border-radius:50%;background:var(--acc);border:3px solid var(--bg)}
.time{display:inline-block;font-weight:700;color:var(--acc);font-size:14px}.note{font-size:14px;color:var(--warn);margin-top:4px}
.show{border:2px solid var(--acc);border-radius:16px;padding:16px;margin:12px 0;background:var(--card)}.show .ko{font:700 24px/1.45 "Noto Sans KR",sans-serif;margin:6px 0}
sup.fn{cursor:pointer;color:var(--acc2);font-weight:700;margin-left:2px}sup.fn:hover{text-decoration:underline}
.src{display:flex;gap:10px;padding:10px 0;border-top:1px dashed var(--line)}.src:first-child{border-top:0}.src .n{min-width:28px;height:28px;border-radius:50%;background:var(--chip);display:flex;align-items:center;justify-content:center;font-weight:700;font-size:13px}
.src.hl{background:color-mix(in srgb,var(--gold) 16%,transparent);border-radius:10px}.q{font-size:13.5px;color:var(--mut);border-left:3px solid var(--gold);padding-left:8px;margin:4px 0}
.src a{color:var(--acc2);word-break:break-all;font-size:13.5px}
details{margin-top:8px}summary{cursor:pointer;color:var(--mut)}
pre{background:var(--paper);border:1px solid var(--line);border-radius:10px;padding:10px;max-height:240px;overflow:auto;font-size:12px;white-space:pre-wrap}
table{width:100%;border-collapse:collapse;font-size:14px}td,th{border-bottom:1px solid var(--line);padding:8px;text-align:left;vertical-align:top}
.tag{display:inline-block;font-size:12px;border:1px solid var(--line);border-radius:999px;padding:1px 8px;margin:2px 2px 0 0;color:var(--mut)}
.bad{color:var(--bad)}.ok{color:var(--ok)}.warn{color:var(--warn)}.sub{color:var(--mut)}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px}
.stat{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:12px}.stat b{font-size:24px;display:block}
ul{padding-left:20px}
@media (max-width:560px){.trust{grid-template-columns:1fr 1fr 1fr}.hero h2{font-size:20px}.show .ko{font-size:21px}}
</style></head><body><main>
<div class="brand"><h1>잇다</h1><span class="en">ItDA</span></div>
<p class="tag-line">흩어진 기록을 믿을 수 있는 하루로 잇습니다 — 공식 공지·현장 기록·검색 결과를 스스로 검증해 나에게 맞는 문화 코스를 만들어요.</p>
<div class="panel">
 <div class="seg" id="mode"><button class="on" data-v="challenge">📂 주어진 자료로 만들기</button><button data-v="live">✏️ 내 여행 직접 입력</button></div>
 <div id="live" hidden>
  <div class="lbl">어디로, 무엇을 하고 싶으세요?</div>
  <textarea id="req" rows="3" placeholder="예) 토요일에 부모님 모시고 경복궁이랑 근처 전통시장 반나절 코스 짜줘"></textarea>
  <div class="lbl">언제 가세요?</div><input type="date" id="date">
  <div class="lbl">함께 가는 분과 조건</div>
  <textarea id="comp" rows="2" placeholder="예) 아버지 무릎이 안 좋아 계단이 어려움, 어머니 비건, 7살 아이 땅콩 알레르기"></textarea>
  <div class="mut small">입력한 내용은 이번 코스를 만드는 데만 쓰이고, 에이전트는 예약·연락·결제를 하지 않습니다.</div>
 </div>
 <div class="lbl">누가 가시나요?</div>
 <div class="chips" id="vis"><button class="chip on" data-v="auto">🤖 알아서 판단</button><button class="chip" data-v="foreign">🌏 해외 방문객</button><button class="chip" data-v="korean">🇰🇷 한국인</button></div>
 <div class="lbl">무엇이 궁금하세요? <span class="mut small">(여러 개 선택)</span></div>
 <div class="chips" id="int"><button class="chip on" data-v="history">📜 역사 이야기</button><button class="chip on" data-v="family">👨‍👩‍👧 가족·동행 배려</button><button class="chip" data-v="kculture">🎤 K-컬처</button></div>
 <button class="go" id="go">코스 만들기</button>
 <div id="prog" hidden><div class="steps"><div></div><div></div><div></div><div></div><div></div></div><div id="st" class="mut small"></div></div>
</div>
<div class="tabs" id="tabs" hidden><button class="on" data-v="user">여행 코스</button><button data-v="dev">검증 과정 (개발자 보기)</button></div>
<div id="res"></div><div id="dev" hidden></div>
<script>
const $=s=>document.querySelector(s),esc=s=>String(s??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
let visitor='auto',mode='challenge';
const pick=(sel,single,cb)=>document.querySelectorAll(sel+' button').forEach(b=>b.onclick=()=>{if(single)document.querySelectorAll(sel+' button').forEach(x=>x.classList.remove('on'));b.classList.toggle('on',single?true:!b.classList.contains('on'));cb&&cb(b)});
pick('#mode',true,b=>{mode=b.dataset.v;$('#live').hidden=mode!=='live'});pick('#vis',true,b=>visitor=b.dataset.v);pick('#int',false);
pick('#tabs',true,b=>{$('#res').hidden=b.dataset.v!=='user';$('#dev').hidden=b.dataset.v!=='dev'});
const STEPS=[['①','자료를 모으고 있어요'],['②','무엇을 확인할지 계획하고 검색하고 있어요'],['③','자료끼리 비교해서 믿을 만한지 따지고 있어요'],['④','상황에 맞는 코스를 짜고 있어요'],['⑤','모든 문장의 근거를 다시 확인하고 있어요']];
$('#go').onclick=async()=>{
  const interests=[...document.querySelectorAll('#int .on')].map(b=>b.dataset.v);
  if(!interests.length){$('#prog').hidden=false;$('#st').textContent='궁금한 주제를 하나 이상 골라 주세요';return}
  if(mode==='live'&&$('#req').value.trim().length<5){$('#prog').hidden=false;$('#st').textContent='어디로 무엇을 하고 싶은지 적어 주세요';return}
  $('#go').disabled=true;$('#res').innerHTML='';$('#dev').innerHTML='';$('#tabs').hidden=true;$('#prog').hidden=false;
  const r=await fetch('run',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({visitor,interests,mode,request:$('#req').value,date:$('#date').value,companions:$('#comp').value})});
  const j=await r.json();if(!r.ok){$('#st').textContent=j.error;$('#go').disabled=false;return}
  const poll=async()=>{const s=await (await fetch('status?job='+j.job)).json();const log=s.lines.join('\n');
    let k=0;STEPS.forEach((x,i)=>{if(log.includes(x[0]))k=i+1});if(s.done&&s.ok)k=5;
    document.querySelectorAll('.steps div').forEach((d,i)=>d.classList.toggle('on',i<k));
    $('#st').textContent=s.done?(s.ok?`완료 · ${s.elapsed}초`:'실행 중 문제가 생겼어요. 검증 과정 탭에서 로그를 확인하세요.'):`${(STEPS[Math.max(0,k-1)]||STEPS[0])[1]} · ${s.elapsed}초`;
    window._log=log;if(!s.done)return setTimeout(poll,1000);$('#go').disabled=false;
    if(s.ok){const d=await (await fetch('result?job='+j.job)).json();renderUser(d);renderDev(d);$('#dev').innerHTML+=`<h2>실행 로그</h2><pre>${esc(log)}</pre>`;$('#tabs').hidden=false}
    else{$('#dev').innerHTML=`<pre>${esc(log)}</pre>`;$('#tabs').hidden=false;$('#dev').hidden=false;$('#res').hidden=true}};poll()};
const TYPE={official_notice:'공식 공지',field_survey:'현장 조사',structured_data:'방문단 정보',internal_guideline:'운영 규칙',interpretation_draft:'해설 자료',community_post:'지역 게시판',promotional:'홍보물',personal_blog:'개인 블로그',advertisement:'광고',archive:'과거 기록',web_search:'웹 검색',public_api:'공공 API',external_instruction:'의심되는 외부 지시',other:'기타'};
const TRUST={use:['믿을 수 있음','g'],use_with_caution:['주의해서 사용',''],background_only:['참고용',''],ignore:['사용 안 함','r']};
function renderUser(d){
  const R=d.result||{},P=R.plan||{},V=R.resolved||{},S={};(R.sources||[]).forEach(s=>S[s.id]=s);
  const order=[],num={};const fn=ids=>(ids||[]).filter(i=>S[i]).map(i=>{if(!(i in num)){order.push(i);num[i]=order.length}return `<sup class="fn" data-i="${esc(i)}">[${num[i]}]</sup>`}).join('');
  const Q=(R.consensus||[]).map(g=>(g.quorum||{}).status),conf=Q.filter(x=>x==='confirmed').length;
  const used=(R.sources||[]).filter(s=>s.trust!=='ignore').length;
  let h=`<div class="hero"><h2>${esc(P.title)}</h2><div>${esc(P.summary)}</div><div class="badges"><span class="b r">초안 · 예약/연락하지 않음</span>${R.visit_date?`<span class="b">📅 ${esc(R.visit_date)}</span>`:''}<span class="b">${{foreign:'🌏 해외 방문객',korean:'🇰🇷 한국인'}[R.lens?.visitor_type]||''}</span></div>
   <div class="trust"><div><b>${used}/${(R.sources||[]).length}</b>사용한 자료</div><div><b>${conf}</b>교차 확인된 정보</div><div><b>${(V.untrusted_instructions||[]).length}</b>무시한 의심 지시</div></div></div>`;
  if((P.day_card||[]).length)h+=`<h2>📱 오늘의 카드</h2><div class="phone"><div class="t">${esc(P.title)}</div><ul>${P.day_card.map(x=>`<li>${esc(x)}</li>`).join('')}</ul></div><p class="mut small" style="text-align:center">화면을 캡처해 두면 현장에서 바로 볼 수 있어요.</p>`;
  if((P.itinerary||[]).length)h+=`<h2>🗺 일정</h2><div class="tl">${P.itinerary.map(i=>`<div class="it"><span class="time">${esc(i.time)}</span><h3>${esc(i.place)}${fn(i.evidence)}</h3><div>${esc(i.activity)}</div>${i.access_notes?`<div class="note">♿ ${esc(i.access_notes)}</div>`:''}</div>`).join('')}</div>`;
  if((P.phrase_cards||[]).length)h+=`<h2>🗣 직원에게 이 화면을 보여주세요</h2>`+P.phrase_cards.map(c=>`<div class="show"><div class="mut small">${esc(c.person)} · ${esc(c.situation)}</div><div class="ko">${esc(c.show_to_staff)}</div><div class="mut">${esc(c.meaning)}</div></div>`).join('');
  if((P.dietary_plan||[]).length)h+=`<h2>🍽 식사 안내</h2>`+P.dietary_plan.map(x=>`<div class="card"><h3>${esc(x.person)} ${(x.needs||[]).map(n=>`<span class="b r">${esc(n)}</span>`).join(' ')}${fn(x.evidence)}</h3><div>${esc(x.guidance)}</div>${x.ask_on_site?`<div class="mut small">현장에서 물어볼 것: ${esc(x.ask_on_site)}</div>`:''}</div>`).join('');
  if((P.interpretation||[]).length)h+=`<h2>📜 이야기</h2>`+P.interpretation.map(x=>`<div class="card"><h3>${esc(x.place)}${fn(x.evidence)}</h3><div>${esc(x.text)}</div>${x.caveats?`<div class="note">※ ${esc(x.caveats)}</div>`:''}</div>`).join('');
  if((P.scenarios||[]).length)h+=`<h2>🔀 혹시 이런 경우엔</h2><div class="card"><ul>${P.scenarios.map(x=>`<li><b>${esc(x.if)}</b> → ${esc(x.then)}${fn(x.evidence)}</li>`).join('')}</ul></div>`;
  if((P.decisions||[]).length)h+=`<details class="card"><summary>🧭 정보가 불완전할 때 이렇게 판단했어요 (${P.decisions.length})</summary><ul>${P.decisions.map(x=>`<li><b>${esc(x.question)}</b><br>→ ${esc(x.choice)} <span class="mut small">(${esc(x.why)})</span></li>`).join('')}</ul></details>`;
  const unc=P.uncertainties||[],apv=P.approvals_needed||[];
  if(unc.length||apv.length)h+=`<h2>✅ 출발 전에</h2><div class="card">${unc.length?`<b>확인이 필요한 것</b><ul>${unc.map(x=>`<li>${esc(x)}</li>`).join('')}</ul>`:''}${apv.length?`<b>에이전트가 하지 않은 일 (승인 필요)</b><ul>${apv.map(x=>`<li>${esc(x)}</li>`).join('')}</ul>`:''}</div>`;
  const TC=R.tool_calls||[],TN={wiki:'위키백과',weather:'날씨',tavily:'웹 검색',brave:'웹 검색',naver:'네이버',tour:'관광공사'};
  if(TC.length)h+=`<h2>🔎 에이전트가 직접 찾아본 것</h2><div class="card"><div class="mut small">주어진 자료로 부족한 정보를 허용된 공식 API로 확인했어요. 찾은 결과도 그대로 믿지 않고 다른 자료와 비교했습니다.</div><ul>${TC.map(c=>{const a=c.args||{};const q=a.query||a.keyword||a.place||'';return `<li>${c.ok?'✅':'⛔'} <b>${esc(TN[c.tool]||c.tool)}</b> “${esc(q)}”${c.why?` <span class="mut small">— ${esc(c.why)}</span>`:''}${c.ok?'':` <span class="bad small">(${esc((c.error||'').slice(0,60))})</span>`}</li>`}).join('')}</ul></div>`;
  const srcRow=(i,n)=>{const s=S[i],t=TRUST[s.trust]||['',''];return `<div class="src" id="src-${esc(i)}"><div class="n">${n}</div><div><b>${s.origin==='external'?'🌐 ':'📄 '}${esc(s.label||s.path)}</b> <span class="b">${esc(TYPE[s.source_type]||s.source_type||'')}</span> <span class="b ${t[1]}">${t[0]}</span>${s.content_date||s.doc_date?` <span class="b">${esc(s.content_date||s.doc_date)}</span>`:''}
     ${(s.quotes||[]).map(q=>`<div class="q">“${esc(q)}”</div>`).join('')}${(s.urls||[]).map(u=>`<div><a href="${esc(u.url)}" target="_blank" rel="noopener">${esc(u.title)}</a></div>`).join('')}${s.trust_reason?`<div class="mut small">${esc(s.trust_reason)}</div>`:''}</div></div>`};
  h+=`<h2>📚 출처</h2><div class="card">${order.length?order.map((i,k)=>srcRow(i,k+1)).join(''):'<span class="mut">인용된 출처가 없습니다.</span>'}</div>`;
  const rest=(R.sources||[]).filter(s=>!(s.id in num));
  if(rest.length)h+=`<details class="card"><summary>참고했지만 코스에 쓰지 않은 자료 ${rest.length}개 · 왜 뺐는지 보기</summary>${rest.map(s=>{const t=TRUST[s.trust]||['',''];return `<div class="src"><div class="n">–</div><div><b>${esc(s.label||s.path)}</b> <span class="b">${esc(TYPE[s.source_type]||s.source_type||'')}</span> <span class="b ${t[1]}">${t[0]}</span><div class="mut small">${esc(s.trust_reason||'')}</div></div></div>`}).join('')}</details>`;
  h+=`<p class="mut small">🛡 이 코스는 NVIDIA OpenShell 보안 샌드박스 안에서 Nemotron이 만들었습니다. 허용된 공식 API 외에는 외부로 아무것도 보내지 않으며, 자료 속 의심스러운 지시는 따르지 않습니다.</p>`;
  $('#res').innerHTML=h;$('#res').hidden=false;$('#dev').hidden=true;
  document.querySelectorAll('sup.fn').forEach(e=>e.onclick=()=>{const t=document.getElementById('src-'+e.dataset.i);if(!t)return;document.querySelectorAll('.src.hl').forEach(x=>x.classList.remove('hl'));t.classList.add('hl');t.scrollIntoView({behavior:'smooth',block:'center'})});
}
function renderDev(d){
  const R=d.result||{},P=R.plan||{},V=R.resolved||{},A=d.audit||[],src={};(R.sources||[]).forEach(s=>src[s.id]=s.path);
  const ev=ids=>(ids||[]).map(i=>`<span class="tag">${esc(src[i]||i)}</span>`).join('');
  const cnt=k=>A.filter(e=>e.kind===k).length;
  let h=`<h2>${esc(P.title)}</h2><p><span class="tag warn">초안 · 예약/발송하지 않음</span> <span class="tag">${esc(R.lens?.visitor_type)} / ${esc((R.lens?.interests||[]).join(', '))}</span> <span class="tag">방문일 ${esc(R.visit_date)}</span></p><p>${esc(P.summary)}</p>`;
  if((P.day_card||[]).length)h+=`<h2>📱 한눈에 보는 일정 카드</h2><div class="card"><ul>${P.day_card.map(x=>`<li>${esc(x)}</li>`).join('')}</ul></div>`;
  if((P.phrase_cards||[]).length)h+=`<h2>🗣 현장 직원에게 보여주세요</h2>`+P.phrase_cards.map(c=>`<div class="card" style="border-color:var(--acc)"><div class="sub">${esc(c.person)} · ${esc(c.situation)}</div><div style="font-size:24px;line-height:1.4;margin:6px 0">${esc(c.show_to_staff)}</div><div class="sub">${esc(c.meaning)}</div></div>`).join('');
  if((P.deliverable_text||'').trim())h+=`<h2>요청 결과물</h2><div class="card" style="white-space:pre-wrap">${esc(P.deliverable_text)}</div>`;
  if((P.decisions||[]).length)h+=`<h2>🧭 핵심 결정 (불완전한 정보에서)</h2><div class="card"><table><tr><th>질문</th><th>선택</th><th>이유</th><th>틀리면</th></tr>${P.decisions.map(d=>`<tr><td>${esc(d.question)}</td><td><b>${esc(d.choice)}</b></td><td>${esc(d.why)}</td><td class="warn">${esc(d.risk_if_wrong)}</td></tr>`).join('')}</table></div>`;
  if((P.scenarios||[]).length)h+=`<h2>🔀 상황별 대안 (Plan B)</h2><div class="card"><ul>${P.scenarios.map(x=>`<li><b>만약</b> ${esc(x.if)} → ${esc(x.then)} ${ev(x.evidence)}</li>`).join('')}</ul></div>`;
  h+=`<h2>일정</h2><div class="card"><table><tr><th>시간</th><th>장소</th><th>활동</th><th>접근·주의</th><th>근거</th></tr>`+(P.itinerary||[]).map(i=>`<tr><td>${esc(i.time)}</td><td>${esc(i.place)}</td><td>${esc(i.activity)}</td><td>${esc(i.access_notes)}</td><td>${ev(i.evidence)}</td></tr>`).join('')+`</table></div>`;
  h+=`<h2>음식 제한</h2>`+(P.dietary_plan||[]).map(x=>`<div class="card"><b>${esc(x.person)}</b> ${(x.needs||[]).map(n=>`<span class="tag bad">${esc(n)}</span>`).join('')}<div>${esc(x.guidance)}</div><div class="sub">현장 확인: ${esc(x.ask_on_site)}</div>${ev(x.evidence)}</div>`).join('');
  h+=`<h2>해설</h2>`+(P.interpretation||[]).map(x=>`<div class="card"><b>${esc(x.place)}</b><div>${esc(x.text)}</div><div class="warn">주의: ${esc(x.caveats)}</div>${ev(x.evidence)}</div>`).join('');
  h+=`<h2>왜 이 정보를 골랐나</h2><div class="card"><table><tr><th>주제</th><th>판정</th><th>상태</th><th>결정 기준</th><th>근거</th><th>버린 자료</th></tr>`+(V.facts||[]).map(f=>`<tr><td>${esc(f.topic)}<br><span class="sub">${esc(f.subject)}</span></td><td>${esc(f.decision)}</td><td class="${f.status==='confirmed'?'ok':'warn'}">${esc(f.status)}</td><td><span class="tag">${esc(f.decided_by)}</span><div class="sub">${esc(f.rationale)}</div></td><td>${ev(f.evidence)}</td><td>${(f.overridden||[]).map(o=>`<div><span class="tag">${esc(src[o.doc]||o.doc)}</span> ${esc(o.reason)}</div>`).join('')}</td></tr>`).join('')+`</table></div>`;
  const li=a=>`<ul>${(a||[]).map(x=>`<li>${x}</li>`).join('')||'<li>없음</li>'}</ul>`;
  const CS=(R.consensus||[]).filter(g=>g.candidates.length>1);
  if(CS.length)h+=`<h2>⚖️ 합의 표 (원문 인용 × 근거 점수)</h2><div class="card"><table><tr><th>주제·속성</th><th>후보 (점수 높은 순)</th><th>정족수 판정 (2/3)</th></tr>`+CS.map(g=>`<tr><td>${esc(g.topic)}<br><span class="sub">${esc(g.attribute)}</span></td><td>${g.candidates.map(c=>`<div><b>${esc(c.value)}</b> <span class="tag">${esc(src[c.doc]||c.doc)}</span> 점수 ${esc(c.score)} ${c.quote_verified?'<span class="ok">✓인용</span>':'<span class="bad">✗인용</span>'}</div>`).join('')}</td><td class="${{confirmed:'ok',tentative:'warn',unresolved:'bad'}[(g.quorum||{}).status]||''}"><b>${{confirmed:'확정',tentative:'잠정',unresolved:'미결'}[(g.quorum||{}).status]||''}</b> ${esc((g.quorum||{}).winner)} (${Math.round(((g.quorum||{}).share||0)*100)}%)</td></tr>`).join('')+`</table></div>`;
  const TV={use:'ok',use_with_caution:'warn',background_only:'sub',ignore:'bad'};
  h+=`<h2>🔎 자료 신뢰 판정</h2><div class="card"><table><tr><th>자료</th><th>종류</th><th>판정</th><th>이유</th></tr>`+(R.sources||[]).map(s=>`<tr><td><span class="tag">${esc(s.path)}</span></td><td>${esc(s.source_type)}</td><td class="${TV[s.trust]||''}"><b>${esc(s.trust)}</b></td><td>${esc(s.trust_reason)}</td></tr>`).join('')+`</table></div>`;
  h+=`<h2>확인 필요 · 승인 필요</h2><div class="card"><b class="warn">확인 필요</b>${li((P.uncertainties||[]).map(esc))}<b>승인 필요 (수행하지 않음)</b>${li((P.approvals_needed||[]).map(esc))}</div>`;
  h+=`<h2>🛡 보안 패널</h2><div class="grid"><div class="stat"><b>${cnt('file_read')}</b>허용된 파일 읽기</div><div class="stat"><b class="bad">${cnt('blocked_read')+cnt('blocked_write')}</b>차단된 파일 접근</div><div class="stat"><b class="bad">${(V.untrusted_instructions||[]).length}</b>무시한 외부 지시</div><div class="stat"><b>${(V.excluded_sources||[]).length}</b>제외한 자료</div><div class="stat"><b class="ok">0</b>외부 전송·예약·발송</div></div>`;
  h+=`<div class="card"><b class="bad">따르지 않은 외부 지시</b>${li((V.untrusted_instructions||[]).map(x=>`<span class="tag">${esc(src[x.doc]||x.doc)}</span> ${esc(x.summary)}`))}<b>제외한 자료</b>${li((V.excluded_sources||[]).map(x=>`<span class="tag">${esc(src[x.doc]||x.doc)}</span> ${esc(x.reason)}`))}</div>`;
  $('#dev').innerHTML=h}
</script></main></body></html>"""


def main() -> None:
    port = int(os.environ.get("ITDA_WEB_PORT", "8501"))
    srv = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    print(f"ItDA UI on http://0.0.0.0:{port}  (runner: {os.environ.get('ITDA_RUNNER', 'host')})")
    srv.serve_forever()


if __name__ == "__main__":
    main()
