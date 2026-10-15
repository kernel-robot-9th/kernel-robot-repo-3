#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
[[ -f .env ]] || { echo '먼저 setup_ubuntu.sh를 실행하세요.' >&2; exit 1; }
set -a
source .env
set +a
exec .venv/bin/python -m uvicorn server.api:create_app --factory --host "${SHOP_BIND:-127.0.0.1}" --port "${SHOP_PORT:-8000}" --workers 1
