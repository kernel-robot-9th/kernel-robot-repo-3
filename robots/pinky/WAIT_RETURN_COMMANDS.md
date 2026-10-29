# 현재 위치에서 두 대를 대기자리로 정렬

2026-10-27. 코드·명령 준비 완료. 실제 로봇 주행 시험은 작업자가 실행한다.

최근 카메라 관측은 P1=중앙 아래쪽 통로, P2=C 구역이었다. 전체 카메라 창을 켜두고, 두 로봇의 localize/navigation/route 준비까지 마친 상태에서 **관제 노트북**에서 실행한다.

```bash
cd /home/noma/dev_ws/kernel-robot-repo-3
bash scripts/run_pinky_wait_pair.sh
```

P1이 선두(front)에 도착하고 방향 정렬을 마치면 P2가 후열(back)로 이동한다. P1 실행이 오류나 취소로 끝나면 셸 명령도 끝나므로 P2 이동은 시작되지 않는다.

각각 실행하려면:

```bash
# 먼저 P1: 현재 위치 → 복귀 경로 합류 → 선두 대기자리
bash scripts/run_pinky_control.sh wait --robot P1 --zone front

# P1 완료 후 P2: 현재 위치 → 복귀 경로 합류 → 후열 대기자리
bash scripts/run_pinky_control.sh wait --robot P2 --zone back
```

`--from`은 필요 없다. 저장된 A/B/C 배치 기록을 출발점으로 쓰지 않고, 카메라 보정이 적용되면 그 좌표를 사용한다. 카메라 관측이 없으면 현재 Nav2 지도 위치를 사용한다.

기존 복귀 경로의 가까운 노드부터 **Route Server로 남은 경로를 계산**하고, 현재 위치에서 짧은 연결 곡선으로 합류한다. 남은 고정 복귀 경로와 선두/후열 목표를 유지하며 마지막에 목표 앞방향으로 회전한다. 구역 팔·적재·하역은 실행하지 않는다. 충전용 정밀주차는 이 명령의 범위가 아니다.

현재 중앙 통로·C 배치를 위한 합류 기능이다. A/B 작업대 내부에서 C 복귀 경로로 곧장 합류하는 범용 장애물 회피 기능은 아니다. A/B 출발은 기존 `move --from A/B --zone front/back` 경로를 사용한다.

P1 선두 배치 이후 A 시험:

```bash
bash scripts/run_pinky_control.sh move --robot P1 --from front --zone A --parking
```

서버/worker 재시작, 그래프 배포는 필요 없다. 로컬 터미널 스크립트가 수정된 코드를 읽는다. 준비 방법은 [카메라 주행 시험 명령서](CAMERA_NAV_TEST_COMMANDS.md)를 참고한다.

검증: 관련 경로·CLI 테스트 16개 통과. 기존 관측값으로 P1은 `return_west`, P2는 `leave_handoff`부터 합류하는 것을 오프라인으로 확인했다. 실제 이동 성공은 아직 확인하지 않았다.
