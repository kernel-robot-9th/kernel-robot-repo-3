# 한 대 관제 시연 — 주행 → 주차 → 적재 → 출발

> **최신 작업 우선순위:** 이 문서는 기존 관제 실행 절차 참고용이다. 현재 성과·남은 작업은 [남은 작업표](CAMERA_NAV_DEMO_PLAN.md)를 따른다. 전체 카메라 주행 보정 후 관제 전체 시나리오를 시험하며, 아래 초기 준비 상태를 현재 장비 상태로 간주하지 않는다.

2026-10-27 수정. 포트폴리오 시연용으로 실행 흐름을 단순화했다.
코드 준비만 완료했으며 원격 배포·서버/worker 재시작·실물 시험은 하지 않았다.

## 실행 방식

- Nav2 완료 → A ArUco 정렬 완료 → 적재 궤적 완료 → 구역 출발로 바로 이어진다.
- 3초 통신 취소, 2초 관측 만료, 관제 명령 시간 제한, 도착 후 정차·자세 중복 검사, 기준 경로 바구니 검사를 제거했다.
- 적재·팔 이탈 확인은 실행을 막지 않는 별도 기록이다. 관제의 `실물 결과 기록`에서 작업 후에도 저장할 수 있다.
- 실행한 상품은 `executed_items`로 기록한다. 실물 적재·하역 확인은 별도 필드이며 자동으로 성공 처리하지 않는다.
- P1은 흰색 eed0(.16, Domain 1), P2는 빨간색 62b2(.17, Domain 2)다. ROS 연결은 로봇별로 분리한다.
- C ACT의 180초 제한·대기 자세 확인 조건도 제거했다. 연속 정책 실행은 `하역 정책 실행 종료`로 끝낸다. 이 버튼은 정책 종료 명령이며 실물 하역 확인과 다르다.
- 모델·보정·자세 파일은 바꾸지 않았다. C 모델은 해당 노트북의 `act.models`에 지정된 방향별 경로를 읽는다.

## 파일과 기록

| 구분 | 위치 |
| --- | --- |
| 코드 묶음 | `runtime/field/pinky-demo/code.tar.gz` |
| 실행용 설정 | `runtime/field/pinky-demo/` — 현장 hardware 원본에서 별도로 생성 |
| 시연 DB | `runtime/hardware/pinky-demo/shopping.db` |
| 시연 worker 기록 | `runtime/hardware/pinky-demo/gateway-a/outbox.json` 등 |
| ArUco 목표 | `runtime/field/pinky-parking/targets.json` |
| 주차 영상·오차·결과 | `runtime/field/pinky-parking/runs/<실행>/` |
| Route Server 준비 자료 | `runtime/field/pinky-demo/routes.json` |

기존 운영 DB·실패 주문·OMX hardware·보정·자세 파일은 유지한다. Pinky의 기존 A/B/C 목적지 좌표도 유지하고 사용하지 않는 검사 설정만 정리했다.

## 1. 코드 전달 — 관제 노트북

장비 사용을 재개할 때 실행한다. 압축 파일에는 소스·웹 빌드만 들어 있으며 환경파일·현장 hardware·보정·자세·마커 목표는 포함하지 않는다.

```bash
scp /home/noma/dev_ws/kernel-robot-repo-3/runtime/field/pinky-demo/code.tar.gz \
  choi-chun-hwan@192.168.0.18:/tmp/pinky-demo-code.tar.gz
```

A 노트북:

```bash
cd /home/choi-chun-hwan/robot_shopping/kernel-robot-repo-3
tar -xzf /tmp/pinky-demo-code.tar.gz
```

B/C는 해당 노트북 프로젝트에 같은 코드를 적용한다. 현장 설정은 각 노트북의 원본을 사용한다.

## 2. 관제 서버 — 관제 노트북

현재 8000번 서버는 이전 코드이므로, 현장에서 기존 실행 터미널의 Ctrl+C로 종료한 뒤 새 코드를 실행한다.

```bash
cd /home/noma/dev_ws/kernel-robot-repo-3
.venv/bin/python -m scripts.prepare_pinky_demo --central --preferred-robot P1
bash scripts/run_pinky_demo_server.sh
```

P2부터 시험하려면 `P1`만 `P2`로 바꾼다. 시연 DB와 기존 운영 DB는 별개다.

## 3. Pinky — 선택한 로봇 터미널

지도·Nav2가 꺼져 있을 때만 아래 순서로 기동한다. 이미 켜져 있으면 그대로 사용한다.

```bash
# P1
bash ~/cartrina-field/run_pinky_robot.sh localize
# RViz의 2D Pose Estimate로 현재 위치·앞방향을 맞춘 다음
bash ~/cartrina-field/run_pinky_robot.sh navigation

# P2는 위 명령 대신
bash ~/cartrina-field/run_pinky_robot_p2.sh localize
# RViz 위치 지정 후
bash ~/cartrina-field/run_pinky_robot_p2.sh navigation
```

영상 주차 입력 선택을 반영할 relay는 한 번 실행한다.

```bash
# P1
bash ~/cartrina-field/run_pinky_robot.sh relay
# P2이면 위 명령 대신
bash ~/cartrina-field/run_pinky_robot_p2.sh relay
```

RViz가 필요하면 관제 새 터미널에서 실행한다. P2는 Domain만 2로 바꾼다.

```bash
source /opt/ros/jazzy/setup.bash
ROS_DOMAIN_ID=1 rviz2 -d /home/noma/dev_ws/kernel-robot-repo-3/config/pinky-field.rviz
```

A/B/C 목적지를 마우스로 다시 찍지 않는다.

## 4. A 마커 목표 저장 — A 노트북

실제로 적재 가능한 바구니 자세로 Pinky를 놓고, 로봇 윗면 마커 목표를 한 번 저장한다. 카메라를 사용하는 다른 프로그램과 worker는 종료된 상태에서 한다.

```bash
cd /home/choi-chun-hwan/robot_shopping/kernel-robot-repo-3
bash scripts/run_pinky_parking.sh teach --robot P1 --zone A
```

P2면 `--robot P2`. 여러 마커는 Tab으로 선택한다. 영상에서 로봇 앞쪽 방향을 클릭한 뒤 Enter로 저장한다.
마커 한 변을 실측한 경우에만 `--marker-size-mm <값>`을 추가한다. 크기 미지정 시 오차 단위는 마커 폭이다.
기본 입력은 A YOLO 카메라다. 상단 전용 카메라는 `pinky-parking.json`의 `zones.A.camera`에 `camera_by_id`, `width`, `height`, `fps`를 지정한다. OMX 보정은 변경하지 않는다.

## 5. Worker와 첫 시험

기존 worker가 실행 중이면 해당 터미널에서 종료한 다음 A에서 실행한다.

```bash
cd /home/choi-chun-hwan/robot_shopping/kernel-robot-repo-3
bash scripts/run_pinky_demo_worker.sh gateway-a
```

1. 선택한 Pinky를 시작 위치에 놓고 현재 위치·앞방향을 맞춘다.
2. `http://192.168.0.11:8000/shop`에서 새 고객을 만들고 진라면 1개를 주문한다.
3. `http://192.168.0.11:8000/admin/pinky/movement`에서 주행 → 영상 주차 → 적재 → 출발을 확인한다. 중간 확인 버튼 없이 이어진다.
4. 실제 적재를 확인하면 `실물 결과 기록`에서 해당 슬롯을 기록한다. 화면 슬롯 1은 코드 슬롯 0이다.

직접 실행도 Enter 대기 없이 진행한다.

```bash
bash scripts/run_pinky_direct_a.sh both --robot P1 --zone A --parking
```

B worker는 코드 적용 후 `bash scripts/run_pinky_demo_worker.sh gateway-b`를 사용한다.
C 연결·모델 파일 교체·현장 검증은 별도다. 이번 코드 수정으로 실물 주차·적재·하역 성공이 확인된 것은 아니다.

## 검증과 Route Server 상태

실물 없는 한 대 연결 시험에서 이전 제한을 넘는 시간과 목표와 다른 위치 응답을 주고도 `NAVIGATE → PICK → LEAVE`가 끝나며, 작업 종료 후 실물 확인을 따로 기록하는 것을 확인했다. 웹 타입 검사·빌드도 통과했다. 전체 단위시험·실물 시험은 하지 않았다.

`routes.json`은 기존 9개 경로, A/B 출발 2개, 앞/뒤 대기점의 준비 자료다. 공용 지도 변환과 교시 주차 목표를 분리했다. Route Server 실행 그래프·두 대 동시주행 스케줄러는 아직 구현하지 않았다. 현재 주행 실행은 Nav2 FollowPath다.
