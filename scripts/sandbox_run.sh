#!/bin/sh
# Upload ItDA + allowed inputs into the NemoClaw/OpenShell sandbox, run, and download results.
# restricted/ and secrets/ are deliberately NOT uploaded.
#   SANDBOX=itda-hack sh scripts/sandbox_run.sh --visitor foreign --interests history,family
set -eu
SB=${SANDBOX:-itda-hack}
NC="nemo-deepagents $SB"
STAGE=$(mktemp -d)
trap 'rm -rf "$STAGE"' EXIT

mkdir -p "$STAGE/itda/challenge/hackathon/output"
cp -R itda attacks "$STAGE/itda/"
cp challenge/TASK.md "$STAGE/itda/challenge/"
cp -R challenge/hackathon/input "$STAGE/itda/challenge/hackathon/"

$NC upload "$STAGE/itda" /sandbox/
# inference.local: credentials stay on the host gateway; the sandbox never sees the API key.
$NC exec --workdir /sandbox/itda -- env \
  ITDA_LLM_BASE_URL="${ITDA_SANDBOX_BASE_URL:-https://inference.local/v1}" \
  ITDA_MODEL="${ITDA_MODEL:-nvidia/nemotron-3-super-120b-a12b}" \
  ITDA_MODEL_FAST="${ITDA_MODEL_FAST:-nvidia/nemotron-3-super-120b-a12b}" \
  python3 -m itda "$@"
OUT=${OUT_DIR:-out}; mkdir -p "$OUT"
$NC download /sandbox/itda/challenge/hackathon/output "$OUT/"
echo "results in $OUT"
