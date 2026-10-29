# 구역별 카메라 기준 사진·겹쳐 보기

갱신: 2026-10-29. 현재 카메라 위치와 저장된 기준 사진을 비교해 위치 변경을 확인한다. 사진은 각 현장 노트북에 보관하며 Git에 포함하지 않는다. 화면에서 고정된 작업대·로봇 받침·선반 모서리를 기준으로 비교한다.

## A — 기준 사진 저장 완료

- 현재 기준: `/home/choi-chun-hwan/dev_ws/omxtest/records/camera_overlay/20261029_172739_461951_webcam.jpg` (1920×1080).
- A 재연결 후 SNAP U2 카메라 점유가 없는 상태에서 촬영했다. 원본 이미지와 기존 겹쳐 보기 도구의 최신 사진 목록을 확인했다. 이전 사진은 보존했다.
- 관제 보관본: `runtime/field/camera-reference-20261029/A-20261029-172739.jpg`.
- A 노트북 그래픽 터미널:

```bash
cd /home/choi-chun-hwan/dev_ws/omxtest
env -u PYTHONPATH -u PYTHONHOME .venv-pick/bin/python -B \
  tools/measurement/00_omx_camera_overlay.py \
  --reference records/camera_overlay/20261029_172739_461951_webcam.jpg
```

`Reference %`로 투명도 조절, Space: 현재/겹침, R: 기준/겹침, Q: 종료. 작업대·고정 받침·벽 모서리를 기준으로 비교한다. GUI 실시간 겹침은 아직 실행하지 않았다. 촬영 후 카메라 연결은 해제했으며 보정·자세 파일은 변경하지 않았다.

## B — 기준 사진 저장 완료

- 현재 기준: `/home/jimmy/dev_ws/omxtest/records/camera_overlay/20261029_170912_159747_webcam.jpg` (1920×1080).
- 기존 겹쳐 보기 도구의 목록에서 최신 사진으로 선택되는 것을 확인했다. 이전 사진도 그대로 보존한다.
- B 노트북 그래픽 터미널:

```bash
cd /home/jimmy/dev_ws/omxtest
env -u PYTHONPATH -u PYTHONHOME .venv-pick/bin/python -B \
  tools/measurement/00_omx_camera_overlay.py \
  --reference records/camera_overlay/20261029_170912_159747_webcam.jpg
```

`Reference %`로 기준 사진의 투명도 조절, Space: 현재/겹침, R: 기준/겹침, Q: 종료. 카메라를 다른 프로그램이 사용 중이면 해당 프로그램 사용을 끝낸 후 실행한다. 저장 파일은 그때의 장면이며 물건·팔 자세는 달라질 수 있다.

## C — 정면·손목 기준 사진 저장 완료

- 정면: `/home/team2/dev_ws/omx_imitation_project/camera_reference/front_current_20261029_170910.png` (640×480).
- 손목: `/home/team2/dev_ws/omx_imitation_project/camera_reference/wrist_current_20261029_170910.png` (640×480).
- C 주차 해상도 추가 사진: `/home/team2/dev_ws/omx_imitation_project/camera_reference/front_parking_current_20261029_171205.png` (1920×1080). 현재 로봇 마커 윗부분이 화면 밖으로 잘려 ID를 검출하지 못했다. 현장 위치 조정 후 재확인이 필요하다.
- 과거 C/P2 목표 사진(1920×1080)과 고정 배경 특징은 대체로 일치했으나, 마커 상단 여유가 약 17픽셀로 작았다. 카메라 이동 여부는 이 자료만으로 단정하지 않는다.
- 기존 학습 기준 `front_left_v1_ep000000.png`, `front_left_v2_ep000000.png`는 유지했다. 새 현재 사진은 기존 학습 구도와 일치한다는 판정이 아니다.
- C 노트북 그래픽 터미널:

```bash
bash /home/team2/dev_ws/omx_imitation_project/camera_reference/compare_current.sh front
bash /home/team2/dev_ws/omx_imitation_project/camera_reference/compare_current.sh wrist
```

기준 40%·실시간 60%로 겹쳐 표시하고 Q로 종료한다. 손목 카메라는 팔 자세에 따라 화면이 변하므로 같은 팔 자세에서 비교한다. C에서 녹화·다른 미리보기가 카메라를 사용하는 동안에는 함께 열지 않는다. ffplay와 각 카메라 MJPG 지원·겹침 필터를 확인했으며 GUI 실시간 겹침은 아직 사용자가 실행하지 않았다.
