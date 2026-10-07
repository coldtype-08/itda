#!/bin/sh
# Upload ItDA + the allowed part of the task pack into the NemoClaw/OpenShell sandbox, run,
# and download results. The layout matches policy/openshell-policy.yaml:
#   /sandbox/itda                   code       (read-only in the policy)
#   /sandbox/pack/TASK.md           request    (read-only)
#   /sandbox/pack/hackathon/input   documents  (read-only)
#   /sandbox/pack/hackathon/output  results    (the only writable app path)
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

PACK=/sandbox/pack
mkdir -p "$STAGE/itda" "$STAGE/pack/hackathon/output"
cp -R itda attacks "$STAGE/itda/"
# Task and inputs: the challenge folder by default, or a live request from the web UI.
cp "${TASK_FILE:-challenge/TASK.md}" "$STAGE/pack/TASK.md"
cp -R "${INPUT_DIR:-challenge/hackathon/input}" "$STAGE/pack/hackathon/input"

# Start clean: upload merges into existing dirs, so stale inputs from a previous run would leak in.
$NC exec -- rm -rf /sandbox/itda "$PACK" >/dev/null 2>&1 || true
$NC upload "$STAGE/itda" /sandbox/
$NC upload "$STAGE/pack" /sandbox/
# Tool API keys (opt-in). They enter the sandbox as env vars, but egress is limited to the
# allow-listed API hosts in policy/presets/, so they cannot be sent anywhere else.
TOOLENV=""
if [ -n "${ITDA_SANDBOX_TOOL_KEYS:-}" ]; then
  for k in TAVILY_API_KEY BRAVE_API_KEY NAVER_CLIENT_ID NAVER_CLIENT_SECRET DATA_GO_KR_KEY PUBLIC_DATA_SERVICE_KEY AKS_API_KEY TMAP_APP_KEY; do
    eval "v=\${$k:-}"; [ -n "$v" ] && TOOLENV="$TOOLENV $k=$v"
  done
fi
# inference.local: the NVIDIA key stays on the host gateway; the sandbox never sees it.
$NC exec --workdir /sandbox/itda -- env PYTHONDONTWRITEBYTECODE=1 \
  ITDA_LLM_BASE_URL="${ITDA_SANDBOX_BASE_URL:-https://inference.local/v1}" \
  ITDA_MODEL="${ITDA_MODEL:-nvidia/nemotron-3-super-120b-a12b}" \
  ITDA_MODEL_FAST="${ITDA_MODEL_FAST:-nvidia/nemotron-3-super-120b-a12b}" \
  ITDA_FAST_BASE_URL="${ITDA_SANDBOX_FAST_BASE_URL:-}" \
  ITDA_MODEL_SMALL="${ITDA_MODEL_SMALL:-}" $TOOLENV \
  ITDA_SMALL_BASE_URL="${ITDA_SANDBOX_SMALL_BASE_URL:-}" \
  python3 -m itda --task "$PACK/TASK.md" --input "$PACK/hackathon/input" --output "$PACK/hackathon/output" "$@"
OUT=${OUT_DIR:-out}; mkdir -p "$OUT"
$NC download "$PACK/hackathon/output" "$OUT/"
echo "results in $OUT"
