# 오른쪽 ACT v2 — 3만~7만 스텝 연속 평가

갱신: 2026-10-20. **이번 준비에서 다운로드 완료 파일로 확인한 3만·4만·5만·6만·7만, 총 5개만 정리했다.** 1만·2만은 이번 정리 대상에 포함되지 않았다. 기본 실행값은 우선 확인할 5만(`050000`)이며 오른쪽 시연용 최종 선택은 실제 평가 후 결정한다. 왼쪽에서 5만이 양호했다는 결과가 오른쪽 성능을 보장하지는 않는다.

실제 팔은 이 준비 작업에서 실행하지 않았다. 관제 통합은 [CONTROL_INTEGRATION_HANDOFF.md](CONTROL_INTEGRATION_HANDOFF.md)를 먼저 읽는다. 오른쪽 모델을 왼쪽 작업에 사용하거나 왼쪽 모델을 오른쪽 작업에 사용하지 않는다.

## 1. 준비된 모델과 검증

| 모델 | STEP_PAD | 로컬 경로 |
| --- | --- | --- |
| 3만 | `030000` | `/home/team2/omx_models/omx_right_act_v2/030000/pretrained_model` |
| 4만 | `040000` | `/home/team2/omx_models/omx_right_act_v2/040000/pretrained_model` |
| 5만 | `050000` | `/home/team2/omx_models/omx_right_act_v2/050000/pretrained_model` |
| 6만 | `060000` | `/home/team2/omx_models/omx_right_act_v2/060000/pretrained_model` |
| 7만 | `070000` | `/home/team2/omx_models/omx_right_act_v2/070000/pretrained_model` |

5개 모두 학습 설정의 데이터셋은 `chun-hwan/omx-unload-right-v2`, 모델 저장소 이름은 `chun-hwan/omx-unload-right-act-v2`다. 각 폴더의 설정·가중치·전처리·후처리·정규화 파일 7개를 원본 ZIP과 동일하게 보관했다. ZIP CRC와 추출 파일 크기·CRC, JSON, safetensors의 CPU 읽기, 프로세서 상대 파일 참조, 현재 LeRobot의 ACT 설정 읽기를 확인했다. 원본 ZIP은 `/home/team2/Downloads`에 유지한다.

각 모델은 가중치 234개 텐서, 전처리·후처리 정규화는 각각 90개 텐서다. 입력은 관절 상태 6개와 `front`·`wrist` RGB 영상 각각 640×480, 출력은 관절 동작 6개다. `chunk_size=100`, `n_action_steps=100`, `temporal_ensemble_coeff=null`을 유지하며 파일을 수정하지 않았다. 5개 체크포인트의 모델 가중치 해시는 모두 다르다.

스텝 폴더 이름은 사용자 다운로드 파일의 이름을 기준으로 구분한다. `train_config.json`의 `steps`는 학습 목표값이며 체크포인트 스텝 자체를 증명하는 필드는 아니다. 현재 3만~6만 파일의 목표값은 100000, 7만 파일은 70000으로 기록돼 있고 이를 수정하지 않았다. 파일 검증은 실제 집기 성능 검증과 별개다.

모델·평가 데이터는 Git에 포함되지 않는다. 다른 PC에서는 해당 `pretrained_model` 폴더의 7개 파일, 로봇 보정 파일과 실행 환경을 별도로 준비한다. 모델의 HF 게시 상태는 이번 준비에서 확인하지 않았다.

## 2. 테스트 준비

- 카메라 미리보기·원격조종·다른 평가를 종료한다. 같은 카메라나 팔을 다른 프로그램에서 동시에 열지 않는다.
- **오른쪽 수집 때의** 카메라 구도·카트 주차·오른쪽 바구니·대기 자세를 복원한다. 왼쪽 기준 이미지가 오른쪽 수집 구도와 같다고 확인하지 않은 상태에서 대신 사용하지 않는다.
- 잘 집히는 물건 3개를 간격 있게 배치한다. 모델을 바꿀 때 같은 물건과 시작 위치를 복원한다.
- 처음에는 아래 기본 5만부터 확인하고, 필요할 때 `STEP_PAD`를 준비된 다른 값으로 바꿔 전체 블록을 다시 실행한다. 다섯 모델을 연달아 자동 실행하는 명령은 아니다.

## 3. 전체 명령 — 한 에피소드 최대 180초

아래 명령은 **실제 팔을 움직인다.** 중간에 30초마다 저장하거나 정책을 초기화하지 않고 한 에피소드로 최대 180초 실행한다. 남은 물건 수나 담기 성공을 자동 판정하지 않으므로 1에피소드가 1개 이동 또는 3개 성공을 뜻하지 않는다.

```bash
source /home/team2/venv/il/bin/activate
cd /home/team2/il_ws/src/lerobot

mkdir -p /home/team2/omx_record_logs
set -o pipefail

STEP_PAD="050000"  # 준비된 값: 030000 / 040000 / 050000 / 060000 / 070000

lerobot-record \
  --robot.type=omx_follower \
  --robot.port=/dev/serial/by-id/usb-ROBOTIS_OpenRB-150_1B8E02E050323952582E3120FF071F2E-if00 \
  --robot.id=omx_follower_arm \
  --robot.cameras='{ front: {type: opencv, index_or_path: "/dev/v4l/by-id/usb-HFSD-231214-J_SNAP_U2-video-index0", width: 640, height: 480, fps: 30, fourcc: MJPG}, wrist: {type: opencv, index_or_path: "/dev/v4l/by-id/usb-Innomaker_Innomaker-U20CAM-720P_SN0001-video-index0", width: 640, height: 480, fps: 30, fourcc: MJPG}}' \
  --policy.path="/home/team2/omx_models/omx_right_act_v2/${STEP_PAD}/pretrained_model" \
  --policy.device=cuda \
  --display_data=true \
  --dataset.repo_id="chun-hwan/eval_omx_right_v2_s${STEP_PAD}_continuous_$(date +%Y%m%d_%H%M%S_%N)" \
  --dataset.single_task="Move one item from the cart to the right basket and return to the waiting pose." \
  --dataset.fps=30 \
  --dataset.num_episodes=1 \
  --dataset.episode_time_s=180 \
  --dataset.reset_time_s=0 \
  --dataset.num_image_writer_processes=0 \
  --dataset.num_image_writer_threads_per_camera=4 \
  --dataset.streaming_encoding=false \
  --dataset.push_to_hub=false \
  --dataset.private=true 2>&1 | tee "/home/team2/omx_record_logs/eval_right_v2_s${STEP_PAD}_continuous_$(date +%Y%m%d_%H%M%S_%N).log"
```

마지막 물건이 **오른쪽 바구니에 내려놓이고 대기 자세로 돌아온 것을 확인한 뒤**, 수동 시험에서는 `Esc`로 종료한다. 카트가 비어도 정책은 허공 집기를 반복할 수 있다. 빈 카트 감지·관제 중지 API는 아직 구현되어 있지 않다. 현재 CLI는 종료 시 연결을 끊으며 기본 설정상 토크를 해제하므로, 종료가 팔 자세 유지와 같다고 가정하지 않는다.

180초는 최대 시간 제한이며 완료 조건이 아니다. 준비 과정에서는 실제 팔을 실행하지 않았다. `n_action_steps=20` 시험 제안은 적용하지 않는다. 영상은 현재 요청 설정인 30 FPS로 수집하고, 느린 제어 루프 경고가 나타나면 해당 로그를 함께 남긴다.

평가 데이터셋과 로그 이름에는 실행할 때마다 새 나노초 시각을 넣는다. 이전 평가를 삭제하거나 HF에 업로드하지 않는다. 데이터셋·로그 이름의 시각은 각각 생성되므로 정확한 데이터 위치는 로그의 `repo_id`로 확인한다.

## 4. 실제 평가 결과 기록

| 모델 | 물건·배치 | 정상 담기 /3 | 대기 복귀 | 주요 실패·개입 | 평가 데이터셋 |
| --- | --- | --- | --- | --- | --- |
| 3만 | 미기록 | — | — | — | — |
| 4만 | 미기록 | — | — | — | — |
| 5만 | 미기록 | — | — | — | — |
| 6만 | 미기록 | — | — | — | — |
| 7만 | 미기록 | — | — | — | — |

실제 오른쪽 바구니에 담긴 수, 복귀, 헛집기·낙하·바구니 밖 놓기와 사람 개입을 기록한다. 오른쪽 최종 체크포인트는 아직 미선정이다. 사용자가 선택한 뒤 관제 인계 문서의 목적지별 모델 선택을 확정한다.

로그: `/home/team2/omx_record_logs/eval_right_v2_s<스텝>_continuous_<실행시각_나노초>.log`

데이터: `/home/team2/.cache/huggingface/lerobot/chun-hwan/eval_omx_right_v2_s<스텝>_continuous_<실행시각_나노초>/`

## 5. 모델 가중치 SHA-256

다른 PC로 복사한 경우 `model.safetensors`의 해시를 비교한다. 전처리·후처리 파일도 함께 복사한다.

| STEP_PAD | model.safetensors SHA-256 |
| --- | --- |
| `030000` | `36fff790714dc7694778278af8eac47576eb6ebce14d83b282c3323d2a874acd` |
| `040000` | `10bbd0c990e23813ceda484a607519e765d6063dd9026e746ed8ec1dbfdfbbc4` |
| `050000` | `3b7477be44204394644d8c385952dc39c9720c086532496d04450408f575112f` |
| `060000` | `cd2e529604a8a50c4f2eed7187eba45c4d94a666b032221eaf0666e89d444e49` |
| `070000` | `57f5da85f9c755aef6524433ac2df2ce433257aec31aa65567d52106d10a35ea` |

추가 녹화·학습 문서는 [RIGHT_RERECORD.md](RIGHT_RERECORD.md)에 참고용으로 유지한다. 이번 준비는 현재 다운로드된 모델의 평가 준비이며 재수집·재학습을 요구하지 않는다.
