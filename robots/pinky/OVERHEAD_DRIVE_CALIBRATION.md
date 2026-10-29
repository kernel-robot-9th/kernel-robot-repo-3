# 전체 카메라 주행 캘리

2026-10-27. P1(ID 0, 검은 변 80mm, 종이 면 높이 143mm)을 관제에서 직접 움직이고 정차 영상을 odom과 함께 기록한다. RViz 초기 위치와 AMCL map 좌표는 측정 정답으로 사용하지 않는다.

## 기록 방법

현재 카메라 구도를 확인한 뒤 빈 통로에서 짧은 직진·회전을 순서대로 실행한다. 각 명령이 끝나면 로봇은 정지한다. `--distance`는 시작 방향 기준 m, `--turn`은 상대 회전 각도다. 양수는 전진/반시계 회전이다. P1 구동부가 ROS Domain 1에서 실행되어 있어야 한다. 이 도구는 Nav2와 관계없이 P1 구동 명령 토픽을 사용한다.

```bash
cd /home/noma/dev_ws/kernel-robot-repo-3
source /opt/ros/jazzy/setup.bash
python3 -m scripts.pinky_camera_drive_calibrate collect \
  --output runtime/field/pinky-overhead/drive-calibration-20261027 --name 00-start
```

정지 기록 예시다. 실제 이동은 해당 명령에 `--distance 0.2` 또는 `--turn 90`을 지정해야 한다. 현장 배치가 바뀌면 이전 이동 순서를 그대로 반복하지 않고 현재 영상에서 이동할 구간을 선택한다. 파일 이름은 숫자로 시작하며, 새 시험은 다른 output 폴더에 기록한다.

- 정차 후 여러 프레임의 모서리 중앙값을 사용한다. 카메라와 로봇 시계가 달라도 이동 중 비동기 측정을 정답으로 섞지 않는다.
- 마커 네 모서리와 odom으로 영상→odom 평면 변환, 마커 부착 각도와 중심 오프셋을 함께 추정한다. 추정한 오프셋은 기존 구역별 주차 설정에 자동 반영하지 않는다.
- `--validation`으로 기록한 위치는 계산에서 제외하고 결과 평가에만 사용한다.
- 사진, 정차 표본 JSON, 이동 중 카메라 검출·odom 기록을 각 이름으로 보존한다.

## 계산과 지도 연결

```bash
python3 -m scripts.pinky_camera_drive_calibrate fit \
  --output runtime/field/pinky-overhead/drive-calibration-20261027
```

`fit.json`은 odom에 대한 적합·별도 위치 오차와 변환을 담는다. 이는 절대적인 실측 오차와 다르며 odom의 축척·미끄러짐 오차가 포함될 수 있다.

`calibration-candidate.json`은 기존 실측 네 점을 이용해 회전·이동만으로 공용 지도에 맞춘 후보값이다. 기존 네 점 때문에 새로운 거리 축척이나 원근 변환을 다시 비틀지 않는다. 기존 중앙 검증점은 여기에도 학습시키지 않는다. 후보는 기존 `calibration.json`이나 주행 설정을 자동 교체하지 않는다.

현장 결과와 다음 단계는 [전체 작업 계획](CAMERA_NAV_DEMO_PLAN.md)에 기록한다.
