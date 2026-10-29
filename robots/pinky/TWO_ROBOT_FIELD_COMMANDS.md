# 두 Pinky 현장 작업·관제 터미널 명령

> **2026-10-27 최신 상태:** 기존 25mm 마커로 A/B/C × P1/P2의 목표·geometry·후진 관측 등록은 완료했다. 아래 초기 준비·미등록·연결 불가 표기는 당시 기록이며, 전체를 반복하지 않는다. 다음 작업은 큰 마커 검출과 전체 카메라 주행 보정이다. 마커 교체 후 필요한 등록 갱신과 최신 시험 순서는 [남은 작업표](CAMERA_NAV_DEMO_PLAN.md)를 따른다.

2026-10-27 준비. **아래 명령은 별도 표기가 없으면 관제 노트북에서 실행한다.**

2026-10-27 출발 경로 수정: P1·P2 공용 `home_to_A/B/handoff`는 선두 대기자리에서
회전 후 통로 쪽으로 30cm 직선 후진하고, 곡선으로 각 구역의 기존 진입점에 연결한다.
출발 직선·곡선·작업대 진입 직선은 한 번의 FollowPath로 이어진다.
곡선 끝에서는 별도 도착·방향 완료를 판정하지 않는다. 두 대기자리와 등록된 주차 목표는 유지한다.
두 로봇의 `FollowPath.use_collision_detection=false`는 사용자 승인으로 적용했다.
관제는 Route Server 연결·요청 접수·계산 결과 대기를 표시한다. 접수 또는 결과 응답이
8초간 없으면 `ComputeRoute`만 한 번 재요청한다. 주행·적재 명령은 자동 재전송하지 않는다.
통합 실행 중 Ctrl-C는 원격 작업에 취소를 직접 전달하고 종료까지 기다린다.
SSH는 별도 세션에서 실행해 관제 Ctrl-C로 먼저 끊기지 않으며, 주차 종료 루틴이 `nav2` 모드로 복귀한다.
회전 전에는 계산 가능한 map→base TF를 비동기로 기다리고, 받은 변환으로 회전 각도를 계산한다.
시작 직후 TF 시간 범위가 아직 겹치지 않는 경우에도 첫 조회 실패만으로 종료하지 않는다.
주행의 최종 목표는 이제 로봇·구역별 저장된 후진 관측 위치다. 정차 목표 축으로 저장된
`goal_forward_m/goal_left_m`를 지도에 변환하며, 실제 정밀주차 목표는 바꾸지 않는다.
P1·P2는 각각 `pinky-route-network-p1.json`/`pinky-route-network-p2.json`을 사용한다.
관측 목표만 `observation_goal_checker`의 위치 허용 오차 5cm를 사용한다.
P1·P2 모두 위치만 판정하는 `PositionGoalChecker`로 경로 추종을 종료한 뒤,
별도 Spin으로 저장된 관측 방향을 맞추고 카메라 정밀주차로 넘긴다.
방향 정렬 직전에는 전체 카메라 위치 보정을 반복하지 않아 도착 판정과 같은 지도 기준을 이어 쓴다.
카메라 정밀주차의 기존 위치·방향 허용 오차와 대기자리 목표는 유지한다.
통합 실행은 도착 후 추가 후진 없이 관측부터 시작한다. 관측 위치에서 주차만 별도 실행할 때는
`parking --robot P1 --zone A --mode align --start-at-observation`을 사용한다.
아래 초기 준비 기록 이후 A/B/C × P1/P2의 목표·관측 위치·마커 geometry는 사용자 등록 완료.
수정 경로의 실제 주행·주차·적재 결과는 현장 시험으로 확인한다.

준비 확인: 두 로봇 모두 지도·AMCL·Nav2·Route Server active. 관제에서 각 14경로/31이동구간 계산 성공.
실제 주행·팔 동작은 이번 준비에서 실행하지 않았다. B는 연결 불가로 배포 대기다.
주행은 관제 ROS 클라이언트가 요청한다. 카메라·팔은 USB가 연결된 구역 노트북에서 실행한다.
주차 등록 영상 창은 해당 구역 노트북에 뜨며, Enter/Q는 명령을 실행한 관제 터미널에서도 입력할 수 있다.

```bash
cd /home/noma/dev_ws/kernel-robot-repo-3
```

## 준비 범위와 남은 현장 입력

| 대상 | 설정 | 현장 작업 |
|---|---|---|
| P1 흰색 | .16 / Domain 1 / 본체 외형 / Route Server | 마커 크기·부착 앞방향 확인, A/B/C 주차 등록 |
| P2 빨간색 | .17 / Domain 2 / 본체 외형 / Route Server | 기존 A 주차 유지, B/C 주차 등록 |
| A | 기존 카메라·팔·보정 유지 | A/P1 등록 및 두 로봇 적재 확인 |
| B | 배포 명령 준비 | .19 재연결 후 배포·B/P1·P2 등록 |
| C | 기존 front 카메라를 주차 입력으로 설정, 좌·우 모델 경로 유지 | 영상으로 구역 확인, C/P1·P2 등록·하역 확인 |

목표는 A/P1·A/P2·B/P1·B/P2·C/P1·C/P2 여섯 조합이다.
각 조합에 **주차 목표 + 후진 관측 위치**가 필요하다. A/P2는 둘 다 저장돼 있다.
P2 마커는 DICT_5X5_1000 / ID 0 / 25mm / 중심 오프셋 0·0 근사 / 앞방향 0°다.
P1 값은 확인 전 임의 복사하지 않는다. 지도 목적지와 기존 OMX 자세·캘리는 다시 기록하지 않는다.

## 1. B 재연결 후 준비

관제의 전용 SSH 공개키를 B에 한 번 등록한다. 암호는 터미널에 직접 입력한다.

```bash
ssh-copy-id -i ~/.ssh/cartrina_field_ed25519.pub jimmy@192.168.0.19
python3 -m scripts.pinky_deploy_stations --zone B
```

설정·주차 코드만 배포하고, B의 hardware·자세·보정·기존 주차 목표는 보존한다.
이 명령은 worker나 장비를 실행하지 않는다.

## 2. 맵 배치·로봇별 초기 위치

이미 지도·Nav2가 실행 중이면 기동 명령을 반복하지 않는다.
로봇 재부팅 후에만 각 로봇에 다음 순서로 실행한다. P2는 `P1`을 `P2`로 바꾼다.

```bash
bash scripts/run_pinky_control.sh setup --robot P1 --phase localize
bash scripts/run_pinky_control.sh rviz --robot P1
# RViz의 2D Pose Estimate로 실제 위치·앞방향 지정
bash scripts/run_pinky_control.sh setup --robot P1 --phase navigation
bash scripts/run_pinky_control.sh setup --robot P1 --phase route
```

이미 기동됐다면 RViz만 연다. 두 RViz는 각각 해당 로봇 Domain으로 열린다.

```bash
bash scripts/run_pinky_control.sh rviz --robot P1
bash scripts/run_pinky_control.sh rviz --robot P2
```

기존 대기 두 자리의 map 좌표:

| 자리 | x | y | 앞방향 yaw |
|---|---:|---:|---:|
| front 선두 | -0.039590 | 1.084466 | -1.540964 rad |
| back 후열 | -0.049731 | 1.424315 | -1.540964 rad |

두 대 시험의 최초 배치는 P1=front, P2=back으로 정하고 다음은 **배치 기록만** 저장한다.

```bash
bash scripts/run_pinky_control.sh locate --robot P1 --zone front
bash scripts/run_pinky_control.sh locate --robot P2 --zone back
```

한 대만 시험하고 그 로봇을 선두에 놓았다면 해당 로봇을 `--zone front`로 기록한다.
손으로 옮긴 뒤에는 RViz 초기 위치와 이 배치 기록을 현재 상태에 맞춘다.
`locate`는 로봇을 움직이거나 AMCL을 변경하지 않는다.

## 3. 키보드로 주차 자리 맞추기

```bash
bash scripts/run_pinky_control.sh teleop --robot P1
```

W/S 전후진, A/D 회전, Space 정지, Q 종료.
이 키보드 프로그램의 Enter는 지도 좌표 교시이므로 이번 **영상 목표 등록에는 사용하지 않는다**.
실제 바구니 적재/하역 위치를 맞춘 뒤 Q로 닫고 아래 영상 등록을 실행한다.

## 4. 구역별 마커 주차 등록

먼저 A/P1, 다음 B/P1·P2, C/P1·P2 순서로 진행한다.
아래 변수 두 개만 해당 조합으로 바꾼다. A/P2는 기존 목표를 유지한다.

```bash
robot=P1
zone=A
bash scripts/run_pinky_control.sh parking --robot "$robot" --zone "$zone" --mode view
```

영상의 사전·ID와 청록색 `0 deg` 화살표를 확인하고 Q.
청록색이 실제 앞이면 0°, 반대면 180°다. 90°/270°는 영상의 마커 축 기준이므로 표시 방향을 확인해 선택한다.
아래 값은 **확인한 값으로 입력**한다. P1을 P2와 같다고 가정하지 않는다.

```bash
read -rp '검은 마커 한 변(mm): ' marker_mm
read -rp '차체 중심에서 마커 전방(mm): ' marker_forward
read -rp '차체 중심에서 마커 좌측(mm): ' marker_left
read -rp '검출 사전(예: DICT_5X5_1000): ' dictionary
read -rp '검출 ID: ' marker_id
read -rp '마커 기준 앞방향(도): ' front_deg
bash scripts/run_pinky_control.sh parking --robot "$robot" --zone "$zone" --mode geometry \
  --marker-size-mm "$marker_mm" --marker-forward-mm "$marker_forward" --marker-left-mm "$marker_left"
bash scripts/run_pinky_control.sh parking --robot "$robot" --zone "$zone" --mode teach \
  --dictionary "$dictionary" --marker-id "$marker_id" --front-angle-deg "$front_deg"
```

실제 주차 목표에 둔 상태에서 Enter로 저장한다. 마우스로 앞방향을 찍지 않는다.
P2를 B/C에 등록할 때는 이미 확인한 값으로 바로 실행할 수 있다:

```bash
bash scripts/run_pinky_control.sh parking --robot P2 --zone "$zone" --mode teach \
  --dictionary DICT_5X5_1000 --marker-id 0 --front-angle-deg 0
```

이어서 로봇팔 쪽으로 조금 후진시켜 마커 전체가 보이는 관측 위치에 놓고 저장한다.

```bash
bash scripts/run_pinky_control.sh parking --robot "$robot" --zone "$zone" --mode teach-observe
# 마커가 검출되면 Enter
bash scripts/run_pinky_control.sh list --zone "$zone"
```

`targets_file`과 `observation_file` 양쪽에 해당 `구역/로봇` 키가 있어야 한다.
등록 후 다시 주차 목표 근처에 두고 정렬만 시험한다. 관측 위치에서 시작하면 추가 후진하므로 목표 근처로 옮긴다.

```bash
bash scripts/run_pinky_control.sh parking --robot "$robot" --zone "$zone" --mode align
```

기존 후진 관측 → 곡선 진입 → 잔여 거리/방향 보정 방식을 그대로 사용한다.
카메라가 바뀌지 않는 한 이미 성공한 목표를 반복 등록하지 않는다.

## 5. 관제에서 단독 주행·적재·하역

**대기 선두 → A 주행만**:

```bash
bash scripts/run_pinky_control.sh move --robot P1 --from front --zone A
```

**대기 선두 → A 정밀주차 → 진라면 1개·슬롯 0 적재**:

```bash
bash scripts/run_pinky_control.sh both --robot P1 --from front --zone A --parking
```

P2 시험은 `--robot P2`로 바꾼다. 같은 로봇에 위 두 명령을 연달아 실행하지 말고 시험할 명령 하나를 선택한다.
이미 A에 도착했다면 주차 또는 `arm`만 실행한다.

**A → B 정밀주차 → 라이스칩 1개·슬롯 1**:

```bash
bash scripts/run_pinky_control.sh both --robot P1 --from A --zone B --parking --sku SKU-RICE-CHIP --slot 1
```

**B → C 정밀주차만**:

```bash
bash scripts/run_pinky_control.sh move --robot P1 --from B --zone C --parking
```

**C 하역만** — P1 기본 left, P2 기본 right. 완료 시 관제 터미널 Enter로 종료한다.
이 직접 시험은 선택 상품 한 개의 시험이며 기존 주문·재고를 변경하지 않는다.

```bash
bash scripts/run_pinky_control.sh arm --robot P1 --zone C --side left
```

**C → 대기 복귀** — 실제 비어 있는 자리를 지정한다. 이 직접 명령은 다른 로봇을 자동 재배치하지 않는다.

```bash
bash scripts/run_pinky_control.sh move --robot P1 --from C --zone front
# 후열 복귀는 --zone back
```

명령 실행 결과와 실물 적재·하역 성공을 따로 확인한다.
주행 기록은 관제 `runtime/field/pinky-navigation/runs/`, 주차 기록·영상은 해당 구역 `runtime/field/pinky-parking/runs/`에 저장된다.

## 6. 새 주문 6개·두 대 운용

1. 여섯 주차 조합의 등록·단독 인계를 마친다.
2. 두 대를 대기 두 자리에 놓고 위 `locate`로 기록한다.
3. A에서 실행하던 기존 gateway-a worker가 있다면 그 터미널에서 Ctrl-C로 종료한다. A의 주문 worker 역할은 관제에서 실행한다.
4. 아래 worker들을 시작한 뒤 관리자 화면에서 연결을 확인하고 **새 주문**을 만든다. 기존 실패 주문을 복원하거나 데이터베이스를 초기화하지 않는다.

**관제 주문 worker** — 명령을 실행하는 시점부터 관제 주문을 받아 실제 장비가 동작할 수 있다:

```bash
mkdir -p runtime/field/logs
nohup bash scripts/run_pinky_control_worker.sh >runtime/field/logs/control-worker.log 2>&1 </dev/null &
```

**B/C 팔 worker** — 기존 동일 worker가 있다면 해당 터미널에서 먼저 종료하고 한 번만 실행한다:

```bash
ssh -i ~/.ssh/cartrina_field_ed25519 jimmy@192.168.0.19 \
  'cd ~/robot_shopping/kernel-robot-repo-3 && nohup bash scripts/run_pinky_station_worker.sh B >runtime/field/control-worker.log 2>&1 </dev/null &'
ssh -i ~/.ssh/cartrina_field_ed25519 team2@192.168.0.20 \
  'cd ~/robot_shopping/kernel-robot-repo-3 && nohup bash scripts/run_pinky_station_worker.sh C >runtime/field/control-worker.log 2>&1 </dev/null &'
```

- 관리자: http://192.168.0.11:8000/admin / 고객: http://192.168.0.11:8000/
- 두 고객 세션을 만들어 P1/P2 배정을 확인하고, 총 6개 주문을 두 세션에 나눠 입력한다. 한 운반 차수의 3슬롯 제한에 따라 후속 운반이 이어진다.
- C 하역 완료는 관리자 화면의 해당 작업 **하역 정책 실행 종료** 버튼으로 전달한다. 화면 표시와 실물 전달을 함께 확인한다.
- 현재 기존 고정 경로는 공유 통로를 쓰므로 **이동·주차는 한 대씩**, 팔 작업은 구역별로 진행한다. 두 대를 같은 통로에서 동시에 달리게 하는 방식은 아니다.
- 후열 로봇은 선두가 출발한 뒤 `queue_advance`를 거쳐 출발한다. C 복귀 때 후열에 다른 로봇이 있으면 그 로봇을 빈 선두로 먼저 이동시키고 후열로 복귀한다.
- 주문의 A 출차 후 B/C 이동은 `A_exit_to_B`/`A_exit_to_handoff`로 이어지며 매번 대기 자리로 되돌아가서 출발하지 않는다.

주문 worker는 이번 준비 과정에서 자동 시작하지 않는다. 물리 등록 전 기존 주문을 받아 움직이지 않도록 시작 명령을 현장 단계에 둔다.
