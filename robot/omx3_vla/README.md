# OMX3 VLA 팀 공유 자료

2026-10-23 작업 폴더의 시연 수집 코드와 문서를 공유한 스냅샷입니다.
현재 작업은 SmolVLA용 시연 수집·검증이며, 학습 모델·자동 하역·관제 실행기 구현은 포함하지 않습니다.
기존 `robots/omx_act`의 ACT 실행기와는 별도 도구입니다.

## 시작 위치

저장소 루트에서 `cd robot/omx3_vla`로 이동한 뒤 실행합니다.
[README_VLA_KO.md](README_VLA_KO.md)의 `/home/team2/robot_shopping` 작업 경로는
이 폴더로 바꿔 읽으세요. 문서에서 언급한 `reports/`는 원래 PC의 실행 결과이며 공유 대상에서 제외했습니다.

OMX를 지원하는 LeRobot 소스 커밋 `8fff0fde`가 설치된 Python 환경이 필요합니다.
원래 PC는 `/home/team2/venv/il/bin/python`을 사용합니다.
`scripts/omx-vla`에도 이 경로가 고정되어 있으므로 다른 PC에서는 해당 환경의 Python으로 아래 명령을 실행하세요.

```bash
python -m omx_vla --help
python -m omx_vla record --basket 0 --session day01_setupA --episodes 5
python -m unittest discover -s tests -v
```

`record`는 `--run`을 붙이지 않으면 장치 연결 없이 계획만 출력합니다.
테스트는 합성 데이터와 가짜 장치를 사용하며 실제 모터를 구동하지 않습니다.

## 설정과 문서

- `configs/omx_vla.json`과 `configs/calibration/`은 원래 장치의 경로·보정값입니다.
  카메라의 `view_confirmed=true`도 원래 현장 상태입니다. 다른 장치에 그대로 적용하지 말고
  장치 ID·보정값·카메라 구도·FPS를 현장에서 확인하세요.
- [README_VLA_KO.md](README_VLA_KO.md): 현재 시연 수집·검증 절차.
- [OMX3_IMITATION_LEARNING_KO.md](OMX3_IMITATION_LEARNING_KO.md): 이전 ACT 설계를 포함한 이력.
- [OMX3_HANDOVER_INTERFACE_KO.md](OMX3_HANDOVER_INTERFACE_KO.md): 다른 PC의 관제·Gazebo 연동 참고.
  이 문서에 나오는 ROS 노드·실행 스크립트는 이 자료에 포함되어 있지 않습니다.
- [OMX_TEAM_OVERVIEW_KO.md](OMX_TEAM_OVERVIEW_KO.md): 이전 팀 구성 및 역할 참고.
  현재 수집 작업 정의와 충돌하는 내용은 `README_VLA_KO.md`를 우선합니다.

로그·캐시·실행 보고서·녹화 데이터·모델은 커밋하지 않습니다.
