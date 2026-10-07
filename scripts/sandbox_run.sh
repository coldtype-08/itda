#!/bin/sh
# Upload ItDA + allowed inputs into the NemoClaw/OpenShell sandbox, run, and download results.
# restricted/ and secrets/ are deliberately NOT uploaded.
#   SANDBOX=itda-hack sh scripts/sandbox_run.sh --visitor foreign --interests history,family
# Local Nano NIM on the L40S for small jobs (tool-result triage; needs the local-inference preset):
#   ITDA_MODEL_SMALL=nvidia/nemotron-3-nano ITDA_SANDBOX_SMALL_BASE_URL=http://host.openshell.internal:8000/v1 \
#   SANDBOX=itda-hack sh scripts/sandbox_run.sh
set -eu
[ -f ~/.itda.env ] && set -a && . ~/.itda.env && set +a
SB=${SANDBOX:-itda-hack}
NC="nemo-deepagents $SB"
STAGE=$(mktemp -d)
trap 'rm -rf "$STAGE"' EXIT

mkdir -p "$STAGE/itda/challenge/hackathon/output"
cp -R itda attacks "$STAGE/itda/"
# Task and inputs: the challenge folder by default, or a live request from the web UI.
cp "${TASK_FILE:-challenge/TASK.md}" "$STAGE/itda/challenge/TASK.md"
cp -R "${INPUT_DIR:-challenge/hackathon/input}" "$STAGE/itda/challenge/hackathon/input"

# Start clean: upload merges into existing dirs, so stale inputs from a previous run would leak in.
$NC exec -- rm -rf /sandbox/itda >/dev/null 2>&1 || true
$NC upload "$STAGE/itda" /sandbox/
# Tool API keys (opt-in). They enter the sandbox as env vars, but egress is limited to the
# allow-listed API hosts in policy/presets/, so they cannot be sent anywhere else.
TOOLENV=""
if [ -n "${ITDA_SANDBOX_TOOL_KEYS:-}" ]; then
  for k in TAVILY_API_KEY BRAVE_API_KEY NAVER_CLIENT_ID NAVER_CLIENT_SECRET DATA_GO_KR_KEY; do
    eval "v=\${$k:-}"; [ -n "$v" ] && TOOLENV="$TOOLENV $k=$v"
  done
fi
# inference.local: credentials stay on the host gateway; the sandbox never sees the API key.
$NC exec --workdir /sandbox/itda -- env \
  ITDA_LLM_BASE_URL="${ITDA_SANDBOX_BASE_URL:-https://inference.local/v1}" \
  ITDA_MODEL="${ITDA_MODEL:-nvidia/nemotron-3-super-120b-a12b}" \
  ITDA_MODEL_FAST="${ITDA_MODEL_FAST:-nvidia/nemotron-3-super-120b-a12b}" \
  ITDA_FAST_BASE_URL="${ITDA_SANDBOX_FAST_BASE_URL:-}" \
  ITDA_MODEL_SMALL="${ITDA_MODEL_SMALL:-}" $TOOLENV \
  ITDA_SMALL_BASE_URL="${ITDA_SANDBOX_SMALL_BASE_URL:-}" \
  python3 -m itda "$@"
OUT=${OUT_DIR:-out}; mkdir -p "$OUT"
$NC download /sandbox/itda/challenge/hackathon/output "$OUT/"
echo "results in $OUT"
