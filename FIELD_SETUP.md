# 관제 1대 + 중계 3대 현장 연결

## 현재 제공 범위

주문·재고·3개씩 다회 운반·좌우 목적지·하역 후 정지 확인·5채널 영상 화면을 구현했다. 기본 실행은 **MOCK**이다. 실물 실행부 코드는 준비했지만 아래 현장 입력값과 실제 장비 시험이 남아 있다. 테스트 통과를 실제 로봇 성공으로 해석하지 않는다.

| PC | 연결 장치 | 실행 |
|---|---|---|
| 관제 | 전체 맵 카메라 1대 | FastAPI·SQLite·웹, 전경 송신, 선택적으로 MediaMTX |
| 중계 A | 적재 A OMX·작업대 카메라 | YOLO 실행·영상 공유, 검증한 Pinky 어댑터 |
| 중계 B | 적재 B OMX·작업대 카메라 | YOLO 실행·영상 공유 |
| 중계 C | 인계 OMX·정면·그리퍼 카메라 | 로컬 ACT 추론·팔 제어·영상 공유 |

PC 4대는 같은 공유기에 유선 연결한다. Pinky 2대도 이 공유기의 내부망을 사용한다. 중앙의 실제 LAN IP를 `ip -4 addr`로 확인한다. 인터넷 연결 여부와 내부 통신은 별개다. ROS 2 도메인·네임스페이스·토픽·Nav2 인터페이스는 실제 주행 성공 설정을 확인해 사용한다. 이 저장소는 해당 이름을 추정해 만들지 않았다.

## 1. 우선 모의 실행

모든 PC에서 동일한 Git 버전을 받는다. 중앙은 Python 3.11~3.13 및 Node 24.12 이상 24.x/pnpm 11을 사용한다. 모의 중계는 CPU·Python으로 실행한다.

```bash
# 중앙 PC, 저장소 루트
bash scripts/setup_ubuntu.sh
pnpm --dir web build
.venv/bin/python scripts/prepare_distributed.py --server http://CENTRAL_LAN_IP:8000
```

`CENTRAL_LAN_IP`는 실제 주소로 바꾼다. 생성한 `runtime/distributed/central.env`는 중앙에만 보관한다. `gateway-a.env`, `gateway-b.env`, `gateway-c.env`는 해당 중계에만 전달한다. 인증 파일은 Git에 올리지 않는다.

```bash
# 중앙 PC
set -a; source runtime/distributed/central.env; set +a
.venv/bin/python -m uvicorn server.api:create_app --factory --host 0.0.0.0 --port 8000 --workers 1
```

```bash
# 각 중계 PC: A 예시. B/C는 파일과 node 이름을 바꾼다.
bash scripts/setup_gateway.sh
set -a; source runtime/distributed/gateway-a.env; set +a
.venv/bin/python -m robot_gateway.runtime --node gateway-a --server "$SHOP_SERVER_URL" --auto
```

고객: `http://CENTRAL_LAN_IP:8000/shop`, 관제: `/admin`. 관리자 토큰은 중앙의 `central.env`에서 확인한다. 두 고객은 별도 브라우저 세션을 사용한다.

재고 초기값은 A 9종 각 1개·B 라이스칩 8개다. 주문 접수 시 예약하고 확인된 적재만 선반 재고에서 차감한다. 4~6개 주문은 고객에게 배정된 Pinky 1대가 3개씩 운반한다. 처음 3개 적재 후 고객이 주문을 마감하면 남은 차수까지 자동으로 왕복한다. 각 인계 차수에서 해당 고객 장바구니 준비를 확인해야 한다.

새로고침·서버 재시작은 재고를 초기화하지 않는다. 구버전 DB는 기록을 보존하고 재고 확인 필요 상태로 막는다. 장비 없는 모의 시험에서는 관리자 ‘새 모의 실행’에서 이전 가상 실행 폐기를 명시적으로 확인하면 기록을 보관하고 17개로 시작한다. 이 동작은 실물 모드에서 사용할 수 없다.

```bash
# 중앙 PC: 자동 검증, 실제 장비 미사용
bash scripts/verify_ubuntu.sh
```

## 2. 실물 설정 준비 — 이 단계에서는 장비가 움직이지 않음

`config/hardware-yolo.example.json`을 A/B의 `runtime/hardware.json`으로, `config/hardware.example.json`을 C의 같은 경로로 복사해 현장 값을 입력한다. 예시 파일은 모두 `armed=false`, 미확인 값은 null이다.

- A/B: 현재 팔의 USB by-id, 카메라 by-id, 집기 설정·캘리·저장 자세 파일 경로를 입력한다. `drop_slots`에는 Pinky별 위치 0·1·2의 접근·놓기 자세 이름을 입력한다. 각각 다른 놓기 자세를 실제로 기록해야 한다. 접시 좌우는 재고 위치로 추가하지 않는다.
- C: 교체된 팔·정면·그리퍼 카메라의 by-id, 보정 디렉터리, 실제 대기 자세 6축 값과 허용 오차, 상대 목표 제한을 입력한다. 옛 `/dev/omx_follower` 별칭을 재사용하지 않는다.
- C 왼쪽: `act-left-v2-050000`, 180초 제한, `n_action_steps=100`. 오른쪽은 null로 두며 선정한 체크포인트를 검증한 뒤 별도로 등록한다. 왼쪽 모델로 오른쪽을 대체하지 않는다.
- A `mobile_factory`: 현장에서 성공한 Pinky 코드를 감싼 `모듈:팩토리함수`를 지정한다. 반환 객체는 `execute(command, cancelled)`를 제공하고 실제 결과만 반환해야 한다. NAVIGATE/LEAVE/STOP은 **프로젝트 내부 명령명**이며 ROS 명령명이 아니다. 정차·이탈·정지는 별도의 관측으로 확인한다. 현재 이 실제 어댑터는 미제공이다.

```bash
python scripts/prepare_yolo_model.py
python scripts/prepare_models.py download --model act-left-v2-050000 --root ~/omx_models
python -m robot_gateway.hardware.config --config runtime/hardware.json
```

준비 검사는 미설정 항목을 출력하고 종료 코드 2를 반환한다. 모터·카메라·CUDA를 열지 않는다. 필요한 값을 확인한 뒤에만 로컬 설정의 `armed`를 true로 바꾼다.

## 3. 장비별 Python 환경

중앙 FastAPI 환경과 ACT 환경을 억지로 합치지 않는다. A/B YOLO는 기존 Ubuntu 24.04·Python 3.12 환경을 우선 사용한다. 의존성 기록은 `robots/omx_yolo/requirements-transfer.txt`에 있다. 기존 동작 환경이 있으면 전체 패키지를 무조건 재설치하지 않는다.

C는 검증에 사용한 Python 3.10 LeRobot 환경에서 **저장소 루트로 이동해** `python -m robot_gateway.hardware.worker ...`를 실행한다. 이 경로는 중앙 FastAPI 패키지 설치를 요구하지 않는다. LeRobot 소스는 `integrations/sources.json`의 Hugging Face 저장소·커밋을 사용하고 `robots/omx_act/patches/omx-wrist-start-position.patch`를 적용한다. 기존에 패치했다면 중복 적용하지 않는다. 필요한 주요 패키지는 LeRobot·PyTorch·OpenCV이며 기존 CUDA 동작 환경을 유지한다. 최신 소스로 무조건 올리지 않는다.

ACT 추론은 로컬 `get_observation()`의 RGB 정면·그리퍼 프레임을 사용한다. 관제에서 돌아온 영상은 추론 입력으로 사용하지 않는다. 영상 공유는 프레임을 복사해 별도 전송 스레드로 넘기며 대기 프레임은 채널당 1개로 제한한다.

## 4. 관측 연결 — 현재 자동 판정기는 미구현

`robot_gateway/hardware/evidence.py`는 실제 센서/비전 실행부가 기록한 관측을 읽는 연결 지점이다. 그 자체가 빈 카트·물체 담기 판정기는 아니다. 현장 판정기 또는 명시적인 운영자 확인 도구가 아래 JSON을 임시 파일로 쓴 뒤 원자적으로 교체해야 한다. 관제에는 이 관측을 임의로 ‘성공’으로 만드는 버튼을 넣지 않았다.

파일: `evidence_directory/<command_id>.<kind>.json`. kind는 `stopped`, `exited`, `arm_clear`, `pick-0`/`pick-1`/`pick-2`, `handoff`, `stop`이다.

```json
{
  "run_id": "명령과 동일", "task_id": "명령과 동일",
  "session_id": "명령과 동일", "device_id": "명령과 동일",
  "observed_at": 0, "source": "vision", "data": {}
}
```

`observed_at`은 실제 관측 Unix 시각이며 예시의 0을 그대로 사용하면 거부된다. source는 vision/feedback/operator 중 실제 근거다. 2초 넘게 오래됐거나 다른 작업의 관측은 사용하지 않는다. PC 시계를 동기화한다. 실물 서버의 정차·바구니 준비 유효기간도 개발 초기값 2초다. 정차 판정기는 대기 중 최신 관측을 계속 갱신해야 하며 중계가 이를 반복 보고한다. 실제 정차 유지 조건과 허용 오차는 현장에서 검증한다.

- 정차: `stopped=true`, `zone_id`. 이탈: `outside=true`, `zone_id`.
- 적재 위치: `confirmed_items=[명령 items 중 실제 적재한 해당 항목]`. 항목의 SKU·slot·item_id를 그대로 대조한다.
- 하역: `confirmed_items`, `basket_id`, `cart_visible`, `cart_empty`, `last_item_placed`, `standby_reached`가 필요하다. 빈 카트만으로 완료할 수 없다. ACT는 대기 자세 피드백도 대조한다.
- 하역 근거 후 중앙이 STOP_POLICY를 보낸다. 실행부는 정책 출력 중지 후 관절 피드백의 안정·토크 유지를 확인하고 응답한다. 이 응답 전에는 하역 완료·Pinky 출발을 허용하지 않는다. 이후 `arm_clear={"clear":true}` 관측도 필요하다.
- 명령·결과·관측 식별자는 실제 중앙 응답에서 가져온다. 시간 만료·프로세스 종료로 성공 관측을 작성하면 안 된다.

## 5. 실제 실행 전환

중앙의 로컬 `runtime/hardware-readiness.json`에 검증한 상품 SKU·하역 방향을 적고 승인한다. 예시 파일은 `config/hardware-readiness.example.json`이다. 실제 재고 시작값이 준비됐는지도 확인한다.

```bash
# 중앙: 기존 모의 서버를 종료한 뒤 별도 DB로 실행
export SHOP_DEVICE_MODE=hardware
export SHOP_GATEWAY_MODE=distributed
export SHOP_DB=runtime/hardware/shopping.db
export SHOP_HARDWARE_READINESS=runtime/hardware-readiness.json
.venv/bin/python -m uvicorn server.api:create_app --factory --host 0.0.0.0 --port 8000 --workers 1

# 각 중계: 담당 인증 환경과 장비 Python 환경에서 실행
python -m robot_gateway.hardware.worker --config runtime/hardware.json --server "$SHOP_SERVER_URL" --execute
```

`--execute`와 `armed=true`가 함께 있어야 실물 실행 경로가 열린다. 모의 명령은 실제 실행부가 거부한다. 중계는 중앙 연결이 3초 이상 확인되지 않으면 새 정책/궤적 출력을 중단하도록 요청한다. 이 요청만으로 실제 정지를 보장하지 않으며 실제 정지 관측은 별도다. 이전 실물 작업·미전달 결과가 outbox에 남으면 자동 재실행하지 않는다.

## 6. 영상 연결

기본 `config/video.json`은 가상 영상 5개다. 관제의 정지 화면·끊김·복구 버튼으로 표시를 시험한다. 영상 표시만으로 작업 상태가 바뀌지 않는다.

간단한 실카메라 확인은 로컬 영상 설정의 transport를 `jpeg`로 바꾸고 `SHOP_VIDEO_CONFIG`에 그 경로를 지정한다. 이 경로는 640px·5FPS 기본 미리보기이며 추론 원본 해상도는 바꾸지 않는다. 전경 JPEG에는 별도 `SHOP_OVERVIEW_TOKEN`을 중앙 서버와 전경 송신기에 동일하게 제공한다.

최종 유선 영상은 H.264/RTSP → MediaMTX → WebRTC 경로를 준비했다. 설치·실제 스트림·브라우저 호환성은 현장 시험 대상이다.

```bash
# 중앙, 실제 IP로 변경
python scripts/prepare_media.py --host CENTRAL_LAN_IP --web-port 8000
# 현장에 준비한 MediaMTX 실행 파일 사용
mediamtx runtime/media/mediamtx.yml
export SHOP_VIDEO_CONFIG=runtime/media/video.json
```

생성된 `gateway-*.json`의 내용을 해당 중계 hardware.json의 `video`에 넣는다. 중앙의 `central.json`은 전경 송신용이다. 파일에 게시·조회 비밀번호가 있으므로 해당 PC에만 전달한다. 내부망에서 중앙 TCP 8000(웹/명령), 8554(RTSP), 8889(WHEP), UDP 8189(WebRTC)를 허용한다. 외부 포트포워딩은 필요 없다.

```bash
# 중앙 카메라 Python 환경
python -m robot_gateway.overview --device /dev/v4l/by-id/실제카메라 --media-config runtime/media/central.json
```

FFmpeg와 OpenCV가 필요하다. 프레임 전송은 별도 스레드이며 지연된 프레임을 쌓지 않는다. 현재 YOLO는 적재 실행 중, ACT는 추론 중에 공유 프레임을 제공한다. 대기 중에도 연속 영상을 제공하려면 카메라 수명주기를 현장에서 추가 검증해야 한다. 실제 5개 스트림으로 ACT 주기·인식 FPS·드롭·CPU/GPU·LAN 부하를 측정해야 한다. 화면의 ‘갱신 경과’는 마지막 수신/디코딩 후 경과 시간이며 카메라부터 화면까지의 지연 측정값이 아니다. 전체 맵 카메라의 좌표 정합과 디지털 트윈 위치 추정은 후속 검증 대상이다.

설정 근거: [MediaMTX WebRTC](https://mediamtx.org/docs/features/webrtc-specific-features), [인증](https://mediamtx.org/docs/features/authentication), [FFmpeg/OpenCV 게시](https://mediamtx.org/docs/publish/python-opencv). 설치한 버전의 설정 호환성을 확인한다.

## 7. 현장에 가져갈 확인 항목

1. 실제 Pinky 주행 코드·맵·정차/이탈 좌표·로봇별 식별값을 A 어댑터에 연결.
2. A/B의 각 Pinky 적재 위치 3곳과 현재 ACT 학습 배치의 호환성 확인.
3. 현재 USB by-id·카메라 구도·캘리·ACT 대기 자세와 정지 허용 오차 입력.
4. 적재·마지막 담기·빈 카트·팔 이탈 관측 생성부 연결. 현재 파일 수신부만 구현됨.
5. 왼쪽 단일 차수 → 왼쪽 두 차수 → 두 고객 공유 구역 → 오른쪽 선정 모델 순서로 시험.
6. 영상 전송 전후 ACT 주기와 중지 응답, 결과 유실/재시작/통신 끊김 시험.

코드 검증 결과는 로컬 `runtime/verification`과 Ubuntu 실행 후 `reports`에 남긴다. 실제 시험은 사용한 코드·모델·장치·배치·성공/실패 조건을 별도로 기록한다.

## 8. 장비 테스트 탭으로 OMX 단독 연결

관리자 → **장비 테스트**에서 중계 A/B/C를 선택한다. `통신 응답 확인`은 해당 중계가 직접 반환한 PONG과 코드 버전을 보여준다. `설정 검사`는 파일·장치 경로와 모델 설정을 검사한다. 경로 존재는 USB 통신·카메라 프레임·추론 성공을 뜻하지 않으며 이 항목들은 미확인으로 표시한다. 암호·토큰은 로그와 내려받는 JSON에 넣지 않는다.

기존 모의 중계 `robot_gateway.runtime`에는 시험 명령 수신이 포함되어 있다. 모의 시험도 주문과 분리된 기록이며, 적재·하역 시험 점유 중에는 새 주문을 제한한다. 중계별 시험은 하나씩 처리하고 같은 중계의 다음 시험은 이전 시험 확인·해제 후 보낸다. 다른 중계의 통신 검사는 계속 가능하다.

실물은 기존 OMX 실험 프로그램과 해당 중계의 운영용 worker를 종료하고 연결 만료(10초) 후 전환한다. 시험용과 운영용 프로그램이 같은 팔·카메라를 동시에 열면 안 된다. 실물 시험 worker는 운영용 worker와 같은 프로세스 잠금 파일을 사용하고 중앙에서도 같은 중계의 중복 실행을 거부한다.

```bash
# 중앙 PC: 기존 서버를 종료하고, 기존 중앙 인증 환경을 불러온 뒤 실행
set -a; source runtime/distributed/central.env; set +a
export SHOP_DEVICE_MODE=hardware
export SHOP_GATEWAY_MODE=distributed
export SHOP_TEST_ONLY=1
export SHOP_DB=runtime/hardware-tests/shopping.db
.venv/bin/python -m uvicorn server.api:create_app --factory --host 0.0.0.0 --port 8000 --workers 1
```

`SHOP_TEST_ONLY=1`은 일반 주문 실행을 막는다. 전체 시나리오의 Pinky/상품 검증 목록이 없어도 진단할 수 있지만 실물 동작의 `armed=true`와 `--execute`, 카메라·모델·자세 검사 조건은 유지한다. 기존 운영/모의 DB를 시험용으로 재사용하지 않는다.

```bash
# 중계 A: 해당 장비의 기존 Python 환경, 저장소 루트
# B/C는 node 이름과 인증 파일을 각각 바꾼다.
set -a; source runtime/distributed/gateway-a.env; set +a
python -m robot_gateway.test_runtime --node gateway-a --mode hardware \
  --server "$SHOP_SERVER_URL" --config runtime/hardware.json
```

위 명령은 장비를 열지 않고 통신·설정 검사만 제공한다. 모델·장치 설정이 없어도 누락 사유를 관제에서 볼 수 있다. 이 단계에선 `armed=false`를 유지해도 된다. 실제 동작 시험 준비 후 로컬 설정의 `armed=true`와 다음 옵션을 함께 사용한다.

```bash
# 같은 프로그램의 진단 실행을 종료하고 재실행
python -m robot_gateway.test_runtime --node gateway-a --mode hardware \
  --server "$SHOP_SERVER_URL" --config runtime/hardware.json --execute
```

- A/B 적재: 선택한 Pinky 배치·슬롯 한 곳의 접근/놓기 자세부터 등록할 수 있다. 미등록 슬롯은 실행할 수 없다. 운영용 worker의 Pinky 어댑터·전체 3슬롯 검사는 그대로 유지된다. 시험은 상품 1개씩이며 고객 재고를 차감하지 않는다.
- C 하역: 기존 Python 3.10 ACT 환경에서 실행한다. 좌/우 모델 선택은 등록된 방향만 가능하다. 원래 카메라 입력·180초 제한·`n_action_steps=100`을 유지한다.
- 하역 실행 중 마지막 담기·빈 카트·카트 시야·대기 자세를 실제로 확인한 뒤 관제에서 운영자 관측을 전달한다. 이는 자동 판정기가 아니다. 관측은 2초 이내 사용되며 실행부가 실제 대기 자세를 대조하고 정책 출력 종료·관절 정지·토크 유지 피드백을 확인한다. 관측이 만료됐으면 현재 상태를 재확인한 뒤 다시 전달한다.
- YOLO 시험의 궤적 종료는 적재 성공 또는 실제 정지를 뜻하지 않는다. 화면은 결과 확인 대기 상태에 머무르며 운영자가 실제 상품 위치·정지를 확인하고 이름·메모를 남겨야 한다. 시험 외 주문 흐름의 실제 적재 관측 조건은 바꾸지 않는다.
- `중지 요청` 버튼은 소프트웨어 요청이다. 수신과 실제 정지를 별도 표시한다. ACT는 정지 피드백을, YOLO 시험은 운영자 실제 정지 확인을 사용한다. 일반 운영 작업을 중단하는 전체 비상정지 화면은 아니다.
- 결과 확인 후 상품을 초기 수량·원위치로 되돌리고 작업 구역을 확인한 다음 **시험 점유 해제**를 누른다. 이 확인 전에는 주문을 재개하지 않는다. 시험 기록으로 재고를 자동 조정하지 않는다.
- 끊김·시간 초과·재시작은 성공으로 처리하지 않고 점유를 유지한다. 실행 종료 보고가 없다면 원래 실행부 종료·실제 정지를 확인한 뒤, 해당 실행의 연결 만료 또는 새 실행부 연결을 확인하고 실패 복구 기록을 남긴다. 재시작한 실행부는 이전 outbox를 자동 실행하지 않으며 관제에서 이전 시험 확인·해제가 완료되면 보존 기록을 정리한다.

선택한 시험의 **시험 로그 JSON 저장**으로 명령·응답·시각·운영자 확인을 공유할 수 있다. 시각은 중앙 수신 기준이며 전송→수락 소요 시간에는 중계 폴링 대기도 포함된다. 네트워크 지연만을 측정한 값이 아니다. 모의 로그에는 MOCK/simulation 표식이 남는다.

```bash
# 장비 없는 별도 프로세스 통합 검증
.venv/bin/python scripts/demo_device_tests.py
```

운영 복귀 시 시험을 해제하고 시험 worker/서버를 종료한다. `unset SHOP_TEST_ONLY` 후 기존 운영용 DB·현장 검증 설정을 사용해 서버와 운영용 worker를 다시 실행한다. 실제 물리 장비·우분투 4대·영상 부하는 현장 시험 대상이다.
