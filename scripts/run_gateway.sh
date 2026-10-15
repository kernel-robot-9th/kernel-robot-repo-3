#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
[[ -x .venv/bin/python ]] || { echo '먼저 bash scripts/setup_gateway.sh를 실행하세요. A는 setup_ubuntu.sh를 사용합니다.' >&2; exit 1; }
node="${1:?gateway-a, gateway-b 또는 gateway-c를 지정하세요}"
case "$node" in gateway-a|gateway-b|gateway-c) ;; *) echo '등록된 중개를 선택하세요.' >&2; exit 2;; esac
shift
config="runtime/distributed/$node.env"
[[ -f "$config" ]] || { echo "이 중개의 인증 파일이 필요합니다: $config" >&2; exit 1; }
set -a
source "$config"
set +a
[[ "${SHOP_NODE_ID:-}" == "$node" ]] || { echo '설정 파일의 SHOP_NODE_ID가 실행할 중개와 다릅니다. 해당 중개 파일을 다시 전달하세요.' >&2; exit 1; }
[[ -n "${SHOP_SERVER_URL:-}" && -n "${SHOP_NODE_TOKEN:-}" ]] || { echo '중개 설정의 서버 주소와 토큰을 확인하세요.' >&2; exit 1; }
exec .venv/bin/python -m robot_gateway.runtime --node "$node" --server "$SHOP_SERVER_URL" "$@"
