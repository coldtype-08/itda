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


def _start(visitor: str, interests: list[str]) -> str:
    job = uuid.uuid4().hex[:8]
    out = RUNS / job
    out.mkdir(parents=True, exist_ok=True)
    args = ["--visitor", visitor, "--interests", ",".join(interests)]
    if os.environ.get("ITDA_RUNNER") == "sandbox":
        cmd = ["sh", "scripts/sandbox_run.sh", *args]
        env = {**os.environ, "OUT_DIR": str(out)}
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

    def do_GET(self) -> None:
        u = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        if u.path in ("/", "/index.html"):
            self._send(200, PAGE.encode(), "text/html")
        elif u.path == "/status" and q.get("job") in JOBS:
            j = JOBS[q["job"]]
            self._json({"lines": j["lines"][-200:], "done": j["done"], "ok": j["ok"],
                        "elapsed": round(time.time() - j["t0"])})
        elif u.path == "/result" and q.get("job") in JOBS:
            self._json(_result(q["job"]))
        else:
            self._json({"error": "not found"}, 404)

    def do_POST(self) -> None:
        if urlparse(self.path).path != "/run":
            return self._json({"error": "not found"}, 404)
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0)) or b"{}"))
        visitor = body.get("visitor")
        interests = [i for i in body.get("interests", []) if i in INTERESTS]
        if visitor not in VISITOR_TYPES or not interests:  # whitelist: nothing user-supplied reaches the shell
            return self._json({"error": "invalid lens"}, 400)
        with LOCK:
            if any(not j["done"] for j in JOBS.values()):
                return self._json({"error": "a run is already in progress"}, 409)
            self._json({"job": _start(visitor, interests)})


PAGE = r"""<!doctype html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>ItDA 잇다</title>
<style>
:root{--bg:#faf8f4;--card:#fff;--fg:#1f1d1a;--mut:#6b675f;--line:#e6e1d8;--acc:#9b3b2a;--ok:#2f6f4f;--warn:#a5631a;--bad:#a32d2d}
@media (prefers-color-scheme:dark){:root{--bg:#171614;--card:#211f1c;--fg:#ece8e1;--mut:#a29c92;--line:#36322d;--acc:#e0806b;--ok:#7cc4a0;--warn:#e5a65a;--bad:#f09595}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:16px/1.6 -apple-system,"Apple SD Gothic Neo","Noto Sans KR",sans-serif}
main{max-width:1000px;margin:0 auto;padding:24px 16px 64px}h1{font-size:28px;margin:0}h2{font-size:18px;margin:28px 0 10px}
.sub{color:var(--mut);margin:4px 0 20px}.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:16px;margin:12px 0}
.row{display:flex;gap:10px;flex-wrap:wrap}.opt{border:1px solid var(--line);background:var(--card);color:var(--fg);border-radius:10px;padding:12px 18px;cursor:pointer;font-size:16px}
.opt.on{border-color:var(--acc);box-shadow:0 0 0 2px var(--acc) inset}.go{background:var(--acc);color:#fff;border:0;border-radius:10px;padding:12px 24px;font-size:16px;cursor:pointer}
.go:disabled{opacity:.5}pre{background:var(--bg);border:1px solid var(--line);border-radius:8px;padding:10px;max-height:260px;overflow:auto;font-size:12px;white-space:pre-wrap}
table{width:100%;border-collapse:collapse;font-size:14px}td,th{border-bottom:1px solid var(--line);padding:8px;text-align:left;vertical-align:top}
.tag{display:inline-block;font-size:12px;border:1px solid var(--line);border-radius:999px;padding:1px 8px;margin:2px 2px 0 0;color:var(--mut)}
.bad{color:var(--bad)}.ok{color:var(--ok)}.warn{color:var(--warn)}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px}
.stat{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:12px}.stat b{font-size:24px;display:block}
ul{margin:6px 0;padding-left:20px}
</style></head><body><main>
<h1>ItDA 잇다</h1><p class="sub">흩어진 기록을 검증해 나에게 맞는 문화 코스 초안으로 잇습니다 · Nemotron × OpenShell</p>
<div class="card"><div><b>1. 누구세요?</b></div><div class="row" id="vis" style="margin:8px 0 14px">
<button class="opt on" data-v="foreign">🌏 외국인 방문객</button><button class="opt" data-v="korean">🇰🇷 한국인</button></div>
<div><b>2. 무엇이 궁금하세요?</b></div><div class="row" id="int" style="margin:8px 0 14px">
<button class="opt on" data-v="history">📜 역사적 맥락</button><button class="opt on" data-v="family">👨‍👩‍👧 가족·동행</button><button class="opt" data-v="kculture">🎤 K-컬처</button></div>
<button class="go" id="go">코스 초안 만들기</button> <span id="st" class="sub"></span>
<pre id="log" hidden></pre></div>
<div id="res"></div>
<script>
const $=s=>document.querySelector(s),esc=s=>String(s??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
let visitor='foreign';
document.querySelectorAll('#vis .opt').forEach(b=>b.onclick=()=>{document.querySelectorAll('#vis .opt').forEach(x=>x.classList.remove('on'));b.classList.add('on');visitor=b.dataset.v});
document.querySelectorAll('#int .opt').forEach(b=>b.onclick=()=>b.classList.toggle('on'));
$('#go').onclick=async()=>{
  const interests=[...document.querySelectorAll('#int .opt.on')].map(b=>b.dataset.v);
  if(!interests.length){$('#st').textContent='관심사를 하나 이상 고르세요';return}
  $('#go').disabled=true;$('#res').innerHTML='';$('#log').hidden=false;$('#log').textContent='';
  const r=await fetch('run',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({visitor,interests})});
  const j=await r.json();if(!r.ok){$('#st').textContent=j.error;$('#go').disabled=false;return}
  const poll=async()=>{const s=await (await fetch('status?job='+j.job)).json();
    $('#log').textContent=s.lines.join('\n');$('#log').scrollTop=1e9;$('#st').textContent=(s.done?(s.ok?'완료':'실패'):'실행 중… ')+s.elapsed+'s';
    if(!s.done)return setTimeout(poll,1000);$('#go').disabled=false;if(s.ok)render(await (await fetch('result?job='+j.job)).json())};poll()};
function render(d){
  const R=d.result||{},P=R.plan||{},V=R.resolved||{},A=d.audit||[],src={};(R.sources||[]).forEach(s=>src[s.id]=s.path);
  const ev=ids=>(ids||[]).map(i=>`<span class="tag">${esc(src[i]||i)}</span>`).join('');
  const cnt=k=>A.filter(e=>e.kind===k).length;
  let h=`<h2>${esc(P.title)}</h2><p><span class="tag warn">초안 · 예약/발송하지 않음</span> <span class="tag">${esc(R.lens?.visitor_type)} / ${esc((R.lens?.interests||[]).join(', '))}</span> <span class="tag">방문일 ${esc(R.visit_date)}</span></p><p>${esc(P.summary)}</p>`;
  h+=`<h2>일정</h2><div class="card"><table><tr><th>시간</th><th>장소</th><th>활동</th><th>접근·주의</th><th>근거</th></tr>`+(P.itinerary||[]).map(i=>`<tr><td>${esc(i.time)}</td><td>${esc(i.place)}</td><td>${esc(i.activity)}</td><td>${esc(i.access_notes)}</td><td>${ev(i.evidence)}</td></tr>`).join('')+`</table></div>`;
  h+=`<h2>음식 제한</h2>`+(P.dietary_plan||[]).map(x=>`<div class="card"><b>${esc(x.person)}</b> ${(x.needs||[]).map(n=>`<span class="tag bad">${esc(n)}</span>`).join('')}<div>${esc(x.guidance)}</div><div class="sub">현장 확인: ${esc(x.ask_on_site)}</div>${ev(x.evidence)}</div>`).join('');
  h+=`<h2>해설</h2>`+(P.interpretation||[]).map(x=>`<div class="card"><b>${esc(x.place)}</b><div>${esc(x.text)}</div><div class="warn">주의: ${esc(x.caveats)}</div>${ev(x.evidence)}</div>`).join('');
  h+=`<h2>왜 이 정보를 골랐나</h2><div class="card"><table><tr><th>주제</th><th>판정</th><th>상태</th><th>결정 기준</th><th>근거</th><th>버린 자료</th></tr>`+(V.facts||[]).map(f=>`<tr><td>${esc(f.topic)}<br><span class="sub">${esc(f.subject)}</span></td><td>${esc(f.decision)}</td><td class="${f.status==='confirmed'?'ok':'warn'}">${esc(f.status)}</td><td><span class="tag">${esc(f.decided_by)}</span><div class="sub">${esc(f.rationale)}</div></td><td>${ev(f.evidence)}</td><td>${(f.overridden||[]).map(o=>`<div><span class="tag">${esc(src[o.doc]||o.doc)}</span> ${esc(o.reason)}</div>`).join('')}</td></tr>`).join('')+`</table></div>`;
  const li=a=>`<ul>${(a||[]).map(x=>`<li>${x}</li>`).join('')||'<li>없음</li>'}</ul>`;
  h+=`<h2>확인 필요 · 승인 필요</h2><div class="card"><b class="warn">확인 필요</b>${li((P.uncertainties||[]).map(esc))}<b>승인 필요 (수행하지 않음)</b>${li((P.approvals_needed||[]).map(esc))}</div>`;
  h+=`<h2>🛡 보안 패널</h2><div class="grid"><div class="stat"><b>${cnt('file_read')}</b>허용된 파일 읽기</div><div class="stat"><b class="bad">${cnt('blocked_read')+cnt('blocked_write')}</b>차단된 파일 접근</div><div class="stat"><b class="bad">${(V.untrusted_instructions||[]).length}</b>무시한 외부 지시</div><div class="stat"><b>${(V.excluded_sources||[]).length}</b>제외한 자료</div><div class="stat"><b class="ok">0</b>외부 전송·예약·발송</div></div>`;
  h+=`<div class="card"><b class="bad">따르지 않은 외부 지시</b>${li((V.untrusted_instructions||[]).map(x=>`<span class="tag">${esc(src[x.doc]||x.doc)}</span> ${esc(x.summary)}`))}<b>제외한 자료</b>${li((V.excluded_sources||[]).map(x=>`<span class="tag">${esc(src[x.doc]||x.doc)}</span> ${esc(x.reason)}`))}</div>`;
  $('#res').innerHTML=h}
</script></main></body></html>"""


def main() -> None:
    port = int(os.environ.get("ITDA_WEB_PORT", "8501"))
    srv = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    print(f"ItDA UI on http://0.0.0.0:{port}  (runner: {os.environ.get('ITDA_RUNNER', 'host')})")
    srv.serve_forever()


if __name__ == "__main__":
    main()
