# C YOLO 하역 — 전달·현장 기록·시험 명령

관제 연결 최신 상태·확인 후 복귀 절차: [CONTROL_HANDOFF_STATUS.md](CONTROL_HANDOFF_STATUS.md).

2026-10-30 · C 현장 기록·단독 시험 및 관제 연결 완료. **아래 init·캘리 절차는 최초 준비용이며 현재 현장 설정을 다시 만들지 않는다.**
아래 장비 명령은 C 노트북의 그래픽 데스크톱 터미널에서 사용한다.

## 1. 코드 전달

C에서 Git 작업 상태를 확인하고 준비 브랜치를 받는다. 로컬 변경이 있으면 먼저 백업·병합한다.

```bash
cd /home/team2/robot_shopping/kernel-robot-repo-3
git status --short --branch
git fetch origin
# 로컬 변경이 없고 처음 받는 경우:
git switch --track origin/codex/c-yolo-unload-20261030
# 이미 이 브랜치에서 작업 중인 경우:
# git pull --ff-only origin codex/c-yolo-unload-20261030
```

C Codex 복붙 인계: [C_CODEX_HANDOFF.md](C_CODEX_HANDOFF.md).
모델 가중치·가상환경·현장 JSON·캘리·자세는 Git 수신만으로 준비되지 않는다.
Git을 사용할 수 없는 경우 `scripts/package_c_yolo.py`로 소스 패키지를 만들 수 있다.

## 2. Python·장치·초기 설정

기존 C 가상환경에서 필요한 모듈을 읽을 수 있으면 그 환경을 사용한다. 먼저 확인:

```bash
C_PY=/home/team2/robot_shopping/kernel-robot-repo-3/runtime/field/c-yolo-venv/bin/python
env -u PYTHONPATH -u PYTHONHOME "$C_PY" -c 'import cv2, numpy, ultralytics, dynamixel_sdk, tkinter; print("C YOLO 의존성 준비됨")'
ls -l /dev/serial/by-id/ /dev/v4l/by-id/
ls -l runtime/field/c-yolo/training_4class_20261030/prepared_models/best_original.pt
```

의존성이 없으면 기존 ACT/VLA 환경을 변경하지 않고 별도 환경을 준비한다. 필요할 때만:

```bash
python3 -m venv runtime/field/c-yolo-venv
C_PY="$PWD/runtime/field/c-yolo-venv/bin/python"
"$C_PY" -m pip install -r robots/omx_yolo/requirements-pick.txt
```

`tkinter`가 없으면 C 노트북의 `python3-tk` 설치가 필요하다. 현재 모델은 C 전용 4품목 `best_original.pt`다. A/B 모델로 교체하지 않으며 실제 모델 경로는 hardware의 weights를 확인한다.

실제 장치 경로 입력 후 C 설정을 최초 한 번 생성한다:

```bash
read -r -p 'C OpenRB /dev/serial/by-id 경로: ' C_SERIAL
read -r -p 'C 상단 카메라 /dev/v4l/by-id 경로: ' C_CAMERA
env -u PYTHONPATH -u PYTHONHOME "$C_PY" -B -m robots.omx_yolo_unload init \
  --serial "$C_SERIAL" --camera "$C_CAMERA" --width 1920 --height 1080

c() { env -u PYTHONPATH -u PYTHONHOME "$C_PY" -B -m robots.omx_yolo_unload "$@"; }
c status
```

새 터미널에서는 프로젝트로 이동하고 `C_PY` 및 `c()`를 다시 설정한다.
최초 `status`의 미기록 항목은 정상이다. C 전용 파일은 `runtime/field/c-yolo/`에만 생성된다.
현장 설정을 다시 `init`하지 않는다. A/B 값이나 A의 모터 보정은 복사하지 않는다.

## 3. 팔 조절·자세 기록

- `jog`: 현재 자세에서 WASD=XY, R/F=Z, Enter=종료, Q=취소. 고정 손목 방식.
- `pose`: 현재 모터 자세 읽기 → Enter 저장. 재기록 시 기존 파일 자동 백업.
- 손으로 옮기려면 팔을 받친 상태에서 `c move -- --torque-off` 실행 후 기록한다. 이 명령은 실제 토크를 해제한다.
- `wait`는 접힌 보관 자세가 아니라 상품을 들고 통과할 수 있는 작업 대기 자세로 기록한다.

각 이름에 맞게 팔을 조정한 후 **하나씩** 실행:

```bash
c jog
c pose wait
```

```bash
c jog
c pose pickup_approach
```

```bash
c jog
c pose drop_left_approach
```

```bash
c jog
c pose drop_left_release
```

```bash
c jog
c pose drop_right_approach
```

```bash
c jog
c pose drop_right_release
```

저장 이름 조회 / 대기 자세로 실제 이동:

```bash
c move -- --list
c move wait --seconds 6
```

그리퍼를 사용할 열림 폭에 두고 `open`, 잡는 폭에 두고 `close`를 각각 기록한다:

```bash
c gripper --record open
c gripper --record close
c gripper --read-current
```

`--read-current`는 현재 Goal Current를 읽는다. 값이 0이면 C에서 확인한 값을 `c gripper --current 실제값`으로 입력한다. 그리퍼 설정을 읽는 명령은 모터에 새 목표를 쓰지 않는다.

## 4. 넓은 한 평면 캘리

두 Pinky 바구니를 나란히 두어 영역을 넓히고, **같은 높이의 기준점**을 분산한다. 캘리 영역과 실제 집기 영역은 별개다. 테두리 윗면과 바닥을 섞지 않는다.

점마다 영상 클릭 → 팔 정렬 → `READ` → `SAVE`는 기존 캘리 도구와 같다.
처음부터 가장자리·중앙에 고르게 기록하며, 아래 이름은 위치를 구분하기 위한 이름이다.

```bash
c calibrate collect --point-name p1
c calibrate collect --point-name p2
c calibrate collect --point-name p3
c calibrate collect --point-name p4
c calibrate collect --point-name p5
c calibrate collect --point-name p6
c calibrate collect --point-name p7
c calibrate collect --point-name p8
c calibrate collect --point-name p9
c calibrate fit --layout single-plane
```

이미 수집한 점으로 재계산할 때는 `c calibrate fit --layout single-plane --overwrite`. 기존 캘리 파일은 백업된다. 같은 이름의 측정점을 다시 수집하려면 CSV에서 해당 행을 확인·정리하거나 새 측정 파일을 지정한 별도 설정을 사용한다.
오차 출력은 참고값이며 새 수치 기준으로 실행을 차단하지 않는다.

## 5. 실제 바구니 영역·상품 높이

캘리용 두 대 배치를 해제한다. P1을 실제 C 주차 위치에 두고 바구니 한 개의 내부 모서리를 순서대로 클릭한 뒤 Enter:

```bash
c region --robot P1
c detect --robot P1
```

P2도 실제 주차 위치에서:

```bash
c region --robot P2
c detect --robot P2
```

노란 선이 실제 집기 영역이다. `detect`는 이 ROI를 잘라 추론하고 원본 좌표로 복원한 검출만 보여주며 팔은 움직이지 않는다. 기본 confidence 0.30 이상인 박스가 초록색으로 표시된다. 실제 적용값은 시작 로그에 나온다. Q 종료.
`preview`와 `adjust --class`는 보간 기록을 다른 품목에 섞지 않도록 지정 클래스 필터를 유지한다.

그리퍼를 실제 상품 접촉 높이에 맞춘 뒤 높이를 읽어 저장한다. 사용할 상품마다 실행하며, 예:

```bash
c product --class rice_chip --read-height
c product --class jin_ramen --read-height
```

상품의 모델 좌표 Z를 이미 알고 있으면 `--read-height` 대신 `--z 값` 사용.
설정 기본값은 팔 이동 6초, 그리퍼 0.8초, 손목 고정이다. 집기 Z·그리퍼 값은 예시값으로 채우지 않는다.

## 6. 낮은 호버·키보드 보정·보간

먼저 카메라와 IK만 사용해 계획 확인(모터 연결 없음):

```bash
c preview --robot P1 --class rice_chip --side left
```

실제 바구니의 서로 다른 위치에 시험 상품을 한 개씩 둔다. 아래 명령은 **자동으로 열린 그리퍼를 상품 위 낮은 호버까지 이동**한다. 이후 WASD/RF로 실제 집기 중심·접촉 Z에 맞추고 Enter 저장한다. 집기·하역은 하지 않는다.

```bash
c adjust --robot P1 --class rice_chip --name front_left
c adjust --robot P1 --class rice_chip --name front_right
c adjust --robot P1 --class rice_chip --name back_left
c adjust --robot P1 --class rice_chip --name back_right
c adjust --robot P1 --class rice_chip --name center
c fit-spatial --robot P1 --class rice_chip
```

- 초기 호버 기본 5mm, `--hover-mm`으로 조정. Enter 전 그리퍼를 **실제 접촉 높이**에 맞춘다.
- 동일 상품이 여러 개 보이면 `--index 0/1/...`으로 선택한다. 처음에는 시험 상품 한 개가 편하다.
- 같은 점 이름을 재기록하면 가장 최근 값을 보간에 사용한다.
- P2 보간은 필요 시 `--robot P2`로 별도 기록. A/B 또는 P1 보정을 P2에 자동 복사하지 않는다.
- 기본 캘리 좌표·고정 XY 오프셋과 직접 맞춘 최종 XYZ를 기록해 기존 보간을 중복 가산하지 않는다.
- 범위 밖은 가장 가까운 경계 보정값을 사용한다. 그 구간의 실제 정확도는 별도 확인 대상이다.

## C 상단 카메라 학습 사진 수집

기존 검출 창을 Q로 종료한 뒤 아래를 실행한다. YOLO 추론이나 모터 연결 없이 카메라만 사용한다.

```bash
cd /home/team2/robot_shopping/kernel-robot-repo-3 && \
env -u PYTHONPATH -u PYTHONHOME \
./runtime/field/c-yolo-venv/bin/python -B -m robots.omx_yolo_unload.capture_dataset
```

- Enter: 현재 원본 1920×1080 사진 저장. 미리보기의 ROI·안내 글씨는 사진에 포함하지 않는다.
- 1 라이스칩 / 2 신라면 / 3 진라면 / 4 새우깡 / 5 치토스 / 6 서울우유.
- 8 혼합 배치 / 0 빈 바구니 / V 학습(train)·검증(val) 전환 / Q 또는 Esc 종료.
- 미리보기 창에 초점을 두고 키를 누른다. 터미널 Enter도 저장한다. 터미널에서는 숫자 또는 V 입력 후 Enter로 전환한다.
- 첫 수집 제안: 최종 선택한 4품목 각각 train 60장 + val 20장, 혼합 train 45장 + val 15장, 빈 바구니 train 15장 + val 5장. 총 400장으로 시작하며 성능을 보장하는 수량은 아니다.
- 위치·각도를 바꾼 후 손을 빼고 저장한다. 검증 사진은 학습 사진과 같은 배치를 연속 촬영하지 말고 새로 배치한다. 실제 집을 때의 배치·높이·조명·일부 겹침을 포함한다.
- 저장 위치: `runtime/field/c-yolo/dataset_capture/날짜-시간-세션/images/train또는val/품목/`. 실행마다 새 세션을 만들고 기존 사진은 보존한다. `captures.jsonl`에 사진별 기록, `summary.json`에 장수가 남는다.
- 폴더명은 촬영 분류 힌트이며 정답 박스 라벨이 아니다. 저장 사진의 상품 박스를 라벨링하고 최종 4품목을 확정한 뒤 학습용 데이터셋을 만든다. 혼합 사진은 모든 대상 상품에 각각 박스를 그린다. 이 도구는 `.pt` 학습을 실행하지 않는다.
- 원본을 보관하며, 학습 준비 시 기록된 ROI/여백과 실제 추론 입력을 맞출 수 있다. 원본 좌표에서 만든 박스를 잘라낸 영상에 그대로 사용하지 않는다.
- 새 4품목 모델 연결 시 기존 실행기의 10품목 라벨 일치 검사도 함께 조정해야 한다. 촬영 도구 추가만으로 새 모델 연결이 완료되지는 않는다.

## 7. 한 개 → 세 개 하역

아래 `--execute`가 있어야 실물 팔이 동작한다. 생략하면 보낼 명령만 출력한다.
`--side`는 **주문 고객의 수령 바구니**다. P1/P2 번호로 다시 결정하지 않는다.

```bash
c run --robot P1 --side left --selection all --max-picks 1 --execute
```

```bash
c run --robot P1 --side right --selection all --max-picks 1 --execute
```

한 개 실물 성공 후 여러 개를 놓고 ROI 하역 (기본 상한 12궤적):

```bash
c run --robot P1 --side left --selection all --execute
```

출력의 `job-id`와 `result_file`을 보관한다. all 모드는 주문 SKU를 골라내지 않으며, 매 궤적 뒤 새 영상에서 남은 검출을 선택한다. 같은 ID 재실행도 현재 영상을 다시 확인한다:

```bash
c run --robot P1 --side left --selection all \
  --job-id 앞서출력된ID --execute
```

연속 3회 미검출은 `no_detections_rechecked`, 궤적 상한 도달은 `pick_limit_reached`다. 둘 다 운영자가 남은 물체와 수령 바구니를 확인해야 한다. `attempted_items`는 완료된 궤적 기록이며 실물 성공이나 주문 SKU 완료가 아니다. 모델이 못 보는 물체까지 빈 바구니로 판정하지 않는다.
기존 SKU 지정 방식은 `--selection ordered --skus SKU-RICE-CHIP ...`로 사용한다. 이 모드만 같은 ID 재실행 시 완료된 주문 항목을 제외한다.
Ctrl+C는 취소를 전달하며 팔은 현재 위치 유지 처리를 한다. 완료 기록은 `runs/`의 JSON에 남는다.

## 8. 관제 연결 — 단독 실물 성공 후

C에서 기록한 설정을 기존 관제 파일에 병합한다. ACT 설정은 보존한다:

```bash
c activate
```

이후 관제에서 연결할 항목:

- C 실행 Python을 실제 사용한 `C_PY`로 `runtime/field/pinky-control.json`의 `stations.C.python`에 지정. `parking_python`은 정밀주차용으로 유지.
- C worker를 현재 방식(현장 실행 또는 관제 RemoteArm)으로 기동할 준비. 코드 실행기는 `unload_engine=yolo`와 `yolo_unload`를 읽는다.
- 현재 주문 시험 프로필의 `handoff_arrival_only`, 지원 상품·수령 방향, C worker 설정을 확인해 C 정밀주차·하역까지 이어지게 설정.
- C 설정 변경은 현장 worker가 이미 실행 중이면 재시작 시 읽는다. 원격 단발 실행은 다음 호출 때 읽는다.
- 관제 주문 완료와 실제 물체 하역 성공을 구분해 기록.

이 문서 작성·코드 준비 과정에서 위 설정 적용, worker 재시작, 원격 전송, 실제 장비 동작은 하지 않았다.
