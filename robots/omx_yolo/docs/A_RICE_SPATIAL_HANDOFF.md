# A 쌀과자 위치별 보정 관제 반영 — 2026-10-29

- [x] A 현장 시험과 같은 위치별 보정 코드·설정 연결.
- [x] 측정점 10개의 최종 XYZ, 내부 보간, 다른 품목의 기존 보정 유지 확인.
- [x] `slot0_release` 저장 시각: **2026-10-29 15:02:44 +09:00**.
- [ ] 재기록한 슬롯 0 놓기 자세의 실물 성공 확인.
- [ ] 관제에서 쌀과자 3개 연속 집기·슬롯 0·1·2 적재 시험. 사용자 요청 후 시작.

사용자 확인 결과는 쌀과자 집기 3회 성공, 슬롯 0 적재 실패, 슬롯 1·2 적재 성공이다.
슬롯 0 재기록은 저장 확인이며 성공 확인이 아니다. 라면 등 다른 품목과 측정 범위 밖 정확도는 검증 완료로 간주하지 않는다.

## 실제 실행 경로

관제의 `RemoteArm` → A 노트북의 `scripts.pinky_station` → `YoloArm` 순서로 실행한다.
팔 실행마다 새 원격 프로세스가 A의 `runtime/field/gateway-a.hardware.json`을 읽는다.
OMX 모듈은 A 저장소 `/home/choi-chun-hwan/robot_shopping/kernel-robot-repo-3/robots/omx_yolo/tools/picking/`에서 import한다.

| 설정 | A 노트북 파일 |
|---|---|
| pick_config | `/home/choi-chun-hwan/dev_ws/omxtest/config/omx_pick_rice_spatial_trial.json` |
| poses_file | `/home/choi-chun-hwan/dev_ws/omxtest/config/single/omx_saved_poses.json` |
| calibration_file | `/home/choi-chun-hwan/dev_ws/omxtest/config/single/omx_xy_calibration.json` |
| motor_frame_file | `/home/choi-chun-hwan/dev_ws/omxtest/config/single/omx_motor_frame.json` |
| 측정 원본 | `/home/choi-chun-hwan/dev_ws/omxtest/records/single/rice_three_recheck_20261029.jsonl` |

슬롯 0·1·2는 각각 `slotN_approach` / `slotN_release`에 연결된다. P1/P2 모두 같은 A 슬롯 매핑을 사용한다.
이동·펼침은 각각 6초, 그리퍼는 별도 설정 0.8초, 손목은 fixed, 선반 접근은 좌우 저장 자세를 사용한다.
기존 `from_folded` 정책은 변경하지 않았다. 펼침 시간 설정이 있다는 이유로 매번 펼침을 실행하지 않는다.

## 보정과 Git 구분

- 공통 코드: `tools/picking/omx_spatial_correction.py` 추가, `pick_core.product_shelf_adjustment` 병합. 이전 상품별·선반별 보정과 관제 수정을 보존한다.
- A 전용 값: `classes.rice_chip.spatial_adjustments_by_shelf`의 좌·우 각 5점. 삼각형 내부 추가 XY·절대 집기 Z를 보간하고, 범위 밖은 최근접 경계 보정값을 사용한다.
- 캘리 행렬·자세·그리퍼 수치·14번 +1024펄스 보정은 변경하지 않았다. 현재 A 팔의 처짐을 보상하는 값일 수 있으므로 B나 정상 팔에 복사하지 않는다.
- 공통 코드와 이 문서는 Git 대상이다. A hardware JSON 및 omxtest의 시험 설정·자세·캘리·모터 JSON은 ignore 대상이므로 코드 배포만으로 현장 적용이 끝나지 않는다.
- 이번에는 B의 코드·설정·장비 파일을 변경하지 않았다.

백업은 관제와 A 저장소의 `runtime/field/a-spatial-sync-20261029-151220/`에 보관했다.
관제 백업에는 원본 스냅샷·계산 검증·배포 결과가 있고, A 백업에는 변경 전 코드·hardware 및 현장 JSON 사본이 있다.
반영 시 주문 worker는 정지 상태였다. 다음 원격 팔 실행부터 최신 설정을 읽으며, 이번 작업에서 worker를 기동하거나 실물 시험을 하지 않았다.
