# ArUco 보정 + odom 정밀주차

## 동작 — Nav2 도킹 제어식을 적용한 후진·전진 주차

1. `reverse_observe`: 등록한 관측 거리까지 0.02m/s로 차체 방향을 유지하며 후진한다. 최초 마커가 안 보여도 후진할 수 있다. 후진 끝에서 속도를 줄여 멈춰 서던 계산은 제거했다.
2. `observe`: 정지하고 마커·odom을 읽어 목표를 계산한다.
3. `advance`: Nav2 1.3.12 `SmoothControlLaw`의 곡률 계산으로 전진하며 방향을 맞춘다. 실제 목표 앞방향 25mm 지점을 제어용 목표로 삼고, 실제 목표 도달 또는 목표 평면 통과 시 정지한다. 이동 중 영상으로 목표를 바꾸지 않는다.
4. `verify`: 정지 상태에서 위치 5mm·방향 2° 이내인지 확인한다. 영상이 보이면 보정하고, 안 보이면 odom으로 확인한다.
5. 정지 재관측에서 좌우 5mm 이내이고 방향 오차만 2°를 넘으면 `align_heading`으로 현재 자리에서 방향을 맞춘 뒤 다시 확인한다. 회전 중 목표는 고정하며 카메라가 보이지 않아도 odom으로 제어한다.
6. 목표가 앞에 남고 좌우 5mm·방향 2° 이내이면 남은 거리만 추가 전진한다. 좌우 위치를 다시 잡거나 목표를 지나친 경우 후진 관측 → 곡선 전진으로 재접근한다. 고정 거리를 추가 전진하거나 오차 때문에 실패 종료하지 않는다.

공식 제어식의 Python 적용이며 Nav2 Docking Server를 실행하는 구성은 아니다.
출처와 Apache-2.0 고지는 `robot_gateway/hardware/nav2_parking_control.py`에 있다.
공식 제어기의 선속도 최소·최대를 모두 기존 0.02m/s로 설정한 계산을 사용한다.
곡률 유지에 필요한 회전 속도가 기존 최대 0.3rad/s에 도달하면 선속도를 함께 줄인다.

정지 관측의 기본 대기 0.25초는 영상 취득을 위한 정지 구간이며 실행 만료·실패 조건이 아니다.
마커 연속 검출·지도·AMCL 위치는 요구하지 않는다. 관측 단계에는 마커가 보여야 새 목표를 계산할 수 있다.
5mm·2° 완료 판정과 25mm 가상 목표는 2026-10-27 사용자 승인값이다.
시간 만료·재시도 횟수·관측 만료·경로 이탈 중단 조건은 추가하지 않았다.
odom 수신은 영상 루프와 별도 ROS 실행기에서 처리한다.

## 현재 P2 등록값

- 검출: `DICT_5X5_1000 / ID 0`.
- 마커 검은 정사각형 한 변: **25mm** — 사용자 제공값, 흰 여백 제외.
- 차체 원점→마커 중심: **전방 0mm / 좌측 0mm** — 사용자가 차체 중앙 위라고 설명한 근사값. 정밀 실측값이 아니다.
- 차체 원점은 현재 P2 URDF에서 양쪽 구동바퀴 축 중앙의 바닥 투영점이다.
- 앞방향은 사용자가 확인한 마커 `0 → 1` 변 기준 **0°**다. 마우스로 새 방향을 찍을 필요가 없다.
- 기존 저장 목표·사진은 유지한다. 실측·근사 입력은 별도 `geometry.json`에 저장한다.

## 명령 위치

아래 명령은 모두 **A 적재 노트북**에서 실행한다.

```bash
cd /home/choi-chun-hwan/robot_shopping/kernel-robot-repo-3
```

### odom 수신만 확인 — 카메라·구동 명령 없음

```bash
bash scripts/run_pinky_parking.sh odom --robot P2 --zone A
```

`odom.pose`, `frame_id: odom`, `base_frame: base_footprint`, 관측 시각이 출력된다.
3초는 이 조회 명령의 발견 대기 시간이다. 실제 주차 중 위치 만료·실행 중단 조건으로 사용하지 않는다.

### 부착 정보 등록 — 카메라·구동 명령 없음

현재 P2 값의 등록 명령:

```bash
bash scripts/run_pinky_parking.sh geometry --robot P2 \
  --marker-size-mm 25 --marker-forward-mm 0 --marker-left-mm 0
```

전방·좌측은 양수, 뒤·오른쪽은 음수다. 나중에 실제 위치를 확인했다면 이 입력값만 갱신한다.
P1은 해당 로봇의 크기·부착 위치로 별도 등록한다. 다른 로봇 값을 자동 복사하지 않는다.

### 후진 관측 위치 등록 — 이동 명령 없음

P2를 실제 주차 목표보다 뒤쪽인 로봇팔 쪽으로 옮겨, 상단 마커 전체가 여유 있게 보이는 위치에 놓는다.
앞방향은 저장한 목표 방향과 비슷하게 둔다. 정확한 map 좌표를 입력할 필요는 없다.

```bash
DISPLAY=:0 XAUTHORITY="$(find /run/user/$(id -u) -maxdepth 1 -name '.mutter-Xwaylandauth.*' -print -quit)" \
bash scripts/run_pinky_parking.sh teach-observe --robot P2 --zone A
```

검출된 ID 0을 확인하고 **Enter**를 누른다. 방향 클릭은 하지 않는다.
카메라 목표와 현재 관측의 차이로 후진 거리를 계산해 `observations.json`에 저장한다.
관측 사진도 저장하며 기존 주차 목표·사진은 덮어쓰지 않는다. 잘못 등록했다면 같은 명령으로 해당 관측 위치만 다시 기록한다.
저장하는 odom 자세는 참고 기록이며, 실제 실행에는 매번 시작 odom에 대한 상대 후진 거리를 사용한다.

### 정렬 시험 — 실제 P2 이동, 팔 동작 없음

관측 등록 후 실제 시험 승인과 배치를 마친 뒤 실행한다.
**대략 주차 목표 근처에서, 앞방향을 목표와 비슷하게 둔 상태로 시작**한다.
처음 후진 → 관측 → 전진 절차를 시험하는 명령이다. 이미 후진 관측 위치에 놓은 상태에서 실행하면 그 위치에서 추가로 후진한다.

```bash
DISPLAY=:0 XAUTHORITY="$(find /run/user/$(id -u) -maxdepth 1 -name '.mutter-Xwaylandauth.*' -print -quit)" \
bash scripts/run_pinky_parking.sh align --robot P2 --zone A
```

A 그래픽 터미널에 올바른 DISPLAY/XAUTHORITY가 있으면 앞 환경변수 없이 실행해도 된다.
터미널과 화면에 `reverse_observe → observe → advance → verify`와 시도 번호가 표시된다. 방향만 보정할 때 `verify → align_heading → verify`로 이어지며, 목표가 앞에 남으면 `advance`를 재개한다.
목표 도달 시 `aligned`, 오차가 남으면 `reverse_observe`로 돌아간다.
Q/Ctrl-C는 취소·기록 종료, Enter는 작업자가 현재 주차를 확인하고 종료하는 명령이다.
자동 판정을 확인할 때는 `aligned` 종료까지 기다린다.

## 기록과 확인 범위

- `runtime/field/pinky-parking/geometry.json`: 로봇별 크기·부착 위치와 근사값 출처.
- `observations.json`, `A-P2-observation.png`: 후진 관측 거리와 참고 영상.
- 기존 `runs/<실행>/events.jsonl`: 검출, 영상 오차, odom 관측·목표, 제어 출처, 단계·시도 번호, 명령, 마지막 정지 영상 보정 시각.
- `result.json`: 제어 방식, 사용한 부착 정보, 최종 odom·목표·오차·판정 기준·마커 가시 여부. `verification_source`가 `camera+odom`이면 마지막 정지 검증에서 마커를 사용했고, `odom`이면 영상 없이 계산했다. 자동 완료는 실물 성공 확인과 구분한다.
- 기존 영상·`latest.jpg` 기록은 그대로 저장한다.

코드 검증: 좌표·부착 오프셋 변환, 세 초기 자세에서 후진·관측·곡선 전진 순서의 수렴,
주행 중 검출 흔들림에 대한 목표 고정, 정지 관측에서만 목표 보정,
목표 통과 시 정지·후진 재시도, 이전 후진 정체 지점의 단계 전환, 잔여 9.86mm 추가 접근,
좌우 0.68mm·방향 4.59°에서 제자리 보정 후 후진 없이 완료하는 동작을 확인했다. 계산 검증 8개가 통과했다.
실물 이력: `20261027-122118-P2-A-align-7b912d`는 약 75.5초·진입 6회 후 aligned였고, 사용자가 정밀주차 성공을 확인했다. 최종 영상 계산 오차는 약 0.70mm·1.82°이며 실측 오차를 뜻하지 않는다. 해당 실행의 원본 `physical_parking_confirmed=false`는 자동 종료 당시 기록으로 보존한다.
이번 제자리 방향 보정의 재시도 감소 효과와 바구니 적재 성공은 아직 실물 확인 전이다.
