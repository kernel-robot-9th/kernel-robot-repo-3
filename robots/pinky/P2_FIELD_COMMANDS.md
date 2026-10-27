# 빨간 P2 (192.168.0.17) 이동·주차좌표 교시 명령

> 2026-10-27 이후 주행 명령은 관제 노트북에서 실행한다.
> 최신 명령: [두 로봇 현장 작업·관제 터미널 명령](TWO_ROBOT_FIELD_COMMANDS.md).
> 아래 A 노트북 직접 실행 명령은 이전 단독 시험 기록이다.

P2 = pinky_62b2 / pinky-2 / ROS Domain 2. 아래 이동과 교시는 `--robot P2`를 지정한다.
로봇별 ROS 연결 설정은 분리하며, A/B/C 목적지는 두 대가 공통으로 사용한다.

## 1. P2 터미널: 시각·센서·지도

관제에서 접속하려면 `ssh pinky@192.168.0.17`. 이미 P2 터미널이면 접속은 생략한다.

```bash
bash ~/cartrina-field/run_pinky_robot_p2.sh sync-clock
bash ~/cartrina-field/run_pinky_robot_p2.sh localize
```

`sync-clock`은 sudo 암호 입력 뒤 관제 서버 시각을 읽어 적용한다.
`localize`는 최초 한 번 실행한다. 기동 파일은 P1과 같은 기준 지도를
`~/cartrina-field/maps/`에서 읽으며 P2의 기존 지도는 변경하지 않는다.

## 2. 관제 노트북 새 터미널: P2 RViz

```bash
source /opt/ros/jazzy/setup.bash
ROS_DOMAIN_ID=2 rviz2 \
  -d /home/noma/dev_ws/kernel-robot-repo-3/runtime/field/pinky-p2-initial-pose.rviz \
  >/tmp/pinky-p2-rviz.log 2>&1 &
```

P2를 맵에 놓고 `2D Pose Estimate`로 현재 위치·앞방향을 대략 지정한다.
목적지를 `2D Goal Pose`로 다시 찍지 않는다.

## 3. P2 터미널: 주행 실행부

```bash
bash ~/cartrina-field/run_pinky_robot_p2.sh navigation
```

기동 상태를 한 번 확인하려면 다음을 실행한다. `active [3]`가 실행 가능한 상태다.

```bash
source /opt/ros/jazzy/setup.bash
ROS_DOMAIN_ID=2 ros2 lifecycle get /planner_server
```

추후 주행 실행부만 다시 읽힐 때는 `navigation` 대신 `restart-navigation`을 사용한다.

## 4. A 적재 노트북 터미널: 원하는 구역으로 이동

```bash
cd /home/choi-chun-hwan/robot_shopping/kernel-robot-repo-3
```

아래 중 필요한 명령 하나만 실행한다. 교시 프로그램이 열려 있다면 먼저 Q로 종료한다.

**A 이동:**
```bash
bash scripts/run_pinky_direct_a.sh move --robot P2 --zone A
```

**B 이동:**
```bash
bash scripts/run_pinky_direct_a.sh move --robot P2 --zone B
```

**C 이동:**
```bash
bash scripts/run_pinky_direct_a.sh move --robot P2 --zone C
```

저장한 공통 A/B/C 좌표와 방향으로 이동한다. 바구니 포함 Nav2 경로를 사용한다.
P2는 진입점 위치 도달(3cm) → 제자리 방향 맞춤 → 최종 후진 순서로 실행한다.
진입점 단계는 각도 판정을 분리하며, P2의 최종 Nav2 도착 허용거리는 2cm이다.
직접 시험은 구간별 정지·자세 중복검사로 중단하지 않고 Nav2 동작 결과를 사용한다.
주행 결과를 표시하고 Enter 대기 없이 집기를 시작한다. 실제 바구니 위치와 적재 결과는 별도로 기록한다.
실제 재도착 정확도와 물체 적재 성공은 현장에서 확인한다. 주문 상태는 변경하지 않는다.

**A 이동 후 집기(진라면 1개 → 슬롯 0):**
```bash
bash scripts/run_pinky_direct_a.sh both --robot P2 --zone A
```
A 주행 동작이 끝나면 Enter 대기 없이 집기를 실행한다. 영상 정렬까지 연결하려면 `--parking`을 추가한다.
P1은 `--robot P1`로 바꾼다.

## 5. 관제 노트북 터미널: 키보드로 미세 조정·저장

```bash
cd /home/noma/dev_ws/kernel-robot-repo-3
source /opt/ros/jazzy/setup.bash
python3 -m scripts.pinky_teach_parking --robot P2
```

- W/S: 전진·후진, A/D: 회전. 반복하거나 길게 누른다.
- Space: 정지.
- 1=A 적재, 2=B 적재, 3=C 하역 선택.
- Enter: 정지 후 현재 선택 구역의 x/y/yaw 저장·갱신.
- Q: 교시 종료. 이후 다음 구역의 이동 명령을 실행한다.

권장 순서: A 이동 → 1 선택·정렬·Enter·Q → B 이동 → 2 선택·정렬·Enter·Q
→ C 이동 → 3 선택·정렬·Enter·Q.

저장 파일은 관제의 `runtime/field/pinky-p2-taught-parking.json`이다.
P1 교시 파일과 계산된 기존 목적지는 변경하지 않는다.

조회만 하려면:

```bash
python3 -m scripts.pinky_teach_parking --robot P2 --list
```

이번에 기록한 A/B/C 좌표는 `runtime/field/pinky-shared-parking.json`으로 반영했다.
P1/P2 이동 명령 모두 이 공통 파일을 읽는다. 이후 교시를 다시 기록하면 공통 파일 반영이 필요하다.

## 자체 주행 제한 제거 반영

TF/odom 관측 시각 만료, 경로·설정 대조 중단, 구간별 정지·자세 재검사, 자체 응답·주행 시간 제한을 제거했다.
로봇의 cmd_vel 중계는 lease·수신시간·속도 상한으로 명령을 차단하지 않고 그대로 전달한다.
Nav2의 실제 실패·취소 및 필요한 TF/목표 데이터가 없는 오류는 그대로 표시한다.
명령은 위와 같으며, Nav2 완료와 실물 주차·적재 성공은 구분한다.

영상 정밀주차 기능의 목표 저장·실행·기록 명령은 [ARUCO_PARKING.md](ARUCO_PARKING.md)를 따른다.
새 영상 제어를 사용하기 전 Pinky 터미널에서 `run_pinky_robot_p2.sh relay`를 한 번 실행한다.
