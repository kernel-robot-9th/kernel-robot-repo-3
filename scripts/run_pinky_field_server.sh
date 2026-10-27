#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
set -a
source runtime/field/central.env
set +a
export SHOP_DEVICE_MODE=hardware SHOP_GATEWAY_MODE=distributed SHOP_TEST_ONLY=0
export SHOP_DB=runtime/hardware/shopping.db
export SHOP_HARDWARE_READINESS=runtime/field/pinky-first-a.readiness.json
unset SHOP_MOTION_BACKEND
exec .venv/bin/python -m uvicorn server.api:create_app --factory --host 0.0.0.0 --port 8000 --workers 1
