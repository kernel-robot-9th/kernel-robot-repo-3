#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
[[ -x .venv/bin/python ]] || { echo '먼저 bash scripts/setup_gateway.sh를 실행하세요.' >&2; exit 1; }
[[ $# == 1 ]] || { echo 'gateway-a, gateway-b 또는 gateway-c 하나만 지정하세요.' >&2; exit 2; }
node="$1"
case "$node" in gateway-a|gateway-b|gateway-c) ;; *) echo '등록된 중계를 선택하세요.' >&2; exit 2;; esac
config="runtime/field/$node.env"
[[ -f "$config" ]] || { echo "이 중개의 설정이 필요합니다: $config" >&2; exit 1; }
set -a
source "$config"
set +a
[[ "${SHOP_NODE_ID:-}" == "$node" && "${SHOP_DEVICE_MODE:-}" == hardware ]] || { echo '해당 중계의 현장 env인지 확인하세요.' >&2; exit 1; }
[[ -n "${SHOP_SERVER_URL:-}" && -n "${SHOP_NODE_TOKEN:-}" && -f "${SHOP_HARDWARE_CONFIG:-}" ]] || { echo '서버 주소·토큰·hardware.json 파일을 확인하세요.' >&2; exit 1; }
# Deliberately no --execute: PING / INSPECT only; no USB camera or motor is opened.
exec .venv/bin/python -m robot_gateway.test_runtime --node "$node" --server "$SHOP_SERVER_URL" --mode hardware --config "$SHOP_HARDWARE_CONFIG"
