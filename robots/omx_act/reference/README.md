# OMX 로봇팔 모방학습 — 녹화부터 ACT 모델 2개 만들기

작성일: 2026-10-19

관제 통합 인계 갱신: 2026-10-20

데스크톱에서 처음 받는 경우: **[DESKTOP_TRAIN.md — Git clone부터 환경 설치·66개 확인·왼쪽 학습까지](DESKTOP_TRAIN.md)**

GitHub: https://github.com/rheffi/omx-imitation-project (비공개). 이 저장소는 프로젝트 문서·카메라 기준 이미지·LeRobot 버전 정보·현재 수정 패치를 관리한다. 학습 코드는 문서의 고정 커밋으로 설치하고, 녹화 데이터와 모델은 Hugging Face로 전달한다.

장치 확인 및 설정 갱신: 2026-10-20

**현재 결정: 왼쪽 ACT v2 5만 스텝 모델과 집기 쉬운 배치로 시연을 마무리하고 관제 통합을 진행한다.** 사용자 시험상 왼쪽 5만이 더 양호했으며 정량 성공률은 미기록이다. **오른쪽 v2 3만~7만 모델 5개도 검증·정리했고, [RIGHT_V2_EVAL.md](RIGHT_V2_EVAL.md)의 전체 명령으로 평가 후 오른쪽 최종 모델을 선택한다.** 추가 학습·수집은 이번 통합의 선행 작업으로 두지 않는다. 관제 세션은 **[CONTROL_INTEGRATION_HANDOFF.md — 모델·환경·시작/완료/중지 요구사항](CONTROL_INTEGRATION_HANDOFF.md)**을 먼저 읽고, 실제 팔 수동 시험은 [LEFT_V2_EVAL.md 3절](LEFT_V2_EVAL.md#3-현재-시연용--5만-스텝-연속-실행)의 전체 연속 실행 명령을 사용한다. 새 팔·8종 기준 수집본은 로컬에서 왼쪽 v2 60개·30,617프레임, 오른쪽 v2 60개·28,962프레임을 확인했다. 저장 개수 확인은 성공 시연 전수 검수나 HF 업로드 확인과 별개다. 기존 v1 데이터와 모델은 유지한다.

실행 명령은 부분 옵션 대신 복붙할 수 있는 전체 블록으로 적었다. 녹화·실제 팔 평가 블록에는 현재 PC의 가상환경 활성화와 장치값을 포함했다. 5090 PC용 학습 블록은 해당 PC의 학습용 가상환경을 활성화한 뒤 실행한다. 명령 블록은 필요한 것 하나를 골라 실행한다.

바로 실행할 명령 위치:

- [현재 작업: 관제 통합 인계와 후속 구현 조건](CONTROL_INTEGRATION_HANDOFF.md)
- [왼쪽 v2 5만 스텝 연속 실행 전체 명령](LEFT_V2_EVAL.md#3-현재-시연용--5만-스텝-연속-실행)
- [오른쪽 v2 3만~7만 스텝 연속 평가 전체 명령](RIGHT_V2_EVAL.md)
- [오른쪽 시험·본 녹화·재개·학습 전체 명령](RIGHT_RERECORD.md)
- [왼쪽 재녹화·재개 전체 명령](LEFT_RERECORD.md)

- [중단 후 녹화 재개·추가 수집](#11-데이터-확인과-추가-녹화)
- [현재 왼쪽 66개로 첫 학습](#12-왼쪽-act-모델-학습--rtx-5090-pc)
- [학습 재개·보강 후 v2 학습](#14-학습-중단과-데이터-추가-후-처리)
- [1만~10만 스텝 비교·전체 평가 명령·결과표](#15-실제-팔에서-첫-평가)

현재 수집 기준:

- 기존 v1은 9종류였다. 재녹화 v2는 높은 물체 1종을 제외한 8종류 중 3개를 카트에 싣는다.
- 시험 녹화 3에피소드에서 두 카메라와 3→2→1→0 흐름을 확인했다.
- 새 v2 첫 수집 목표는 방향별 60에피소드이며, 현재 로컬에 왼쪽·오른쪽 각각 60개 저장을 확인했다.
- 기존 보강안(현재 보류): 평가 후 필요하면 방향별 v2 누적 99개까지 보강한다. v2 60개 기준 추가 39개다. 기존 v1 수량과 합산하지 않으며 성공 시연 검수 후 학습용 개수는 달라질 수 있다.
- 한 카트를 비우는 동안에는 같은 물건으로 3→2→1→0을 기록한다. 완전히 비운 뒤 다음 카트의 조합과 위치를 바꾼다.
- 저장·인코딩 중 `→` 입력이 다음 녹화에 남으면 0프레임 에피소드 오류가 날 수 있다. 해당 구간에는 키를 누르지 않고 다음 `Recording episode ...` 로그를 확인한다.

학습은 별도의 RTX 5090 PC에서 실행한다. 현재 OMX 연결 PC는 원격조종·녹화·실제 팔 평가에 사용한다. 이 문서의 학습 명령은 5090 PC용이고, 장치 포트·카메라 설정과 평가 명령은 현재 OMX 연결 PC용이다.

명령은 강의자료와 현재 PC의 `/home/team2/il_ws/src/lerobot` 소스를 확인해 정리했다. 리더암·서브암의 장치 경로, 기존 보정 파일의 ID, 모터 읽기 통신, 외장 카메라 2대의 경로와 영상 수신을 확인해 공통 설정에 반영했다. 손목을 초기 자세로 정렬한 뒤 사용자가 원격조종 정상 동작을 확인했다. 실제 집기 중 카메라 구도와 데이터 품질은 시험 녹화에서 확인한다. 최신 인터넷 예제를 따라 패키지를 일괄 업그레이드하지 않고 강의에서 사용한 환경을 유지한다.

## 0. 현재 진행 — 5만 스텝 시연과 관제 통합

**관제 통합 세션은 [CONTROL_INTEGRATION_HANDOFF.md](CONTROL_INTEGRATION_HANDOFF.md)를 먼저 읽는다.** 왼쪽 v2 5만 스텝 모델로 잘 집히는 물건·배치를 사용해 시연하고, 관제에서 주차 후 시작 → 카트 비움·마지막 담기·대기 복귀 확인 → 실제 동작 중지 확인 → 완료 표시와 핑키 출발을 연결한다. 이 연동은 아직 구현되어 있지 않다.

현재 CLI는 물건이 없어도 동작을 반복할 수 있다. 30초씩 3회 평가에서 발생한 중간 끊김을 피하려고 **한 에피소드 최대 180초**의 연속 실행을 사용한다. 최대 시간 만료나 정상 종료가 하역 성공을 의미하지 않는다. 수동 시험 전체 명령은 [LEFT_V2_EVAL.md 3절](LEFT_V2_EVAL.md#3-현재-시연용--5만-스텝-연속-실행)에 있다. `n_action_steps=20` 시험 제안은 적용하지 않고 기존값 100을 유지한다.

| 모델 | 현재 노트북의 경로 | 현재 용도 |
| --- | --- | --- |
| 왼쪽 v2 5만 | `/home/team2/omx_models/omx_left_act_v2/050000/pretrained_model` | 시연용 선택 |
| 왼쪽 v2 10만 | `/home/team2/omx_models/omx_left_act_v2/100000/pretrained_model` | 비교 참고용 유지 |
| 오른쪽 v2 3만~7만 | `/home/team2/omx_models/omx_right_act_v2/<030000~070000>/pretrained_model` | 1만 간격 5개 준비, 실제 평가 후 선택 |

모델·녹화 자료는 Git에 포함되지 않는다. 다른 PC에서 실행하려면 모델 폴더의 7개 파일과 로봇 보정 파일, 해당 PC의 LeRobot 실행 환경을 별도로 준비한다. 관제 통신 방식과 API/토픽 이름은 후속 세션에서 기존 관제 구조에 맞춰 결정한다. 오른쪽은 3만·4만·5만·6만·7만 모델을 준비했고 우선 평가 기본값은 5만이다. 1만·2만은 이번 준비에 포함되지 않았으며, 오른쪽 시연용 최종 체크포인트와 성능은 아직 미확정이다.

기존 v1 평가 명령은 아래 15절에 참고용으로 남겨 두었다. 새 팔·8종 기준 데이터는 로컬 왼쪽 v2 60개·30,617프레임, 오른쪽 v2 60개·28,962프레임이다. 추가 수집·재학습은 현재 보류하며, 필요할 때만 [왼쪽 문서](LEFT_RERECORD.md), [오른쪽 문서](RIGHT_RERECORD.md)를 사용한다. 이번 문서 갱신에서는 실제 팔을 실행하지 않았다.

## 1. 만들려는 동작

1. 핑키가 손님 한 명이 주문한 물건 3개를 싣고 정해진 위치에 주차한다.
2. 왼쪽 또는 오른쪽 장바구니 중 이번 주문의 목적지가 지정된다.
3. 고정된 로봇팔이 카트 안 물건을 하나씩 지정된 장바구니로 옮긴다.
4. 카트가 비면 작업을 종료한다.

물건 종류에 따라 좌우를 분류하지 않는다. 한 주문을 처리하는 동안 목적지는 바뀌지 않는다.

이번 학습에서는 두 모델을 따로 만든다.

| 모델 | 맡는 동작 | 작업 시작 시 선택 |
|---|---|---|
| 왼쪽 ACT | 카트에서 물건 하나를 집어 왼쪽 장바구니에 놓고 대기 자세로 복귀 | 목적지가 왼쪽인 주문 |
| 오른쪽 ACT | 카트에서 물건 하나를 집어 오른쪽 장바구니에 놓고 대기 자세로 복귀 | 목적지가 오른쪽인 주문 |

실제 배치 시험에서 4개는 집기 어렵다는 사용자 판단에 따라 한 카트의 시작 수량을 3개로 정했다. 물건이 3개·2개·1개 남았다고 모델을 각각 만들지 않는다. 각 방향의 모델 하나가 해당 방향의 모든 남은 개수 상태를 학습한다. 좌우 데이터를 조건 없이 섞어 모델 하나로 학습하지 않는다.

주차 완료 신호, 목적지에 따른 모델 선택, 물건이 남았는지 확인, 성공·실패 판단과 재시도는 별도 실행 로직이다. 아래 과정을 끝내면 두 개의 집어 옮기기 모델을 확보하는 것이고, 전체 하역 자동화가 모두 구현되는 것은 아니다.

## 2. 현재 확인된 것과 남은 것

| 항목 | 현재 상태 |
|---|---|
| 실습 진행 | 사용자가 강의 실습을 완료했다고 설명함 |
| 가상환경 | `source ~/venv/il/bin/activate` 후 `(il)` 표시 확인 |
| Hugging Face 로그인 | 성공 |
| Hugging Face 사용자명 | `chun-hwan` |
| 토큰 | fine-grained 토큰으로 로그인됨. 값은 문서에 저장하지 않음 |
| 업로드 권한 | 실제 생성·업로드로 확인 필요 |
| 고정 배치 | 사용자 설명상 선반 높이 약 11cm. 외장 웹캠 영상에서 팔·선반·바구니가 보이는 것 확인. 실제 주차·집기 구도는 추가 확인 필요 |
| 실제 물건 종류·크기 | 총 9종류. 모양은 다양하나 비슷하고 OMX로 집을 만한 물건으로 선정했다고 사용자 확인. 개별 이름·크기는 아직 기록하지 않음 |
| 카트 시작 수량 | 3개로 결정. 실제 배치에서 4개는 집기 어려웠음 |
| 원격조종 | 초기 손목 자세 정렬 후 `max_relative_target=0.2`를 사용한 재시험에서 사용자가 정상 동작 확인 |
| 시험 녹화 | 고정 이름 `omx-unload-left-pilot`으로 3에피소드·1,258프레임 저장 및 두 영상 검수 완료 |
| 왼쪽 본 녹화 | 로컬 66에피소드·37,012프레임 확인. `episode_index=35`는 실패 의심 시연으로 재검수 필요 |
| 녹화 방향키 | 실제 녹화에 사용 중. 저장·인코딩 중 입력 후 0프레임 저장 오류 발생 이력이 있어 단계 로그를 확인 |
| 주차 오차·바구니 높이·거리 | 측정·확인 필요 |
| 서브암(팔로워) 포트 | `/dev/serial/by-id/usb-ROBOTIS_OpenRB-150_1B8E02E050323952582E3120FF071F2E-if00` → 현재 `/dev/ttyACM1`, 새 USB 일련번호·모터 ID 읽기로 역할 확인; by-id 직접 사용 |
| 리더암 포트 | `/dev/serial/by-id/usb-ROBOTIS_OpenRB-150_E743255D50323952582E3120FF07301D-if00` → 현재 `/dev/ttyACM0`, 새 USB 일련번호·모터 ID 읽기로 역할 확인; by-id 직접 사용 |
| 기존 보정 ID | 서브암 `omx_follower_arm`, 리더암 `omx_leader_arm`. 각 파일의 6개 관절 항목 존재 확인, 현재 장치에서의 보정 적합성은 원격조종 전 확인 필요 |
| 외장 웹캠 | SNAP U2 → 현재 `/dev/video6`, 뷰 이름 `front` |
| 서브암 카메라 | Innomaker-U20CAM-720P → 현재 `/dev/video4`, 뷰 이름 `wrist`로 설정. 실제 집기 자세의 구도 확인 필요 |
| 카메라 입력 확인 | 두 대 모두 640×480, 요청·보고 FPS 30, MJPG 형식으로 동시에 열어 각 40프레임 수신 확인. 지속적인 30FPS 처리 성능은 별도 검증 필요 |
| 학습 PC | 별도의 RTX 5090 PC 사용 예정. 해당 PC의 OS·LeRobot 환경·CUDA 동작은 아직 확인하지 않음 |
| 현재 PC CUDA 사용 가능 여부 | 실제 모델 추론 전에 확인 필요 |

기존 Git credential helper 경고는 HF 로그인 실패를 뜻하지 않는다. 토큰은 정상 저장됐다. 일반적인 LeRobot Hub 업로드를 위해 지금 Git의 전역 credential 설정을 바꿀 필요는 없다. fine-grained 토큰에는 이번 데이터셋과 모델을 생성·업로드할 수 있는 권한이 있어야 한다.

## 3. 녹화 전에 준비할 것

### 물건과 배치

- 실제 사용할 물건 중 가볍고 그리퍼로 잡기 쉬운 종류부터 정한다.
- 겹쳐 쌓지 않고, 집게가 들어갈 간격을 두고 3개를 놓는다.
- 바닥 테이프로 핑키 주차 위치와 방향을 표시한다.
- 좌우 장바구니와 카메라 위치를 고정한다. 좌우 기준은 작업자와 팀원이 동일하게 정하고 배치 사진에도 표시한다.
- 카트 중앙·모서리·가장 먼 위치에서 집어 목적지까지 옮기는 동작을 원격조종으로 먼저 확인한다.
- 선반 높이 11cm만으로 작업 가능 여부를 판단하지 않는다. 팔 기준 카트 바닥 높이, 테두리 높이, 수평 거리, 물건 크기가 중요하다.
- 팔이 카트 테두리를 넘고 좌우 목적지 모두에 닿는지 확인한다.

### 카메라와 시연

- 카트 안 물건, 집는 부위, 목적지 안에 놓는 장면이 충분히 보이는지 확인한다.
- 팔이 접근하면서 물건을 가리는 장면도 확인한다. 카메라 수는 실제 장비에 맞춘다.
- 녹화와 실행에서 카메라 이름·위치·해상도·FPS를 유지한다.
- 일정한 조명을 사용하고 녹화 중 사람 손이나 몸이 불필요하게 화면에 들어가지 않게 한다.
- 기존 보정 ID를 유지하고 원격조종이 정상인지 확인한다.
- 시작·종료에 사용할 대기 자세를 정한다. 시작할 때 그리퍼는 열린 상태로 맞춘다.
- 여러 제어 프로그램이 같은 팔 또는 카메라를 동시에 사용하지 않게 한다.

### 계정과 PC

- HF 로그인 사용자명이 `chun-hwan`인지 확인한다.
- 저장 공간과 업로드 연결을 확인한다.
- 토큰 값은 문서·명령 기록·메신저에 복사하지 않는다.
- W&B는 이번 예제에서 끈다. W&B 계정 준비는 필요 없다.
- 학습 전 5090 PC에서 CUDA 연산이 되는지 확인한다. HF 웹사이트에 데이터를 올리는 것만으로 학습이 시작되지는 않는다.

## 4. 장치 확인과 공통 설정

### 4-1. 확인 명령

가상환경을 켠 터미널에서 실행한다.

```bash
source ~/venv/il/bin/activate
cd ~/il_ws/src/lerobot
hf auth whoami
ls -l /dev/omx*
ls -l /dev/serial/by-id /dev/v4l/by-id
v4l2-ctl --list-devices
df -h /home/team2
python -c 'import torch; print("CUDA:", torch.cuda.is_available()); print("GPU:", torch.cuda.get_device_name(0) if torch.cuda.is_available() else "사용 불가")'
```

`/dev/omx*`가 없으면 강의에서 사용한 실제 포트 또는 장치 별칭을 확인한다. 포트를 추측해서 지정하지 않는다. `v4l2-ctl`이 없으면 기존 강의의 카메라 확인 방법을 사용한다.

여러 `/dev/video*` 노드가 보인다고 모두 별도의 카메라는 아니다. 이번 확인에서 영상 입력으로 사용한 외장 카메라는 `/dev/video4`와 `/dev/video6`이다. 노트북 내장 HP True Vision 카메라(`/dev/video0` 등)는 이번 학습 입력에서 제외한다. 보정 파일을 지우거나 새 보정 ID를 임의로 만들지 않는다.

### 4-2. 실제 연결 확인 결과

#### 로봇팔

| 역할 | 녹화에 사용할 경로 | 현재 연결 | USB 일련번호 |
|---|---|---|---|
| 리더암 | `/dev/serial/by-id/usb-ROBOTIS_OpenRB-150_E743255D50323952582E3120FF07301D-if00` | `/dev/ttyACM0` | `E743255D50323952582E3120FF07301D` |
| 서브암 / 팔로워 | `/dev/serial/by-id/usb-ROBOTIS_OpenRB-150_1B8E02E050323952582E3120FF071F2E-if00` | `/dev/ttyACM1` | `1B8E02E050323952582E3120FF071F2E` |

기존 `/etc/udev/rules.d/99-omx.rules`는 이전 팔의 일련번호여서 `/dev/omx_*` 별칭이 생성되지 않는다. 녹화에서는 위 새 장치의 고정 by-id 경로를 직접 사용한다. 2026-10-20 SDK 읽기 점검으로 리더 1~6번·팔로워 11~16번의 모델과 설정을 확인했고 하드웨어 오류는 모두 0이었다. 모터 쓰기·토크 활성화·팔 움직임은 실행하지 않았다.

기존 보정 파일:

```text
/home/team2/.cache/huggingface/lerobot/calibration/teleoperators/omx_leader/omx_leader_arm.json
/home/team2/.cache/huggingface/lerobot/calibration/robots/omx_follower/omx_follower_arm.json
```

두 파일 모두 `shoulder_pan`, `shoulder_lift`, `elbow_flex`, `wrist_flex`, `wrist_roll`, `gripper` 항목이 존재한다. 보정 파일의 존재는 현재 연결된 팔에서 보정이 유효하다는 검증과는 다르므로 녹화 전 원격조종 상태를 확인한다.

#### 카메라

| 학습 뷰 | 장치명 | 현재 영상 장치 | 공통 설정 |
|---|---|---|---|
| `front` | SNAP U2 외장 웹캠 | `/dev/video6` | 640×480 / 요청 FPS 30 / MJPG |
| `wrist` | Innomaker-U20CAM-720P 서브암 카메라 | `/dev/video4` | 640×480 / 요청 FPS 30 / MJPG |

연결 순서에 따른 번호 변경을 줄이기 위해 실제 명령에는 다음 고정 경로를 사용한다.

```text
front: /dev/v4l/by-id/usb-HFSD-231214-J_SNAP_U2-video-index0
wrist: /dev/v4l/by-id/usb-Innomaker_Innomaker-U20CAM-720P_SN0001-video-index0
```

두 장치를 동시에 열어 각각 40프레임을 수신했고, 반환 영상 크기는 둘 다 640×480이었다. 드라이버의 지원 모드와 OpenCV의 보고 FPS는 30으로 확인됐다. 이 짧은 확인으로 장시간 녹화에서의 안정적인 30FPS 처리가 검증된 것은 아니다. 스냅샷과 진단 JSON은 `/tmp/omx_device_check_20261019/`에 임시 저장했다.

영상에서 확인한 사항:

- `front`: 작업대의 로봇팔·선반·바구니가 보인다. 핑키가 주차한 실제 집기 구도는 아직 확인하지 않았다.
- `wrist`: 현재 팔 자세에서는 선반 표면이 대부분 보인다. 집기 자세에서 물건과 그리퍼 접촉 부위가 보이는지 녹화 전에 확인한다. 보이지 않으면 카메라 방향·팔의 대기 자세를 조정한다.
- 뷰 이름 `front`와 `wrist`는 이번 프로젝트의 입력 이름이다. 이후 수집·학습·평가에서 동일하게 유지한다.

### 4-3. 확인된 공통 설정

아래는 장치값을 한곳에 모은 참고 설정이다. 이후 녹화·학습·평가 블록에는 필요한 값을 직접 넣었으므로 이 변수를 먼저 실행하지 않아도 된다. 카메라 구도와 원격조종을 확인한 뒤 녹화를 시작한다.

```bash
HF_USER='chun-hwan'
PROJECT_DIR='/home/team2/dev_ws/omx_imitation_project'

FOLLOWER_PORT='/dev/serial/by-id/usb-ROBOTIS_OpenRB-150_1B8E02E050323952582E3120FF071F2E-if00'
LEADER_PORT='/dev/serial/by-id/usb-ROBOTIS_OpenRB-150_E743255D50323952582E3120FF07301D-if00'
FOLLOWER_ID='omx_follower_arm'
LEADER_ID='omx_leader_arm'
CAMERAS='{ front: {type: opencv, index_or_path: "/dev/v4l/by-id/usb-HFSD-231214-J_SNAP_U2-video-index0", width: 640, height: 480, fps: 30, fourcc: MJPG}, wrist: {type: opencv, index_or_path: "/dev/v4l/by-id/usb-Innomaker_Innomaker-U20CAM-720P_SN0001-video-index0", width: 640, height: 480, fps: 30, fourcc: MJPG}}'

TASK_LEFT='Move one item from the cart to the left basket and return to the waiting pose.'
TASK_RIGHT='Move one item from the cart to the right basket and return to the waiting pose.'
MODEL_VERSION='v2'
```

이번 설정은 외장 카메라 두 대를 사용한다. 로봇에 장착한 카메라만 쓰거나 웹캠만 쓰는 설정으로 중간에 바꾸지 않는다. 구도를 바꿔야 한다면 본 수집 전에 확정하고 이후 녹화와 실행에서 유지한다. 모든 좌우 녹화·평가 명령에는 위와 같은 카메라 경로와 설정을 직접 넣었다.

위 카메라 문자열과 로봇·리더 설정을 설치된 LeRobot의 `RecordConfig` 파서로 검증했다. 두 뷰 모두 `OpenCVCameraConfig`로 해석됐고, 고정 경로·640×480·30FPS·MJPG 값이 전달되는 것을 확인했다. 문서의 Bash 명령 블록도 구문 검사를 통과했다. 이 파서 검사는 로봇 연결이나 녹화를 실행하지 않는다. 5090 PC의 설치 환경과 실제 학습은 별도 확인이 필요하다.

## 5. 데이터셋과 모델 이름

| 용도 | HF 저장소 ID |
|---|---|
| 반복 시험 녹화 | `chun-hwan/omx-unload-left-pilot` (매번 초기화 후 재사용) |
| 기존 왼쪽 본 녹화 | `chun-hwan/omx-unload-left-v1` |
| 높은 물체 제외 후 왼쪽 재녹화 | `chun-hwan/omx-unload-left-v2` |
| 기존 오른쪽 본 녹화 | `chun-hwan/omx-unload-right-v1` |
| 새 팔 기준 오른쪽 본 녹화 | `chun-hwan/omx-unload-right-v2` |
| 오른쪽 반복 시험 녹화 | `chun-hwan/omx-unload-right-pilot` |
| 왼쪽 학습 모델 | `chun-hwan/omx-unload-left-act-v1` |
| 기존 오른쪽 학습 모델 | `chun-hwan/omx-unload-right-act-v1` |
| 새 오른쪽 학습 모델 | `chun-hwan/omx-unload-right-act-v2` |
| 왼쪽 첫 평가 | `chun-hwan/eval_omx_unload_left_trial01` |
| 오른쪽 첫 평가 | `chun-hwan/eval_omx_unload_right_trial01` |

이름은 작업용 제안이며 저장소가 이미 만들어졌다는 뜻은 아니다. LeRobot은 업로드할 때 데이터셋 저장소를 생성할 수 있으므로 HF 웹에서 미리 빈 저장소를 만들 필요는 없다. fine-grained 권한을 특정 저장소로 제한했다면 그 설정에 맞춰 저장소 생성·쓰기 권한을 준비한다.

본 녹화 명령은 `--dataset.push_to_hub=true`로 업로드를 켠다. `--dataset.private=true`로 비공개 생성을 요청한다. 시험 녹화는 빠르게 반복할 수 있도록 로컬 저장을 기본으로 하고, 필요할 때만 8절의 명령으로 같은 HF 시험 저장소에 덮어쓴다. 이미 존재하는 저장소의 공개 범위가 바뀌었다고 가정하지 말고 웹에서 확인한다.

## 6. 에피소드는 어떻게 찍는가

한 에피소드는 다음 범위다.

> 열린 그리퍼로 대기 → 물건 하나에 접근 → 잡기 → 들어 올리기 → 지정 장바구니에 놓기 → 열린 그리퍼로 대기 자세 복귀

9종류 중 물건 3개를 골라 싣고 다음 순서로 수집한다. A·B·C를 실었다면 A를 옮긴 뒤 B·C 그대로 다음 녹화를 하고, B를 옮긴 뒤 C 그대로 마지막 녹화를 한다.

| 에피소드 | 카트 시작 상태 | 한 번 수행할 동작 | 끝난 상태 |
|---|---|---|---|
| 1 | 3개 | 하나 옮기고 복귀 | 2개 |
| 2 | 남은 2개 그대로 | 하나 옮기고 복귀 | 1개 |
| 3 | 마지막 1개 | 하나 옮기고 복귀 | 빈 카트 |

중간 에피소드마다 카트에 물건을 다시 채우지 않는다. 목적지 장바구니에 옮겨진 물건도 한 카트를 비울 때까지 그대로 둔다. 따라서 카트의 남은 물건과 목적지의 쌓인 물건이 모두 실제 흐름에 맞게 보인다.

카트를 비운 뒤 리셋 시간에 카트를 다시 채우고 목적지 장바구니를 초기 상태로 비운다. 물건 배치를 조금 바꿔 반복한다. 실제 운용에서 장바구니가 비어 있지 않은 상태로 시작한다면 그 조건은 별도 시연과 평가에 추가한다.

예를 들어 첫 카트는 A·B·C, 다음 카트는 D·E·F, 그다음은 A·D·G처럼 조합을 바꾼다. 같은 카트의 3→2→1→0 도중에 다른 물건으로 교체하지 않는다. A~I는 9종류를 구분하기 위한 임시 이름이다.

### 녹화 키와 리셋 시간

현재 방향키로 실제 녹화를 진행했다. 다만 저장·인코딩 중 누른 `→`가 다음 녹화 시작에 남아 0프레임 저장 오류를 일으킨 것으로 의심되는 사례가 있다. `→`는 짧게 한 번 누르고 다음 단계 로그를 확인한다.

점검 결과: 현재 확인한 데스크톱은 X11이고, 설치된 `pynput`은 1.8.2이며, LeRobot의 `is_headless()`는 False였다. 초기화 대기 후 키 리스너의 시작·종료는 정상 동작했다. 이후 사용자가 로봇을 연결하지 않는 키 입력 단독 테스트를 실행했고, `Right arrow key pressed. Exiting loop...` 메시지와 녹화→준비 / 준비→녹화 전환이 반복해서 출력됐다. 키 인식과 이벤트 플래그 전환은 정상이다. 다만 이 결과만으로 실제 녹화에서의 전환 지연·미동작 원인이 해결됐다고 판단하지 않는다. 다음 단계는 실제 시험 녹화에서 키 수신 메시지와 단계 전환 로그를 확인하는 것이다. 로봇 제어 코드나 키 입력 구현은 변경하지 않았다.

| 상황 / 키 | 동작 |
|---|---|
| 녹화 중 `→` | 현재 녹화를 끝내고 리셋 단계로 이동 |
| 리셋 중 `→` | 리셋 대기를 끝내고 다음 녹화로 이동 |
| `←` | 현재 에피소드를 취소하고 재녹화 요청 |
| `Esc` | 세션 종료 요청. 저장·인코딩·업로드 절차로 진행 |

성공적으로 복귀한 뒤 `→`를 누르고, 리셋 단계에서 다음 장면을 확인한 뒤 다시 `→`를 누른다. 리셋 시간에도 원격조종은 가능하지만 데이터셋 프레임으로 기록되지는 않는다.

아래 예제의 30초 녹화·60초 리셋은 초기 설정이다. 실제 시연 속도에 맞춰 조정한다. 녹화 제한 시간이 먼저 끝나 미완료 시연이 저장되지 않게 한다. 준비가 안 됐는데 리셋 타이머가 끝나면 다음 녹화가 시작되므로 시간 여유를 둔다.

실패한 시연은 `←`로 취소하고 에피소드 시작 상태를 복구한다. 해당 에피소드에서 이미 옮긴 물건이 있다면 다시 되돌린다. `Esc`는 실패 데이터 삭제 키가 아니며 진행 중 버퍼가 저장될 수 있다. 키 입력이 실제로 반영되는지는 시험 녹화에서 확인한다.

## 7. 수집량과 수집 순서

수집량은 방향별로 계산한다. 약 100개로 성공률이 보장되는 것은 아니다.

| 단계 | 왼쪽 | 오른쪽 | 목적 |
|---|---:|---:|---|
| 시험 녹화 | 별도 데이터셋 3에피소드(1카트) | 필요 시 별도 시험 | 방향키·영상·제어·저장·업로드 확인 |
| 첫 학습용 | 60에피소드(20카트) | 60에피소드(20카트) | 양쪽 합계 120개로 각 방향 첫 모델 학습·평가 |
| 평가 후 보강 | 추가 39에피소드(13카트) | 추가 39에피소드(13카트) | 필요하면 실패 조건 중심으로 추가 |
| 보강 후 누적 목표 | 99에피소드(33카트) | 99에피소드(33카트) | 양쪽 누적 합계 198개로 새 모델 학습·평가 |

카트 한 번 비우기가 3에피소드다. 한쪽 기준 20카트가 60에피소드, 33카트가 99에피소드다. 양쪽을 각각 99개씩 모으면 본 데이터는 총 198에피소드다. 첫 60개 평가 후 필요하면 13카트, 즉 39에피소드를 추가한다. 실패 시연을 취소·재녹화했다면 실제 정상 저장된 에피소드 수를 기준으로 센다.

99개는 첫 60개를 포함한 누적 수량이다. 처음부터 99개를 모두 모으는 대신 60개에서 실제 성공률을 확인해 보강 대상을 정한다. 시험 녹화와 평가 기록은 본 학습용 수량에서 제외한다.

### 물건 9종류의 수집 배분

- 첫 60에피소드에서는 한쪽 방향 기준으로 물건별 약 6~7회씩 옮기도록 분배한다. 특정 종류가 누락되지 않게 한다.
- 누적 99에피소드라면 9종류를 각각 11회씩 옮기는 균등 배분이 가능하다. 왼쪽·오른쪽을 각각 따로 센다.
- 균등 배분 예시는 첫 60개에서 A~F를 각 7회, G~I를 각 6회 옮기고, 추가 39개에서 A~F를 각 4회, G~I를 각 5회 옮기는 것이다.
- 위 배분은 관리용 예시다. 첫 평가에서 특정 물건·위치가 자주 실패하면 그 조건을 우선 보강하고 실제 수량을 기록한다.
- 물건 조합뿐 아니라 카트 안 위치와 집는 순서를 바꿀 수 있도록 배치한다. 특정 물건만 늘 마지막에 남는 편향을 줄인다.
- 기록에는 방향, 카트 번호, 실은 물건 3종, 실제 집은 순서, 저장된 에피소드 번호를 남긴다.

최소한 다음 장면을 포함한다.

- 물건이 3개·2개·1개 남아 있는 상태.
- 카트 중앙, 좌우, 팔에서 가까운 곳과 먼 곳에서 집는 상태.
- 실제 사용할 물건 종류와 실제 가능한 방향·자세.
- 주변 물건과 목적지에 이미 옮겨진 물건이 보이는 상태.

처음부터 물건 종류, 주차 위치, 조명을 한꺼번에 크게 바꾸지 않는다. 우선 실제 시연 가능한 범위에서 위치를 조금 바꾼다. 물건 선택은 접근하기 쉬운 것부터 등 일관된 기준을 사용한다. 항상 한 위치만 먼저 집어 특정 남은 개수와 특정 위치가 완전히 묶이지 않도록 배치를 바꾼다.

## 8. 시험 녹화 3개 — 같은 이름으로 덮어쓰기

시험 데이터셋은 `omx-unload-left-pilot` 하나만 사용한다. 잘 잡히는 물건 3개로 카트를 한 번 비우며 영상·손목 동작·방향키를 확인한다. 시험을 반복할 때 이름이나 에피소드 수를 계속 늘리지 않는다.

현재 설치본에는 `lerobot-record --overwrite` 옵션이 없다. `--resume=true`는 덮어쓰기가 아니라 기존 데이터에 에피소드를 추가하는 옵션이므로 이 시험에는 사용하지 않는다. 아래 블록은 이전 로컬 시험 폴더를 삭제하고 같은 경로에 새로 녹화한다. 삭제 대상은 시험 데이터뿐이며, 본 수집 명령에는 이 초기화를 사용하지 않는다.

기존 녹화를 종료한 뒤 **아래 블록 전체를 매번 실행**한다. `rm`과 `lerobot-record`는 `&&`로 연결돼 있어 삭제 성공 후 녹화가 시작된다. `lerobot-record` 부분만 따로 재실행하지 않는다. 녹화가 끝나면 `→`로 준비 단계로 넘기고, 준비가 끝나면 다시 `→`로 다음 녹화를 시작한다. 30초·60초를 모두 기다릴 필요는 없다.

```bash
source /home/team2/venv/il/bin/activate
cd /home/team2/il_ws/src/lerobot

PILOT_ROOT="$HOME/.cache/huggingface/lerobot/chun-hwan/omx-unload-left-pilot"
rm -rf -- "$PILOT_ROOT" && \
lerobot-record \
  --robot.type=omx_follower \
  --robot.port=/dev/serial/by-id/usb-ROBOTIS_OpenRB-150_1B8E02E050323952582E3120FF071F2E-if00 \
  --robot.id=omx_follower_arm \
  --robot.cameras='{ front: {type: opencv, index_or_path: "/dev/v4l/by-id/usb-HFSD-231214-J_SNAP_U2-video-index0", width: 640, height: 480, fps: 30, fourcc: MJPG}, wrist: {type: opencv, index_or_path: "/dev/v4l/by-id/usb-Innomaker_Innomaker-U20CAM-720P_SN0001-video-index0", width: 640, height: 480, fps: 30, fourcc: MJPG}}' \
  --teleop.type=omx_leader \
  --teleop.port=/dev/serial/by-id/usb-ROBOTIS_OpenRB-150_E743255D50323952582E3120FF07301D-if00 \
  --teleop.id=omx_leader_arm \
  --display_data=true \
  --dataset.repo_id=chun-hwan/omx-unload-left-pilot \
  --dataset.root="$PILOT_ROOT" \
  --dataset.single_task="Move one item from the cart to the left basket and return to the waiting pose." \
  --dataset.fps=30 \
  --dataset.num_episodes=3 \
  --dataset.episode_time_s=30 \
  --dataset.reset_time_s=60 \
  --dataset.push_to_hub=false \
  --dataset.private=true
```

현재 설치본은 Rerun 뷰어를 초기화한 뒤 데이터셋 폴더를 생성한다. 기존 폴더가 남아 있으면 `FileExistsError`로 실제 녹화·카메라 전송이 시작되지 않고 뷰어 초기화 로그만 보일 수 있다. 위 초기화는 이 폴더 충돌을 없앤다. 그래도 영상이 없으면 터미널의 첫 오류를 확인한다.

기존 버전으로 남은 로컬 시험 데이터도 버리려면 아래 명령을 한 번 실행한다. 이후에는 위 고정 이름만 사용한다.

```bash
rm -rf -- \
  "$HOME/.cache/huggingface/lerobot/chun-hwan/omx-unload-left-pilot-v2" \
  "$HOME/.cache/huggingface/lerobot/chun-hwan/omx-unload-left-pilot-v3"
```

시험 결과를 HF에도 올리고 싶을 때만, 정상 종료와 저장 완료 후 아래 명령을 실행한다. `--delete "*"`는 같은 시험 저장소의 이전 파일을 정리하면서 이번 로컬 데이터로 교체한다. 저장소 이름을 바꾸거나 매 시험마다 업로드할 필요는 없다.

```bash
source /home/team2/venv/il/bin/activate
cd /home/team2/il_ws/src/lerobot

hf upload chun-hwan/omx-unload-left-pilot "$HOME/.cache/huggingface/lerobot/chun-hwan/omx-unload-left-pilot" . \
  --repo-type dataset \
  --private \
  --exclude "images/*" \
  --delete "*"
```

확인할 항목:

- [ ] 올바른 카메라 영상이 나오고 집을 범위·놓을 위치·집는 순간이 보인다.
- [ ] 명령 실행 직후 손목이 불필요하게 회전하지 않고 리더 조작에 따른 팔로워 동작이 정상이다.
- [ ] 한 에피소드에 물건 하나 옮기기와 대기 자세 복귀가 모두 들어 있다.
- [ ] 3→2→1→빈 카트 순서로 기록됐다.
- [ ] `→`로 녹화→준비 / 준비→녹화 전환이 되고 `←`·종료 키도 동작한다.
- [ ] 로컬에 영상과 관절 데이터가 저장됐다.
- [ ] 필요한 경우 같은 HF 시험 저장소에 업로드하고 공개 범위를 확인했다.

시험에서 문제가 있으면 본 수집 전에 해결한다. 시험 데이터는 본 학습 데이터에 자동으로 섞이지 않는다. 재시험은 위 초기화·녹화 블록 전체를 다시 실행한다. 본 수집 데이터를 이어 찍을 때는 다음 절의 `--resume=true`를 사용한다.

## 9. 왼쪽 본 녹화 60개 — 처음 수집할 때만

방향키와 시험 저장 검증 후 시작한다. 물건 9종류 중 3개씩 싣고 총 20카트를 비운다. 물건 조합은 카트를 비운 뒤에 바꾼다. 60개를 정상 저장하면 첫 학습·평가 단계로 넘어간다.

```bash
source /home/team2/venv/il/bin/activate
cd /home/team2/il_ws/src/lerobot

lerobot-record \
  --robot.type=omx_follower \
  --robot.port=/dev/serial/by-id/usb-ROBOTIS_OpenRB-150_1B8E02E050323952582E3120FF071F2E-if00 \
  --robot.id=omx_follower_arm \
  --robot.cameras='{ front: {type: opencv, index_or_path: "/dev/v4l/by-id/usb-HFSD-231214-J_SNAP_U2-video-index0", width: 640, height: 480, fps: 30, fourcc: MJPG}, wrist: {type: opencv, index_or_path: "/dev/v4l/by-id/usb-Innomaker_Innomaker-U20CAM-720P_SN0001-video-index0", width: 640, height: 480, fps: 30, fourcc: MJPG}}' \
  --teleop.type=omx_leader \
  --teleop.port=/dev/serial/by-id/usb-ROBOTIS_OpenRB-150_E743255D50323952582E3120FF07301D-if00 \
  --teleop.id=omx_leader_arm \
  --display_data=true \
  --dataset.repo_id=chun-hwan/omx-unload-left-v1 \
  --dataset.single_task="Move one item from the cart to the left basket and return to the waiting pose." \
  --dataset.fps=30 \
  --dataset.num_episodes=60 \
  --dataset.episode_time_s=30 \
  --dataset.reset_time_s=60 \
  --dataset.push_to_hub=true \
  --dataset.private=true
```

중간에 종료했으면 신규 생성 명령을 재실행하지 않고 11절의 재개 명령 블록을 사용한다. 세션 끝은 가능하면 카트를 비운 시점에 맞춘다.

## 10. 오른쪽 본 녹화 60개 — 처음 수집할 때만

현재 새 팔·8종 작업은 [RIGHT_RERECORD.md](RIGHT_RERECORD.md)의 오른쪽 v2 명령을 사용한다. 아래 v1 블록은 이전 작업 참고다.

팔·카메라·주차 위치를 유지하고 목적지만 오른쪽으로 바꾼다. 왼쪽과 별도 데이터셋에 20카트, 60에피소드를 모은다. 여기에도 9종류를 모두 포함한다. 오른쪽으로 원격조종할 수 있는지는 사전 확인한다.

```bash
source /home/team2/venv/il/bin/activate
cd /home/team2/il_ws/src/lerobot

lerobot-record \
  --robot.type=omx_follower \
  --robot.port=/dev/serial/by-id/usb-ROBOTIS_OpenRB-150_1B8E02E050323952582E3120FF071F2E-if00 \
  --robot.id=omx_follower_arm \
  --robot.cameras='{ front: {type: opencv, index_or_path: "/dev/v4l/by-id/usb-HFSD-231214-J_SNAP_U2-video-index0", width: 640, height: 480, fps: 30, fourcc: MJPG}, wrist: {type: opencv, index_or_path: "/dev/v4l/by-id/usb-Innomaker_Innomaker-U20CAM-720P_SN0001-video-index0", width: 640, height: 480, fps: 30, fourcc: MJPG}}' \
  --teleop.type=omx_leader \
  --teleop.port=/dev/serial/by-id/usb-ROBOTIS_OpenRB-150_E743255D50323952582E3120FF07301D-if00 \
  --teleop.id=omx_leader_arm \
  --display_data=true \
  --dataset.repo_id=chun-hwan/omx-unload-right-v1 \
  --dataset.single_task="Move one item from the cart to the right basket and return to the waiting pose." \
  --dataset.fps=30 \
  --dataset.num_episodes=60 \
  --dataset.episode_time_s=30 \
  --dataset.reset_time_s=60 \
  --dataset.push_to_hub=true \
  --dataset.private=true
```

## 11. 데이터 확인과 추가 녹화

### 학습 전 확인

- 좌우 데이터셋이 분리돼 있고 목적지를 잘못 놓은 시연이 없는지 본다.
- 각 에피소드가 성공한 집기·놓기·복귀로 끝나는지 본다.
- 마지막 1개를 옮기는 장면이 충분한지 확인한다.
- 흔들리는 영상, 가려진 집기, 긴 멈춤, 미완료 시연을 확인한다.
- 데이터셋의 `meta/info.json`에서 실제 에피소드 수와 카메라 feature를 확인한다.
- HF 업로드가 끝났는지와 로컬 저장본이 남아 있는지 확인한다.
- 저장된 에피소드를 나중에 삭제할 때는 영상 파일만 임의로 지우지 않고 설치 버전에 맞는 데이터셋 편집 도구를 사용한다.

기본 로컬 위치는 다음과 같다. HF 관련 경로 환경변수나 `--dataset.root`를 바꾸면 달라진다.

```text
~/.cache/huggingface/lerobot/chun-hwan/omx-unload-left-v1/
~/.cache/huggingface/lerobot/chun-hwan/omx-unload-right-v1/
```

### 현재 개수 확인 — 녹화 PC

중단 후에는 마지막 화면의 에피소드 번호 대신 아래 실제 저장 개수를 확인한다. 로그의 번호는 0부터 센다.

```bash
source /home/team2/venv/il/bin/activate
cd /home/team2/il_ws/src/lerobot

python - <<'CHECK'
import json
from pathlib import Path
from lerobot.utils.constants import HF_LEROBOT_HOME
for side in ("left", "right"):
    p = HF_LEROBOT_HOME / "chun-hwan" / f"omx-unload-{side}-v1" / "meta/info.json"
    if not p.exists():
        print(side, "저장된 데이터셋 없음")
        continue
    info = json.loads(p.read_text())
    print(side, "저장:", info["total_episodes"], "프레임:", info["total_frames"])
CHECK
```

### HF에 올라간 왼쪽 개수 확인 — 녹화 PC

터미널의 업로드와 `Exiting` 로그가 끝난 뒤 실행한다. 아래 결과가 로컬의 66개와 일치한 다음 5090 PC에서 첫 학습을 시작한다.

```bash
source /home/team2/venv/il/bin/activate
cd /home/team2/il_ws/src/lerobot

python - <<'CHECK_HF'
import json
from huggingface_hub import hf_hub_download
p = hf_hub_download(
    repo_id="chun-hwan/omx-unload-left-v1",
    repo_type="dataset",
    filename="meta/info.json",
    force_download=True,
)
with open(p) as f:
    info = json.load(f)
print("HF 왼쪽 저장:", info["total_episodes"], "프레임:", info["total_frames"])
CHECK_HF
```

### 중간 중단 후 목표 개수까지 재개 — 왼쪽

현재는 왼쪽 66개로 먼저 학습한다. 이 블록은 이후 보강하기로 정했을 때 사용한다. `TARGET_EPISODES=99`는 누적 목표이며 현재 66개면 자동으로 33개만 추가한다. 중간에 다시 멈춰도 다음 실행에서 저장 개수를 다시 읽어 남은 수량을 계산한다. 다른 목표로 재개하려면 블록 맨 위의 목표 숫자만 정하고 블록 전체를 실행한다.

```bash
source /home/team2/venv/il/bin/activate
cd /home/team2/il_ws/src/lerobot

TARGET_EPISODES=99
CURRENT_EPISODES=$(python - <<'COUNT'
import json
from lerobot.utils.constants import HF_LEROBOT_HOME
p = HF_LEROBOT_HOME / "chun-hwan" / "omx-unload-left-v1" / "meta/info.json"
print(json.loads(p.read_text())["total_episodes"])
COUNT
) &&
REMAINING_EPISODES=$((TARGET_EPISODES - CURRENT_EPISODES)) &&
if [ "$REMAINING_EPISODES" -gt 0 ]; then
  echo "현재 ${CURRENT_EPISODES}개 → ${REMAINING_EPISODES}개 추가 → 목표 ${TARGET_EPISODES}개"
  lerobot-record \
    --resume=true \
    --robot.type=omx_follower \
    --robot.port=/dev/serial/by-id/usb-ROBOTIS_OpenRB-150_1B8E02E050323952582E3120FF071F2E-if00 \
    --robot.id=omx_follower_arm \
    --robot.cameras='{ front: {type: opencv, index_or_path: "/dev/v4l/by-id/usb-HFSD-231214-J_SNAP_U2-video-index0", width: 640, height: 480, fps: 30, fourcc: MJPG}, wrist: {type: opencv, index_or_path: "/dev/v4l/by-id/usb-Innomaker_Innomaker-U20CAM-720P_SN0001-video-index0", width: 640, height: 480, fps: 30, fourcc: MJPG}}' \
    --teleop.type=omx_leader \
    --teleop.port=/dev/serial/by-id/usb-ROBOTIS_OpenRB-150_E743255D50323952582E3120FF07301D-if00 \
    --teleop.id=omx_leader_arm \
    --display_data=true \
    --dataset.repo_id=chun-hwan/omx-unload-left-v1 \
    --dataset.single_task="Move one item from the cart to the left basket and return to the waiting pose." \
    --dataset.fps=30 \
    --dataset.num_episodes="$REMAINING_EPISODES" \
    --dataset.episode_time_s=30 \
    --dataset.reset_time_s=60 \
    --dataset.push_to_hub=true \
    --dataset.private=true
else
  echo "이미 ${CURRENT_EPISODES}개 저장됨. 목표 ${TARGET_EPISODES}개까지 추가할 녹화 없음."
fi
```

### 중간 중단 후 목표 개수까지 재개 — 오른쪽

오른쪽 데이터셋이 이미 있을 때 사용한다. 누적 목표 99개 기준이며, 현재 60개라면 자동으로 39개만 추가한다. 처음 60개를 모으는 중 중단했다면 블록 맨 위를 `TARGET_EPISODES=60`으로 정하고 전체를 실행한다. 오른쪽 데이터셋이 아직 없으면 10절의 신규 수집 명령을 사용한다.

```bash
source /home/team2/venv/il/bin/activate
cd /home/team2/il_ws/src/lerobot

TARGET_EPISODES=99
CURRENT_EPISODES=$(python - <<'COUNT'
import json
from lerobot.utils.constants import HF_LEROBOT_HOME
p = HF_LEROBOT_HOME / "chun-hwan" / "omx-unload-right-v1" / "meta/info.json"
print(json.loads(p.read_text())["total_episodes"])
COUNT
) &&
REMAINING_EPISODES=$((TARGET_EPISODES - CURRENT_EPISODES)) &&
if [ "$REMAINING_EPISODES" -gt 0 ]; then
  echo "현재 ${CURRENT_EPISODES}개 → ${REMAINING_EPISODES}개 추가 → 목표 ${TARGET_EPISODES}개"
  lerobot-record \
    --resume=true \
    --robot.type=omx_follower \
    --robot.port=/dev/serial/by-id/usb-ROBOTIS_OpenRB-150_1B8E02E050323952582E3120FF071F2E-if00 \
    --robot.id=omx_follower_arm \
    --robot.cameras='{ front: {type: opencv, index_or_path: "/dev/v4l/by-id/usb-HFSD-231214-J_SNAP_U2-video-index0", width: 640, height: 480, fps: 30, fourcc: MJPG}, wrist: {type: opencv, index_or_path: "/dev/v4l/by-id/usb-Innomaker_Innomaker-U20CAM-720P_SN0001-video-index0", width: 640, height: 480, fps: 30, fourcc: MJPG}}' \
    --teleop.type=omx_leader \
    --teleop.port=/dev/serial/by-id/usb-ROBOTIS_OpenRB-150_E743255D50323952582E3120FF07301D-if00 \
    --teleop.id=omx_leader_arm \
    --display_data=true \
    --dataset.repo_id=chun-hwan/omx-unload-right-v1 \
    --dataset.single_task="Move one item from the cart to the right basket and return to the waiting pose." \
    --dataset.fps=30 \
    --dataset.num_episodes="$REMAINING_EPISODES" \
    --dataset.episode_time_s=30 \
    --dataset.reset_time_s=60 \
    --dataset.push_to_hub=true \
    --dataset.private=true
else
  echo "이미 ${CURRENT_EPISODES}개 저장됨. 목표 ${TARGET_EPISODES}개까지 추가할 녹화 없음."
fi
```

### 목표 개수와 관계없이 한 카트만 추가 — 왼쪽 3개

현재 저장된 개수에 3개를 더한다. 중간에 멈춘 목표 수량을 자동 계산하는 용도가 아니라, 실제로 시연 3개를 추가하고 싶을 때 사용한다.

```bash
source /home/team2/venv/il/bin/activate
cd /home/team2/il_ws/src/lerobot

lerobot-record \
  --resume=true \
  --robot.type=omx_follower \
  --robot.port=/dev/serial/by-id/usb-ROBOTIS_OpenRB-150_1B8E02E050323952582E3120FF071F2E-if00 \
  --robot.id=omx_follower_arm \
  --robot.cameras='{ front: {type: opencv, index_or_path: "/dev/v4l/by-id/usb-HFSD-231214-J_SNAP_U2-video-index0", width: 640, height: 480, fps: 30, fourcc: MJPG}, wrist: {type: opencv, index_or_path: "/dev/v4l/by-id/usb-Innomaker_Innomaker-U20CAM-720P_SN0001-video-index0", width: 640, height: 480, fps: 30, fourcc: MJPG}}' \
  --teleop.type=omx_leader \
  --teleop.port=/dev/serial/by-id/usb-ROBOTIS_OpenRB-150_E743255D50323952582E3120FF07301D-if00 \
  --teleop.id=omx_leader_arm \
  --display_data=true \
  --dataset.repo_id=chun-hwan/omx-unload-left-v1 \
  --dataset.single_task="Move one item from the cart to the left basket and return to the waiting pose." \
  --dataset.fps=30 \
  --dataset.num_episodes=3 \
  --dataset.episode_time_s=30 \
  --dataset.reset_time_s=60 \
  --dataset.push_to_hub=true \
  --dataset.private=true
```

### 목표 개수와 관계없이 한 카트만 추가 — 오른쪽 3개

```bash
source /home/team2/venv/il/bin/activate
cd /home/team2/il_ws/src/lerobot

lerobot-record \
  --resume=true \
  --robot.type=omx_follower \
  --robot.port=/dev/serial/by-id/usb-ROBOTIS_OpenRB-150_1B8E02E050323952582E3120FF071F2E-if00 \
  --robot.id=omx_follower_arm \
  --robot.cameras='{ front: {type: opencv, index_or_path: "/dev/v4l/by-id/usb-HFSD-231214-J_SNAP_U2-video-index0", width: 640, height: 480, fps: 30, fourcc: MJPG}, wrist: {type: opencv, index_or_path: "/dev/v4l/by-id/usb-Innomaker_Innomaker-U20CAM-720P_SN0001-video-index0", width: 640, height: 480, fps: 30, fourcc: MJPG}}' \
  --teleop.type=omx_leader \
  --teleop.port=/dev/serial/by-id/usb-ROBOTIS_OpenRB-150_E743255D50323952582E3120FF07301D-if00 \
  --teleop.id=omx_leader_arm \
  --display_data=true \
  --dataset.repo_id=chun-hwan/omx-unload-right-v1 \
  --dataset.single_task="Move one item from the cart to the right basket and return to the waiting pose." \
  --dataset.fps=30 \
  --dataset.num_episodes=3 \
  --dataset.episode_time_s=30 \
  --dataset.reset_time_s=60 \
  --dataset.push_to_hub=true \
  --dataset.private=true
```

`num_episodes`는 이번 실행에서 추가할 개수다. `--resume=true`는 녹화 데이터셋에 추가하는 옵션이며 덮어쓰기가 아니다. 모터 경고로 멈춘 시연은 저장 개수와 별개로 성공 여부를 검수한다. 기존 본 데이터 폴더는 삭제하지 않는다.

### PC 두 대의 역할과 전달 순서

| 단계 | 실행할 PC | 작업 |
|---|---|---|
| 녹화 | 현재 OMX 연결 PC | 리더암·서브암·카메라로 시연을 수집하고 HF에 데이터셋 업로드 |
| 학습 | RTX 5090 PC | HF의 좌우 데이터셋을 내려받아 ACT 모델 두 개를 학습하고 HF에 모델 업로드 |
| 실제 평가 | 현재 OMX 연결 PC | HF의 학습 모델을 불러와 실제 팔에서 평가 |

5090 PC에 로봇팔이나 카메라를 옮겨 연결할 필요는 없다. 저장된 영상·관절 상태·행동 데이터로 학습한다. 현재 PC의 USB 포트나 보정 파일도 학습 명령에는 넣지 않는다.

비공개 데이터셋을 읽고 모델을 업로드할 수 있도록 5090 PC에서도 HF에 로그인한다. 다른 PC에서 로그인했다고 자동 인증되지는 않는다. 이번 가이드에서는 동일한 `chun-hwan` 계정을 사용한다. 토큰은 해당 PC의 로그인 화면에 입력하고 문서나 메신저로 옮기지 않는다.

5090 PC의 환경에는 현재 녹화 환경과 호환되는 LeRobot 코드와 데이터셋 포맷이 필요하다. 현재 PC에서 확인한 기준은 다음과 같다.

```text
LeRobot: 0.4.4
LeRobot Git commit: 8fff0fde7c79f23a93d845d1a50e985de01f8b8a
소스 변경 상태: 팔로워 시작 시 손목 목표를 현재 원시 위치로 맞추는 4줄 변경 있음
torch: 2.10.0
torchvision: 0.25.0
torchcodec: 0.10.0
huggingface_hub: 0.35.3
```

위 버전은 현재 녹화 PC에서 읽은 값이며 5090 PC에서 설치·검증됐다는 뜻은 아니다. 우선 같은 LeRobot 소스와 호환되는 의존성 조합을 사용한다. 5090은 Blackwell 지원 PyTorch CUDA 빌드가 필요하다. PyTorch 공식 문서는 2.7에서 Blackwell과 CUDA 12.8 빌드 지원을 소개한다. 현재 LeRobot의 `torch` 요구 범위는 `>=2.2.1,<2.11.0`이므로 GPU 지원만 보고 최신 패키지로 일괄 업그레이드하지 않는다. 실제 설치 명령은 5090 PC의 OS·드라이버·기존 환경을 확인한 뒤 정한다.

### 5090 PC에서 학습 전 확인

아래 명령은 Linux 또는 WSL의 Bash 기준이다. 5090 PC의 학습용 가상환경을 먼저 활성화한다. 이 PC의 사용자명이나 소스 경로가 `/home/team2`와 같다고 가정하지 않는다.

```bash
hf auth whoami
nvidia-smi
python - <<'PY'
import torch
print('torch:', torch.__version__)
print('torch CUDA build:', torch.version.cuda)
print('CUDA available:', torch.cuda.is_available())
if not torch.cuda.is_available():
    raise SystemExit('CUDA 사용 불가: 학습 환경 확인 필요')
print('GPU:', torch.cuda.get_device_name(0))
print('compute capability:', torch.cuda.get_device_capability(0))
x = torch.ones((4, 4), device='cuda')
print('CUDA matmul check:', (x @ x).sum().item())
PY
```

GPU가 보이는 것뿐 아니라 위 작은 CUDA 연산까지 성공하는지 확인한다. 장시간 학습은 이 문서 작성 중 실행하지 않았다.

아래 학습 명령에는 사용자명·모델 버전·출력 경로·배치 크기를 직접 넣었다. 별도 공통 변수를 설정하지 않아도 된다. 5090 PC의 학습용 가상환경에는 `lerobot-train`이 설치돼 있어야 한다.

배치 크기 16은 초기 제안이다. GPU 메모리와 처리 시간을 확인해 조정한다. 데이터가 추가됐다면 학습 시작 로그의 실제 에피소드 수와 HF 메타데이터가 일치하는지 확인한다.

## 12. 왼쪽 ACT 모델 학습 — RTX 5090 PC

현재 왼쪽 로컬 저장본은 66개다. HF에도 66개가 반영된 것을 확인하고, 5090 PC에서 학습용 가상환경을 활성화한 뒤 아래 블록을 실행한다. 실패 의심 시연 검수는 저장 개수 확인과 별개다. 100,000스텝은 강의·설치 코드에 맞춘 초기 설정이며 성능을 보장하지 않는다. CUDA 메모리가 부족하면 배치 크기를 낮춘다.

```bash
lerobot-train \
  --dataset.repo_id=chun-hwan/omx-unload-left-v1 \
  --policy.type=act \
  --policy.device=cuda \
  --policy.repo_id=chun-hwan/omx-unload-left-act-v1 \
  --policy.push_to_hub=true \
  --output_dir="$HOME/omx_imitation_training/outputs/omx_left_act_v1" \
  --job_name=omx_left_act_v1 \
  --batch_size=16 \
  --steps=100000 \
  --save_checkpoint=true \
  --save_freq=10000 \
  --wandb.enable=false
```

v1 학습의 5090 PC 로컬 최종 체크포인트:

```text
~/omx_imitation_training/outputs/omx_left_act_v1/checkpoints/last/pretrained_model/
```

HF 모델 저장소의 공개 범위는 데이터셋의 `private=true` 설정과 별개다. 비공개 모델이 필요하면 모델 저장소 설정을 별도로 확인한 뒤 업로드한다. 위 예제에는 모델 비공개 설정을 지정하지 않았다.

## 13. 오른쪽 ACT 모델 학습 — RTX 5090 PC

현재 오른쪽 v2 학습은 [RIGHT_RERECORD.md](RIGHT_RERECORD.md)의 7절 또는 아래 14절을 사용한다. 아래 v1 블록은 이전 작업 참고다.

5090 PC에서 우선 왼쪽 학습이 끝난 뒤 오른쪽을 순차 실행한다.

```bash
lerobot-train \
  --dataset.repo_id=chun-hwan/omx-unload-right-v1 \
  --policy.type=act \
  --policy.device=cuda \
  --policy.repo_id=chun-hwan/omx-unload-right-act-v1 \
  --policy.push_to_hub=true \
  --output_dir="$HOME/omx_imitation_training/outputs/omx_right_act_v1" \
  --job_name=omx_right_act_v1 \
  --batch_size=16 \
  --steps=100000 \
  --save_checkpoint=true \
  --save_freq=10000 \
  --wandb.enable=false
```

v1 학습의 5090 PC 로컬 최종 체크포인트:

```text
~/omx_imitation_training/outputs/omx_right_act_v1/checkpoints/last/pretrained_model/
```

두 모델의 로컬 체크포인트와 HF 업로드 결과를 각각 확인한다. 업로드에 실패해도 로컬 모델이 정상 저장돼 있다면 학습을 처음부터 다시 할 필요는 없다.

## 14. 학습 중단과 데이터 추가 후 처리

### 중단된 학습 이어서 실행하기 — 왼쪽 v1

5090 PC의 학습용 가상환경에서 실행한다. 마지막 체크포인트의 설정을 그대로 불러오므로 처음 학습의 모든 옵션을 다시 적을 필요는 없다. 데이터 수집의 재개와 구분한다.

```bash
lerobot-train \
  --config_path="$HOME/omx_imitation_training/outputs/omx_left_act_v1/checkpoints/last/pretrained_model/train_config.json" \
  --resume=true
```

### 중단된 학습 이어서 실행하기 — 오른쪽 v1

```bash
lerobot-train \
  --config_path="$HOME/omx_imitation_training/outputs/omx_right_act_v1/checkpoints/last/pretrained_model/train_config.json" \
  --resume=true
```

### 높은 물체 제외 후 새 데이터로 학습 — 왼쪽 v2

[왼쪽 재녹화 문서](LEFT_RERECORD.md)의 8종 데이터 `chun-hwan/omx-unload-left-v2`만 사용해 새로 학습한다. 기존 v1 데이터 66개를 자동으로 합치지 않는다. 새 데이터의 성공 시연·저장 개수와 HF 업로드를 확인한 뒤 5090 PC에서 아래 블록 전체를 실행한다. 기존 학습을 이어가는 `--resume=true`는 사용하지 않는다.

```bash
source "$HOME/venv/omx_train/bin/activate"
cd "$HOME/omx_imitation_training/lerobot"

lerobot-train \
  --dataset.repo_id=chun-hwan/omx-unload-left-v2 \
  --policy.type=act \
  --policy.device=cuda \
  --policy.repo_id=chun-hwan/omx-unload-left-act-v2 \
  --policy.push_to_hub=true \
  --output_dir="$HOME/omx_imitation_training/outputs/omx_left_act_v2" \
  --job_name=omx_left_act_v2 \
  --batch_size=16 \
  --steps=100000 \
  --save_checkpoint=true \
  --save_freq=10000 \
  --wandb.enable=false
```

### 새 팔·8종 오른쪽 데이터로 학습 — 오른쪽 v2

오른쪽 v2 성공 시연과 HF 업로드 확인 후 5090 PC에서 실행한다. 왼쪽 데이터와 기존 오른쪽 v1을 합치지 않는다.

```bash
source "$HOME/venv/omx_train/bin/activate"
cd "$HOME/omx_imitation_training/lerobot"

lerobot-train \
  --dataset.repo_id=chun-hwan/omx-unload-right-v2 \
  --policy.type=act \
  --policy.device=cuda \
  --policy.repo_id=chun-hwan/omx-unload-right-act-v2 \
  --policy.push_to_hub=true \
  --output_dir="$HOME/omx_imitation_training/outputs/omx_right_act_v2" \
  --job_name=omx_right_act_v2 \
  --batch_size=16 \
  --steps=100000 \
  --save_checkpoint=true \
  --save_freq=10000 \
  --wandb.enable=false
```

### 보강 모델 학습 중단 후 재개 — 왼쪽 v2

```bash
lerobot-train \
  --config_path="$HOME/omx_imitation_training/outputs/omx_left_act_v2/checkpoints/last/pretrained_model/train_config.json" \
  --resume=true
```

### 보강 모델 학습 중단 후 재개 — 오른쪽 v2

```bash
lerobot-train \
  --config_path="$HOME/omx_imitation_training/outputs/omx_right_act_v2/checkpoints/last/pretrained_model/train_config.json" \
  --resume=true
```

## 15. 실제 팔에서 첫 평가

### 현재 목표 — 1만~10만 스텝 중 실제로 잘되는 모델 고르기

왼쪽 ACT v1 학습에서 1만 스텝 간격으로 저장한 10개 체크포인트를 비교한다. 학습 스텝이나 loss만으로 최종 모델을 정하지 않고, 같은 조건에서 물건을 왼쪽 바구니에 담는 결과로 선택한다. 오른쪽 모델의 비교는 별도로 진행한다.

이 절의 우선 실행 대상은 다운로드한 **로컬 체크포인트**다. 각 모델은 다음 구조로 보관하고, 비교가 끝날 때까지 기존 모델과 원본 ZIP을 유지한다. 다운로드 완료와 파일 검증은 별개다. 아직 내려받거나 압축을 풀지 않은 모델은 이 경로에 준비된 뒤 시험한다.

```text
/home/team2/omx_models/omx_left_act_v1/
├── 010000/pretrained_model/
├── 020000/pretrained_model/
├── 030000/pretrained_model/
├── 040000/pretrained_model/
├── 050000/pretrained_model/
├── 060000/pretrained_model/
├── 070000/pretrained_model/
├── 080000/pretrained_model/
├── 090000/pretrained_model/
└── 100000/pretrained_model/
```

`pretrained_model`에는 가중치 하나만 넣지 않고 `config.json`, `model.safetensors`, `train_config.json`, 전처리·후처리 JSON과 각각의 정규화 가중치까지 **7개 파일**을 함께 둔다. 현재까지 정리·검증한 모델은 1만·4만·5만·6만·7만·8만·10만 스텝이다. 10만 모델은 `100000/pretrained_model`에 보관했고, 7개 파일·프로세서 참조·가중치 형식·모델 설정 읽기를 확인했다. 7만·8만 모델은 각각 `070000/pretrained_model`, `080000/pretrained_model`에 보관했으며, 두 모델의 7개 파일·프로세서 참조·가중치 형식을 확인했다. 두 모델의 가중치는 서로 다르고, 원본 ZIP은 다운로드 폴더에 유지한다. 이 문서 수정에서 다른 모델의 다운로드나 검증, 팔 실행을 완료한 것으로 표시하지 않는다.

`STEP_PAD`는 실제 압축 해제가 끝난 폴더의 6자리 값이어야 한다. 다운로드 폴더에 ZIP만 있는 상태는 실행 준비가 끝난 것이 아니다. 없는 로컬 경로를 넣으면 모델 로더가 이를 HF 저장소 ID로 해석해 `HFValidationError`와 마지막 `RecordConfig` 오류를 낼 수 있다. 6만 스텝은 `060000/pretrained_model`에 정리했고 CUDA 설정 읽기까지 확인했다.

### 비교 전에 카메라와 물건 배치 고정

아래는 기존 v1 평가용 기준이다. 현재 왼쪽 v2의 반투명 비교 명령은 [LEFT_V2_EVAL.md — 정면 카메라 구도 복원](LEFT_V2_EVAL.md#정면-카메라-구도-복원--반투명-비교)을 사용한다.

정면 카메라는 아래 명령으로 기존 학습 영상과 겹쳐 맞춘다. 기존 영상 40%, 실시간 영상 60%이며, 로봇 베이스와 선반 모서리처럼 움직이지 않는 부분을 기준으로 비교한다. 물건이나 팔의 움직이는 부분을 기준으로 맞추지 않는다. 녹화·다른 카메라 미리보기를 종료한 뒤 실행하고, 맞춘 뒤 `q`로 닫아 카메라를 반환한다.

```bash
ffplay -hide_banner -loglevel error \
  -window_title "OMX alignment - old 40%, live 60%" \
  -f v4l2 \
  -input_format mjpeg \
  -video_size 640x480 \
  -framerate 30 \
  -i /dev/v4l/by-id/usb-HFSD-231214-J_SNAP_U2-video-index0 \
  -filter_threads 1 \
  -vf "movie=/home/team2/dev_ws/omx_imitation_project/camera_reference/front_left_v1_ep000000.png[ref];[in][ref]blend=all_expr='A*0.6+B*0.4'[out]"
```

정면·손목 카메라, 카트와 왼쪽 바구니 위치, 조명, 팔의 대기 자세를 비교 중 유지한다. 카메라가 다시 움직이거나 모터 오류가 난 시험은 모델의 일반 실패와 구분해 기록하고, 조건을 복구한 뒤 다시 시험한다.

물건 9종에 1~9번을 붙여 아래 구성을 채운다. A에는 모양이 서로 다른 대표 물건 3개를 넣고, B·C에는 나머지 물건을 3개씩 배정한다. 구성별 처음 놓는 위치와 방향을 사진으로 남기거나 바닥에 표시해 모델마다 재현한다.

| 구성 | 물건 번호·이름 3개 | 시작 배치 사진 또는 위치 메모 |
| --- | --- | --- |
| A — 1차·2차 공통 | 미기록 | 미기록 |
| B — 2차 | 미기록 | 미기록 |
| C — 2차 | 미기록 | 미기록 |

### 1차 비교 — 10개 모델 × 카트 1회

1. 동일한 구성 A와 시작 배치로 각 모델을 시험한다.
2. 모델당 아래 **3에피소드 명령을 한 번** 실행한다. 한 에피소드는 한 개 집기 → 왼쪽 바구니에 놓기 → 대기 자세 복귀다.
3. 성공하면 물건을 보충하지 않고 카트를 3→2→1→0으로 비운다. 모델을 바꿀 때는 A의 물건 3개와 처음 배치를 다시 준비한다.
4. 각 에피소드는 30초로 고정하고, 준비 시간은 0초로 둔다. **방향키 없이 30초 실행 → 저장 → 다음 30초 실행 → 저장 → 마지막 30초 실행 후 종료**한다. 실행 시간은 약 90초에 모델 로딩·저장·인코딩 시간이 더해진다.
5. 중간 준비 시간이 없으므로 카트와 팔을 손으로 정리하지 않고 이어서 관찰한다. 실패로 물건이 남으면 남은 상태에서 다음 에피소드가 시작하며, 3→2→1→0이 보장되는 것은 아니다. 개입이 필요하면 실행을 중단하고 해당 결과와 미시도 구간을 구분해 기록한 뒤, 같은 시작 배치를 준비해 새 실행으로 재시험한다.
6. 총 30번의 집기 시도로 상위 2~3개를 고른다. 정상 담기 횟수를 우선하고, 복귀와 실패 모습을 함께 본다. 3번만으로 성능이 확정된 것은 아니므로 후보를 2차에서 재시험한다.

아래 블록은 **자동으로 10개 모델을 연속 실행하지 않는다.** 한 번 실행하면 선택한 모델만 3에피소드 시험한다. 맨 위 `STEP_PAD` 한 곳을 표의 값으로 바꾸고 블록 전체를 복사한다. 매 실행마다 평가 데이터셋에 시각을 붙이므로 기존 평가 폴더를 덮어쓰지 않는다. 평가는 로컬에 저장하고 HF 업로드는 하지 않는다.

```bash
source /home/team2/venv/il/bin/activate
cd /home/team2/il_ws/src/lerobot

STEP_PAD="050000"  # 실행할 모델의 스텝: 아래 표의 6자리 값으로 변경
lerobot-record \
  --robot.type=omx_follower \
  --robot.port=/dev/serial/by-id/usb-ROBOTIS_OpenRB-150_1B8E02E050323952582E3120FF071F2E-if00 \
  --robot.id=omx_follower_arm \
  --robot.cameras='{ front: {type: opencv, index_or_path: "/dev/v4l/by-id/usb-HFSD-231214-J_SNAP_U2-video-index0", width: 640, height: 480, fps: 30, fourcc: MJPG}, wrist: {type: opencv, index_or_path: "/dev/v4l/by-id/usb-Innomaker_Innomaker-U20CAM-720P_SN0001-video-index0", width: 640, height: 480, fps: 30, fourcc: MJPG}}' \
  --policy.path="/home/team2/omx_models/omx_left_act_v1/${STEP_PAD}/pretrained_model" \
  --policy.device=cuda \
  --display_data=true \
  --dataset.repo_id="chun-hwan/eval_omx_left_s${STEP_PAD}_cart_$(date +%Y%m%d_%H%M%S)" \
  --dataset.single_task="Move one item from the cart to the left basket and return to the waiting pose." \
  --dataset.fps=30 \
  --dataset.num_episodes=3 \
  --dataset.episode_time_s=30 \
  --dataset.reset_time_s=0 \
  --dataset.push_to_hub=false \
  --dataset.private=true
```

이 설정은 **30초마다 자동 전환**한다. 집기 완료나 빈 카트를 감지해 전환·정지하는 기능은 아니며, 한 에피소드 안에서 실제로 옮긴 물건 수가 달라질 수 있다. 정상 담기 수는 영상에서 실제로 옮긴 물건을 확인해 기록하고, 세 에피소드 실행을 세 개 성공으로 간주하지 않는다.

평가 영상은 `/home/team2/.cache/huggingface/lerobot/chun-hwan/eval_omx_left_s<스텝>_cart_<실행시각>/`에 저장된다. 실행 시각 또는 데이터셋 이름을 아래 표에 남긴다. 세부 결과는 영상과 함께 확인하며, 명령 자체가 성공 여부를 자동 판정하지는 않는다.

| 스텝 | STEP_PAD | 정상 담기 /3 | 대기 자세 복귀 /3 | 무개입 카트 전체 성공 | 실패·개입 / 평가 데이터셋 | 2차 후보 |
| --- | --- | --- | --- | --- | --- | --- |
| 1만 | 010000 | — | — | — | — | — |
| 2만 | 020000 | — | — | — | — | — |
| 3만 | 030000 | — | — | — | — | — |
| 4만 | 040000 | — | — | — | — | — |
| 5만 | 050000 | — | — | — | — | — |
| 6만 | 060000 | — | — | — | — | — |
| 7만 | 070000 | — | — | — | — | — |
| 8만 | 080000 | — | — | — | — | — |
| 9만 | 090000 | — | — | — | — | — |
| 10만 | 100000 | — | — | — | — | — |

### 2차 비교 — 후보별 3가지 구성 × 2회

후보 모델마다 A·B·C를 두 번씩 시험한다. 위 3에피소드 명령의 `STEP_PAD`를 후보 값으로 바꿔 카트마다 한 번 실행한다. **후보 하나당 6카트·18번의 집기 시도**다. 세 후보면 54번, 두 후보면 36번이며, 각각 1차 30번과 별도다. 1차 결과를 2차 18번에 섞어 세지 않는다.

모델마다 A 1회차 → B 1회차 → C 1회차 → A 2회차 → B 2회차 → C 2회차 순서와 시작 배치를 동일하게 맞춘다. 팔이 수행하는 물건 선택 순서까지 사람이 강제하지는 않는다.

아래 표를 후보별로 복사해서 사용한다. 각 시도의 성공까지 걸린 시간과 헛집기·낙하·잘못된 위치에 놓기·복귀 실패·사람 개입을 메모한다. 실패는 30초 제한 내 미완료로 표시하고, 성공한 시도의 시간만 따로 비교한다.

후보 스텝: **미선정**

| 구성 | 반복 | 정상 담기 /3 | 대기 자세 복귀 /3 | 무개입 카트 전체 성공 | 성공 시간·실패·개입 / 평가 데이터셋 |
| --- | --- | --- | --- | --- | --- |
| A | 1 | — | — | — | — |
| B | 1 | — | — | — | — |
| C | 1 | — | — | — | — |
| A | 2 | — | — | — | — |
| B | 2 | — | — | — | — |
| C | 2 | — | — | — | — |

### 성공 기준과 최종 선택 기록

- **정상 담기:** 카트의 물건 한 개를 집어 왼쪽 바구니 안에 놓았다. 헛집기, 바구니 밖 낙하, 사람이 집기·담기를 도운 시도는 정상 담기로 세지 않는다.
- **대기 자세 복귀:** 정상 담기 후 그리퍼를 열고 학습 때의 대기 자세로 돌아왔다. 담기는 성공했지만 복귀가 실패한 경우 두 항목을 구분한다.
- **카트 전체 성공:** 사람의 도움 없이 세 에피소드 모두 정상 담기와 복귀를 마쳤다. 물건이 남았는데 세 번 실행했다는 이유만으로 성공으로 세지 않는다.
- **선택 순서:** 2차 정상 담기 성공률을 우선한다. 비슷하면 무개입 카트 전체 성공, 대기 자세 복귀, 성공 시간과 반복 실패 유형을 함께 비교한다. 차이가 불분명하면 해당 후보만 같은 조건으로 추가 비교한다.

| 후보 스텝 | 정상 담기 /18 | 복귀 /18 | 무개입 카트 전체 성공 /6 | 주요 실패·성공 시간 | 선택 여부·이유 |
| --- | --- | --- | --- | --- | --- |
| 후보 1 — 미선정 | — | — | — | — | — |
| 후보 2 — 미선정 | — | — | — | — | — |
| 후보 3 — 필요 시 | — | — | — | — | — |

- 최종 선택 스텝: **미선정**
- 최종 모델 경로: **미선정**
- 비교 날짜·카메라 기준·선택 이유: **미기록**

### 필요할 때만 — 선택한 로컬 모델 한 에피소드 확인

처음 보는 모델의 동작을 한 번 먼저 확인하려면 아래 블록을 쓴다. `STEP_PAD` 한 곳을 바꾼다. 이 사전 확인은 위의 공통 조건 1차·2차 결과와 구분해 기록한다. 3개 물건이 실린 카트를 한 에피소드만 실행하면 한 개 이동만 평가한다.

```bash
source /home/team2/venv/il/bin/activate
cd /home/team2/il_ws/src/lerobot

STEP_PAD="100000"  # 실행할 모델의 스텝: 아래 표의 6자리 값으로 변경
lerobot-record \
  --robot.type=omx_follower \
  --robot.port=/dev/serial/by-id/usb-ROBOTIS_OpenRB-150_1B8E02E050323952582E3120FF071F2E-if00 \
  --robot.id=omx_follower_arm \
  --robot.cameras='{ front: {type: opencv, index_or_path: "/dev/v4l/by-id/usb-HFSD-231214-J_SNAP_U2-video-index0", width: 640, height: 480, fps: 30, fourcc: MJPG}, wrist: {type: opencv, index_or_path: "/dev/v4l/by-id/usb-Innomaker_Innomaker-U20CAM-720P_SN0001-video-index0", width: 640, height: 480, fps: 30, fourcc: MJPG}}' \
  --policy.path="/home/team2/omx_models/omx_left_act_v1/${STEP_PAD}/pretrained_model" \
  --policy.device=cuda \
  --display_data=true \
  --dataset.repo_id="chun-hwan/eval_omx_left_s${STEP_PAD}_single_$(date +%Y%m%d_%H%M%S)" \
  --dataset.single_task="Move one item from the cart to the left basket and return to the waiting pose." \
  --dataset.fps=30 \
  --dataset.num_episodes=1 \
  --dataset.episode_time_s=30 \
  --dataset.reset_time_s=0 \
  --dataset.push_to_hub=false \
  --dataset.private=true
```

### HF에 업로드한 모델 평가

아래부터는 로컬 체크포인트 비교 명령과 별개로, HF에 업로드된 왼쪽·오른쪽 v1·v2 모델을 평가할 때 쓰는 전체 명령이다. 현재 PC에 해당 모델을 읽을 권한이 있어야 한다. 현재 설치본에 맞춰 `lerobot-record`에 `--policy.path`를 지정하며, 평가 데이터셋 이름은 `eval_`로 시작해야 한다.

### 왼쪽 한 번 평가

```bash
source /home/team2/venv/il/bin/activate
cd /home/team2/il_ws/src/lerobot

lerobot-record \
  --robot.type=omx_follower \
  --robot.port=/dev/serial/by-id/usb-ROBOTIS_OpenRB-150_1B8E02E050323952582E3120FF071F2E-if00 \
  --robot.id=omx_follower_arm \
  --robot.cameras='{ front: {type: opencv, index_or_path: "/dev/v4l/by-id/usb-HFSD-231214-J_SNAP_U2-video-index0", width: 640, height: 480, fps: 30, fourcc: MJPG}, wrist: {type: opencv, index_or_path: "/dev/v4l/by-id/usb-Innomaker_Innomaker-U20CAM-720P_SN0001-video-index0", width: 640, height: 480, fps: 30, fourcc: MJPG}}' \
  --policy.path=chun-hwan/omx-unload-left-act-v1 \
  --policy.device=cuda \
  --display_data=true \
  --dataset.repo_id=chun-hwan/eval_omx_unload_left_trial01 \
  --dataset.single_task="Move one item from the cart to the left basket and return to the waiting pose." \
  --dataset.fps=30 \
  --dataset.num_episodes=1 \
  --dataset.episode_time_s=30 \
  --dataset.reset_time_s=60 \
  --dataset.push_to_hub=false \
  --dataset.private=true
```

### 오른쪽 한 번 평가

```bash
source /home/team2/venv/il/bin/activate
cd /home/team2/il_ws/src/lerobot

lerobot-record \
  --robot.type=omx_follower \
  --robot.port=/dev/serial/by-id/usb-ROBOTIS_OpenRB-150_1B8E02E050323952582E3120FF071F2E-if00 \
  --robot.id=omx_follower_arm \
  --robot.cameras='{ front: {type: opencv, index_or_path: "/dev/v4l/by-id/usb-HFSD-231214-J_SNAP_U2-video-index0", width: 640, height: 480, fps: 30, fourcc: MJPG}, wrist: {type: opencv, index_or_path: "/dev/v4l/by-id/usb-Innomaker_Innomaker-U20CAM-720P_SN0001-video-index0", width: 640, height: 480, fps: 30, fourcc: MJPG}}' \
  --policy.path=chun-hwan/omx-unload-right-act-v1 \
  --policy.device=cuda \
  --display_data=true \
  --dataset.repo_id=chun-hwan/eval_omx_unload_right_trial01 \
  --dataset.single_task="Move one item from the cart to the right basket and return to the waiting pose." \
  --dataset.fps=30 \
  --dataset.num_episodes=1 \
  --dataset.episode_time_s=30 \
  --dataset.reset_time_s=60 \
  --dataset.push_to_hub=false \
  --dataset.private=true
```

한 개를 옮기고 대기 자세로 돌아왔을 때 작업자가 `→`로 종료한다. 30초는 동작 시간 제한일 뿐 성공 판정이나 자동 종료 조건이 아니다. 이상 동작은 즉시 중지하고, 종료 시 팔의 토크가 해제될 수 있으므로 하드웨어에 맞는 정지 절차를 확인한다.

평가 로그는 로컬에 저장하고 HF에는 업로드하지 않는다. 첫 평가를 저장한 뒤에는 아래 재평가 명령을 사용해 같은 평가 데이터셋에 추가한다. 학습 데이터셋 이름을 평가에 재사용하지 않는다.

### 왼쪽 한 번 재평가 — 기존 평가 기록에 추가

```bash
source /home/team2/venv/il/bin/activate
cd /home/team2/il_ws/src/lerobot

lerobot-record \
  --resume=true \
  --robot.type=omx_follower \
  --robot.port=/dev/serial/by-id/usb-ROBOTIS_OpenRB-150_1B8E02E050323952582E3120FF071F2E-if00 \
  --robot.id=omx_follower_arm \
  --robot.cameras='{ front: {type: opencv, index_or_path: "/dev/v4l/by-id/usb-HFSD-231214-J_SNAP_U2-video-index0", width: 640, height: 480, fps: 30, fourcc: MJPG}, wrist: {type: opencv, index_or_path: "/dev/v4l/by-id/usb-Innomaker_Innomaker-U20CAM-720P_SN0001-video-index0", width: 640, height: 480, fps: 30, fourcc: MJPG}}' \
  --policy.path=chun-hwan/omx-unload-left-act-v1 \
  --policy.device=cuda \
  --display_data=true \
  --dataset.repo_id=chun-hwan/eval_omx_unload_left_trial01 \
  --dataset.single_task="Move one item from the cart to the left basket and return to the waiting pose." \
  --dataset.fps=30 \
  --dataset.num_episodes=1 \
  --dataset.episode_time_s=30 \
  --dataset.reset_time_s=60 \
  --dataset.push_to_hub=false \
  --dataset.private=true
```

### 오른쪽 한 번 재평가 — 기존 평가 기록에 추가

```bash
source /home/team2/venv/il/bin/activate
cd /home/team2/il_ws/src/lerobot

lerobot-record \
  --resume=true \
  --robot.type=omx_follower \
  --robot.port=/dev/serial/by-id/usb-ROBOTIS_OpenRB-150_1B8E02E050323952582E3120FF071F2E-if00 \
  --robot.id=omx_follower_arm \
  --robot.cameras='{ front: {type: opencv, index_or_path: "/dev/v4l/by-id/usb-HFSD-231214-J_SNAP_U2-video-index0", width: 640, height: 480, fps: 30, fourcc: MJPG}, wrist: {type: opencv, index_or_path: "/dev/v4l/by-id/usb-Innomaker_Innomaker-U20CAM-720P_SN0001-video-index0", width: 640, height: 480, fps: 30, fourcc: MJPG}}' \
  --policy.path=chun-hwan/omx-unload-right-act-v1 \
  --policy.device=cuda \
  --display_data=true \
  --dataset.repo_id=chun-hwan/eval_omx_unload_right_trial01 \
  --dataset.single_task="Move one item from the cart to the right basket and return to the waiting pose." \
  --dataset.fps=30 \
  --dataset.num_episodes=1 \
  --dataset.episode_time_s=30 \
  --dataset.reset_time_s=60 \
  --dataset.push_to_hub=false \
  --dataset.private=true
```

### 보강한 왼쪽 v2 모델 한 번 평가

왼쪽 첫 평가 데이터셋이 이미 있는 상태에서 실행한다.

```bash
source /home/team2/venv/il/bin/activate
cd /home/team2/il_ws/src/lerobot

lerobot-record \
  --resume=true \
  --robot.type=omx_follower \
  --robot.port=/dev/serial/by-id/usb-ROBOTIS_OpenRB-150_1B8E02E050323952582E3120FF071F2E-if00 \
  --robot.id=omx_follower_arm \
  --robot.cameras='{ front: {type: opencv, index_or_path: "/dev/v4l/by-id/usb-HFSD-231214-J_SNAP_U2-video-index0", width: 640, height: 480, fps: 30, fourcc: MJPG}, wrist: {type: opencv, index_or_path: "/dev/v4l/by-id/usb-Innomaker_Innomaker-U20CAM-720P_SN0001-video-index0", width: 640, height: 480, fps: 30, fourcc: MJPG}}' \
  --policy.path=chun-hwan/omx-unload-left-act-v2 \
  --policy.device=cuda \
  --display_data=true \
  --dataset.repo_id=chun-hwan/eval_omx_unload_left_trial01 \
  --dataset.single_task="Move one item from the cart to the left basket and return to the waiting pose." \
  --dataset.fps=30 \
  --dataset.num_episodes=1 \
  --dataset.episode_time_s=30 \
  --dataset.reset_time_s=60 \
  --dataset.push_to_hub=false \
  --dataset.private=true
```

### 보강한 오른쪽 v2 모델 한 번 평가

오른쪽 첫 평가 데이터셋이 이미 있는 상태에서 실행한다.

```bash
source /home/team2/venv/il/bin/activate
cd /home/team2/il_ws/src/lerobot

lerobot-record \
  --resume=true \
  --robot.type=omx_follower \
  --robot.port=/dev/serial/by-id/usb-ROBOTIS_OpenRB-150_1B8E02E050323952582E3120FF071F2E-if00 \
  --robot.id=omx_follower_arm \
  --robot.cameras='{ front: {type: opencv, index_or_path: "/dev/v4l/by-id/usb-HFSD-231214-J_SNAP_U2-video-index0", width: 640, height: 480, fps: 30, fourcc: MJPG}, wrist: {type: opencv, index_or_path: "/dev/v4l/by-id/usb-Innomaker_Innomaker-U20CAM-720P_SN0001-video-index0", width: 640, height: 480, fps: 30, fourcc: MJPG}}' \
  --policy.path=chun-hwan/omx-unload-right-act-v2 \
  --policy.device=cuda \
  --display_data=true \
  --dataset.repo_id=chun-hwan/eval_omx_unload_right_trial01 \
  --dataset.single_task="Move one item from the cart to the right basket and return to the waiting pose." \
  --dataset.fps=30 \
  --dataset.num_episodes=1 \
  --dataset.episode_time_s=30 \
  --dataset.reset_time_s=60 \
  --dataset.push_to_hub=false \
  --dataset.private=true
```

## 16. 3개 카트 전체 평가

단일 물건 평가가 확인된 뒤 여러 물건으로 확장한다. 각 에피소드는 30초, 중간 준비 시간은 0초로 자동 진행한다. 작업자는 실제 물건 이동 결과를 관찰한다.

1. 학습 때와 같은 범위 안에서 새로운 배치로 물건 3개를 놓는다.
2. 방향에 맞는 모델을 고른다.
3. 아래 방향별 전체 명령을 사용한다. 한 카트는 물건 하나씩 옮기는 3에피소드이며 기존 단일 물건 평가 기록에 추가한다.
4. 방향키 없이 30초씩 3에피소드를 진행한다. 에피소드 사이에는 저장·인코딩에 필요한 시간이 들어갈 수 있다.
5. 실행 중 카트를 다시 채우지 않는다. 물건 이동 완료를 자동 판정하지 않으므로 실제로 남은 물건과 복귀 동작을 관찰한다.
6. 3회 종료 후 결과를 기록하고 카트를 다시 채워 새 배치로 반복한다. 도중에 상태 정리가 필요하면 실행을 중단하고 실패·개입과 미시도 구간을 기록한 뒤 재시험한다.

### 왼쪽 v1 — 한 카트 3개 평가

15절의 왼쪽 첫 평가가 저장된 뒤 실행한다. 반복 평가에도 같은 블록을 사용한다.

```bash
source /home/team2/venv/il/bin/activate
cd /home/team2/il_ws/src/lerobot

lerobot-record \
  --resume=true \
  --robot.type=omx_follower \
  --robot.port=/dev/serial/by-id/usb-ROBOTIS_OpenRB-150_1B8E02E050323952582E3120FF071F2E-if00 \
  --robot.id=omx_follower_arm \
  --robot.cameras='{ front: {type: opencv, index_or_path: "/dev/v4l/by-id/usb-HFSD-231214-J_SNAP_U2-video-index0", width: 640, height: 480, fps: 30, fourcc: MJPG}, wrist: {type: opencv, index_or_path: "/dev/v4l/by-id/usb-Innomaker_Innomaker-U20CAM-720P_SN0001-video-index0", width: 640, height: 480, fps: 30, fourcc: MJPG}}' \
  --policy.path=chun-hwan/omx-unload-left-act-v1 \
  --policy.device=cuda \
  --display_data=true \
  --dataset.repo_id=chun-hwan/eval_omx_unload_left_trial01 \
  --dataset.single_task="Move one item from the cart to the left basket and return to the waiting pose." \
  --dataset.fps=30 \
  --dataset.num_episodes=3 \
  --dataset.episode_time_s=30 \
  --dataset.reset_time_s=0 \
  --dataset.push_to_hub=false \
  --dataset.private=true
```

### 오른쪽 v1 — 한 카트 3개 평가

15절의 오른쪽 첫 평가가 저장된 뒤 실행한다.

```bash
source /home/team2/venv/il/bin/activate
cd /home/team2/il_ws/src/lerobot

lerobot-record \
  --resume=true \
  --robot.type=omx_follower \
  --robot.port=/dev/serial/by-id/usb-ROBOTIS_OpenRB-150_1B8E02E050323952582E3120FF071F2E-if00 \
  --robot.id=omx_follower_arm \
  --robot.cameras='{ front: {type: opencv, index_or_path: "/dev/v4l/by-id/usb-HFSD-231214-J_SNAP_U2-video-index0", width: 640, height: 480, fps: 30, fourcc: MJPG}, wrist: {type: opencv, index_or_path: "/dev/v4l/by-id/usb-Innomaker_Innomaker-U20CAM-720P_SN0001-video-index0", width: 640, height: 480, fps: 30, fourcc: MJPG}}' \
  --policy.path=chun-hwan/omx-unload-right-act-v1 \
  --policy.device=cuda \
  --display_data=true \
  --dataset.repo_id=chun-hwan/eval_omx_unload_right_trial01 \
  --dataset.single_task="Move one item from the cart to the right basket and return to the waiting pose." \
  --dataset.fps=30 \
  --dataset.num_episodes=3 \
  --dataset.episode_time_s=30 \
  --dataset.reset_time_s=0 \
  --dataset.push_to_hub=false \
  --dataset.private=true
```

### 왼쪽 v2 — 한 카트 3개 평가

v2 모델 업로드와 왼쪽 첫 평가 기록이 준비된 뒤 실행한다.

```bash
source /home/team2/venv/il/bin/activate
cd /home/team2/il_ws/src/lerobot

lerobot-record \
  --resume=true \
  --robot.type=omx_follower \
  --robot.port=/dev/serial/by-id/usb-ROBOTIS_OpenRB-150_1B8E02E050323952582E3120FF071F2E-if00 \
  --robot.id=omx_follower_arm \
  --robot.cameras='{ front: {type: opencv, index_or_path: "/dev/v4l/by-id/usb-HFSD-231214-J_SNAP_U2-video-index0", width: 640, height: 480, fps: 30, fourcc: MJPG}, wrist: {type: opencv, index_or_path: "/dev/v4l/by-id/usb-Innomaker_Innomaker-U20CAM-720P_SN0001-video-index0", width: 640, height: 480, fps: 30, fourcc: MJPG}}' \
  --policy.path=chun-hwan/omx-unload-left-act-v2 \
  --policy.device=cuda \
  --display_data=true \
  --dataset.repo_id=chun-hwan/eval_omx_unload_left_trial01 \
  --dataset.single_task="Move one item from the cart to the left basket and return to the waiting pose." \
  --dataset.fps=30 \
  --dataset.num_episodes=3 \
  --dataset.episode_time_s=30 \
  --dataset.reset_time_s=0 \
  --dataset.push_to_hub=false \
  --dataset.private=true
```

### 오른쪽 v2 — 한 카트 3개 평가

v2 모델 업로드와 오른쪽 첫 평가 기록이 준비된 뒤 실행한다.

```bash
source /home/team2/venv/il/bin/activate
cd /home/team2/il_ws/src/lerobot

lerobot-record \
  --resume=true \
  --robot.type=omx_follower \
  --robot.port=/dev/serial/by-id/usb-ROBOTIS_OpenRB-150_1B8E02E050323952582E3120FF071F2E-if00 \
  --robot.id=omx_follower_arm \
  --robot.cameras='{ front: {type: opencv, index_or_path: "/dev/v4l/by-id/usb-HFSD-231214-J_SNAP_U2-video-index0", width: 640, height: 480, fps: 30, fourcc: MJPG}, wrist: {type: opencv, index_or_path: "/dev/v4l/by-id/usb-Innomaker_Innomaker-U20CAM-720P_SN0001-video-index0", width: 640, height: 480, fps: 30, fourcc: MJPG}}' \
  --policy.path=chun-hwan/omx-unload-right-act-v2 \
  --policy.device=cuda \
  --display_data=true \
  --dataset.repo_id=chun-hwan/eval_omx_unload_right_trial01 \
  --dataset.single_task="Move one item from the cart to the right basket and return to the waiting pose." \
  --dataset.fps=30 \
  --dataset.num_episodes=3 \
  --dataset.episode_time_s=30 \
  --dataset.reset_time_s=0 \
  --dataset.push_to_hub=false \
  --dataset.private=true
```

각 방향에서 우선 카트 10회씩 평가해 본다. 이 수량은 초기 비교용이며 일반적인 신뢰성 보증은 아니다. 평가 배치를 촬영하거나 메모해서 이전·보강 모델을 비슷한 조건에서 비교한다.

| 기록 항목 | 의미 |
|---|---|
| 모델 버전·방향 | 예: left / v1 |
| 물건 종류·시작 개수 | 실제 물건 종류와 시작 수량 3개 |
| 물건별 성공 | 잡기·운반·올바른 장바구니에 놓기·복귀까지 완료 |
| 카트 전체 성공 | 시작한 모든 물건을 지정된 장바구니로 옮김 |
| 실패 상황 | 헛집기 / 운반 중 떨어짐 / 놓기 실패 / 테두리 접촉 / 복귀 실패 등 |
| 개입·재시도 | 물건 배치 변경이나 사람이 도운 경우 구분 |

물건별 성공률과 카트 전체 성공률을 함께 본다. 동작 한 번의 성공이 전체 주문 성공을 보장하지 않는다. 학습 loss만으로 모델을 선택하지 않는다.

## 17. 모델 2개 확보 후 남는 작업

다음은 후속 구현 항목이며 이 문서 작성이나 모델 학습만으로 완료되지 않는다.

- 핑키의 주차 완료와 작업 시작 신호 연결.
- 주문 목적지에 따라 왼쪽·오른쪽 모델 선택.
- 물건 한 개 이동 완료를 판단하고 다음 실행으로 넘어가기.
- 카트가 비었는지 판단하고 반복 종료.
- 헛집기·낙하 등 실패 감지와 제한된 재시도.
- 하역 완료 후 핑키 출발 허용.

특히 빈 카트에서 정책을 계속 실행하지 않는다. 마지막 물건을 옮기는 시연을 학습시켰다고 빈 카트 감지·자동 정지가 구현되는 것은 아니다. 정상 주문의 실린 개수를 신뢰할 수 있다면 반복 제어의 입력으로 쓸 수 있지만, 시도 횟수만 세면 집기 실패를 놓치므로 성공 확인이 필요하다.

## 18. 진행 체크리스트

- [x] HF 로그인 및 사용자명 `chun-hwan` 확인.
- [x] 집을 물건 9종류와 카트당 3개 기준 결정(사용자 확인).
- [ ] 물건 9종류의 이름·크기와 수집 횟수 기록.
- [ ] 주차 위치·바구니 위치·대기 자세 고정.
- [x] 팔로워·리더 장치 별칭 및 USB 일련번호 대응 확인.
- [x] 기존 보정 파일과 ID 확인.
- [x] 외장 카메라 2대의 장치 경로·영상 수신·640×480 / 요청 FPS 30 확인.
- [x] 현재 연결한 팔에서 원격조종 정상 동작 확인(사용자 재시험 결과).
- [ ] 핑키 주차 및 실제 집기 자세에서 두 카메라 구도 확정.
- [ ] 좌우 목적지 원격조종 가능 여부 확인.
- [x] 현재 시험 녹화 3개·1,258프레임 및 두 영상 검수.
- [ ] 기존 시험 녹화 영상의 완결 여부와 HF 업로드 상태 검수.
- [x] 방향키 단독 테스트에서 `→` 수신과 두 단계 전환 확인(사용자 출력 결과).
- [ ] 실제 시험 녹화에서 단계 전환·재녹화·종료 키 동작 확인.
- [ ] 고정 이름 시험 녹화 3개 및 로컬 덮어쓰기·저장 확인(HF 업로드는 필요 시).
- [x] 왼쪽 본 데이터 로컬 66개·37,012프레임 저장 확인.
- [ ] 왼쪽 실패 의심 시연·카메라 구도 변화 검수 및 HF 최종 개수 확인.
- [ ] 오른쪽 v2 시험 녹화 3개 확인 후 60개(20카트) 수집·검수·HF 업로드.
- [ ] 5090 PC의 LeRobot 호환 환경·HF 로그인·CUDA 연산 확인.
- [ ] 왼쪽 ACT 학습 및 체크포인트 확인.
- [ ] 오른쪽 ACT 학습 및 체크포인트 확인.
- [ ] 기존 v1 10만 스텝 한 에피소드 확인 및 결과 기록.
- [ ] 높은 물체 1종 제외 후 남은 8종·카메라·배치 확정.
- [x] 왼쪽 v2 로컬 60개·30,617프레임 저장 확인.
- [ ] 왼쪽 v2 성공 시연 검수·HF 업로드 확인.
- [ ] 새 v2 데이터만 사용한 왼쪽 ACT 재학습·평가.
- [ ] 필요 시 기존 왼쪽 1만~10만 스텝의 1차 비교: 10개 모델 × 3시도.
- [ ] 왼쪽 상위 2~3개 후보의 2차 비교: 후보별 18시도 및 최종 모델 선택.
- [ ] 각 방향 단일 물건 평가 후 카트 전체 평가.
- [ ] 필요하면 실패 조건을 보강해 방향별 99개(약 100개) 수집.
- [ ] 보강 데이터로 v2 학습·재평가.
- [ ] 최종 좌우 모델 두 개의 경로·카메라·보정 설정 기록.

## 참고 자료와 확인 근거

- [강의자료 폴더](https://drive.google.com/drive/folders/1SnNm3rp0WVtFLZaa-eDXU9YDT7KrmO47)
- [06. CLI에 Hugging Face 토큰 등록](https://drive.google.com/file/d/1HXlIUJloYULCsrCp-yYmyxYiZYomPrKT/view)
- [07. 데이터 수집 — OMX-AI](https://drive.google.com/file/d/1gbOWNkWWQQv31FURICen3pauK__hn7zS/view)
- [09. 모방학습 모델 학습 및 추론 — OMX-AI](https://drive.google.com/file/d/1psKtgS3cq9ke0_Pk-TP9RNwNQYrS_O4d/view)
- [HF 인증 공식 안내](https://huggingface.co/docs/huggingface_hub/en/quick-start#authentication)
- [LeRobot ACT 공식 설명](https://github.com/huggingface/lerobot/blob/main/docs/source/act.mdx)
- [PyTorch Blackwell·CUDA 12.8 지원 설명](https://pytorch.org/blog/pytorch-2-7/)
- 설치 코드: `/home/team2/il_ws/src/lerobot/src/lerobot/scripts/lerobot_record.py`
- 설치 코드: `/home/team2/il_ws/src/lerobot/src/lerobot/utils/control_utils.py`
- 설치 코드: `/home/team2/il_ws/src/lerobot/src/lerobot/configs/train.py`

수량·배치·명령의 시간 설정은 이번 프로젝트를 위한 초기 제안이다. 장치 설정과 실제 성공률을 확인하며 조정한다.
