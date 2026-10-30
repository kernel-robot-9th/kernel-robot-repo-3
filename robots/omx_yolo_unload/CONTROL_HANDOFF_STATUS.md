# C YOLO → 관제 주문 연결

2026-10-30 · C 최신 코드·관제 설정 연결 및 서버·중계 기동 완료 / 실물 전체 주문 시험 미실시

## 지금 상태

- [x] 관제 `HANDOFF`에 고객 바구니·좌우·로봇·주문 항목 유지.
- [x] C YOLO 실행 종료 → `WAIT_UNLOAD_REVIEW` → **전체 상품 실제 하역 확인 · 복귀** 연결.
- [x] 검출·시도 횟수를 주문 item_id/slot에 대입하지 않음. 작업자가 확인한 현재 HANDOFF 항목만 배송 확인 처리.
- [x] 미검출 종료 후보와 최대 시도 도달 결과를 보존하고 화면에 표시. 시도 기록은 배송 실적과 별개.
- [x] 테스트 화면의 C 로봇 선택·YOLO 결과 확인 지원. 기존 ACT 확인 절차 유지.
- [x] C 하역·설정 검사 Python은 `c-yolo-venv`, 주차 Python은 기존 환경 유지. 하역/검사는 PYTHONPATH·PYTHONHOME을 해제해 실행.
- [x] 현재 시연에 `worker-c.json`, `unload_engine=yolo`, `handoff_arrival_only=false` 저장. 기존 DB·실행 저널·outbox 보존.
- [x] C 최신 미커밋 하역 소스를 비교·수신. 기존 Pinky 관련 로컬 수정은 별도 보존.
- [x] 재부팅 후 C 하역 CLI 미실행 확인. `activate`로 실제 `gateway-c.hardware.json`에 YOLO 연결, 기존 ACT 설정·백업 보존.
- [x] 서버·A/B/C worker 기동, 관리자 API 확인. C 응답: online=true, allow_motion=true, unload_engine=yolo, issues=[]. 주문·동작 명령은 보내지 않음.
- [ ] P1 전체 주문·실물 하역·확인·복귀 시험.
- [ ] P2 하역 현장 확인 후 6개 한 주문·두 대 시연 및 녹화.

C SSH 재연결 후 최신 파일과 활성화 결과를 확인했다. C 실행 Python은 `runtime/field/c-yolo-venv/bin/python`. 운영 confidence=0.5, all 모드·max_picks=12, P1 네 품목 각 5점/P2 0점 확인. 설정 활성화 전 백업은 `runtime/field/gateway-c.hardware.json.20261030-142952-872685.bak`. 관제 소스 수신·이전 코드 백업은 `runtime/field/c-integration-20261030-142921/`. 현재 DB에는 고객 세션 2개, task·command 0개이며 초기화하지 않았다.

## 현장 인계 기준 — 설정·파일 원격 확인 완료

- C의 단독 하역 성공은 사용자 확인. 이후 추가 보간 완료, 전체 조합 재시험은 아님.
- C 전용 4클래스 순서: `shin_ramen, jin_ramen, rice_chip, cheetos`.
- 운영 모델: `runtime/field/c-yolo/training_4class_20261030/prepared_models/best_original.pt`, confidence 0.5. A/B 공용 모델을 바꾸지 않음.
- `selection_mode=all`, `max_picks=12`, fixed 손목, from_folded false.
- 같은 높이의 바구니 **3개**로 캘리 완료. 현재 넓힌 ROI·기본 캘리·자세 보존.
- P1: 4품목 각각 보간 5점. 신라면→진라면, 쌀과자→치토스 공유. P2 보간 미기록, 자동 복사 금지.
- `attempted_items`는 궤적 시도, `executed_items=[]`. `stop_reason=no_detections_rechecked`와 `empty_scene_candidate=true`는 비움 후보, `pick_limit_reached`는 최대 횟수 도달.
- 새 실행 저널은 `awaiting_operator_review`, 실제 배송 확정 아님.
- 기존 `C_CODEX_HANDOFF.md`는 초기 준비 설명. 최신 현장 상태는 이 문서와 C 실제 파일을 우선한다.

## 실행 흐름

`주문 → A/B 적재 → C 이동·정밀주차 → C YOLO 하역 → 실물 확인 대기 → 작업자 확인 → 해당 로봇 상품 인계 기록 → 대기 복귀`

관제 이동 화면의 **전체 상품 실제 하역 확인 · 복귀**는 해당 로봇의 이번 운반 상품을 모두 지정한 좌우 수령 바구니에 놓았다는 확인이다. 남은 상품이 있으면 누르지 않고 현장 상태를 정리한다. 실행 실패·진행 중 명령은 이 버튼으로 성공 처리하지 않는다. 확인을 반복해도 복귀 명령을 중복 생성하지 않는다.

3회 미검출이나 12회 시도를 성공 판정으로 쓰지 않는다. 실행 원본 결과는 그대로 남기며 사용자 확인은 별도 관측 기록이다. C 로컬 저널은 원격 실행 근거로 보존하고, 관제 확인으로 로컬 저널을 임의 변경하지 않는다.

## 다음 연결 작업 — 한 실행 단위씩

### C 노트북: 현재 CLI 종료·장치 사용 상태 확인 후

현재 소스 diff와 현장 파일을 먼저 백업한다. 관제의 이전 C 코드를 덮어 배포하지 않는다.

```bash
cd /home/team2/robot_shopping/kernel-robot-repo-3
env -u PYTHONPATH -u PYTHONHOME ./runtime/field/c-yolo-venv/bin/python -B -m robots.omx_yolo_unload activate
```

기존 ACT 설정과 `gateway-c.hardware.json` 백업을 보존한다. `activate`만으로 worker가 기동되지는 않는다.

### 관제: 설정 재준비가 필요할 때만

현재 선택된 시연 폴더에는 이미 적용했다. 다른 시연 폴더를 새로 준비했을 때 사용:

```bash
cd /home/noma/dev_ws/kernel-robot-repo-3
bash scripts/run_six_item_demo.sh configure-c
```

이 명령은 기존 시연 DB를 초기화하지 않으며 C 연결 설정과 worker 파일만 백업·갱신한다.

### 관제: C 최신 코드·활성화와 기존 작업 상태 확인 후

```bash
cd /home/noma/dev_ws/kernel-robot-repo-3
bash scripts/run_six_item_demo.sh server
```

별도 터미널에서 필요한 worker를 기동한다. 기존 미완료 작업이 있으면 먼저 상태를 확인한다. worker 기동은 기존 주문을 실행할 수 있다.

```bash
cd /home/noma/dev_ws/kernel-robot-repo-3
bash scripts/run_six_item_demo.sh start-workers
```

처음에는 P1으로 C 지원 품목 주문 1건을 진행하고 화면에서 실제 하역 확인 후 복귀까지 본다. 이후 P2를 확인하고 한 주문에 쌀과자 3개+A/B 배치에 맞춘 나머지 3개를 주문해 두 대 전체 흐름을 확인한다. 전열/후열 실제 배치·전체 카메라·Nav2는 시험 직전에 확인한다.

## 검증 범위

오프라인으로 빈 검출 후보/최대 횟수 종료에서 이탈 보류, 사용자 확인 후 1회 복귀, 6개 주문의 로봇별 인계 분리, 실패 시 배송 미기록, YOLO 테스트 확인, C 설정 백업·DB 보존·주차 Python 유지 등을 검증했다. ROS·카메라·모터를 사용한 현장 성공을 의미하지 않는다.

검증: C 실행기 단위시험 20개(system Python의 OpenCV·NumPy 사용), 관제·중계·6개 주문 관련 18개 통과. 웹 타입 검사·배포 빌드 성공. 관제 기본 venv에는 OpenCV/NumPy가 없으므로 C 캘리 도구 시험은 system Python으로 분리했다.
