# 대기 주차 — 후열 기준 고정 경로 시험

갱신: 2026-10-28. 벽 접촉 실패 후 전략을 변경했다. **새 그래프는 사용자 적용 후 P1/P2 운영 인덱스 해시 일치 확인 완료**다. P2는 Nav2 복귀 통로 합류까지 성공했으나 주차 기준점과 실제 위치가 11.5cm 어긋났고, 곡선 끝 방향 오차 약 24°를 맞추려다 반복 회전·벽 접촉으로 실패했다. 주차 성공은 아직 미확인이다.
그래프 적용은 반복하지 않는다. 진입 기준점의 카메라 위치 보정과 곡선→직선 연속 추종으로 관제 코드를 수정했으므로 실행 중인 터미널 명령을 Ctrl+C로 종료한 뒤 시험 명령을 새로 실행한다. 로봇 재시작은 필요 없다. 예전 `pinky_wait_setup apply --stage waiting`은 v3/v4 통합 그래프를 덮어쓰므로 사용하지 않는다.

**최신 사용자 확인:** 진입 기준점 위치 보정·곡선/직선 연속 추종 수정 후 P2 후열 주차, P1 전열 주차, P2 후열→전열 직진 모두 실물 성공을 확인했다. 아래 실패 기록은 수정 배경이며 이후 성공 기록이 최신이다.

## 1. 주차 전략과 현재 상태

- 후열이 비어 있으면 복귀 → 카메라로 열린 공간의 진입 기준점까지 이동 → 진입 방향 정렬 → 곡선과 마지막 10cm 직선을 연속 추종 → 후열 정밀주차. 곡선 끝에서는 별도 방향 완료 조건으로 멈추지 않는다.
- 후열 정렬 뒤 전열도 비어 있으면 같은 주차선으로 약 46cm 전진하고 끝낸다. 전열에서 별도 회전·정밀주차·재진입을 반복하지 않는다.
- 후열에 로봇이 있고 전열이 비어 있으면 그 로봇을 움직이지 않는다. 복귀 로봇이 전열 앞쪽 열린 공간에서 회전한 뒤 곡선 후진 → 마지막 10cm 직선 후진으로 주차한다.
- 전열에 로봇이 있으면 복귀 로봇은 후열에 주차한다. 주문 복귀는 중앙 제어의 자리 기록으로 위 동작을 선택한다.
- 로봇별 저장된 후열·전열 **중심 좌표는 보존**, 두 중심을 연결한 방향을 공통 주차 방향으로 사용한다. 원본 마커 기록·사진도 보존한다.
- Route Server에 세 이동 경로를 등록한다. 일반 복귀 통로는 Nav2, 주차 기동은 Route Server가 반환한 고정 경로를 카메라+odom으로 추종한다. 열린 공간에서만 제자리 회전하고 벽 옆에서는 목표를 향해 자유 곡선·제자리 회전을 만들지 않는다.
- 후열·전열 직접 주차 완료는 기존 **3cm·7°**다. 후열→전열은 방향을 유지하며 종방향 잔여거리 3cm에서 종료하고 실제 횡오차·각도도 기록한다.
- 주차 경로 검토에는 바구니 **실측 127×155mm**, 본체·부착 기준은 기존 모델값을 사용한다. Nav2 주행은 **70% 바구니**를 유지한다. P1/P2 관제 프로필에서 0.7 적용 기록을 확인했다.
- 고정 경로 추종 구간은 직접 속도 제어이므로 Nav2 충돌 검사로 보호되는 구간이 아니다. 바구니 회전 외곽은 경로 준비 때 검토하며 새로운 충돌 중단·경로 이탈 차단 조건은 추가하지 않았다.

실패 기록의 11.5cm 진입 오차와 곡선 끝 약 24° 오차를 재현한 소프트웨어 검증을 포함해 관련 24개 검증을 통과했다. 이는 실물 성공 판정이 아니다. 이미 벽에 닿은 자세에서 이어 돌리지 않고 P2를 통로로 옮겨 아래 후열 시험을 새로 실행한다. 기존 전체 카메라가 보이면 출발 위치 보정은 명령에서 처리한다.

## 2. 준비 결과와 그림 — 이동 없음

준비 명령은 이미 수행했다. 기준점·설정을 바꾼 경우에만 다시 수행한다.

```bash
cd /home/noma/dev_ws/kernel-robot-repo-3
python3 -m scripts.pinky_route_modes prepare
python3 -m scripts.pinky_wait_preview
```

- 미리보기: `runtime/field/pinky-wait-parking/rear-first-preview.png`
- 외곽 계산 결과: 같은 이름의 JSON. 회전 위치의 전체 회전 외곽과 다른 대기 로봇도 포함한다.
- 두 로봇 모두 모델상 벽 최소 간격은 후열 진입 약 6.6cm, 전열 후진 약 7.9~8.0cm, 전열 직진 약 7.3cm이며 반대 자리 로봇과 겹침은 없었다.
- 이는 2m×1.5m 기준 모델 계산이다. 실제 바닥 외곽·카메라 좌표 오차가 있으므로 실물 간격이나 성공 보장이 아니다.
- `prepare`는 새 목표를 `runtime/field/pinky-route-modes/wait-targets.json`에 준비하며 운영 중인 대기 목표·로봇 그래프는 바꾸지 않는다.

## 3. 새 그래프 적용 — 이동 없음, 작업자가 실행

실행 중인 주행·주차 명령은 해당 터미널에서 Ctrl+C로 끝낸 상태에서 적용한다. 전체 카메라·센서·AMCL은 유지한다.

```bash
cd /home/noma/dev_ws/kernel-robot-repo-3
python3 -m scripts.pinky_route_modes apply --robot P1
python3 -m scripts.pinky_route_modes apply --robot P2
```

각 Route Server를 재로딩하고 새 대기 목표와 경로 인덱스를 연결한다. 원본은 `runtime/field/pinky-route-modes/backup-*`에 보존한다.
바구니 70%가 이미 적용된 두 로봇에 basket 적용이나 Nav2 재시작을 반복하지 않는다. 웹 빌드·관제 서버 재시작도 이번 터미널 시험에는 필요 없다.

## 4. P2 후열 주차 → 전열 직진 — 한 단계씩 실행

P2를 벽에 붙이지 않은 통로에 두고, 먼저 후열을 비워 둔다. 전체 카메라는 기존 위치 프로그램으로 켜 둔다.
다른 로봇의 실제 위치와 중앙 자리 기록이 같아야 한다. 수동으로 옮겼다면 `locate --robot P1 --zone 실제구역`으로 기록만 맞춘다.
`locate`는 위치 추정이나 이동 명령이 아니다.

**후열 정밀주차만 시험:**

```bash
bash scripts/run_pinky_control.sh wait --robot P2 --zone back --route-version 4
```

기존 복귀 경로에 합류 → `waiting_entry_position`(기준점 위치 보정, 이미 3cm 이내면 생략) → `waiting_open_turn` → `waiting_back_curve` → `waiting_back_straight` → `aligned` 순서다.
`parking --robot P2 --zone back --mode align`도 이제 같은 등록 경로로 합류한다. 벽 옆 현재 위치에서 곧바로 자유 곡선을 만들지 않는다.

**위 단계가 성공했고 전열이 비었으면 직진 이동만 시험:**

```bash
bash scripts/run_pinky_control.sh move --robot P2 --from back --zone front --route-version 4
```

`queue_straight` → `advanced`로 끝난다. 정밀주차 옵션은 필요 없다.

**하역/통로에서 전열까지 한 번에 복귀:**

```bash
bash scripts/run_pinky_control.sh wait --robot P2 --zone front --route-version 4
```

자리 기록상 후열이 비어 있으면 후열 정밀주차 후 전진한다. 후열이 점유돼 있으면 아래 전열 후진 경로를 선택한다.

## 5. 후열 점유 시 전열 직접 후진 주차

P1이 실제 후열에 있고 전열이 비었으며, P2가 복귀 통로에 있을 때 사용한다.
P1을 수동 배치했을 때만 먼저 자리 기록을 맞춘다.

```bash
bash scripts/run_pinky_control.sh locate --robot P1 --zone back
bash scripts/run_pinky_control.sh wait --robot P2 --zone front --route-version 4
```

P1은 움직이지 않는다. P2는 전열 앞쪽 공간 → `waiting_entry_position`(필요 시) → `waiting_open_turn` → `waiting_front_curve` → `waiting_front_straight` → `aligned` 순서다.
P1 시험은 로봇 이름을 바꾼다. v3 비교는 같은 실제 시작 배치에서 `--route-version 3`으로 별도 회차를 실행한다.

## 6. 기록·주문 연결

- Route Server 기록: `runtime/field/pinky-navigation/runs/`. 버전·그래프 해시와 계산 경로를 남긴다.
- 주차 기록: `runtime/field/pinky-wait-parking/runs/`. `plan.json`에 계산 경로·실측 외곽, `events.jsonl`에 현재 위치·속도·단계, 성공 시 `result.json`을 남긴다.
- 카메라가 잠시 사라지면 마지막 카메라↔odom 연결로 계속 추종하고 최종 완료는 재관측으로 확인한다.
- 두 자리가 비었을 때 주문 복귀도 후열 주차 → 전열 직진으로 연결했다. 후열 점유 시 다른 로봇을 먼저 전열로 옮기던 처리는 제거했다.
- 후열 주차 성공 후 전열 이동이 실패하면 중앙 기록은 후열로 남는다. 성공하지 않은 전열 도착을 기록하지 않는다.
- 터미널 명령은 실행할 때 새 코드를 읽는다. **주문 시연 전에는 기존 중앙 worker를 종료한 뒤 `bash scripts/run_pinky_control_worker.sh`로 한 번 재기동**해야 한다. 중복 실행하지 않는다. 이번 준비에서는 worker를 재시작하지 않았다.
- 새 전략의 실제 성공·벽 간격·반복성·출차는 사용자 시험으로 확인한다. 충전 접촉은 그 이후다.
