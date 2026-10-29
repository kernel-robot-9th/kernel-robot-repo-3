# 주문 1건 · 상품 6개 · Pinky 두 대 시험

**첫 시험 후 오류 처리 반영 / 충전 후 재시험 대기. v3 사용.**

- [x] 주문·고객은 각각 1건 유지, P1/P2에 3슬롯씩 배정.
- [x] A 쌀과자 3개, B 나머지 상품으로 시험 상품 배치.
- [x] P1 `home_depart` 구간 통과 후 P2 후열→전열→출차. P1 목적지 도착·정밀주차를 기다리지 않음.
- [x] 두 대 적재 종료 후 P1만 C 이동. P2는 B 주차자리에서 적재 상태로 대기.
- [x] C에서는 카메라 정밀주차·팔 작업을 호출하지 않고 `C 도착 · 하역 대기`로 유지. 완료 처리하지 않음.
- [ ] 실제 연속 출차 간격·경로 간섭·두 대 적재·P1 C 도착 확인.

## 현재 결과와 재개 순서 — 2026-10-29

- [x] 주문 1건·상품 6개 배차, P1/P2 A/B 주행·정밀주차 실행.
- [x] 첫 오류 기록 보존: A 쌀과자 집기 3회 실패 사용자 확인, B 진라면 적재 후 카메라 끊김으로 중단.
- [x] 카메라 5초·1회 재연결, 부분 완료 전달, 중단 주문 거절 시 worker 유지 코드 반영.
- [x] A 위치별 보정 10점·시험 설정 연결, `slot0_release` 15:02:44 저장 확인. [A 상세](../omx_yolo/docs/A_RICE_SPATIAL_HANDOFF.md).
- [x] 이후 카메라 끊김·적재 문제 해결 사용자 보고 수신.
- [ ] 충전 후 B 모터 USB, 두 로봇 마커 인식 및 ROS 실행 상태 확인.
- [ ] 이전 ERROR 주문과 로그를 보존하고 **새 시험 실행 폴더·DB로 전환** 후 재시험. 현재 `prepare`는 포인터가 있으면 기존 폴더를 재사용하므로 이것만 재실행해도 새 시험이 되지는 않는다.
- [ ] 두 대 실제 적재 성공 및 P1 C 도착 확인. C 하역은 계속 보류.

아래 명령은 새 시험 데이터가 준비된 다음 사용한다. 이전 실패 주문의 worker부터 바로 재기동하지 않는다.

## 1. 배치와 위치 갱신 — 관제 터미널

**P1 흰색을 전열, P2 빨간색을 후열에 실제로 배치한 뒤** 실행한다. `queue`는 대기열 기록만 바꾸며 로봇을 움직이지 않는다.

```bash
cd /home/noma/dev_ws/kernel-robot-repo-3
bash scripts/run_six_item_demo.sh queue
bash scripts/run_pinky_control.sh camera-pose --robot P1
bash scripts/run_pinky_control.sh camera-pose --robot P2
```

재부팅 후 Nav2가 꺼져 있다면 해당 로봇에만 기존 `setup --phase localize`, `camera-pose`, `setup --phase navigation`, `setup --phase route` 순서로 준비한다. 이미 켜져 있으면 재시작하지 않는다.

## 2. 주문 실행 연결 — 관제 터미널

관제 서버는 이번 시험 전용 DB로 실행한다. A/B 재캘리나 직접 집기 프로그램은 종료한 상태여야 한다. **아래부터 새 관제 주문이 실제 장비 명령으로 실행된다.** 첫 시험 worker는 중단한 상태이며 재시험 준비 후 다시 기동한다.

```bash
bash scripts/run_six_item_demo.sh start-workers
```

두 worker 모두 관제 노트북에서 실행한다. gateway-a는 Pinky 두 대와 A 원격 적재를, gateway-b는 B 원격 적재를 담당한다. B 노트북에서 별도 주문 worker를 중복 실행하지 않는다. C worker는 필요 없다.

## 3. 화면에서 주문 한 번

1. [고객 화면](http://192.168.0.11:8000/shop)에서 새 고객을 시작한다. 이전 시험 로그인은 새 실행에서 다시 로그인한다.
2. **쌀과자 3개 + B에 실제 준비한 상품 3개**를 한 번에 주문한다. 예: 진라면·신라면·치토스 각 1개. 예시는 이번 시험의 실물 성공을 보장하지 않는다.
3. `인계 요청`으로 주문을 마감한다. 두 대 적재가 끝나기 전에 눌러도 P1의 C 이동은 적재 완료 후에 시작한다.
4. [관리자 주문 화면](http://192.168.0.11:8000/admin/orders)에서 같은 고객 아래 로봇별 작업·슬롯을 확인한다.
5. P1이 C에 도착해 **하역 대기**, P2가 B에서 **적재 완료 · 구역 대기**이면 이번 시험 종료다.

## 4. 기록과 시험 종료

실행 데이터·worker 로그 위치:

```bash
python3 -c 'import json; print(json.load(open("runtime/field/six-item-demo-current.json"))["directory"])'
```

위 폴더의 `shopping.db`, `worker-a.log`, `worker-b.log`와 기존 주행·정밀주차·적재 녹화를 보관한다. 실제 물체 적재 성공은 화면의 프로그램 실행 완료와 별도로 확인한다.

시험을 마친 뒤 주문 연결을 종료한다:

```bash
bash scripts/run_six_item_demo.sh stop-workers
```

기존 `runtime/hardware/pinky-demo/shopping.db`와 재고·실패 이력은 보존했다. 새 시험 DB의 재고는 **쌀과자 3개·나머지 각 1개로 설정한 시험 수량**이며 재고를 자동 측정한 값이 아니다. 같은 시험 데이터로 다시 주문하지 말고 시험 결과 확인 후 다음 실행을 준비한다.

서버가 꺼진 경우에만 별도 터미널에서 복구:

```bash
bash scripts/run_six_item_demo.sh server
```
