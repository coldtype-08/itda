#!/bin/sh
# Save the policy actually enforced on the sandbox into the repo (README submission requirement).
set -eu
SB=${SANDBOX:-itda-hack}
openshell policy get "$SB" --full | sed -n '/^---$/,$p' | tail -n +2 > policy/itda-hack.policy.yaml
nemo-deepagents "$SB" policy list > policy/itda-hack.presets.txt 2>&1 || true
echo "saved policy/itda-hack.policy.yaml ($(wc -l < policy/itda-hack.policy.yaml) lines) and policy/itda-hack.presets.txt"
grep -E "^  [a-z_]+:$" policy/itda-hack.policy.yaml | sed 's/^/  network policy:/' || true
