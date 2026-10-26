# OMX3 VLA 시연 준비

2026-10-23 현재 작업 정의:

- 핑키 트레이의 **모든 상품**을 한 개씩 옮긴다. SKU별 선택은 하지 않는다.
- 관제가 목적지 `basket_id`를 지정한다. **0 = OMX2 가까운 바구니, 1 = OMX2에서 먼 바구니**다.
- `Move all items from the Pinky tray into basket 0.` / `... basket 1.` 두 문장을 사용한다.
- 한 시연은 상품 하나 투입 후 관측 대기 자세로 복귀하는 구간이다. 트레이에 여러 개가
  있는 배치와 마지막 하나를 옮기는 배치를 모두 수집한다. 전체 반복·빈 트레이 판정은
  향후 실행기의 역할이며, 이번 수집 도구에는 자동 하역·완료 판정이 구현되지 않았다.
- 학습 모델은 SmolVLA. 기존 ACT/좌우/핑키별 고정 목적지 문서는 이전 설계다.

## 준비된 환경

작업 폴더 `/home/team2/robot_shopping`, Python `/home/team2/venv/il/bin/python`을 사용한다.
기존 패키지는 `reports/environment-before.txt`의 버전을 유지하고 SmolVLA 추가 의존성만 설치했다.
데이터셋 읽기 캐시는 작업 폴더의 `.cache/huggingface/datasets`에 생성한다.
로컬 LeRobot 소스는 `/home/team2/il_ws/src/lerobot`이며 수정하지 않는다.
`reports/environment.json`은 코드 import와 GPU 연산 결과다. 사전학습 가중치 로딩이나
실제 VLA 추론 성공을 의미하지 않는다. 가중치 다운로드와 학습은 시연 확보 후 진행한다.

```bash
cd /home/team2/robot_shopping
./scripts/omx-vla doctor
./scripts/omx-vla probe
./scripts/omx-vla capture
```

`probe`는 1Mbps에서 모터 PING만 전송한다. 모터 설정·토크·위치를 쓰지 않는다.
팔로워 ID 11~16, 리더 ID 1~6 응답으로 역할을 식별했다. 숫자 포트는 바뀔 수 있어
`configs/omx_vla.json`은 `/dev/serial/by-id`, `/dev/v4l/by-id` 고유 경로를 사용한다.
기존 udev 별칭은 다른 장치의 일련번호를 가리키므로 이 도구에서 사용하지 않는다.

## 시연 전 현장에서 확인할 것

1. `capture` 결과의 `front.jpg`에서 핑키 트레이와 바구니 번호·투입 지점이 보여야 한다.
2. `wrist.jpg`에서 집게와 집을 상품이 보여야 한다. 실제 손목 카메라 위치를 조정한 뒤
   `configs/omx_vla.json`의 해당 `view_confirmed`를 `true`로 변경한다.
   이름 `wrist`만 지정했다고 실제 장착 위치가 검증된 것은 아니다.
   2026-10-23 캡처에서는 전체 카메라 약 30FPS, 근접 카메라 약 21FPS가 측정됐다.
   집기 자세·조명을 맞춘 뒤 속도를 다시 확인하고, 30FPS가 유지되지 않으면 지원되는
   공통 FPS로 카메라 및 기록 설정을 낮춘 뒤 새 데이터셋에서 시작한다.
3. ffplay 등 카메라를 점유한 미리보기는 닫는다. 수집 중에는 Rerun 미리보기를 사용한다.
4. 트레이에서 각 바구니까지 충돌 없이 이동할 수 있는지 확인한다. 처음은 상품 한 개로 시작한다.
5. 팔을 지지하고 리더·팔로워 자세와 그리퍼를 맞춘다. 초기 자세 차이가 크면 기록을 시작하지 않는다.

보정 JSON은 기존 파일의 복사본이다. 연결 전에 모터의 현재 보정값과 비교하며,
다르면 자동 보정/덮어쓰기를 하지 않고 중단한다. `record --run`은 모터를 실제로 연결하고
모드·PID·토크를 설정한다. 팔로워는 모든 관절의 현재 위치를 목표로 넣은 후 토크를 켠다.
리더 그리퍼는 기존 LeRobot 설정대로 움직일 수 있다.
명령 제한 5.0은 **LeRobot 정규화 위치 단위**이며 각도 5도 또는 속도 제한이 아니다.
관절 범위·물리 충돌을 보장하는 기능은 아니다.

## 기록

`--run`이 없으면 설정과 계획만 출력하며, 장치에 접속하지 않는다.

```bash
./scripts/omx-vla record --basket 0 --session day01_setupA --episodes 5
# 실제 기록: 작업자가 준비된 상태에서 터미널에서 실행
./scripts/omx-vla record --basket 0 --session day01_setupA --episodes 5 --run
# 같은 데이터셋에 바구니 1 시연 추가
./scripts/omx-vla record --basket 1 --session day01_setupA --episodes 5 --resume --run
```

- 처음에는 바구니별 5회로 기록 경로를 점검하고, 이상 없으면 각 30회 수준으로 늘린다.
- 전체 명령은 유지하되, 한 에피소드에는 한 상품을 옮기고 팔이 복귀하는 동작을 담는다.
- `Enter`: 다음 에피소드 시작. `→`: 현재 에피소드 종료. `←`: 폐기. `Esc`: 폐기 후 전체 종료.
- 종료 후 상품 투입과 팔 복귀를 확인하고 `y`를 입력한 시연만 저장한다. 실패는 `n`으로 폐기한다.
- 카메라가 오래된 프레임을 반환하거나 제어 주기가 크게 지연되면 중단하고 해당 시연을 폐기한다.
- 저장·배치 재설정 중에는 리더를 따라 움직이지 않는다. 다음 기록 전에 리더 자세를 다시 맞춘다.
- 중단/종료 시 팔로워의 토크를 유지한다. 자동 복귀나 비상정지는 아니다. 팔을 지지한 뒤 현장 절차로 종료한다.
- Ctrl+C나 비정상 종료로 리뷰가 없는 에피소드가 남으면 검증 도구가 실패 처리한다.

데이터는 `datasets/omx3_pinky_all`에 LeRobot v3 형식으로 저장한다. Hub 업로드 코드는 없다.
관측은 `observation.images.front`, `observation.images.wrist`, `observation.state`이며
행동은 `action`이다. 팔 5관절과 그리퍼의 순서는 설정 계약에 저장된다.
`action`에는 제한 적용 후 `send_action()`이 반환한 목표를 저장한다.
카메라 두 대는 하드웨어 동기화되지 않으며 같은 제어 주기의 최신 프레임을 사용한다.
LeRobot 타임스탬프는 고정 FPS 인덱스이며 실제 주기 측정값은 리뷰 메타데이터에 별도 저장한다.

`meta/omx_contract.json`: 카메라·단위·관절 순서·보정 파일 해시·작업 문장.
`meta/omx_reviews.jsonl`: 에피소드별 바구니·세션·사람의 성공 확인·실제 수집 시간.
재개할 때 설정 계약이 달라지면 거부한다. 카메라 위치 등 시각 조건을 바꿨다면
새 `--session` 이름을 사용하고, 입력 구조/보정이 바뀌면 새 `--root`를 사용한다.

## 데이터 검증과 영상 검토

```bash
./scripts/omx-vla validate
./scripts/omx-vla validate --require-both
./scripts/omx-vla review --episode 0
```

검증은 관절 차원·순서, 유한값, 프레임 번호·시간, 작업 문장·목적지·리뷰 일치,
각 에피소드의 처음/중간/마지막 프레임을 양쪽 영상에서 디코딩할 수 있는지 확인한다.
모든 영상 프레임이나 물리적 성공을 자동 인증하지 않는다. `review`는 Rerun에서
영상·상태·명령을 보여 주며 로봇을 움직이는 `lerobot-replay`와 다르다.

학습 전에는 양쪽 바구니 데이터와 여러 수집 세션을 확보하고, 같은 세션이 학습·평가에
섞이지 않게 분리한다. 여러 상품→마지막 상품→빈 트레이 상태도 실제 영상으로 검토한다.
학습 실행·자동 집기·트레이 비움 판정·관제 연결은 후속 작업이다.

## 검증 명령

```bash
/home/team2/venv/il/bin/python -m unittest discover -s tests -v
```

테스트는 임시 폴더의 합성 영상과 가짜 장치를 사용한다. 실제 모터를 구동하지 않는다.
실제 시연 데이터가 없는 상태에서 테스트 통과를 VLA 학습/하역 성공으로 해석하지 않는다.
