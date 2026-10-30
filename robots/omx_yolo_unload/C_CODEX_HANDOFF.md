# C 노트북 Codex 인계 — YOLO 하역 현장 완성

2026-10-30: C 현장 캘리·단독 하역 및 관제 연결, GitHub main 병합 완료. 최신 운영 상태는 [CONTROL_HANDOFF_STATUS.md](CONTROL_HANDOFF_STATUS.md)를 우선한다. 아래 초기 준비 순서를 처음부터 반복하지 않는다.

```text
카트리나 프로젝트 C 구역 YOLO 하역을 이 노트북에서 캘리·자세 기록·실물 시험하고 필요한 코드를 수정하려 한다.
기존 ACT/VLA 하역이 아직 완성되지 않아, 전체 주문 시연과 영상 촬영을 위해 A/B의 YOLO 좌표 집기 방식을 C 하역에 재사용한다.

[작업 위치·Git]
- 이 컴퓨터는 C 노트북, 사용자 team2, 현장 IP 192.168.0.20이다. 실제 상태부터 확인한다.
- 프로젝트: /home/team2/robot_shopping/kernel-robot-repo-3
- 저장소: https://github.com/kernel-robot-9th/kernel-robot-repo-3
- 준비 브랜치: codex/c-yolo-unload-20261030
- 이번 C 코드는 main에도 병합됐다. 현장 변경이 남아 있으므로 기존 브랜치와 작업 파일을 확인한 뒤 병합한다.
- 먼저 git status와 현재 브랜치를 확인하고, C 로컬 변경·현장 JSON·모델·데이터를 보존한다. reset --hard, clean, 강제 checkout 하지 않는다.
- 로컬 변경이 없다면 git fetch origin 후 git switch --track origin/codex/c-yolo-unload-20261030으로 받는다. 이미 로컬 브랜치가 있으면 switch 후 git pull --ff-only origin codex/c-yolo-unload-20261030을 사용한다. 변경이 있으면 백업하고 필요한 코드만 병합한다.
- 인증 문제는 초기에 확인한다. 웹 파일 업로드로 우회하지 않는다.

[작업 방식]
- 적용되는 AGENTS.md와 사용 가능한 dev-plan-gate·efficient-tool-usage 스킬을 읽는다.
- 먼저 읽기 전용 확인 후 최소 변경·현장 시험 계획을 짧게 제시한다. 변경·재시작·장비 동작은 사용자가 마지막 단어 '진행'으로 승인한 범위에서 한다.
- 시간 부족하다. 실물 상품 1개 하역 성공부터 만든다. 불필요한 전체 점검·전체 재설정·안전 조건 추가로 작업을 늘리지 않는다.
- 현장 Enter·클릭·키보드 조작은 이 노트북 터미널에서 사용자가 한다.
- 비밀번호·토큰·환경파일 내용은 출력하지 않는다.
- 저장 완료, 동작 궤적 완료, 실제 집기·하역 성공은 구분한다.

[시나리오와 측정]
- 앞에 정밀주차한 Pinky의 작은 바구니에서 상품을 집어 주문 고객에게 배정된 왼쪽 또는 오른쪽 수령 바구니에 놓는다.
- P1/P2 번호로 하역 좌우를 고정하지 않는다. 실제 명령의 basket_side(left/right)를 사용한다.
- Pinky 바구니가 좁아 캘리 기준점을 넓게 잡기 어렵다. 두 Pinky 바구니를 같은 높이로 나란히 두어 넓은 단일 평면을 캘리한다.
- 실사용 검출 영역은 한 대 바구니 내부만 사용한다. 넓은 캘리 영역과 실제 집기 ROI를 분리하고 P1/P2 각각 기록한다.
- 기준면 높이와 실제 상품의 집기 Z는 구분한다. 상품별 집기 높이는 C에서 측정한다.
- 기본 캘리 후 실제 집기가 어긋나면 C에서 위치별 추가 XY와 절대 집기 Z를 기록·보간한다. A/B 보정값을 복사하지 않는다.
- 기록 범위 밖은 가장 가까운 경계값을 사용하지만 그 정확도는 별도 실물 확인 대상이다.

[먼저 읽을 파일]
- robots/omx_yolo_unload/README.md
- robots/omx_yolo_unload/FIELD_COMMANDS.md
- robots/omx_yolo_unload/core.py, runtime.py, field.py
- robots/pinky/CAMERA_NAV_DEMO_PLAN.md
- 공통 실행: robot_gateway/hardware/yolo.py
- 공통 좌표·보간: robots/omx_yolo/tools/picking/pick_core.py, omx_spatial_correction.py

[준비된 코드·현장 파일]
- python -m robots.omx_yolo_unload로 init/status/calibrate/pose/move/gripper/product/region/detect/preview/jog/adjust/fit-spatial/run/activate 사용 가능하다. 정확한 인자는 FIELD_COMMANDS.md와 --help를 확인한다.
- C 전용 새 설정 기본 경로: runtime/field/c-yolo/gateway-c.yolo.hardware.json
- init은 실제 장치 경로로 최초 한 번만 사용한다. 이미 기록한 파일을 재초기화하지 않는다.
- 공통 YOLO 코드·카메라 재연결·영상·부분 완료 처리를 재사용한다. A/B 실행 경로는 보존한다.
- 준비된 코드에서 필요한 자세는 아래 6개다:
  wait
  pickup_approach
  drop_left_approach / drop_left_release
  drop_right_approach / drop_right_release
- wait는 상품을 든 채 통과할 작업 대기 자세로 기록한다.
- 초기 팔 이동은 구간당 6초, 그리퍼는 별도 0.8초, 손목 fixed다. 실제 C 설정을 확인한다.
- 모터 구성·부호·프레임·그리퍼 값은 C 실물을 확인한다. A 모터 14번 +1024 보정이나 A/B 장비 식별값을 적용하지 않는다.
- 기존 C ACT/VLA 환경·모델·수집 데이터·카메라 설정은 보존한다.
- 모델 가중치 best.pt, 가상환경, runtime 현장 JSON과 캘리·자세는 Git에 포함되지 않는다. 실제 존재 여부를 확인하고 누락된 모델만 별도 전달받는다. A/B에서 성공한 모델이라도 C의 위쪽 시점 검출은 확인해야 한다.

[현장 작업 순서]
1. Git 코드 수신 → 실제 팔·포트·카메라·Python·가중치·기존 프로세스 확인. 카메라를 사용 중인 팀원 작업을 임의 종료하지 않는다.
2. C 전용 설정, 그리퍼, 6개 자세 기록. 같은 높이의 넓은 평면 캘리와 P1/P2 한 바구니 ROI 기록.
3. 상품별 Z·검출 확인 → preview로 좌표/계획 확인 → 상품 1개를 지정한 좌우 바구니로 실제 하역.
4. 필요하면 adjust로 실제 집기 위치를 맞춰 기록하고 fit-spatial로 보간. 실제 사용한 설정·캘리·자세 경로를 남긴다.
5. 상품 3개 연속 하역, 좌/우, P1/P2를 필요한 순서로 검증한다. 수행하지 않은 조합은 미검증으로 적는다.
6. 관제 연결은 단독 성공 뒤 확인한다. activate는 기존 gateway-c.hardware.json의 ACT 설정을 보존하며 unload_engine=yolo와 yolo_unload 경로를 추가하고 백업한다. 이 명령만으로 worker 재시작이나 전체 주문 연결이 완료된 것은 아니다.
7. 관제의 C 실행 Python과 주차 Python, HANDOFF 품목·basket_side, 하역 도착까지만 실행하는 설정(handoff_arrival_only), worker 선택을 확인한다. 관제 노트북 변경·재시작은 담당 세션에 인계한다.

[오류·재시도]
- run은 --execute가 없으면 명령 내용만 출력한다. 실제 시험은 사용자 승인 후 --execute로 한다.
- 동일 작업 재개는 같은 --job-id와 동일한 상품 목록·로봇·방향을 사용한다. 완료 궤적 기록을 읽어 이미 끝난 항목을 건너뛴다.
- 궤적이 끝났으나 물체 집기에 실패한 경우도 있을 수 있다. 재시도 전 실물 상태와 완료 기록을 확인하고 자동으로 성공이라고 판단하지 않는다.
- 하역 결과에는 physical_delivery_confirmed=false / operator_review_required가 남는다. 관제의 최종 완료 처리가 실제 인계 확인과 어떻게 연결되는지 확인한다.

[현재 검증 수준·결과 인계]
- C 단독 하역 성공은 사용자 확인, P1 네 품목 보간 5점과 관제 연결 완료. P2 동일 보간 적용은 추가 요청 사항이며 전체 주문 실물 시험은 아직이다.
- 로컬 검증과 전체 주문 성공을 구분한다. 추가 코드 수정은 간결하게 하고 해당 변경만 필요한 시험을 한다.
- 마무리할 때 수정 파일, 실제 Python·카메라·모터·모델 경로, 사용한 설정/캘리/자세, 상품·좌우·P1/P2별 실물 결과, 미검증 항목, 관제에서 해야 할 변경을 정리한다. 비밀값은 제외한다.
- 현장 JSON은 ignore되어 있으므로 Git 푸시와 별도로 백업·전달할 파일 목록을 남긴다. 커밋 메시지는 한국어로 작성한다.
- Three.js/ACS는 이번 범위가 아니다. 먼저 C 하역과 전체 시연을 완성한다.

우선 현재 파일과 연결 상태를 읽기 전용으로 확인하고, 이 C 노트북에서 진행할 최소 작업 순서와 첫 실행 명령을 정리해 줘.
```
