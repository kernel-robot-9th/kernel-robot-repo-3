#!/usr/bin/env bash
# Start manually only after physical station teaching; never starts from deployment.
set -eo pipefail
cd "$(dirname "$0")/.."
source /opt/ros/jazzy/setup.bash
export PYTHONPATH="$PWD${PYTHONPATH:+:$PYTHONPATH}:/usr/lib/python3/dist-packages"
set -a
source runtime/field/gateway-a.env
set +a
exec .venv/bin/python -u -m robot_gateway.hardware.worker \
  --config runtime/field/pinky-control-worker.json --server "$SHOP_SERVER_URL" --execute
