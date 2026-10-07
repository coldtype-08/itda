#!/bin/sh
# Save evidence that ItDA runs inside the OpenShell sandbox and that the policy blocks what it
# should, into docs/evidence.txt. Run on the server after at least one demo run (web UI or
# scripts/sandbox_run.sh), check the file, then commit it:
#   sh scripts/collect_evidence.sh
# Key values that can show up in logs (query-string keys, bearer tokens) are masked before saving.
set -u
cd "$(dirname "$0")/.."
SB=${SANDBOX:-itda-hack}
NC="nemo-deepagents $SB"
OUT=docs/evidence.txt
mask() {
  sed -E -e 's/\x1b\[[0-9;]*m//g' \
    -e 's/([Ss]ervice[Kk]ey|app[Kk]ey|api_?[Kk]ey|[Kk]ey|token|secret)=[^&[:space:]"]+/\1=<masked>/g' \
    -e 's/nvapi-[A-Za-z0-9_-]+/nvapi-<masked>/g' -e 's/tvly-[A-Za-z0-9_-]+/tvly-<masked>/g' \
    -e 's/(Bearer|X-Naver-Client-Secret:|X-API-Key:|appKey:) *[A-Za-z0-9._-]+/\1 <masked>/g'
}

# use the attack script from this checkout, even if no run has uploaded it yet
$NC exec -- mkdir -p /sandbox/itda >/dev/null 2>&1 || true
$NC upload attacks /sandbox/itda/ >/dev/null 2>&1 || true

{
  echo "# ItDA - OpenShell sandbox evidence"
  echo "# collected $(date '+%Y-%m-%d %H:%M:%S %Z')  sandbox: $SB  commit: $(git rev-parse --short HEAD 2>/dev/null)"
  echo
  echo "## 1. Attack demo, run INSIDE the sandbox (every line is expected to be BLOCKED)"
  echo "\$ $NC exec -- sh /sandbox/itda/attacks/run_attacks.sh"
  $NC exec -- sh /sandbox/itda/attacks/run_attacks.sh 2>&1
  echo
  echo "## 2. OpenShell deny log (OCSF, most recent 40)"
  echo "\$ openshell logs $SB --source sandbox | grep DENIED | tail -40"
  openshell logs "$SB" --source sandbox 2>&1 | grep -a DENIED | tail -40
  echo
  echo "## 3. Applied presets"
  $NC policy list 2>&1 | grep -a "●"
  echo
  echo "## 4. NVIDIA stack, enforced policy, last agent run (scripts/stack_check.sh)"
  sh scripts/stack_check.sh 2>&1
  echo
  echo "## 5. Last agent run: what it read and wrote (sandbox paths = it ran inside the sandbox)"
  A=$(ls -t $(find out -name audit.json 2>/dev/null) 2>/dev/null | head -1)
  if [ -n "$A" ]; then
    python3 - "$A" <<'PY'
import json, sys
a = json.load(open(sys.argv[1]))
print("audit:", sys.argv[1])
reads = [e["path"] for e in a if e["kind"] == "file_read"]
writes = sorted({e["path"] for e in a if e["kind"] == "file_write"})
print(f"files read: {len(reads)}   blocked reads: {sum(e['kind'] == 'blocked_read' for e in a)}")
for p in reads[:12]:
    print("  read ", p)
for p in writes:
    print("  wrote", p)
eps = sorted({e.get("endpoint") or "?" for e in a if e["kind"] == "llm_call" and e.get("ok")})
print("model endpoints used:", ", ".join(eps))
print("untrusted instructions flagged:", [e.get("doc") for e in a if e["kind"] == "untrusted_instruction"])
print("tools blocked by the app allow-list:", sum(e["kind"] == "tool_blocked" for e in a))
PY
  else
    echo "no audit.json yet - run the agent once (web UI or scripts/sandbox_run.sh)"
  fi
} 2>&1 | mask > "$OUT"

echo "saved $OUT ($(wc -l < "$OUT") lines): BLOCKED=$(grep -ac 'BLOCKED' "$OUT")  ALLOWED=$(grep -ac 'ALLOWED  <--' "$OUT")  DENIED=$(grep -ac 'DENIED' "$OUT")"
echo "check it, then: git add $OUT && git commit -m 'Sandbox evidence' && git push"
