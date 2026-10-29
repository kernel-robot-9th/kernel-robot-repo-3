# v3/v4 주행 경로 선택 — 준비·적용·실물 시험

갱신: 2026-10-28. 코드·두 로봇 그래프·웹 빌드 준비 완료. 로봇 배포·관제 운영 화면 적용·실물 시험은 미실시.

**이후 배포 상태:** 같은 날 사용자 승인으로 P1/P2 그래프 배포·Route Server active·관제 운영 웹/서버·중앙 worker 재기동을 완료했다.
초기 선택은 v4이며 선택 API에서 두 로봇 배포 true를 확인했다. 실제 이동은 실행하지 않았다.
이후 자동 시간 동기화도 적용해 두 로봇이 관제 서버 .11과 동기화됨을 사용자 로그로 확인했다. 재부팅 후 자동 복구만 미검증이다.
바구니 70%는 두 관제 프로필에서 적용 기록을 확인했다.

**최신 주차 변경:** 후열 정밀주차 → 전열 직진, 후열 점유 시 전열 직접 후진 주차로 코드를 바꾸고 두 그래프를 다시 준비했다.
**새 그래프는 사용자 적용 후 두 운영 인덱스 해시 일치 확인 완료**이므로 아래 2번은 반복하지 않는다. 이번 변경은 웹 빌드·서버 재시작이 필요 없고,
주문 시연 전에는 기존 중앙 worker를 새 코드로 재기동한다. 개별 시험은 [대기 주차 명령서](WAIT_PARKING_TEST_COMMANDS.md)를 따른다.

## 기준과 공통 설정

| 선택 | 기준 | 주행 방식 |
|---|---|---|
| v3 기본 순환 경로 | 첨부 `replay-1.html` / 저장소 `robots/pinky/reference/data/v3/` | 순환 도로를 따라 작업대 진출입 |
| v4 작업대 간 단축 경로 | 첨부 `replay.html` / 저장소 `robots/pinky/reference/compact_routes.py` | 대기에서 짧은 곡선 진입, A→B→C는 가까운 연결, 별도 복귀 통로 |

원본 replay의 경로를 기준으로 비교한다. 현장에는 최신 실측 주차·관측 위치와 카메라 대기 목표를 연결하므로 원본 재생과 모든 좌표가 같다는 뜻은 아니다.
두 방식 모두 OMX 집기/하역, A/B/C 영상 주차, 대기 정렬 **3cm·7°**, 주행용 바구니 **70%** 설정을 공통으로 사용한다.
바구니 충돌 설정의 실제 적용 여부는 별도이며 그래프 배포만으로 충돌 검사가 켜지지 않는다.

관리자 `/admin/pinky/movement`에서 두 로봇 공통 방식을 선택한다. 선택 변경은 **다음 고객 시작부터** 적용된다.
이미 시작한 고객은 주문·이동·하역·복귀까지 해당 고객에게 저장된 버전을 유지한다. 재시작 후에도 선택은 DB에 남는다.
선택 버튼 자체는 이동 명령을 보내지 않는다. 미리보기는 원본 계획이며 실제 실행 경로와 구분해 표시한다.

## 1. 사전 준비 — 로봇 연결·이동 없음

```bash
cd /home/noma/dev_ws/kernel-robot-repo-3
python3 -m scripts.pinky_route_modes prepare
```

이미 준비된 파일:

- `runtime/field/pinky-route-modes/P1.json`, `P1.geojson`
- `runtime/field/pinky-route-modes/P2.json`, `P2.geojson`
- `runtime/field/pinky-route-modes/wait-targets.json` — 준비본. apply에서 운영 목표로 연결
- `runtime/field/route-modes-web-build/index.html`

각 로봇의 한 그래프 안에 v3/v4 각각 14개 논리 경로를 서로 다른 노드 ID로 등록한다.
명령의 `route_version`으로 해당 노드만 요청하므로 선택 때마다 Route Server를 다시 시작하지 않는다.
최신 현장 목표를 다시 기록했다면 먼저 해당 관측값을 관제로 동기화한 뒤 prepare를 다시 수행한다.

## 2. 로봇별 그래프 적용 — 이동 없음

전체 카메라 프로그램과 기존 센서·위치추정은 유지한다.

```bash
python3 -m scripts.pinky_route_modes apply --robot P1
python3 -m scripts.pinky_route_modes apply --robot P2
```

각 Route Server를 한 번 재로딩한다. 원본 그래프·프로필은 `runtime/field/pinky-route-modes/backup-*`에 보존한다.
이 적용에는 준비된 공통 대기 경로도 포함된다. 이후 기존 단일 경로용 `pinky_wait_setup apply --stage waiting`을 실행하면
두 버전 그래프를 덮어쓰므로, 대기 경로 변경은 이 문서의 prepare/apply로 갱신한다.

## 3. 관리자 화면 적용 — 관제 서버 재시작, 이동 없음

```bash
bash scripts/apply_pinky_camera_web.sh runtime/field/route-modes-web-build
```

이 빌드에는 앞서 준비한 실측 바구니·대기 목표 표시도 포함한다.
영상 중계가 서버 재시작 중 종료됐다면 기존 [영상 명령](FIELD_VIDEO_COMMANDS.md)으로 중계를 다시 실행한다.
주문 시연 전 중앙 worker도 기존 실행을 종료하고 한 번 다시 실행해 코드와 경로 인덱스를 읽는다.

```bash
bash scripts/run_pinky_control_worker.sh
```

기존 worker와 중복 실행하지 않는다. 기존 실패 주문을 되살리지 않고 새 고객·새 주문으로 시험한다.

## 4. 터미널 구간 시험 — 사용자가 한 줄씩 실행

터미널 명령은 관리자 선택과 별개로 **`--route-version`으로 명시**한다. 생략 시 기존 호환값 v4다.
아래 출발점은 P1이 실제 선두 대기자리에 있을 때만 맞는다.

```bash
bash scripts/run_pinky_control.sh move --robot P1 --from front --zone A --parking --route-version 4
```

동일한 시작 배치·위치추정 준비 후 v3 비교:

```bash
bash scripts/run_pinky_control.sh move --robot P1 --from front --zone A --parking --route-version 3
```

A에 도착한 뒤 A→B 비교는 해당 회차의 버전을 유지한다.

```bash
bash scripts/run_pinky_control.sh move --robot P1 --from A --zone B --parking --route-version 4
bash scripts/run_pinky_control.sh move --robot P1 --from A --zone B --parking --route-version 3
```

위 두 줄은 연속 실행용이 아니다. 각각 실제 A 출발 상태에서 해당 버전 회차에 사용한다.
실제 집기·하역 명령은 두 방식에서 공통이다.

## 5. 비교·촬영 순서

1. 공통 대기 정렬·복귀·출차 확인. 필요 시 [대기 시험 명령서](WAIT_PARKING_TEST_COMMANDS.md) 참조.
2. 바구니 70% 충돌 설정 적용 후 같은 구간 확인. `pinky_wait_setup apply --stage basket`은 두 버전 그래프를 바꾸지 않는다.
3. v4 한 대 전체 흐름 → v3 한 대 전체 흐름 → 방식별 두 대 운용.
4. 같은 로봇·출발점·목적지·설정으로 반복하고, 최신 설정 적용 후 기록만 같은 집합으로 비교한다.
5. 원본 계획 / 현장 Route Server 경로 / 회차별 Nav2 추정 궤적을 공용 맵 위에 겹친다.
6. 실제 바닥 궤적은 전체 카메라 영상과 대조한다. 바닥 도로 표시는 이 결과 후 결정한다.

주행 JSONL: `runtime/field/pinky-navigation/runs/`.
`route_identity`에 `route_version`, 논리 경로명, 원본 source hash, 배포 graph SHA256을 남긴다.
기존 기록에는 버전·배포 해시가 없거나 옛 경로가 사용됐으므로 최신 경로 반복성 근거로 섞지 않는다.
전체 카메라는 현재 좌표·최신 영상만 저장하며 연속 위치 이력/녹화가 항상 남는 것은 아니다.
실제 궤적 비교용 전체 카메라 녹화·이력 수집은 반복 시험 전에 별도로 준비해야 한다.

## 10/28 v3 중간 지점 반복 전후진 수정

A 출차 `dock_leave`에서 목표 위치 오차 약 0.5cm·방향 오차 약 20°인 상태로 전후진하다 code=105가 발생했다. 기존 일반 판정은 위치 8cm·방향 약 14.3°였으므로 위치 도달 후 방향 조건에서 넘어가지 못했다.
P1/P2 공통 관제 실행부에서 v3의 전진 중간 구간(`home_depart`, `home_merge`, `dock_leave`, `exit`, `road`, `entry` 등)에 기존 `PositionGoalChecker` 5cm를 선택하도록 수정했다. 방향은 이어지는 경로와 기존 회전 구간에서 정렬한다. v4, 최종 관측 방향 정렬, 카메라 정밀주차는 유지한다.
그래프 좌표·로봇 설정 변경이나 재배포는 필요 없고, 새 CLI 실행부터 적용된다. 장시간 실행 중인 관제 worker는 전체 주문 시험 전에 최신 코드 반영이 필요하다. 관련 검증 28개 통과, 수정 후 실물 시험은 아직이다.

A 출차 중 멈췄고 실제 위치를 다른 곳으로 옮기지 않았다면, 관제에서 아래 명령으로 A→C 경유→대기 복귀를 재시험한다. 팔 동작은 없다.

```bash
cd /home/noma/dev_ws/kernel-robot-repo-3
bash scripts/run_pinky_control.sh move --robot P1 --from A --zone front --route-version 3
```

## 검증 범위

선택 API 인증, 선택의 DB 저장, 기존 고객 버전 유지, 신규 고객 적용, 두 버전 노드 ID 분리와 공통 주차 목표를 오프라인으로 확인한다.
관련 API·경로·대기 정렬 테스트 **31개 통과**, TypeScript/Vite 빌드 통과.
별도로 실행한 기존 분산 테스트에서는 이전에 제거된 watchdog·활성 중계 교체 차단을 기대하는 3개가 실패했다.
이번 준비에서 그 제한을 복원하거나 전체 테스트 통과로 보고하지 않았다.
웹 빌드와 코드 준비는 실물 주행·두 대 교행·충돌 회피 성공을 뜻하지 않는다.

## 10/28 P1 v3 후속 실물 시험 완료

전열→A→B→C→후열 주차→전열 직진 정상 종료. A/C 정밀주차는 첫 진입 후 odom으로 완료, B는 두 번째 진입 후 최종 마커까지 확인했다. 기존 code=105 중간 구간 반복 전후진 중단은 이번 시험에서 재발하지 않았다. 별도 복귀를 포함해 후열→전열 복귀 2회 완료. 적재·하역과 P2 시험은 하지 않았다.
[사진·영상·수정 내역과 기록기 중단 1회 상세](../../runtime/field/p1-v3-autotest-20261028-131429/REPORT.md).

## 10/28 v3·v4 오버랩 비교 자료

P1 v4 추가 시험과 v3 원본을 같은 맵에 겹친 PNG/SVG 생성 완료. v4 A/B 주차·전열 복귀 완료, C 진입 code=104와 C 카메라 열기 실패를 그대로 표시했다. 주행 설정 변경 없이 확보한 버전별 1회 자료다. [비교 보고서와 재생성 명령](../../runtime/field/p1-v3-v4-comparison-20261028-134448/REPORT.md). 도구는 `python3 -m scripts.pinky_route_overlap --help`.
