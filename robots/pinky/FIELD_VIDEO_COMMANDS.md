# 현장 영상 미리보기

2026-10-27. A·B YOLO 미리보기와 전체 카메라 영상을 관제에 연결했다.
C 전면·손목 카메라 지원 코드는 배포했으나, 팀원의 모방학습 녹화 때문에 실행은 보류했다.

관제 노트북:

```bash
cd /home/noma/dev_ws/kernel-robot-repo-3
bash scripts/run_field_video.sh start
bash scripts/run_field_video.sh status
```

화면: http://192.168.0.11:8000/admin/video
개별 화면: `/admin/omx/load-a`, `/admin/omx/load-b`도 같은 영상을 사용한다.
A·B에는 기존 집기 모델과 검출 설정으로 계산한 상자·클래스명·신뢰도를 표시한다.
전체 영상은 실행 중인 `run_pinky_camera_navigation.sh run`의 프레임을 공유한다.

현재 관제 및 `run_pinky_control.sh`의 원격 station 실행은 작업 시작 시 미리보기에서 카메라를 인계받고,
작업이 읽는 프레임을 공유한다. 종료·오류 후 미리보기가 다시 카메라를 연다.
별도의 omxtest 프로그램을 직접 실행할 때는 아래 명령으로 미리보기를 먼저 종료한다.

```bash
bash scripts/run_field_video.sh stop
```

중계 로그: `runtime/field/video-preview/relay.log`.
각 현장의 최근 검출 목록: `runtime/field/station-video/detections.json`.
C는 기본 시작 대상에서 제외한다. 녹화 종료 후 C 재개를 별도로 진행한다.

검증: 인증된 5개 영상 채널 업로드가 작업 상태를 바꾸지 않는 테스트와 카메라 인계 해제 테스트 2개 통과.
A·B 카메라 인계/반환을 모터 명령 없이 확인. 실제 팔 작업 중 영상 전환은 다음 현장 작업에서 확인한다.
