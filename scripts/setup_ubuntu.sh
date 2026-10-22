#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
if [[ "$(uname -s)" != Linux ]]; then
  echo 'Ubuntu 노트북에서 실행하세요.' >&2
  exit 1
fi
command -v python3 >/dev/null || { echo 'Python 3.11~3.13이 필요합니다.' >&2; exit 1; }
command -v node >/dev/null || { echo '중앙 서버 웹 빌드용 Node.js 24.12 이상 24.x가 필요합니다.' >&2; exit 1; }
command -v pnpm >/dev/null || { echo 'Node.js 24.12 이상 24.x와 pnpm 11이 필요합니다. 중개만 설치하려면 setup_gateway.sh를 사용하세요.' >&2; exit 1; }
[[ "$(pnpm --version)" == 11.* ]] || { echo '이 프로젝트는 pnpm 11을 사용합니다. README의 버전 준비 절차를 확인하세요.' >&2; exit 1; }
python3 -c 'import sys; assert (3,11) <= sys.version_info[:2] < (3,14), "Python 3.11~3.13 필요"'
node -e 'const [a,b]=process.versions.node.split(".").map(Number); if(a!==24 || b<12) throw Error("Node 24.12 이상 24.x 필요")'
[[ -d .venv ]] || python3 -m venv .venv
.venv/bin/python -m pip install --quiet -e '.[test]'
(cd web && pnpm install --frozen-lockfile)
.venv/bin/python - <<'PY'
from pathlib import Path
import os
import secrets
path = Path('.env')
if not path.exists():
    descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(descriptor, 'w') as output:
        output.write('SHOP_ADMIN_TOKEN=' + secrets.token_urlsafe(32) + '\n')
        output.write('SHOP_GATEWAY_TOKEN=' + secrets.token_urlsafe(32) + '\n')
        output.write('SHOP_DB=runtime/shopping.db\n')
    print('단일 중개 호환용 .env 생성. 이번 분산 실행에서는 이 파일을 사용하지 않습니다.')
else:
    print('기존 단일 중개용 .env 유지. 현장 설정에서는 runtime/field/ 설정을 사용합니다.')
PY
echo '설치 완료. pnpm --dir web build로 웹을 빌드하세요.'
echo '현장 인증 파일은 FIELD_SETUP.md 순서에 따라 관제 PC에서 prepare_field.py로 생성하세요.'
