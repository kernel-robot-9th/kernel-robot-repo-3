# A 상단 카메라 · Pinky 윗면 ArUco 주차

2026-10-27 변경: 현재 정렬은 **후진 관측 → Nav2 도킹 제어식 곡선 전진 → 확인/재시도** 절차를 사용한다.
카메라 목표는 정지 관측 때만 계산하고, 이동 중에는 고정 목표를 odom으로 추종한다.
실제 크기·부착 위치 등록 및 최신 명령은 [ODOM_PARKING.md](ODOM_PARKING.md)를 따른다.

## 현재 준비 상태

검출·목표 기록·영상 피드백 주차·JSONL/MP4 기록과 기존 A 집기 연결을 작성했다.
합성 영상 검출, 30도 회전 검출, 평면 좌표 변환, 다섯 초기 자세의 수학적 수렴,
명령 선택, 목표 JSON/PNG와 실행 JSONL/result/MP4 저장을 장비 없이 확인했다.
실제 마커 ID·목표 영상은 아직 기록하지 않았고 실물 주차·적재 성공을 확인한 상태가 아니다.
현재 현장 연결 준비 대상은 A다. B/C는 카메라 설정·목표를 확인한 뒤 확장한다.

## 명령 위치

아래 카메라·주차·집기 명령은 모두 **A 적재 노트북 터미널**에서 실행한다.

```bash
cd /home/choi-chun-hwan/robot_shopping/kernel-robot-repo-3
```

### 1. 카메라와 마커 확인 — 로봇 명령 없음

```bash
bash scripts/run_pinky_parking.sh view --robot P2 --zone A
```

영상에 검출 사전·ID가 표시된다. Q로 종료한다. 카메라 각도와 기존 OMX 캘리는 바꾸지 않는다.
ID가 여러 개면 Tab으로 선택하거나 다음 명령에 `--marker-id 숫자`를 지정한다.

### 2. 정확한 주차 자세를 영상 목표로 저장 — 로봇 명령 없음

바구니를 실제 적재에 맞는 자세에 놓고 아래를 실행한다.

```bash
bash scripts/run_pinky_parking.sh teach --robot P2 --zone A
```

선택된 윗면 마커를 확인하고, **마커 중심에서 보았을 때 로봇 앞쪽으로 향하는 점**을
영상에서 한 번 클릭한다. 가능하면 방향이 분명한 먼 점을 선택한다.
Enter 또는 S를 누르면 현재 마커 네 모서리·앞방향·원본 사진을 저장하고 종료한다.
이 클릭은 마커를 붙인 각도를 로봇 앞방향이라고 임의 가정하지 않기 위한 기준 등록이다.

검은 사각형의 실제 한 변 길이를 알면 `--marker-size-mm 실제길이`를 추가한다.
모르면 생략할 수 있고, 오차는 mm 대신 마커 한 변의 배수로 표시된다.
목표 영상 기록에는 크기를 생략할 수 있다. 현재 odom 정렬에는 별도 geometry 등록의 실제 크기를 사용하며,
미입력 크기를 임의의 50mm 거리로 환산하지 않는다.

목표 조회:

```bash
bash scripts/run_pinky_parking.sh list --robot P2 --zone A
```

### 3. 영상 주차 전 명령 중계 파일 읽히기

**P2 터미널**에서 한 번 실행한다. Nav2·지도·AMCL은 재시작하지 않는다.

```bash
bash ~/cartrina-field/run_pinky_robot_p2.sh relay
```

P1은 `bash ~/cartrina-field/run_pinky_robot.sh relay`다.
이번 코드 준비 작업에서는 중계 프로세스를 재시작하지 않았다. 새 기능을 쓸 때 위 명령으로 읽힌다.

중계는 평소 `/cmd_vel`을 전달한다. 영상 주차 중에는 명시적으로 선택한
`/cartrina/pN/parking_cmd_vel`을 전달하고, 끝나면 다시 Nav2 입력으로 돌린다.
이는 Nav2의 0 속도 명령이 영상 제어를 덮어쓰지 않게 하는 입력 선택이다.
lease 만료·프레임 시각 만료·속도 초과로 명령을 거부하는 조건은 없다.

### 4. 영상 정렬만 실행 — 실제 로봇 이동

**A 적재 노트북 터미널:**

```bash
bash scripts/run_pinky_parking.sh align --robot P2 --zone A
```

먼저 `teach-observe`로 마커가 잘 보이는 후진 관측 위치를 등록한다.
정렬 실행 시 등록 거리만큼 일정 속도 후진 → 정지 관측 → 고정 목표로 곡선 전진 → 정지 확인을 수행한다.
처음 마커가 안 보여도 odom 후진이 가능하다. 이동 중 마커 미검출로 진행을 중단하지 않는다.
새 영상 보정은 정지 관측 때만 반영한다. 좌우 5mm 이내이면 방향 오차를 현재 자리에서 보정하고, 목표가 앞에 남고 방향 2° 이내이면 남은 거리만 추가 전진한다. 좌우 위치를 다시 잡거나 목표를 지나친 경우 후진 재시도한다.
Q/Ctrl-C는 취소, Enter는 현재 주차를 작업자가 확인하고 종료하는 명령이다.

보정 속도·제어 이득·목표 판정은 `runtime/field/pinky-parking.json`의 `control`에서 조정한다.
사용자가 승인한 완료 판정은 위치 5mm·방향 2도다. 제어용 가상 목표는 실제 목표 앞방향 25mm다. 이는 목표 도달 판정이며 실측 정확도 보장이 아니다.
차체와 바구니의 고정 관계 및 마커 높이 평면을 사용하므로 현장에서 실제 바구니 위치를 확인한다.

### 5. 주행 → 영상 정렬 → 집기 — 실제 로봇·팔 동작

목표 저장과 중계 반영이 끝난 뒤에 실행한다.

```bash
bash scripts/run_pinky_direct_a.sh both --robot P2 --zone A --parking
```

자동 영상 정렬이 끝나면 Enter 대기 없이 집기를 시작한다. 실제 주차·적재 확인은 실행 결과와 별도로 기록한다.
Q로 영상 정렬을 취소한 경우 집기를 실행하지 않는다.
기존 `--parking` 없는 명령은 기존의 수동 정렬 흐름이다.

입력 선택을 수동으로 Nav2에 돌리려면, 카메라 없이 다음을 실행할 수 있다.

```bash
bash scripts/run_pinky_parking.sh release --robot P2 --zone A
```

## 저장 자료

- `runtime/field/pinky-parking/targets.json`: 구역/로봇별 마커 ID·사전·목표 모서리·앞방향·크기.
- `runtime/field/pinky-parking/A-P2-target.png`: 목표 원본 사진.
- `runtime/field/pinky-parking/runs/<실행>/events.jsonl`: 관측·오차·명령·목표 저장 이벤트.
- 같은 폴더의 `latest.jpg`, `parking-*.mp4`: 검출·목표·오차를 겹친 영상.
- `result.json`: 종료 상태, 최종 오차, 영상 상태, 작업자 확인과 팔 실행 결과.

`aligned`는 영상상 목표 판정이다. 실제 주차·적재 성공과 구분한다.
P1/P2는 같은 지도 목적지를 쓰지만, 윗면 마커의 부착 위치·각도가 달라 목표 영상은 구분한다.
