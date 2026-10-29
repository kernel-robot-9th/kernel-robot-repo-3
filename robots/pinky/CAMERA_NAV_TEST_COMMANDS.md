# 전체 카메라 위치 표시·P1 주행 시험 명령

2026-10-27. 코드·설정·웹 빌드만 준비했다. 아래 서버 반영, 로봇 기동, 위치 보정과 실제 이동은 작업자가 실행한다.

모든 명령은 **관제 노트북**에서 실행한다. 목표는 약 6~7cm 지도 정렬 차이를 허용한 대략적인 위치·방향 보정이다. 최종 A/B/C 정밀주차는 구역별 카메라를 사용한다.

현재 P1 통로·P2 C 배치에서 대기자리로 먼저 정렬하려면, 두 로봇 준비 후 [현재 위치→선두/후열 정렬 명령](WAIT_RETURN_COMMANDS.md)을 사용한다. 손으로 선두에 옮길 필요 없다.

## 1. 관제 화면 반영 — 한 번

```bash
cd /home/noma/dev_ws/kernel-robot-repo-3
bash scripts/apply_pinky_camera_web.sh
```

준비된 화면 파일을 반영하고 현재 프로젝트의 8000번 관제 서버를 재시작한다. 기존 `runtime/hardware/pinky-demo/shopping.db`와 실물 설정을 유지한다. DB 초기화·worker 재시작·로봇 이동은 하지 않는다.

화면: http://192.168.0.11:8000/admin/pinky/movement
브라우저를 새로고침하면 **전체 카메라 위치** 지도가 추가된다. 파란색 P1/흰색 로봇, 빨간색 P2/빨간색 로봇이며 화살표는 앞방향이다.

## 2. 터미널 1 — 전체 카메라 켜두기

다른 전체 카메라 영상 창이 열려 있으면 그 창에서 Q로 종료한다.

```bash
cd /home/noma/dev_ws/kernel-robot-repo-3
bash scripts/run_pinky_camera_navigation.sh run
```

이 프로그램 자체는 로봇을 움직이지 않는다. 창을 켜둔 상태에서 다음 터미널을 사용한다. Q 또는 Ctrl+C로 종료하면 관제에는 실행 대기로 표시되고, 다음 이동은 기존 Nav2 위치추정을 사용한다.

관측값만 읽는 명령:

```bash
bash scripts/run_pinky_camera_navigation.sh status
```

`running: true`, 로봇별 `visible: true`, `map_pose`와 `layout_pose`가 표시된다. P2도 보이면 함께 표시되며 P2의 ROS 실행 여부와는 별개다.

## 3. 터미널 2 — P1 실행 준비

재부팅 후 실행부가 꺼진 상태를 포함한 준비 순서다. 첫 SSH 명령의 sudo 암호는 터미널에 직접 입력한다. 이전 P1 시각이 관제와 달랐으므로 먼저 맞춘다.

```bash
cd /home/noma/dev_ws/kernel-robot-repo-3
ssh -t -i /home/noma/.ssh/cartrina_field_ed25519 pinky@192.168.0.16 \
  "sudo -v && sudo timedatectl set-ntp false && sudo date -u -s '@$(date +%s)'"
bash scripts/run_pinky_control.sh setup --robot P1 --phase localize
bash scripts/run_pinky_control.sh setup --robot P1 --phase navigation
bash scripts/run_pinky_control.sh setup --robot P1 --phase route
```

`localize`는 이미 실행 중인 구동부·AMCL을 중복 기동하지 않는다. `navigation`은 기존 Nav2 실행부를 다시 시작하고, `route`는 Route Server를 준비한다. setup 명령은 해당 실행 스크립트만 로봇에 복사하며 지도·hardware·주차 설정을 덮어쓰지 않는다. 이 단계는 이동 목표를 보내지 않는다.

**P1을 실제 선두 대기자리(front)에 놓은 다음**, 이동 없이 카메라 위치를 Nav2에 반영한다.

```bash
bash scripts/run_pinky_control.sh camera-pose --robot P1
```

`카메라 위치 보정: {"published": true, ...}`는 `/initialpose`에 위치를 발행한 결과다. `transport_acked`는 DDS 전달 확인이며 AMCL 적용 완료 판정은 아니다. 서비스 응답은 기다리지 않는다. `published: false`면 함께 출력된 사유를 확인한다. 카메라 창이 켜져 있고 P1 마커가 보이는지 확인한 뒤 같은 명령으로 다시 적용할 수 있다. RViz 마우스 위치 지정은 필요 없다.

## 4. P1 → A 이동·정밀주차 시험

```bash
bash scripts/run_pinky_control.sh move --robot P1 --from front --zone A --parking
```

실제 주행 명령이다. 전체 카메라로 출발 위치·앞방향을 보정하고 기존 Route Server 경로로 A 후진 관측 지점에 이동한 뒤 A 카메라 정밀주차로 이어진다. **적재는 실행하지 않는다.**

- 출발 전과 완료된 경로 구간 사이에서만 카메라 보정을 요청한다. 이동 중 매 프레임 초기 위치를 다시 보내지 않는다.
- 현재 마커가 보이지 않거나 카메라 프로그램이 꺼져 있으면 보정 없이 기존 Nav2 추정으로 계속한다.
- 구역 카메라 정밀주차 중에는 전체 카메라가 위치를 다시 설정하지 않는다.
- 주행 로그의 `camera_localization`에 적용 여부와 카메라 위치가 기록된다.

## P2는 이후 같은 순서

P2 관제 위치 표시는 위 카메라 프로그램 하나로 준비된다. P2 실제 시험 때는 준비 명령의 `P1`을 `P2`, SSH 주소 `.16`을 `.17`로 바꾼다. 선두에 놓고 시험한다면:

```bash
bash scripts/run_pinky_control.sh camera-pose --robot P2
bash scripts/run_pinky_control.sh move --robot P2 --from front --zone A --parking
```

이는 실제로 선두 대기자리에 놓았을 때의 명령이다. 후열에서 두 대를 함께 운용하는 전체 주문 시험은 별도 단계다.

## 준비·검증 근거

- `runtime/field/pinky-overhead/navigation-calibration.json`: 기존 캘리를 보존한 시연용 사본.
- `runtime/field/pinky-camera-navigation.json`: P1 ID 0/180°, P2 ID 1/270°, 80mm·143mm 설정.
- `runtime/field/pinky-overhead/navigation-offline-preview.jpg`: 기존 저장 사진으로 처리한 방향 표시. 현재 실시간 사진이 아니다.
- 관련 좌표·방향·실시간 연결 종료·ROS 요청·인증 API 테스트 11개 통과, Vue 타입 검사·별도 폴더 빌드 완료.
- 아직 실제 카메라 위치 보정 후 주행 성공 여부는 시험하지 않았다.
