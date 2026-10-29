# 전체 카메라로 두 대기자리 목표 기록

2026-10-27. 관제 Ubuntu 노트북에서 기록한다. 로봇은 사용자가 최종 대기자리와 앞방향에 맞춰 놓는다. 이 도구는 ROS 연결·바퀴·팔 명령 없이 영상 목표만 저장한다.

## 기록 대상

| 자리 | 로봇 | 마커 | 마커 기준 앞방향 |
| --- | --- | --- | --- |
| front: 기존 선두 | 흰색 P1 | DICT_5X5_1000 / ID 0 / 80mm | 180° |
| front: 기존 선두 | 빨간 P2 | DICT_5X5_1000 / ID 1 / 80mm | 270° |
| back: 기존 후열 | 흰색 P1 | DICT_5X5_1000 / ID 0 / 80mm | 180° |
| back: 기존 후열 | 빨간 P2 | DICT_5X5_1000 / ID 1 / 80mm | 270° |

기존 두 자리의 공용 지도 위치를 재사용한다. 카메라 목표는 로봇별로 따로 기록한다. 마커를 차체에 붙인 방향이 바뀌지 않으면 자리마다 앞방향을 다시 클릭할 필요가 없다.

## 현장 순서

카메라를 사용하는 기존 `Pinky marker count` 창 또는 전체 카메라 프로그램을 그 창의 Q로 닫는다. 카메라는 기록 중 위치·각도·해상도를 유지한다. 다른 구역의 카메라와 A/B/C 주차 목표는 변경하지 않는다.

```bash
cd /home/noma/dev_ws/kernel-robot-repo-3
```

아래 명령을 하나씩 실행한다. 화면의 **노란 화살표는 실제 로봇 정면**이다. 로봇이 맞는 자리에 놓였고 해당 ID가 검출되면 **관제 터미널 또는 영상 창에서 Enter**로 저장한다. S도 저장, Q/Esc는 취소다. 저장하면 프로그램이 종료된다.

### 1. 선두 / 흰색 P1

```bash
bash scripts/run_pinky_overhead.sh wait --robot P1 --slot front \
  --dictionary DICT_5X5_1000 --marker-id 0 --size-mm 80 --front-angle-deg 180 \
  --marker-forward-mm 0 --marker-left-mm 0
```

### 2. 선두 / 빨간 P2

P1을 옮기고 같은 선두 자리에 P2를 놓는다.

```bash
bash scripts/run_pinky_overhead.sh wait --robot P2 --slot front \
  --dictionary DICT_5X5_1000 --marker-id 1 --size-mm 80 --front-angle-deg 270 \
  --marker-forward-mm 0 --marker-left-mm 0
```

### 3. 후열 / 흰색 P1

```bash
bash scripts/run_pinky_overhead.sh wait --robot P1 --slot back \
  --dictionary DICT_5X5_1000 --marker-id 0 --size-mm 80 --front-angle-deg 180 \
  --marker-forward-mm 0 --marker-left-mm 0
```

### 4. 후열 / 빨간 P2

```bash
bash scripts/run_pinky_overhead.sh wait --robot P2 --slot back \
  --dictionary DICT_5X5_1000 --marker-id 1 --size-mm 80 --front-angle-deg 270 \
  --marker-forward-mm 0 --marker-left-mm 0
```

### 등록값 조회

```bash
bash scripts/run_pinky_overhead.sh wait-list
```

`front/P1`, `front/P2`, `back/P1`, `back/P2` 네 키와 ID·크기·앞방향·저장 시각을 확인한다. 같은 조합을 다시 기록하면 해당 목표만 갱신하고 다른 세 조합은 유지한다.

## 저장 자료와 지도 좌표

- `runtime/field/pinky-overhead/wait-targets.json`: 네 목표의 원본 검출 모서리·ID·크기·마커 기준 앞방향·카메라 설정·좌표 상태.
- `front-P1-target.png` 등: 각 목표의 기준 영상.
- `front-P1-target-view.jpg` 등: 검출 테두리와 실제 앞방향 표시 영상.
- `wait-targets.previous.json`: 직전 목표 파일 백업.

현재 전체 카메라 캘리와 상단 높이는 미등록이다. 이 상태에서는 **영상 목표 기록만 성공**하며 `map_pose`는 `null`이다. 주행 보정·자동 대기 정밀주차·충전 성공을 의미하지 않는다. 기존 A/B/C 목표와 경로 파일은 건드리지 않는다.

바닥부터 마커 면까지 실제 높이를 알고 있다면 각 기록 명령에 `--height-mm 숫자`를 추가할 수 있다. 같은 높이·해상도·렌즈 설정의 카메라 캘리가 이미 있으면 차체 지도 좌표도 저장한다. 원본 검출 모서리는 남기므로 이후 좌표 연결의 입력으로 쓸 수 있다.

전체 카메라 캘리는 [기존 절차](OVERHEAD_CAMERA.md)를 사용한다. 최소 네 개의 넓게 분포한 **실측 지도 대응점**이 필요하다. 두 대기자리에서 로봇을 바꿔 네 번 기록한 것은 서로 다른 위치 네 점의 캘리를 대신하지 않는다.

로봇 정보 등록에서도 마우스 대신 `--marker-id`와 `--front-angle-deg`를 사용할 수 있다. P1은 180°, P2는 270°다. `robot` 모드에는 실제 마커 높이 `--height-mm`도 입력한다.

다음 단계는 카메라·공용 지도 좌표 등록과 주행 위치 보정이다. 자동 대기 주차의 고정 진입·출차 경로와 충전 기능은 별도 후속 작업이다.
