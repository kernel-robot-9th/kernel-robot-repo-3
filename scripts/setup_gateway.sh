#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
[[ "$(uname -s)" == Linux ]] || { echo 'Ubuntu 중개 노트북에서 실행하세요.' >&2; exit 1; }
command -v python3 >/dev/null || { echo 'Python 3.11~3.13이 필요합니다.' >&2; exit 1; }
python3 -c 'import sys; assert (3,11) <= sys.version_info[:2] < (3,14), "Python 3.11~3.13 필요. ROS Python과 별도 환경을 사용하세요."'
[[ -d .venv ]] || python3 -m venv .venv
.venv/bin/python -m pip install -e .
echo '중개 Python 준비 완료. ROS·YOLO·모방학습·카메라 드라이버 설치는 포함하지 않습니다.'
