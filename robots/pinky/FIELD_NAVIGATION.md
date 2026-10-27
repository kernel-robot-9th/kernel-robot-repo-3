# P1 실제 주행·A 적재 시험 준비

> 아래는 P1 초기 준비 기록이다. 2026-10-27 현재 P2/A에는 실제 Route Server를 연결했다.
> A에서 `bash scripts/run_pinky_direct_a.sh both --robot P2 --zone A --parking`을 실행하면
> 고정 경로 → 영상 정밀주차 → 진라면 1개·슬롯 0 적재 순서다.
> P2의 바구니 외형 확장은 제거했고 기본 본체 외형을 적용했다.
> 경로 계산만 검증했으며 변경 후 실물 주행·적재는 미확인이다. 상세: [Route Server 적용 기록](ROUTE_SERVER_PLAN.md).

흰색 P1 = `pinky_eed0`, `192.168.0.16`, ROS Domain 1. A 노트북이 실행한다.
실패한 기존 주문은 보존한다. 아래 직접 시험은 주문·재고를 변경하지 않는다.

## 목적지 기준

`reference/data/v4/layout.json`의 실측 배치를 저장 지도
`runtime/field/pinky-map-new.yaml`의 외벽·칸막이에 맞췄다.
`runtime/field/pinky-p1-measured-goals.json`이 고정 좌표 변환과 목적지 파일이다.
마우스로 찍은 A goal 및 X +3cm 후보는 이전 기록으로만 보존했다.

| 구역 | 배치 중앙 X | 벽→Pinky·바구니 접합부 | ROS map (x, y, yaw) |
|---|---:|---:|---|
| A | 0.30m | 0.43m | (0.814132, 1.610165, -3.111760) |
| B | 0.90m | 0.43m | (0.832029, 1.010432, -3.111760) |
| C | 1.60m | 0.42m | (0.862904, 0.311042, -3.111760) |

중심→접합부 오프셋은 기존 모델의 -0.0759777993m를 유지했다. 이 오프셋은
실물 재측정값이 아니다. 지도 벽 맞춤 잔차는 실물 정밀주차 오차를 뜻하지 않는다.
위치는 로봇 중심 기준이고, 앞방향은 통로 쪽·후면 바구니는 작업대 쪽이다.

재생성(관제, ROS·장비 연결 없음):

```bash
python3 -m scripts.pinky_register_measured_map
python3 -m scripts.pinky_route_preview --profile runtime/field/pinky-mobile.json \
  --map runtime/field/pinky-map-new.yaml --output runtime/field/pinky-measured-dock-check.json
```

## 실제 출발 방식

출발 위치 15cm 일치 검사는 제거했다. 고정 홈 지점의 제자리 회전도 강제하지 않는다.
Nav2 `BasketEntry`(Smac Hybrid / REEDS_SHEPP)가 현재 추정 위치·방향에서
A 접근점까지 바구니 외곽을 포함한 전진·후진 진입 경로를 계산한다.
이후 기존 v4 `dock_reverse` 직선 후진 구간을 FollowPath로 실행한다.
전체 원본 home 경로를 따라갔다고 보고하지 않는다. 목적지는 위 실측 기준으로 고정한다.
오류에는 실패한 구간·Nav2 상태·오류 코드·메시지를 표시한다.

## 충전 후 적용·시험 명령

P1 전원을 계속 켜두었고 지도·센서가 실행 중이면 **P1 터미널**에서 새 설정만 읽힌다:

```bash
bash ~/cartrina-field/run_pinky_robot.sh restart-navigation
```

P1을 재부팅했다면 `localize` → RViz 초기 위치 → `navigation` 순서로 시작한다.
들어 옮긴 경우 RViz **2D Pose Estimate**로 현재 위치·앞방향을 대략 다시 지정한다.
목적지는 마우스로 다시 찍지 않는다.

**A 적재 노트북 터미널** (`/home/choi-chun-hwan/robot_shopping/kernel-robot-repo-3`):

```bash
cd /home/choi-chun-hwan/robot_shopping/kernel-robot-repo-3
bash scripts/run_pinky_direct_a.sh move  # 주행만
bash scripts/run_pinky_direct_a.sh pick  # 정렬된 바구니에 진라면 1개·슬롯 0 적재만
bash scripts/run_pinky_direct_a.sh both  # 주행 → 수동 정렬 확인 Enter → 적재
```

위 세 명령은 선택지다. 시험할 모드 하나만 실행한다. 기존
`bash runtime/field/run-pinky-direct-a.sh`도 `both`로 연결된다.
적재만 실행할 때는 즉시 팔 동작을 시작한다. 동작 종료와 실제 물체 적재 성공은 별개다.

OMX는 A의 `~/dev_ws/omxtest/config/` 보정·자세·그리퍼를 그대로 읽는다.
운영 관제의 다음 기동에 쓸 준비 파일도 새 목적지 파일을 가리키도록 갱신했다.
이번 준비에서는 worker·Nav2 재시작이나 실제 주행·팔 동작을 하지 않았다.
B/C 목적지는 계산했지만, B/C 실제 주행·하역과 두 대 운용은 아직 검증하지 않았다.
