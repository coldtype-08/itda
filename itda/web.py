"""Minimal demo UI (stdlib only): pick a lens, run the agent, watch progress, read results.

    python3 -m itda.web                      # agent runs on this host
    ITDA_RUNNER=sandbox SANDBOX=itda-hack python3 -m itda.web   # agent runs inside OpenShell

Open http://<host>:8501
"""
from __future__ import annotations

import json
import os
import re
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


def _runner() -> str:
    """Where the agent actually runs. Only scripts/web_up.sh (ITDA_RUNNER=sandbox) runs it inside OpenShell."""
    return "sandbox" if os.environ.get("ITDA_RUNNER") == "sandbox" else "host"


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


CHALLENGE_TASK = ROOT / "challenge" / "TASK.md"
CHALLENGE_INPUT = ROOT / "challenge" / "hackathon" / "input"


def _write_task(task_dir: Path, header: str, body: str) -> Path:
    task_dir.mkdir(parents=True, exist_ok=True)
    (task_dir / "TASK.md").write_text(header + body, encoding="utf-8")
    return task_dir / "TASK.md"


def _challenge_query(job_dir: Path, req: dict) -> Path:
    """Challenge mode with the user's own question about the provided materials."""
    date = (req.get("date") or "").strip()[:10]
    comp = (req.get("companions") or "").strip()[:1000]
    return _write_task(job_dir / "task", "# 요청 (주어진 자료에 대한 사용자 질문)\n",
                       (req.get("request") or "").strip()[:2000]
                       + (f"\n\n방문일: {date}" if date else "") + (f"\n동행자·조건: {comp}" if comp else "")
                       + "\n\n주어진 자료 폴더를 근거로 답한다. 예약·연락·결제는 하지 않는다.\n")


def _followup_inputs(job_dir: Path, parent: dict, question: str) -> tuple[Path, Path]:
    """Follow-up: same materials + the previous draft (as something to revise, not evidence) +
    the previous task with the new question appended. Runs through the full trust pipeline again."""
    import shutil
    inp = job_dir / "input"
    shutil.copytree(parent["input_dir"], inp, dirs_exist_ok=True)
    prev = {}
    found = [p for p in Path(parent["out"]).rglob("itda_result.json")]
    if found:
        r = json.loads(found[0].read_text())
        pl = r.get("plan", {})
        prev = {k: pl.get(k) for k in ("title", "summary", "itinerary", "dietary_plan", "considerations",
                                         "decisions", "scenarios", "uncertainties")}
    (inp / "followup").mkdir(parents=True, exist_ok=True)
    (inp / "followup" / "previous_draft.json").write_text(
        json.dumps({"note": "ItDA가 이전에 만든 초안 (사실 근거 아님, 수정 대상)", **prev}, ensure_ascii=False, indent=1),
        encoding="utf-8")
    base = Path(parent["task_file"]).read_text(encoding="utf-8")
    task = _write_task(job_dir / "task", base, f"\n\n[연계 질문]\n{question.strip()[:1000]}\n"
                       "이전 초안(followup/previous_draft.json)을 바탕으로 이 질문에 답하고, 필요하면 코스를 수정한다. "
                       "바뀐 점을 분명히 적는다.\n")
    return task, inp


def _start(visitor: str, interests: list[str], req: dict | None = None) -> str:
    job = uuid.uuid4().hex[:8]
    out = RUNS / job
    out.mkdir(parents=True, exist_ok=True)
    args = ["--visitor", visitor, "--interests", ",".join(interests)]
    if req and req.get("lang") in ("ko", "en", "ja", "zh"):
        args += ["--lang", req["lang"]]
    elif req and visitor != "foreign" and re.search(r"[가-힣]", (req.get("request") or "") + (req.get("followup") or "")):
        args += ["--lang", "ko"]  # a question typed in Korean gets a Korean answer unless 'foreign' was chosen
    extra_env = {}
    task, inp = CHALLENGE_TASK, CHALLENGE_INPUT
    req = req or {}
    parent = JOBS.get(req.get("parent") or "")
    if parent and (req.get("followup") or "").strip():
        task, inp = _followup_inputs(RUNS / f"{job}_in", parent, req["followup"])
    elif req.get("mode") == "live":
        task, inp = _live_inputs(RUNS / f"{job}_in", req)
    elif (req.get("request") or "").strip():
        task = _challenge_query(RUNS / f"{job}_in", req)
    if task != CHALLENGE_TASK or inp != CHALLENGE_INPUT:
        args += ["--task", str(task), "--input", str(inp)]
        extra_env = {"TASK_FILE": str(task), "INPUT_DIR": str(inp)}
    if os.environ.get("ITDA_RUNNER") == "sandbox":
        sb_args = [a for a in args if a not in ("--task", "--input") and a not in extra_env.values()]
        cmd = ["sh", "scripts/sandbox_run.sh", *sb_args]
        env = {**os.environ, "OUT_DIR": str(out), **extra_env}
    else:
        cmd = [sys.executable, "-m", "itda", *args, "--output", str(out)]
        env = dict(os.environ)
    JOBS[job] = {"lines": [f"$ {' '.join(cmd)}"], "done": False, "ok": None, "out": str(out), "t0": time.time(),
                 "runner": _runner(),
                 "task_file": str(task), "input_dir": str(inp), "mode": req.get("mode")}

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
    data: dict = {"runner": JOBS[job].get("runner", _runner())}
    for name, key in (("itda_result.json", "result"), ("audit.json", "audit")):
        if name in found:
            data[key] = json.loads(found[name].read_text())
    if "course_draft.md" in found:
        data["markdown"] = found["course_draft.md"].read_text()
    if "llm_transcript.json" in found:
        data["transcript"] = json.loads(found["llm_transcript.json"].read_text())
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
            body = PAGE.replace("__ITDA_RUNNER__", _runner()).encode()
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
        if body.get("followup") and body.get("parent") not in JOBS:
            return self._json({"error": "이전 결과를 찾을 수 없어요. 코스를 먼저 만들어 주세요"}, 400)
        if body.get("mode") == "live" and not body.get("followup") and len((body.get("request") or "").strip()) < 5:
            return self._json({"error": "요청 내용을 적어 주세요"}, 400)
        with LOCK:
            if any(not j["done"] for j in JOBS.values()):
                return self._json({"error": "a run is already in progress"}, 409)
            self._json({"job": _start(visitor, interests, body)})


from .web_page import PAGE  # noqa: E402  (Tailwind page)


def main() -> None:
    port = int(os.environ.get("ITDA_WEB_PORT", "8501"))
    srv = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    print(f"ItDA UI on http://0.0.0.0:{port}  (runner: {os.environ.get('ITDA_RUNNER', 'host')})")
    srv.serve_forever()


if __name__ == "__main__":
    main()
