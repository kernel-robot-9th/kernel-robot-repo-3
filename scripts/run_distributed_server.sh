#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
[[ -x .venv/bin/python ]] || { echo '먼저 bash scripts/setup_ubuntu.sh를 실행하세요.' >&2; exit 1; }
[[ -f runtime/distributed/central.env ]] || { echo 'prepare_distributed.py로 중앙 설정을 먼저 생성하세요.' >&2; exit 1; }
set -a
source runtime/distributed/central.env
set +a
[[ "${SHOP_GATEWAY_MODE:-}" == distributed ]] || { echo '분산 실행용 central.env인지 확인하세요.' >&2; exit 1; }
exec .venv/bin/python -m uvicorn server.api:create_app --factory --host "${SHOP_BIND:-0.0.0.0}" --port "${SHOP_PORT:-8000}" --workers 1
