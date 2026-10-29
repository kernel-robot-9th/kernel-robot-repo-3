# 주문 1건 · 상품 6개 · Pinky 두 대 시험

**최근 시험 완료 / 다음 주문 기반 전체 시험은 C 하역 작업 완료 후. v3 사용.**

- [x] 주문·고객은 각각 1건 유지, P1/P2에 3슬롯씩 배정.
- [x] A 쌀과자 3개, B 나머지 상품으로 시험 상품 배치.
- [x] P1 `home_depart` 구간 통과 후 P2 후열→전열→출차. P1 목적지 도착·정밀주차를 기다리지 않음.
- [x] 두 대 적재 종료 후 P1만 C 이동. P2는 B 주차자리에서 적재 상태로 대기.
- [x] C에서는 카메라 정밀주차·팔 작업을 호출하지 않고 `C 도착 · 하역 대기`로 유지. 완료 처리하지 않음.
- [ ] 실제 적재 성공과 연속 출차·경로 간섭은 전체 시험에서 확인.

## 최근 결과와 남은 작업 — 2026-10-29

- [x] 주문 1건·상품 6개 두 대 배차. 관제상 P1 C 도착 `WAIT_UNLOAD`, P2 B `WAIT_LOADED`.
- [x] A/P1 목표 재기록 후 사용자가 조정된 위치의 실물 적재를 적절하다고 확인했다. A/P2 목표도 P1 기준과 비교해 재기록했다. P2 실물 적재와 새 목표 자동 주차는 미확인이다.
- [x] B 집기 실패 후 B 자체 측정 20점으로 위치별 보간 적용. 사용자 현장 확인: 진라면 slot0·치토스 slot1·서울우유 slot2 성공.
- [x] B 성공 설정으로 hardware 경로 전환 및 B 터미널에서 실제 관제 코드 import 검증.
- [x] B 유선 랜선 재연결로 관제·P1·P2·C와 B 통신 복구.
- [ ] C 완료 후 관제 주문 실물 시험.
- [x] C에서 정밀주차가 실행되지 않은 원인 확인: `handoff_arrival_only=true` 설정으로 C 주차와 팔 작업을 호출하지 않았다. 카메라나 마커가 실패했다는 증거는 없다.
- [ ] 팀원의 C VLA 하역 작업 완료와 실행 경로 인계.
- [x] 기존 주문·로그 보존 후 C 도착 전용 제한을 해제한 새 v3 시험 DB 준비. 두 로봇 하역·완료는 모의 확인.
- [ ] C 준비 후 실제 정밀주차·하역 실행부·C worker 연결을 확인한다. 새 DB를 다시 만들면 도착 전용 설정이 돌아가므로 확인한다.
- [ ] C 작업 완료 후 주문 → 두 대 주행·실제 적재 → C 정밀주차·실제 하역 → 완료 시험과 녹화.

**아래는 이전 C 도착까지만 시험한 당시 명령이다. 다음 전체 시험을 위한 준비가 아니며, C 작업이 끝난 뒤 실행 경로·worker·완료 기준을 다시 정리한다.**

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

관제 서버는 이번 시험 전용 DB로 실행한다. A/B 재캘리나 직접 집기 프로그램은 종료한 상태여야 한다. **아래부터 새 관제 주문이 실제 장비 명령으로 실행된다.** 현재 worker 가동 상태는 실행 전 확인한다.

```bash
bash scripts/run_six_item_demo.sh start-workers
```

두 worker 모두 관제 노트북에서 실행한다. gateway-a는 Pinky 두 대와 A 원격 적재를, gateway-b는 B 원격 적재를 담당한다. B 노트북에서 별도 주문 worker를 중복 실행하지 않는다. C worker는 필요 없다.

## 3. 화면에서 주문 한 번

1. [고객 화면](http://192.168.0.11:8000/shop)에서 새 고객을 시작한다. 이전 시험 로그인은 새 실행에서 다시 로그인한다.
2. **쌀과자 3개 + B에 실제 준비한 상품 3개**를 한 번에 주문한다. 예: 진라면·신라면·치토스 각 1개. 예시는 이번 시험의 실물 성공을 보장하지 않는다.
3. `인계 요청`으로 주문을 마감한다. 두 대 적재가 끝나기 전에 눌러도 P1의 C 이동은 적재 완료 후에 시작한다.
4. [관리자 주문 화면](http://192.168.0.11:8000/admin/orders)에서 같은 고객 아래 로봇별 작업·슬롯을 확인한다.
5. 이 이전 시험 프로필은 P1 **C 도착·하역 대기**, P2 **B 적재 대기**에서 끝난다. C 정밀주차·하역을 실행하지 않으므로 다음 전체 시험의 완료 기준으로 사용하지 않는다.

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
