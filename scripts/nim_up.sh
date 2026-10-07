#!/bin/sh
# Start Nemotron 3 Nano as a local NIM on the L40S (port 8000) and wait until it is ready.
# Uses NVIDIA_API_KEY from ~/.itda.env (build.nvidia.com keys also work for nvcr.io).
#   sh scripts/nim_up.sh          # first run downloads the image + weights (~tens of GB)
set -eu
[ -f ~/.itda.env ] && set -a && . ~/.itda.env && set +a
: "${NVIDIA_API_KEY:?put NVIDIA_API_KEY in ~/.itda.env first}"
# NIM 2.x images need CUDA 13 (driver >= 580). Older drivers (e.g. 565 = CUDA 12.7) run the 1.7.0 image.
DRV=$(nvidia-smi --query-gpu=driver_version --format=csv,noheader 2>/dev/null | head -1 | cut -d. -f1)
if [ "${DRV:-0}" -ge 580 ]; then DEFAULT_TAG=latest; else DEFAULT_TAG=1.7.0; fi
IMAGE=${NIM_IMAGE:-nvcr.io/nim/nvidia/nemotron-3-nano:$DEFAULT_TAG}
echo "driver ${DRV:-?} -> $IMAGE"
CACHE=${LOCAL_NIM_CACHE:-$HOME/.cache/nim}
mkdir -p "$CACHE"
echo "$NVIDIA_API_KEY" | docker login nvcr.io -u '$oauthtoken' --password-stdin >/dev/null
if ! docker ps --format '{{.Names}}' | grep -qx itda-nano; then
  docker rm -f itda-nano >/dev/null 2>&1 || true
  docker run -d --name itda-nano --restart unless-stopped --gpus all --shm-size=16GB \
    -e NGC_API_KEY="$NVIDIA_API_KEY" -v "$CACHE:/opt/nim/.cache" -p 8000:8000 "$IMAGE" >/dev/null
fi
echo "waiting for NIM (first start downloads weights; follow with: docker logs -f itda-nano)"
i=0
until curl -sf localhost:8000/v1/health/ready >/dev/null 2>&1; do
  i=$((i + 1)); [ $((i % 6)) -eq 0 ] && docker logs --tail 2 itda-nano 2>&1 | sed 's/^/  | /'
  sleep 10
done
echo "ready. served models:"
curl -s localhost:8000/v1/models | python3 -c "import sys,json;[print(' ',m['id']) for m in json.load(sys.stdin)['data']]"
