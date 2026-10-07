#!/bin/sh
# Evidence that the NVIDIA stack is actually in use (run on the server after one agent run).
#   sh scripts/stack_check.sh
cd "$(dirname "$0")/.."
SB=${SANDBOX:-itda-hack}
say() { printf '\n\033[1m== %s\033[0m\n' "$*"; }

say "L40S + local NIM (Nemotron 3 Nano)"
nvidia-smi --query-gpu=name,memory.used,memory.total --format=csv,noheader
docker ps --filter name=itda-nano --format '{{.Image}}  {{.Status}}'
curl -s -m 5 localhost:8000/v1/models | python3 -c "import sys,json;print('served:', [m['id'] for m in json.load(sys.stdin)['data']])" 2>/dev/null || echo "local NIM not answering"

say "NeMoClaw (sandbox lifecycle + managed inference route)"
nemo-deepagents "$SB" status 2>&1 | grep -aiE "sandbox|phase|model|provider|ready|running" | head -6
nemo-deepagents inference get 2>&1 | grep -aiE "provider|model|route" | head -4

say "OpenShell (sandbox, enforced policy, denials)"
openshell sandbox list 2>&1 | grep -a "$SB"
echo "network policies:"; openshell policy get "$SB" --full 2>/dev/null | awk '/^network_policies:/{f=1;next} /^[^ ]/{f=0} f && /^  [^ ].*:$/{print}' | sed 's/^/ /'
echo "landlock: $(openshell policy get "$SB" --full 2>/dev/null | grep -A1 '^landlock' | tail -1)"
echo "denied events in sandbox log: $(openshell logs "$SB" --source sandbox 2>/dev/null | grep -ac DENIED)"

say "Last agent run (audit.json): which model served which step, through which endpoint"
A=$(ls -t $(find out -name audit.json 2>/dev/null) 2>/dev/null | head -1)
[ -n "$A" ] && python3 - "$A" <<'PY'
import json, sys, collections
a = json.load(open(sys.argv[1]))
print("file:", sys.argv[1])
c = collections.Counter((e.get("model"), e.get("endpoint")) for e in a if e["kind"] == "llm_call" and e.get("ok"))
for (m, ep), n in c.most_common():
    where = {"inference.local": "OpenShell gateway → build.nvidia.com NIM",
             "host.openshell.internal:8000": "L40S local NIM (via OpenShell)",
             "localhost:8000": "L40S local NIM (host)",
             "integrate.api.nvidia.com": "build.nvidia.com NIM (host, no sandbox)"}.get(ep, ep or "?")
    print(f"  {n:3d} calls  {m:42s}  {where}")
print("  small-model fallbacks:", sum(e["kind"] == "small_model_fallback" for e in a))
print("  tool calls ok/blocked:", sum(e["kind"] == "tool_call" and e.get("ok") for e in a), "/",
      sum(e["kind"] == "tool_blocked" for e in a))
PY
[ -z "$A" ] && echo "no audit.json yet - run the agent once (web UI or scripts/sandbox_run.sh)"
