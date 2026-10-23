# OMX3 관제 통신과 Gazebo 동기화

> 2026-10-23: 이 문서는 기존 v1 규격이다. 새 작업은 `basket_id: 0/1`과 트레이 전체
> 비우기를 사용한다. 아래 `left/right`, 핑키별 고정 목적지, 상품 ID별 완료 규격과의
> 변환 또는 관제 변경은 아직 구현하지 않았다. 최신 시연 준비는
> [README_VLA_KO.md](README_VLA_KO.md)를 따른다.

현재 PC에 관제 노드와 OMX3 관절 동기화 옵션을 구현했다. 상대 PC의 학습 모델 실행기,
실물 도킹 센서, 투입 성공 판정, 자동 출발 제어는 별도 연동 대상이다.
이 노드는 모터를 제어하지 않으며 `release_pinky`는 출발 허가 상태값이다.

## 실행

같은 네트워크와 ROS_DOMAIN_ID를 사용하고 ROS 2 DDS discovery가 양쪽에서 되는지 확인한다.
실제 로봇 상태와 시뮬레이션 상태의 토픽을 구분한다.

```bash
source /opt/ros/jazzy/setup.bash
source ros_ws/install/setup.bash
export ROS_DOMAIN_ID=0
ros2 run gazebo_multi_robot_bringup omx3_handover
# 별도 터미널: Gazebo가 실행 중이면 먼저 정상 종료하고 시작
./scripts/run_manufacturer_five_robot.sh omx3_mode:=mirror real_domain_id:=0
```

OMX3 mirror는 가상 OMX3 제어기를 실행하지 않는다. 기존 OMX2 옵션은 유지한다.
상대 PC는 `/real/omx3/joint_states`에 sensor_msgs/JointState를 20Hz 목표로 전송한다.
이름은 `joint1`~`joint5`, `gripper_joint_1`, 위치는 제조사 URDF와 일치하는 라디안 값이다.
LeRobot 정규화 값을 그대로 발행하지 않는다. 다른 이름은 상대 PC에서 변환한다.
유효 데이터가 0.5초 끊기거나 발행자가 1개가 아니면 표시 갱신을 중단한다.
상태는 `/digital_twin/omx3/status`에서 확인한다. 상품 위치 동기화는 포함하지 않는다.

## 인계 프로토콜 v1

아래 토픽 메시지 형식은 모두 std_msgs/String의 JSON이다. 동일 의미의 ROS 인터페이스 패키지를
추후 도입할 수 있지만 상대 PC는 우선 아래 형식으로 맞춘다.

관제 프로그램 → `/supervisor/omx3/handover/request`:

```json
{"request_id":"unique-001","order_id":"order-001","pinky_id":"pinky1","docked":true,"stationary":true,"items":[{"object_id":"cup-001","sku":"ramen"}]}
```

`docked`와 `stationary`는 실제 관제의 최신 상태 검증 결과여야 한다. 현재 노드 자체는
도킹 센서를 읽지 않는다. 주문당 items 1~4개, 물체 ID 중복 금지, 같은 SKU는 여러 개 허용한다.

관제 노드 → `/real/omx3/handover/request`:
위 요청에서 `docked`, `stationary`를 제외하고 `basket`을 추가한다.
핑키1은 `left`, 핑키2는 `right`다. 좌우는 기존 맵의 x=1.29m / 1.91m 바구니 기준이며 실물과 대조한다.
상대 PC는 실제 도킹/안전 상태를 재확인하고 요청 ID로 중복 실행을 방지해야 한다.

상대 PC → `/real/omx3/handover/status` (실행 중에도 1Hz 이상 권장):

```json
{"request_id":"unique-001","state":"running","placed_object_ids":[]}
```

state: accepted / running / completed / failed. placed_object_ids는 누적 완료 물체 목록이다.
완료 메시지에는 모든 물체 ID와 실제 결과 확인, 안전 복귀 확인이 필요하다:

```json
{"request_id":"unique-001","state":"completed","placed_object_ids":["cup-001"],"placement_verified":true,"arm_safe":true}
```

관제 노드 → `/supervisor/omx3/handover/status`:
request, state, placed_object_ids, release_pinky를 포함한 작업 상태.
출발 제어기는 일치하는 request_id/pinky_id의 `release_pinky=true`를 확인해야 한다.
다른 요청 ID·알 수 없는 물체·진행 역행·증거 플래그 없는 완료는 거부한다.

기본 10초 동안 유효 상태가 없으면 communication_lost로 고정하고
`/real/omx3/handover/stop`에 request_id와 reason을 보낸다.
상대 PC는 이 중단 요청 처리와 자체 통신 watchdog을 반드시 구현해야 한다.
네트워크가 끊긴 경우 이 토픽만으로 실물 정지를 보장할 수 없다.
failed/communication_lost에서는 핑키를 해제하지 않고 새 인계를 차단한다.

작업 이력은 기본 `~/.ros/omx3_handover_jobs.json`에 보관한다.
재시작하면 진행 중 작업은 communication_lost로 고정한다. 동일 request_id 재요청은 재실행하지 않는다.
현재 자동 복구 API는 없다. 현장에서 팔과 상품을 확인하고 작업을 정리한 뒤 노드를 종료하고,
이력을 보관한 채 새 journal_path로 재시작한다. 새 인계에는 새 요청 ID를 사용한다.
관제 노드는 한 인스턴스만 실행한다. journal 파일을 실행 중 편집하지 않는다.

## 검증 범위

순수 로직 테스트는 바구니 분기, 중복, 동시 인계 차단, 입력 검증, 완료 조건,
진행 역행, 실패/시간 초과 고정을 포함한다. 별도 ROS 도메인의 두 노드로 요청과 완료 왕복을 검증한다.
실제 두 PC 네트워크, 실물 동작, Gazebo OMX3 실제 화면 일치는 상대 PC 연결 후 검증해야 한다.
