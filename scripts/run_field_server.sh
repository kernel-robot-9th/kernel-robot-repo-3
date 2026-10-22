#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
[[ -x .venv/bin/python ]] || { echo '먼저 bash scripts/setup_ubuntu.sh를 실행하세요.' >&2; exit 1; }
[[ -f runtime/field/central.env ]] || { echo '먼저 scripts/prepare_field.py로 현장 설정을 생성하세요.' >&2; exit 1; }
set -a
source runtime/field/central.env
set +a
[[ "${SHOP_GATEWAY_MODE:-}" == distributed && "${SHOP_DEVICE_MODE:-}" == hardware && "${SHOP_TEST_ONLY:-}" == 1 ]] || { echo '현장 설정용 central.env가 필요합니다.' >&2; exit 1; }
[[ -z "${SHOP_MOTION_BACKEND:-}" ]] || { echo '현장 설정에는 모의 이동 backend를 사용하지 않습니다.' >&2; exit 1; }
exec .venv/bin/python -m uvicorn server.api:create_app --factory --host "${SHOP_BIND:-0.0.0.0}" --port "${SHOP_PORT:-8000}" --workers 1
