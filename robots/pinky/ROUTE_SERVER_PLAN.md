# replay v4 기반 Route Server 연결 계획

## 2026-10-27 관제·두 대 준비 적용

최신 실행 명령은 [두 로봇 현장 명령서](TWO_ROBOT_FIELD_COMMANDS.md)를 따른다.
P1/P2 모두 Route Server active이며, 관제에서 각각 14경로/31이동구간의 ComputeRoute가 성공했다.
기존 9경로에 A/B 출차 및 출차 이후 연결 구간 5개를 추가했다. 공용 대기점과 저장된 구역 주차점을 연결하며,
목적지 보정으로 대기점까지 이동하던 기존 방식은 공용 경로에서 사용하지 않는다.
관제 주문 실행기는 공유 이동 순서와 선두/후열을 관리한다. 실제 이동·주차는 한 대씩 실행하며
구역별 팔 작업은 별도로 진행한다. 동시 통로 주행을 구현했다고 보고하지 않는다.
실물 검증은 남아 있고, 아래 P2/A 단일 적용 기록은 이전 단계 이력이다.

## 확인한 원본

- `/home/noma/Downloads/replay.html`, 제목 `Pinky 짧은 동선 · v4 검토안`.
- HTML에 포함된 config·paths·runs를 읽었고, v4 경로 9개의 점 개수와 끝 자세가
  현재 `robots/pinky/compact.py` 기준 경로와 일치함을 확인했다.
- 두 Pinky 모두 `/opt/ros/jazzy/share/nav2_route/package.xml`과
  `nav2_msgs/action/ComputeRoute.action`이 설치돼 있다.
- 2026-10-27 P2의 `home_to_A`에 실제 Route Server를 연결했다. 아래 적용 범위 외 경로는 후속 작업이다.

## 적용 완료 — P2 대기 → A

- A의 기존 `field_routes.plan(..., 'home_to_A')`에서 지도 변환·저장 목적지가 반영된 경로를 GeoJSON으로 내보냈다. 좌표를 새로 측정하거나 바꾸지 않았다.
- P2 Route Server가 두 이동 구간의 `ComputeRoute`를 처리하고, 실행기는 반환된 Path를 `FollowPath`로 전달한다. 전진·후진 방향 및 회전 구간은 기존 의미를 유지한다. A 진입에 임의 Hybrid 경로를 다시 계산하지 않는다.
- P2 local/global costmap의 바구니 확장을 제거하고 기본 본체 외형 `±0.06m` 사각형을 적용했다. 본체 기준 Nav2 충돌 검사는 남는다.
- A → P2 실제 요청 검증: `home_short_departure` 401점, `dock_reverse` 133점, 모두 status 4 / error 0. Route Server active 및 실행 중 외형 변경을 확인했다. **이 검증에서는 로봇·팔을 움직이지 않았다.**
- 결과: `runtime/field/pinky-route-server-check.json`. 실제 실행 시 경로·지도/odom 위치·속도·구간 결과는 A의 `runtime/field/pinky-navigation/runs/*.jsonl`에 남는다.
- A 설정: `runtime/field/pinky-mobile-p2.json`의 `route_index_file`. 그래프 재생성은 A 저장소에서 `python3 -m scripts.pinky_export_routes --profile runtime/field/pinky-mobile-p2.json`으로 한다. 재생성한 GeoJSON은 P2에 배포하고 Route Server가 다시 읽어야 반영된다.
- P2 재부팅 후 Route Server 기동: `bash ~/cartrina-field/run_pinky_route_server.sh`. 현재는 active 상태다.

이번 그래프는 A 단일 시험 경로다. 아래 9개 경로·두 대기 자리의 공통 그래프 및 두 대 운용까지 완료한 것은 아니다. 고정 경로 적용 후 실제 주행·적재 성공은 현장 시험으로 확인한다.

## 기존 대기 자리 — 다시 지정하지 않음

| 역할 | layout-v4 x/y/yaw |
|---|---|
| 대기 선두 front | `(0.8, -1.375, 0)` |
| 대기 후열 back | `(0.46, -1.375, 0)` |

이는 **ROS map 좌표가 아닌 원본 layout-v4 좌표**다.
기존 `layout_to_map` 변환으로 지도에 옮긴다. 주차 마커 목표를 바꿨다고 대기 자리나 전체 도로를 이동시키지 않는다.
선두 출발 → 후열의 선두 이동 → 복귀 자리 배정이라는 기존 큐 의미를 재사용한다.

## 재사용할 경로

`queue_advance`, `home_to_A`, `home_to_B`, `home_to_handoff`,
`A_to_B`, `A_to_handoff`, `B_to_handoff`,
`handoff_to_home_front`, `handoff_to_home_back`.

공통 지도 변환을 적용한 도로 그래프에 대기·분기·진입점을 놓는다.
Route Server는 그래프 경로를 선택하고, 기존 v4 곡선 및 전진·후진·회전 구간 의미를
실행기에 전달한다. 그래프의 같은 물리 통로가 여러 경로 이름으로 중복 점유되지 않게 연결한다.
현재 `field_routes.plan`은 A/B/C 도착 경로 위주이므로, 구역 간 이동과 복귀 경로까지 확장해야 한다.

## 영상 정밀주차와의 경계

1. Route Server 경로로 구역 카메라에서 윗면 마커가 보이는 진입점까지 이동.
2. Nav2 추종 종료 후 영상 제어가 바퀴 명령을 담당.
3. 구역/로봇별 목표 마커 자세로 정렬하고 적재·하역에 인계.
4. 작업 완료 후 출차 구간을 실행하고 Route Server 경로로 다음 구역 또는 대기 자리로 이동.

영상 정렬은 `scripts.pinky_parking.run_parking`을 호출한다.
Route Server로 바꿔도 목표 기록·마커 검출·영상 제어·시험 기록 코드는 재사용한다.

## 두 대의 동시 이동에서 달라지는 부분

원본 normal 실행 결과에는 `one_moving_at_a_time: true`가 있고,
프레임마다 `move_owner`가 한 로봇 또는 null이다.
즉 **기존 자료는 두 대 운용이지만 동시 주행 구현 자료는 아니다.**

원본의 전역 이동권 한 개를 그대로 쓰면 두 대가 동시에 움직일 수 없다.
독립된 구간은 동시에 이동하고, 공유 통로·작업대 진입·C 하역·대기줄 합류의 사용 순서는
기존 관제 작업대 점유 및 구간 상태와 연결한다. Route Server 자체가 두 로봇의 스케줄러를 대신하지 않는다.

## 다음 변경 범위 제안 — 아직 미승인·미구현

1. A 영상 주차와 실제 집기 확인을 먼저 완료한다.
2. 기존 9개 경로와 두 대기 자리를 지도 기준 그래프로 내보내고 Route Server 설정을 준비한다.
3. 한 대의 선두 출발 → A → 필요 시 B → C → 대기 복귀를 Route Server 명령으로 연결한다.
4. 후열 이동과 복귀 자리 배정을 붙이고, 분리된 구간의 두 대 동시 이동을 확인한다.

위 후속 범위와 별도로 P2/A 단일 Route Server 연결 및 본체 외형 적용은 완료했다. 실제 이동·팔 동작은 수행하지 않았다.
