#!/bin/sh
# One-shot, re-runnable setup of the ItDA environment on a fresh Linux GPU server.
# Reproduces exactly what the team built: NemoClaw + OpenShell sandbox (Restricted tier, no
# optional presets), ItDA's least-privilege egress presets, local Nemotron Nano NIM on the GPU,
# challenge data, then verifies everything and runs the attack demo.
#
#   cp .env.example ~/.itda.env && chmod 600 ~/.itda.env   # fill in keys first
#   sh scripts/setup_server.sh                              # SKIP_NIM=1 to skip the local model
set -eu
cd "$(dirname "$0")/.."
SB=${SANDBOX:-itda-hack}
say() { printf '\n\033[1m== %s\033[0m\n' "$*"; }
die() { printf '\n\033[31mSTOP: %s\033[0m\n' "$*"; exit 1; }

[ -f ~/.itda.env ] || die "~/.itda.env not found. cp .env.example ~/.itda.env, fill NVIDIA_API_KEY, chmod 600"
set -a; . ~/.itda.env; set +a
: "${NVIDIA_API_KEY:?NVIDIA_API_KEY missing in ~/.itda.env}"

say "1/6 host preflight (OpenShell needs Linux >= 6.2 with Landlock ABI >= 3, Docker >= 28)"
ABI=$(python3 -c "import ctypes;print(ctypes.CDLL(None,use_errno=True).syscall(444,None,0,1))")
DOCKER=$(docker version --format '{{.Server.Version}}' 2>/dev/null || echo 0)
echo "kernel $(uname -r) | landlock ABI $ABI | docker $DOCKER | gpu $(nvidia-smi --query-gpu=name,driver_version --format=csv,noheader 2>/dev/null || echo none)"
[ "$ABI" -ge 3 ] || die "Landlock ABI $ABI < 3. Ubuntu 22.04: sudo apt-get install -y linux-generic-hwe-22.04 && sudo reboot"
[ "${DOCKER%%.*}" -ge 28 ] || die "Docker $DOCKER < 28. sudo apt-get install -y docker-ce docker-ce-cli containerd.io"
sudo loginctl enable-linger "$USER" 2>/dev/null || true

say "2/6 NemoClaw + OpenShell sandbox '$SB' (Restricted tier, no optional presets, Nemotron Super)"
export NVIDIA_INFERENCE_API_KEY="$NVIDIA_API_KEY"
export NEMOCLAW_AGENT=langchain-deepagents-code NEMOCLAW_PROVIDER=build \
       NEMOCLAW_MODEL=${NEMOCLAW_MODEL:-nvidia/nemotron-3-super-120b-a12b} NEMOCLAW_SANDBOX_NAME="$SB" \
       NEMOCLAW_POLICY_TIER=restricted NEMOCLAW_POLICY_MODE=custom NEMOCLAW_POLICY_PRESETS="" \
       NEMOCLAW_RESOURCE_PROFILE=creator NEMOCLAW_NON_INTERACTIVE=1 NEMOCLAW_ACCEPT_THIRD_PARTY_SOFTWARE=1
if ! command -v nemo-deepagents >/dev/null 2>&1; then
  curl -fsSL https://www.nvidia.com/nemoclaw.sh | bash
elif ! openshell sandbox list 2>/dev/null | grep -q "^$SB "; then
  nemo-deepagents onboard --non-interactive --yes-i-accept-third-party-software
else
  echo "sandbox $SB already exists - keeping it"
fi

say "3/6 ItDA egress presets (policy/presets/*.yaml) and removal of broad defaults"
nemo-deepagents "$SB" policy add --from-dir policy/presets/ --yes 2>&1 | grep -E "Applied|rror" || true
for p in local-inference personal-open-internet github pypi npm huggingface brew; do
  nemo-deepagents "$SB" policy remove "$p" --yes >/dev/null 2>&1 || true
done
nemo-deepagents "$SB" policy list | grep "●" || true

say "4/6 local Nemotron Nano NIM on the GPU (port 8000)"
if [ -n "${SKIP_NIM:-}" ]; then echo "skipped (SKIP_NIM=1)"; else sh scripts/nim_up.sh; fi

say "5/6 challenge data"
sh scripts/fetch_challenge.sh

say "6/6 verification"
sh scripts/sandbox_check.sh
SANDBOX="$SB" sh scripts/sandbox_run.sh --mock >/dev/null 2>&1 && echo "sandbox upload/run/download: OK (mock)" || echo "sandbox run: FAILED (see scripts/sandbox_run.sh)"
openshell sandbox exec -n "$SB" -- sh /sandbox/itda/attacks/run_attacks.sh || true

say "done. next:"
cat <<EOF
  real run in sandbox : ITDA_SANDBOX_TOOL_KEYS=1 ITDA_MODEL_SMALL=nvidia/nemotron-3-nano \\
                        ITDA_SANDBOX_SMALL_BASE_URL=http://host.openshell.internal:8000/v1 sh scripts/sandbox_run.sh
  score               : python3 eval/run_eval.py out ; python3 eval/run_cases.py
  web UI + public URL : sh scripts/web_up.sh
EOF
