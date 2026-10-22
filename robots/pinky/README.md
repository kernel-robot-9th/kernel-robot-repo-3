# Pinky 기준 경로 모의 연결

## v4 주문·이동 통합 (2026-10-22)

현재 주문 통합은 **v4**다. `scripts/preview.py start --port 8001 --reference --auto` 또는 중앙 서버의 `SHOP_MOTION_BACKEND=reference_v4`로 선택한다. 네 PC 설정은 [현장 안내](../../FIELD_SETUP.md)의 1절을 따른다. 아래 v3 설명은 독립 경로 시험에만 해당한다.

- 주문당 최대 6개, 카트 3개, 같은 고객·Pinky의 여러 회차 운반. 출발 후 추가 주문은 다음 회차로 넘긴다.
- 회차 내 방문은 A→B→인계 순서이며 필요 없는 적재장은 건너뛴다. 인계 후 대기 위치로 복귀한다.
- 이동 허가는 1개다. 다른 로봇이 정차한 상태의 팔 작업은 병행 가능하다. 원래 구역·목표 구역을 함께 예약하고 도착 후 출발 구역을 해제한다. 인계 구역은 대기 복귀 때 해제한다.
- 빈 선두 로봇이 후열 주문을 막으면 `home_to_handoff`→후열 전진→`handoff_to_home_back`으로 순서를 조정한다. 상품·정책 실행이 없는 명시적인 대기열 조정 작업이다.
- `source-v4.json`이 경로 생성기·배치·공통 기하 코드 해시를 고정한다. 출처는 `pinky-omx-sim2real`의 `route-plan-v4-review-20261022`다. 팀 저장소는 외부 소스 폴더 없이 실행 가능하다.
- 수신은 `run / job / task / session / robot / source hash / frame / sequence / sim_epoch`를 검증한다. 위치 관측 만료 3초, 결과 불명·중지 시 점유 유지, 서버·중계 재시작 후 자동 재실행 금지다. 명령 수락과 모의 도착·정지는 별도 기록이다.
- v4 주문 실행에서는 독립 v3 이동 시험을 금지한다. 두 실행부가 한 로봇을 동시에 조작하지 않게 한다.

`server/reference.py`는 기존 주문·재고·팔 결과 엔진 위에서 v4 배차를 수행한다. `robots/pinky/compact.py`는 검증 가능한 기준 경로, `simulator.py`는 중계 A의 모의 위치 실행부다. 실제 ROS 인터페이스 이름이나 정밀 주차 판정을 만들지 않았다. **물리 추종·카메라 관측·실제 Pinky 주행·OMX 동작을 검증한 결과가 아니다.** 실물 모드와 함께 선택하면 서버가 거부한다.

검증 명령: `python -m pytest -q`, `python scripts/demo_reference_orders.py`. HTTP 보고서는 `runtime/verification/v4-orders-*/verification.json`, 화면에서도 실행 기록 JSON을 저장할 수 있다. 보고서에는 실물 검증 여부를 `false`로 남긴다. 단위 검사는 가상 시계와 합성 관측을 사용하고, HTTP 검사는 별도 서버·중계 프로세스로 기준 경로를 재생한다.

## v3 독립 이동 시험

도로 v3의 한 경로를 관제에서 요청하고 중계 A가 실행하는 단독 시험이다. `reference_path`는 기준 자세를 따라가는 모의 실행이며 **실물 주행·Isaac 바퀴 물리 추종·정밀주차 검증이 아니다.** 시험마다 경로 시작점에서 출발하고 두 로봇의 연속 운용 상태는 유지하지 않는다.

## 실행과 화면

기존 모의 관제·중계 A(`robot_gateway.runtime`)를 실행하면 관리자 **Pinky 이동** 탭을 사용할 수 있다. NumPy·ROS·Isaac 설치가 필요하지 않다. 실제 장비 모드에서는 이 시험을 거부한다. 4대 실행 방법은 [현장 안내](../../FIELD_SETUP.md)를 따른다.

한 PC에서 UI와 별도 서버/중계 프로세스를 확인하려면 저장소 루트에서 실행한다.

```bash
pnpm --dir web build
.venv/bin/python scripts/preview.py start --port 8001
# http://127.0.0.1:8001/admin#motion
# 관리자 토큰: runtime/preview-8001/credentials.json의 admin
# 종료: .venv/bin/python scripts/preview.py stop --port 8001
```

Windows에서는 `.venv/bin/python`을 `.venv/Scripts/python.exe`로 바꾼다. preview는 루프백 전용이며 현장 LAN 서버 실행 명령과 다르다.

1. 중계 A의 준비 상태를 확인하고 로봇·경로·배속을 선택한다.
2. 이동 요청 후 전송, 수락, 진행 위치, 도착·정지를 각각 확인한다. 분홍색은 Pinky, 노란색은 후면 바구니, 초록 경로는 전진, 주황 경로는 후진이다.
3. 필요하면 **중지 요청** 또는 새 시험의 **경로 30% 지점 모의 실패**를 사용한다. 중지 요청 수신은 실행부 정지 확인과 별도다.
4. 종료·정지 확인 후 **종료된 모의 시험 해제**로 다음 시험을 허용한다. 시험은 고객 주문·적재 내역·재고를 변경하지 않는다. 시험 점유 중에는 새 주문과 다른 동작 시험을 막는다.
5. **로그 JSON 저장**으로 명령·출처·도로 버전·수신 기록을 보관한다.

연결 끊김·관측 만료·서버 재시작은 `UNCERTAIN`으로 남기고 점유를 유지한다. 위치를 임의로 계속 움직이거나 성공 처리하지 않는다. 원래 모의 실행부 종료를 확인하고 연결 만료/새 실행부 연결 조건이 충족된 뒤 실패로 정리한다.

## 가져온 기준과 출처

원본: `pinky-omx-sim2real/deliverables/route-v3-20261022`. `reference/source.json`에 가져온 파일 6개의 원본 상대 경로·SHA-256을 고정했다. 시작할 때 파일 해시를 확인하고 관제와 중계의 source hash가 같아야 요청을 허용한다. 원본 데이터는 변경하지 않았다. 원본 프로젝트 전체·Isaac 자산·영상은 가져오지 않았다.

- 도로 버전 3, graph schema 2, 노드 19개·간선 26개·경로 16개. Nav2 저장 경로 형식이 아니다.
- 좌표는 `layout-v3`: X 0~2m, Y -1.5~0m. 실제 ROS map 좌표와의 변환은 미확인이다.
- A/B/인계 폭 0.6/0.6/0.8m, 작업대 깊이 0.75m. 위 통로는 서쪽 방향, 아래 통로는 동쪽 방향이다.
- 대기줄 선두 (0.8, -1.375, 0), 후열 (0.46, -1.375, 0). 독립 주차면으로 해석하지 않는다. FIFO 운영 제어는 후속 작업이다.
- 바구니 0.127 × 0.155 × 0.043m의 후면 강체 외곽을 사용한다. 경로의 2cm 기하 여유는 물리 안전거리나 실제 주차 오차 검증값이 아니다. 바닥 저항은 이 실행부에서 계산하지 않는다.

## 명령·관측 계약

기존 장비 시험 API와 인증을 재사용한다. `NAVIGATE`는 프로젝트 내부 명령명이다. 확인하지 않은 ROS 토픽·서비스·액션 이름을 추가하지 않았다. 요청은 `node_id=gateway-a`, `parameters={robot_id, route_id, rate}`이며 rate는 1/2/4다.

실행부는 `execute(command, cancelled)` 인터페이스 뒤에서 동작한다. 관측은 run/command/task/robot 식별자, frame/route version/source hash, sim epoch/sequence, 시뮬 시각, 관측 Unix 시각, pose/speed/progress, arrived/halted를 포함한다. 독립 시험에는 고객 session이 없어 null이다.

- 서버는 출처·경로와 자세의 일치·순번·시각·정지 근거를 확인한다. 같은 순번의 재수신으로 진행률이나 유효기간을 늘리지 않는다.
- 수신 이후 경과는 중앙 monotonic clock으로 계산한다. 실행 중 관측이 3초 동안 없으면 결과 불명으로 중지 요청한다. 관측 Unix 시각은 PC 간 동기화가 필요하고 2초 넘게 오래된 관측을 거부한다.
- 중앙 단절 시 중계의 기존 3초 watchdog이 실행 취소를 요청한다. 수신/실행 정지 결과를 별도로 기록한다.
- 시간 경과·프로세스 정상 종료만으로 성공하지 않는다. 올바른 경로 끝의 `arrived=true`, `halted=true` 결과가 필요하고 중지 요청 뒤의 도착은 성공으로 처리하지 않는다.
- 중계의 위치 전송 대기는 최신 관측 하나만 유지한다. 화면은 약 1초마다 조회하며 궤적 보간으로 실제 관측을 꾸미지 않는다.

## 검증 — 2026-10-22 개발 PC

```bash
.venv/bin/python -m pytest -q
.venv/bin/python scripts/demo_pinky_motion.py
```

관제 전체 자동시험 144개 통과(이 기능 23개 포함), 웹 TypeScript/Vite 빌드 통과. 16개 경로의 후면 바구니 포함 기하 검사를 통과했다. 별도 서버·중계 프로세스 HTTP 시험 5개 항목도 통과했다: 도착·정지 확인, 중지 수신/정지 구분, 실패 처리, 관측 끊김 시 점유 유지, 고객 세션·재고 불변. JSON 결과는 `runtime/verification/pinky-motion-*/verification.json`에 남는다. Ubuntu 검증 스크립트에도 이 HTTP 시험을 추가했다.

Windows 브라우저에서 지도·후면 바구니 표시, 정상 도착, 이동 중 중지와 정지 확인, 모의 실패, 시험 해제, 경로 재선택을 확인했다. 브라우저 콘솔 오류는 없었다. Ubuntu·다중 PC LAN·실물은 아직 시험하지 않았다.

## 다음 연결

현재는 1~3단계(기준 데이터, 단독 모의 명령/관측, 관제 지도/로그)까지다. 이후 4~6단계에서 두 로봇 통행·합류·FIFO 대기줄, 주문 및 다회 운반 연결, Isaac 바퀴 제어 추종을 별도로 검증한다. 실제 Pinky 주행 코드를 연결할 때는 ROS 배포판·실제 인터페이스·namespace·맵 좌표 변환·후진 정차 확인을 먼저 확인한다. OMX 작업 시작 허용에 이 모의 도착을 실물 근거로 사용하면 안 된다.
