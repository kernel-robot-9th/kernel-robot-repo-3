#!/usr/bin/env bash
# B/C arm worker. Pinky navigation and camera parking are requested centrally.
set -eo pipefail
cd "$(dirname "$0")/.."
case "${1:-}" in
  B) node=gateway-b; python="$HOME/dev_ws/omxtest/.venv-pick/bin/python" ;;
  C) node=gateway-c; python="$HOME/venv/il/bin/python" ;;
  *) echo '사용: bash scripts/run_pinky_station_worker.sh B|C'; exit 2 ;;
esac
set -a
source "runtime/field/$node.env"
set +a
exec "$python" -u -m robot_gateway.hardware.worker --execute \
  --config "runtime/field/pinky-control-$node.json" --server "$SHOP_SERVER_URL"
