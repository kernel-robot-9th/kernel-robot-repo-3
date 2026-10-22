# 왼쪽 ACT v2 — 5만 스텝 시연·연속 평가

갱신: 2026-10-20. **현재 시연에는 사용자 시험에서 더 잘 동작한 5만 스텝을 사용한다.** 관제 연동은 [CONTROL_INTEGRATION_HANDOFF.md](CONTROL_INTEGRATION_HANDOFF.md)를 먼저 읽는다. 추가 학습 대신 집기 쉬운 배치로 시연하고, 완료 판정·실제 중지는 관제 통합에서 구현한다. 정량 성공률은 아직 기록하지 않았다.

다운로드한 두 모델은 모두 `chun-hwan/omx-unload-left-v2`로 학습한 **왼쪽 v2**다. 오른쪽 모델과 기존 v1 모델은 별도로 관리한다. 파일 정리·설정 읽기는 확인했고, 이 정리 작업에서 실제 팔 평가는 실행하지 않았다.

## 1. 모델 경로와 검증 결과

| 모델 | STEP_PAD | 로컬 경로 |
| --- | --- | --- |
| 왼쪽 v2 5만 | 050000 | `/home/team2/omx_models/omx_left_act_v2/050000/pretrained_model` |
| 왼쪽 v2 10만 | 100000 | `/home/team2/omx_models/omx_left_act_v2/100000/pretrained_model` |

각 폴더에 설정·모델·전처리·후처리·정규화 파일 7개를 함께 넣었다. ZIP 압축 해제·JSON·safetensors 형식·프로세서의 상대 파일 참조·ACT 설정 읽기를 확인했다. 모델 가중치는 234개 텐서, 전처리·후처리 정규화 가중치는 각각 90개 텐서다. 두 모델의 가중치는 서로 다르고 같은 스텝의 v1 가중치와도 다르다. 원본 ZIP은 `/home/team2/Downloads`에 유지한다.

입력은 관절 상태 6개와 `front`·`wrist` RGB 영상 각각 640×480, 출력은 관절 동작 6개다. 두 모델의 `chunk_size=100`, `n_action_steps=100`이다. 모델 파일 자체와 학습 메타데이터는 수정하지 않았다. 파일명에 붙은 스텝 값을 기준으로 폴더를 구분했으며 가중치 파일 자체가 학습 스텝을 증명하는 것은 아니다.

모델·녹화 데이터는 Git 저장소 밖에 있고 문서만 Git으로 전달한다. 다른 컴퓨터에서 평가하려면 해당 `pretrained_model` 폴더의 7개 파일도 함께 옮긴다.

### 정면 카메라 구도 복원 — 반투명 비교

왼쪽 v2 본 녹화의 첫 프레임 부근을 기준으로 기존 영상 40%·실시간 영상 60%를 겹친다. 녹화·원격조종·다른 미리보기를 종료한 뒤 아래 전체 명령을 실행한다. 로봇 베이스·선반 모서리·바구니 테두리가 겹치도록 맞추고 고정한다. 팔은 자세가 다를 수 있으므로 고정된 부분을 기준으로 비교한다. 종료는 `q`다.

```bash
ffplay -hide_banner -loglevel error \
  -window_title "OMX v2 alignment - reference 40%, live 60%" \
  -f v4l2 \
  -input_format mjpeg \
  -video_size 640x480 \
  -framerate 30 \
  -i /dev/v4l/by-id/usb-HFSD-231214-J_SNAP_U2-video-index0 \
  -filter_threads 1 \
  -vf "movie=/home/team2/dev_ws/omx_imitation_project/camera_reference/front_left_v2_ep000000.png[ref];[in][ref]blend=all_expr='A*0.6+B*0.4'[out]"
```

기준 이미지는 `camera_reference/front_left_v2_ep000000.png`다. README 15절의 v1용 기준 이미지와 구분한다.

## 2. 먼저 한 에피소드 확인

카메라 미리보기·원격조종·다른 평가를 종료하고, 수집 때와 같은 카메라 구도·카트·왼쪽 바구니·대기 자세를 준비한다. 물건 하나를 옮기는 동작부터 감독하며 확인한다. 아래 블록은 **실제 팔이 정책대로 움직이는 평가 명령**이다.

현재 기본값은 시연에 선택한 5만 스텝(`050000`)이다. 10만을 참고 비교할 때만 맨 위 `STEP_PAD`를 `100000`으로 바꾼다. 아래 1회 확인은 최대 30초이므로 실제 연속 하역 시연에는 **3절의 연속 실행 명령**을 사용한다.

```bash
source /home/team2/venv/il/bin/activate
cd /home/team2/il_ws/src/lerobot

mkdir -p /home/team2/omx_record_logs
set -o pipefail

STEP_PAD="050000"  # 시연 기본 5만 / 10만 참고 비교 시에만 100000

lerobot-record \
  --robot.type=omx_follower \
  --robot.port=/dev/serial/by-id/usb-ROBOTIS_OpenRB-150_1B8E02E050323952582E3120FF071F2E-if00 \
  --robot.id=omx_follower_arm \
  --robot.cameras='{ front: {type: opencv, index_or_path: "/dev/v4l/by-id/usb-HFSD-231214-J_SNAP_U2-video-index0", width: 640, height: 480, fps: 30, fourcc: MJPG}, wrist: {type: opencv, index_or_path: "/dev/v4l/by-id/usb-Innomaker_Innomaker-U20CAM-720P_SN0001-video-index0", width: 640, height: 480, fps: 30, fourcc: MJPG}}' \
  --policy.path="/home/team2/omx_models/omx_left_act_v2/${STEP_PAD}/pretrained_model" \
  --policy.device=cuda \
  --display_data=true \
  --dataset.repo_id="chun-hwan/eval_omx_left_v2_s${STEP_PAD}_single_$(date +%Y%m%d_%H%M%S_%N)" \
  --dataset.single_task="Move one item from the cart to the left basket and return to the waiting pose." \
  --dataset.fps=30 \
  --dataset.num_episodes=1 \
  --dataset.episode_time_s=30 \
  --dataset.reset_time_s=0 \
  --dataset.num_image_writer_processes=0 \
  --dataset.num_image_writer_threads_per_camera=4 \
  --dataset.streaming_encoding=false \
  --dataset.push_to_hub=false \
  --dataset.private=true 2>&1 | tee "/home/team2/omx_record_logs/eval_left_v2_s${STEP_PAD}_single_$(date +%Y%m%d_%H%M%S_%N).log"
```

한 에피소드는 최대 30초다. 동작 확인 후 `Esc`로 일찍 종료할 수 있다. 물건 이동 완료나 빈 카트를 자동으로 감지해 정지하는 명령은 아니다. 평가 데이터셋 이름과 로그에 스텝·실행 시각이 포함되며 HF 업로드는 끈다. 이름에는 나노초까지 넣고, `lerobot-record`를 실행할 때마다 명령 안에서 새 시각을 생성한다. 같은 터미널에서 명령만 다시 실행해도 새 평가 폴더가 생기므로 `_2`, `_3`을 수동으로 붙이지 않는다. 기존 평가 데이터는 유지한다. 데이터와 로그의 나노초 값은 별도로 생성되며, 정확한 데이터셋 이름은 해당 로그의 `repo_id`에서 확인한다.

## 3. 현재 시연용 — 5만 스텝 연속 실행

물건 3개를 잘 집히는 위치에 놓고 수집 때와 같은 카메라·주차·바구니·대기 자세를 준비한다. 아래는 **한 에피소드로 최대 180초** 실행한다. 30초마다 저장하거나 정책을 초기화하지 않는다. `n_action_steps`는 모델의 기존값 100을 유지하며, 제안만 했던 20으로 바꾸지 않는다.

**현재 명령에는 빈 카트 인식·마지막 담기 확인·관제 중지 API가 없다.** 카트가 비면 허공 집기를 반복할 수 있으므로 마지막 담기와 대기 자세 복귀를 확인하고 수동 시험에서는 `Esc`로 종료한다. 180초는 최대 실행 시간이지 완료 조건이 아니다. 현재 CLI는 종료할 때 로봇 연결을 끊고 기본 설정상 토크도 해제하므로, 종료와 대기 자세 유지가 같다고 가정하지 않는다. 관제용 정지·유지 처리는 인계 문서의 후속 구현 사항이다.

```bash
source /home/team2/venv/il/bin/activate
cd /home/team2/il_ws/src/lerobot

mkdir -p /home/team2/omx_record_logs
set -o pipefail

STEP_PAD="050000"  # 시연 기본 5만 / 10만 참고 비교 시에만 100000

lerobot-record \
  --robot.type=omx_follower \
  --robot.port=/dev/serial/by-id/usb-ROBOTIS_OpenRB-150_1B8E02E050323952582E3120FF071F2E-if00 \
  --robot.id=omx_follower_arm \
  --robot.cameras='{ front: {type: opencv, index_or_path: "/dev/v4l/by-id/usb-HFSD-231214-J_SNAP_U2-video-index0", width: 640, height: 480, fps: 30, fourcc: MJPG}, wrist: {type: opencv, index_or_path: "/dev/v4l/by-id/usb-Innomaker_Innomaker-U20CAM-720P_SN0001-video-index0", width: 640, height: 480, fps: 30, fourcc: MJPG}}' \
  --policy.path="/home/team2/omx_models/omx_left_act_v2/${STEP_PAD}/pretrained_model" \
  --policy.device=cuda \
  --display_data=true \
  --dataset.repo_id="chun-hwan/eval_omx_left_v2_s${STEP_PAD}_continuous_$(date +%Y%m%d_%H%M%S_%N)" \
  --dataset.single_task="Move one item from the cart to the left basket and return to the waiting pose." \
  --dataset.fps=30 \
  --dataset.num_episodes=1 \
  --dataset.episode_time_s=180 \
  --dataset.reset_time_s=0 \
  --dataset.num_image_writer_processes=0 \
  --dataset.num_image_writer_threads_per_camera=4 \
  --dataset.streaming_encoding=false \
  --dataset.push_to_hub=false \
  --dataset.private=true 2>&1 | tee "/home/team2/omx_record_logs/eval_left_v2_s${STEP_PAD}_continuous_$(date +%Y%m%d_%H%M%S_%N).log"
```

평가 폴더와 로그는 실행할 때마다 새 이름으로 생성한다. 기존 평가를 삭제하거나 HF에 올리지 않는다. 실행 로그의 `repo_id`로 정확한 데이터셋 위치를 확인한다. 이 문서 갱신에서는 팔을 실행하지 않았다.

## 4. 참고용 — 30초씩 3회 자동 평가

**현재 시연에는 3절의 연속 실행을 사용한다. 아래는 시간 제한 비교용으로만 유지한다.** 남은 8종 중 물건 3개를 싣고, 모델마다 같은 시작 배치를 준비한다. 기본값은 5만 스텝이며, 10만을 참고 비교할 때만 `STEP_PAD`를 바꾼다. 평가 폴더와 로그 이름은 매 실행마다 자동으로 달라지므로 이름을 직접 수정할 필요가 없다.

**30초 실행 → 저장 → 다음 30초 실행 → 저장 → 마지막 30초 실행 후 종료**한다. 중간 준비 시간은 0초라 방향키를 누를 필요가 없다. 약 90초에 로딩·저장·인코딩 시간이 더해진다. 에피소드마다 정책 상태가 초기화되며, 한 번도 멈추지 않는 90초 단일 동작과는 다르다.

```bash
source /home/team2/venv/il/bin/activate
cd /home/team2/il_ws/src/lerobot

mkdir -p /home/team2/omx_record_logs
set -o pipefail

STEP_PAD="050000"  # 시연 기본 5만 / 10만 참고 비교 시에만 100000

lerobot-record \
  --robot.type=omx_follower \
  --robot.port=/dev/serial/by-id/usb-ROBOTIS_OpenRB-150_1B8E02E050323952582E3120FF071F2E-if00 \
  --robot.id=omx_follower_arm \
  --robot.cameras='{ front: {type: opencv, index_or_path: "/dev/v4l/by-id/usb-HFSD-231214-J_SNAP_U2-video-index0", width: 640, height: 480, fps: 30, fourcc: MJPG}, wrist: {type: opencv, index_or_path: "/dev/v4l/by-id/usb-Innomaker_Innomaker-U20CAM-720P_SN0001-video-index0", width: 640, height: 480, fps: 30, fourcc: MJPG}}' \
  --policy.path="/home/team2/omx_models/omx_left_act_v2/${STEP_PAD}/pretrained_model" \
  --policy.device=cuda \
  --display_data=true \
  --dataset.repo_id="chun-hwan/eval_omx_left_v2_s${STEP_PAD}_cart_$(date +%Y%m%d_%H%M%S_%N)" \
  --dataset.single_task="Move one item from the cart to the left basket and return to the waiting pose." \
  --dataset.fps=30 \
  --dataset.num_episodes=3 \
  --dataset.episode_time_s=30 \
  --dataset.reset_time_s=0 \
  --dataset.num_image_writer_processes=0 \
  --dataset.num_image_writer_threads_per_camera=4 \
  --dataset.streaming_encoding=false \
  --dataset.push_to_hub=false \
  --dataset.private=true 2>&1 | tee "/home/team2/omx_record_logs/eval_left_v2_s${STEP_PAD}_cart_$(date +%Y%m%d_%H%M%S_%N).log"
```

세 에피소드 실행이 세 개 성공을 뜻하지 않는다. 한 에피소드에서 실제로 옮긴 수가 다를 수 있고, 실패해 물건이 남아도 시간에 따라 다음 에피소드로 넘어간다. 실제 담긴 물건·복귀·남은 물건을 관찰한다. 카트가 먼저 비거나 중단이 필요하면 `Esc`로 종료한다. 성공 수는 실제 영상과 결과로 판정한다.

## 5. 결과 기록

평가 영상은 `/home/team2/.cache/huggingface/lerobot/chun-hwan/eval_omx_left_v2_s<스텝>_<single 또는 continuous 또는 cart>_<실행시각_나노초>/`에 저장된다. 실행 로그는 `/home/team2/omx_record_logs/`에 있다.

| 모델 | 물건·배치 | 정상 담기 /3 | 대기 자세 복귀 | 주요 실패·개입 | 평가 데이터셋 |
| --- | --- | --- | --- | --- | --- |
| v2 5만 | 시연용 선택, 상세 배치 미기록 | 정량 미기록 | 미기록 | 사용자 평가상 10만보다 양호 | 미기록 |
| v2 10만 | 미기록 | — | — | — | — |

공중에서 닫기·헛집기·운반 중 낙하·바구니 밖 놓기·복귀 실패를 구분해 기록한다. 새 수집 영상은 [LEFT_RERECORD.md](LEFT_RERECORD.md), 오른쪽 수집·학습은 [RIGHT_RERECORD.md](RIGHT_RERECORD.md)를 참고한다.

현재 관제 인계와 후속 구현 조건은 [CONTROL_INTEGRATION_HANDOFF.md](CONTROL_INTEGRATION_HANDOFF.md)에 정리했다. 현재 성공 배치의 사진·물건 목록·대기 자세 수치는 아직 문서화되지 않았으므로 촬영 준비 때 기록한다.
