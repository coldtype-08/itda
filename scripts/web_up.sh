#!/bin/sh
# Start the ItDA web UI in the background (agent runs INSIDE the OpenShell sandbox, Nano on the L40S
# for small jobs) and expose it through a Cloudflare quick tunnel with a shared access token.
#   sh scripts/web_up.sh          # prints the public URL to share
#   sh scripts/web_up.sh stop
set -eu
cd "$(dirname "$0")/.."
mkdir -p out
if [ "${1:-}" = "stop" ]; then pkill -f "itda.web" || true; pkill -f "cloudflared tunnel" || true; echo stopped; exit 0; fi
[ -f ~/.itda.env ] && set -a && . ~/.itda.env && set +a
TOKEN=${ITDA_WEB_TOKEN:-$(python3 -c "import secrets;print(secrets.token_urlsafe(9))")}
pkill -f "itda.web" 2>/dev/null || true
ITDA_WEB_TOKEN="$TOKEN" ITDA_RUNNER=${ITDA_RUNNER:-sandbox} SANDBOX=${SANDBOX:-itda-hack} ITDA_SANDBOX_TOOL_KEYS=1 \
ITDA_MODEL_SMALL=nvidia/nemotron-3-nano ITDA_SANDBOX_SMALL_BASE_URL=http://host.openshell.internal:8000/v1 \
  nohup python3 -m itda.web > out/web.log 2>&1 &
sleep 2; curl -sf -o /dev/null "localhost:${ITDA_WEB_PORT:-8501}/?t=$TOKEN" && echo "UI up on :${ITDA_WEB_PORT:-8501} (runner: ${ITDA_RUNNER:-sandbox})" || { cat out/web.log; exit 1; }

CF=$(command -v cloudflared || echo "$HOME/.local/bin/cloudflared")
if [ ! -x "$CF" ]; then
  mkdir -p "$HOME/.local/bin"
  curl -fsSL -o "$CF" https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 && chmod +x "$CF"
fi
pkill -f "cloudflared tunnel" 2>/dev/null || true
nohup "$CF" tunnel --no-autoupdate --url "http://localhost:${ITDA_WEB_PORT:-8501}" > out/tunnel.log 2>&1 &
for i in $(seq 1 30); do
  URL=$(grep -oE "https://[a-z0-9-]+\.trycloudflare\.com" out/tunnel.log | head -1 || true)
  [ -n "$URL" ] && break; sleep 1
done
[ -n "${URL:-}" ] || { echo "tunnel failed:"; tail -5 out/tunnel.log; exit 1; }
echo
echo "share this link:  $URL/?t=$TOKEN"
echo "(local:            http://localhost:${ITDA_WEB_PORT:-8501}/?t=$TOKEN)   stop: sh scripts/web_up.sh stop"
