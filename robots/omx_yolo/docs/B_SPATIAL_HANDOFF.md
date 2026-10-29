# B 위치별 보간·관제 인계 — 2026-10-29

## 현재 결과

- [x] B 현장 사용자가 **진라면→slot0, 치토스→slot1, 서울우유→slot2** 실제 적재 성공을 확인했다.
- [x] 기존 카메라 캘리 행렬을 유지하고 B에서 라면군·나머지 상품군을 좌우 각 5점씩 총 20점 측정했다.
- [x] B `gateway-b.hardware.json`의 `yolo.pick_config`를 실제 성공 설정 `omx_pick_spatial_trial.json`으로 전환하고 저장 확인했다.
- [x] 사용자가 B 터미널에서 관제 `YoloArm`의 실제 모듈 경로로 import·설정 로딩을 확인했다. 10개 상품 좌우 각 5점, 선반·슬롯 자세, 캘리 파일, 6초·0.8초·fixed 설정 확인.
- [x] B 유선 랜선 재연결 후 관제·P1·P2·C에서 B 통신 복구. 관제에서 SSH 및 실제 import·설정 검증 완료.
- [ ] C 하역 준비 완료 후 관제 주문으로 실제 적재를 확인한다. 현재 로컬 성공을 관제 성공으로 기록하지 않는다.

## B 현장 파일

- 프로젝트: `/home/jimmy/robot_shopping/kernel-robot-repo-3`
- 시험 설정: `/home/jimmy/dev_ws/omxtest/config/omx_pick_spatial_trial.json` · SHA256 `d63db500a1abb7a3cb70bc70d7b78c085271e516e4ceffafbb70d0184807c665`
- 측정 원본: `/home/jimmy/dev_ws/omxtest/records/single/omx_b_spatial_samples.jsonl` · 20점 · SHA256 `96af5866f94b3076aa68a8b8549e7665946aacdbbfa4416dca2e075ec4959289`
- 자세: `/home/jimmy/dev_ws/omxtest/config/single/omx_saved_poses.json` · SHA256 `95413e5d3115857d15e32ea2f664a7cfc8e5ebb8c9a4be9ccfe51db19a4039a9`
- 캘리: `/home/jimmy/dev_ws/omxtest/config/single/omx_xy_calibration.json` · SHA256 `793939573a95f38c67cd381373c9a2d382ae35e3d56c8aa1f9be5931095854fa`
- hardware 변경 전 백업: B 프로젝트 `runtime/field/b-spatial-control-link-20261029-164819/`

해시는 인계 당시와 대조한 값이다. 이후 현장 수정이 있다면 최신 파일을 확인한다. 측정 중 `shelf_left_approach`만 재기록했으며, 슬롯 자세는 유지했다. 이동·펼침 6초, 그리퍼 0.8초, fixed 손목과 B 전용 그리퍼를 사용한다.

## 적용 범위·계산

- 라면군은 진라면으로 좌우 10점 측정, 진라면·신라면에 적용.
- 나머지 상품군은 서울우유로 좌우 10점 측정, 서울우유·바나나우유 2종·M&M·치토스·초코파이·새우깡·라이스칩에 적용. 공유 상품 전체가 실물 검증된 것은 아니다.
- 기존 캘리 XY를 보간 위치로 사용한다. 직접 맞춘 최종 목표와 기존 보정을 포함한 목표의 차이를 추가 XY로 쓰며, 직접 맞춘 **최종 절대 Z**를 사용한다. 기존 보정은 지우지 않는다.
- 삼각형 내부는 선형 보간하고 범위 밖은 최근접 경계 보정값을 사용한다. 범위 밖 정확도와 전체 영역 반복 신뢰성은 미검증이다.
- B 로컬 OMX와 B 관제 복사본의 보간 모듈·`pick_core.py`는 각각 동일하다. 관제 공통 코드와 `pick_core.py` 차이는 빈 줄 하나였으며 공통 모듈 해시는 같다.
- A 전용 ID14 +1024 모터 보정·A 현장값은 B에 적용하지 않았다.

## Git·다음 확인

- B `omxtest` 위치별 보간 코드 2개를 한국어 커밋 `f020196ea1f76cf6da57e70b9a8fdd788ce7e541`으로 정리해 브랜치와 GitHub main에 반영했다. 관제의 GitHub SSH 인증으로 동일 커밋을 전송했고, 관제 main에는 공통 코드가 이미 포함돼 있다. B 현장 Git HEAD를 강제로 바꾸지 않았다.
- 시험 JSON·측정 원본·자세·캘리·hardware는 Git 제외이므로 현장 백업을 유지한다. B 작업 폴더 전체를 reset하거나 덮어쓰지 않는다.
- B 터미널과 관제 SSH로 `robot_gateway.hardware.yolo` 경로의 실제 import·성공 설정·좌우 5점·슬롯 자세·캘리·시간 설정을 장비 동작 없이 확인했다. 다음 확인은 C 작업 완료 후 관제 주문 실제 적재다.
- B 인계에 기록된 목표 Z와 실제 모터 피드백 Z의 차이는 일부 측정점에서 존재했다. 이번 세 상품의 성공을 전체 위치의 기계적 추종 문제가 해결된 것으로 확대하지 않는다.
