"""Compare one Nemotron call with and without thinking: python3 scripts/speedtest.py [model]"""
import json, os, sys, time, urllib.request

model = sys.argv[1] if len(sys.argv) > 1 else "nvidia/nemotron-3-super-120b-a12b"
base = os.environ.get("ITDA_LLM_BASE_URL", "https://integrate.api.nvidia.com/v1")
msg = [{"role": "user", "content": '두 자료 중 2026-10-10 운영시간을 JSON {"hours","source"}로만: (A) 2025 블로그 토 10-18시 (B) 2026-10-06 상인회 공지 10/10은 10-14시만'}]
for label, extra in (("thinking OFF", {"chat_template_kwargs": {"enable_thinking": False}}), ("thinking ON (default)", {})):
    body = {"model": model, "messages": msg, "max_tokens": 4096, "temperature": 0.1, **extra}
    req = urllib.request.Request(base + "/chat/completions", data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json",
                                          "Authorization": f"Bearer {os.environ.get('NVIDIA_API_KEY', 'unused')}"})
    t = time.time()
    try:
        p = json.loads(urllib.request.urlopen(req, timeout=180).read())
        c = p["choices"][0]
        print(f"{label:<22} {time.time() - t:5.1f}s tokens={p.get('usage', {}).get('total_tokens')} "
              f"→ {(c['message'].get('content') or '')[:90]!r}")
    except Exception as e:
        print(f"{label:<22} ERROR {e}")
