# 새 로봇팔로 왼쪽 재녹화 — 전체 터미널 명령

갱신: 2026-10-20. 이 문서는 높은 물체 1종을 제외한 **8종·카트당 3개**로 왼쪽 시연을 다시 수집하는 전체 명령이다. 현재 왼쪽 v2는 로컬 **60에피소드·30,617프레임** 저장을 확인했다. 기존 v1 데이터와 모델도 유지한다. 아래 신규 60개 명령은 이미 있는 데이터에 다시 실행하지 않고, 추가가 필요하면 재개 절을 사용한다. 오른쪽 작업은 [RIGHT_RERECORD.md](RIGHT_RERECORD.md), 다운로드한 왼쪽 v2 5만·10만 모델 평가는 [LEFT_V2_EVAL.md](LEFT_V2_EVAL.md)를 따른다. 로컬 개수 확인은 성공 시연 전수 검수나 HF 업로드 확인과 별개다.

## 1. 이번 연결에 맞춘 설정

| 역할 | 고정 USB 경로 | 현재 장치 | 모터 ID |
| --- | --- | --- | --- |
| 리더 | `/dev/serial/by-id/usb-ROBOTIS_OpenRB-150_E743255D50323952582E3120FF07301D-if00` | `/dev/ttyACM0` | 1~6 |
| 팔로워 | `/dev/serial/by-id/usb-ROBOTIS_OpenRB-150_1B8E02E050323952582E3120FF071F2E-if00` | `/dev/ttyACM1` | 11~16 |

기존 `/dev/omx_leader`·`/dev/omx_follower` 별칭 규칙은 이전 팔의 일련번호여서 현재 생성되지 않는다. **아래 명령은 새 장치의 by-id 경로를 직접 사용하므로 sudo나 udev 수정 없이 실행한다.** 보정 ID는 기존 `omx_leader_arm`·`omx_follower_arm`을 유지한다. 읽기 점검에서 새 모터의 ID·모델·Drive Mode·Homing Offset이 해당 프로필과 일치했고 하드웨어 오류는 모두 0이었다. 실제 손목 방향·집기 자세는 다음 원격조종 단계에서 확인한다.

카메라 이름·설정은 `front`·`wrist`, 640×480, MJPG, 30FPS다. 두 카메라를 동시에 읽는 짧은 시험에서 각각 60프레임, 약 30.0·30.1FPS를 확인했다. 이는 로봇 제어·화면 표시·저장을 모두 합친 녹화 성능을 보장하지 않는다.

저장 워커는 **프로세스 0개·카메라당 스레드 4개(두 카메라 합계 8개)**를 명시한다. 현재 설치본의 기본값과 같다. 스트리밍 인코딩은 끄고, 에피소드 종료 후 영상을 인코딩한다. 워커 수를 올리는 것만으로 30FPS가 보장되지는 않는다. 로그는 `/home/team2/omx_record_logs`에 남긴다.

## 2. 원격조종 먼저 — 저장 없이 새 팔 동작 확인

카메라 미리보기·다른 녹화·평가를 종료하고, 양쪽 팔을 비슷한 대기 자세에 둔 뒤 실행한다. 손목 회전·그리퍼 개폐와 각 관절을 작은 동작으로 확인한다. 끝나면 이 터미널에서 `Ctrl+C`로 종료한 뒤 다음 블록을 실행한다. 이 명령은 리더 조작을 팔로워에 전달하며 데이터는 저장하지 않는다.

```bash
source /home/team2/venv/il/bin/activate
cd /home/team2/il_ws/src/lerobot

lerobot-teleoperate \
  --robot.type=omx_follower \
  --robot.port=/dev/serial/by-id/usb-ROBOTIS_OpenRB-150_1B8E02E050323952582E3120FF071F2E-if00 \
  --robot.id=omx_follower_arm \
  --robot.cameras='{ front: {type: opencv, index_or_path: "/dev/v4l/by-id/usb-HFSD-231214-J_SNAP_U2-video-index0", width: 640, height: 480, fps: 30, fourcc: MJPG}, wrist: {type: opencv, index_or_path: "/dev/v4l/by-id/usb-Innomaker_Innomaker-U20CAM-720P_SN0001-video-index0", width: 640, height: 480, fps: 30, fourcc: MJPG}}' \
  --teleop.type=omx_leader \
  --teleop.port=/dev/serial/by-id/usb-ROBOTIS_OpenRB-150_E743255D50323952582E3120FF07301D-if00 \
  --teleop.id=omx_leader_arm \
  --display_data=true \
  --fps=30
```

## 3. 시험 녹화 3개 — 프레임 속도와 새 시나리오 확인

아래 초기화는 **기존 시험 폴더 `omx-unload-left-pilot`만 삭제**한다. 기존 본 데이터 v1·새 본 데이터 v2는 삭제하지 않는다. HF 업로드는 끈다.

이 시험에서는 3개→2개→1개로 각각 하나만 옮긴 뒤 대기 자세를 유지하고, **세 에피소드 모두 녹화 중 방향키를 누르지 말고 30초 타이머로 끝낸다.** 준비 단계에서만 `→`로 다음 시작을 앞당긴다. 마지막 물건까지 옮기면 카트는 비어 있고 준비 시간이 더 필요한 경우 타이머 시작 전에 장면을 준비한다. 저장·인코딩 중에는 키를 누르지 않는다. 시험 데이터는 본 학습에 넣지 않는다.

```bash
source /home/team2/venv/il/bin/activate
cd /home/team2/il_ws/src/lerobot

mkdir -p /home/team2/omx_record_logs
set -o pipefail

PILOT_ROOT="/home/team2/.cache/huggingface/lerobot/chun-hwan/omx-unload-left-pilot"
rm -rf -- "$PILOT_ROOT" &&
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
  --dataset.num_image_writer_processes=0 \
  --dataset.num_image_writer_threads_per_camera=4 \
  --dataset.streaming_encoding=false \
  --dataset.push_to_hub=false \
  --dataset.private=true 2>&1 | tee "/home/team2/omx_record_logs/left_pilot_$(date +%Y%m%d_%H%M%S).log"
```

시험 종료 후 아래로 저장 개수와 프레임 수를 확인한다. 정상적인 30FPS 수집이라면 각 30초 에피소드는 약 900프레임이다. 타이머 종료라는 조건에서만 `프레임 수 ÷ 30초`가 실제 수집 속도의 근사치다. 방향키로 일찍 끝낸 영상에는 이 계산을 적용하지 않는다. 낮게 나온다면 로그의 `Record loop is running slower` 메시지와 당시 설정을 보고 원인을 좁힌 뒤 본 수집으로 넘어간다.

```bash
source /home/team2/venv/il/bin/activate
cd /home/team2/il_ws/src/lerobot

python - <<'FPS_CHECK'
import json
from pathlib import Path
import pyarrow.parquet as pq
root = Path('/home/team2/.cache/huggingface/lerobot/chun-hwan/omx-unload-left-pilot')
info = json.loads((root / 'meta/info.json').read_text())
print('저장', info['total_episodes'], '에피소드 /', info['total_frames'], '프레임')
for p in sorted((root / 'meta/episodes').rglob('*.parquet')):
    for row in pq.ParquetFile(p).read(columns=['episode_index', 'length']).to_pylist():
        print(f"에피소드 {row['episode_index']}: {row['length']}프레임, 30초 타이머 종료였다면 약 {row['length'] / 30:.2f} FPS")
FPS_CHECK

```

## 4. 왼쪽 v2 본 녹화 — 신규 60개

시험 결과를 확인한 뒤 아래 전체 블록으로 시작한다. **처음 만들 때 한 번만** 사용한다. 기존 v1에 이어 붙이지 않는다. 물건 8종을 7~8회씩 옮기도록 분배하고 조합·위치를 바꾼다. 한 카트에서는 3→2→1→0을 유지하며 중간에 물건을 다시 넣지 않는다. 20카트가 60에피소드다.

본 녹화는 성공적으로 물건 하나를 담고 열린 그리퍼로 대기 자세에 복귀하면 녹화 중 `→`, 준비가 끝나면 준비 단계에서 `→`를 누른다. `←`는 실패한 시연 취소·재녹화, `Esc`는 종료다. 준비 시간은 60초다. 집게가 실제 물체를 잡을 높이까지 내려가 닫는 성공 시연을 남긴다.

```bash
source /home/team2/venv/il/bin/activate
cd /home/team2/il_ws/src/lerobot

mkdir -p /home/team2/omx_record_logs
set -o pipefail

lerobot-record \
  --robot.type=omx_follower \
  --robot.port=/dev/serial/by-id/usb-ROBOTIS_OpenRB-150_1B8E02E050323952582E3120FF071F2E-if00 \
  --robot.id=omx_follower_arm \
  --robot.cameras='{ front: {type: opencv, index_or_path: "/dev/v4l/by-id/usb-HFSD-231214-J_SNAP_U2-video-index0", width: 640, height: 480, fps: 30, fourcc: MJPG}, wrist: {type: opencv, index_or_path: "/dev/v4l/by-id/usb-Innomaker_Innomaker-U20CAM-720P_SN0001-video-index0", width: 640, height: 480, fps: 30, fourcc: MJPG}}' \
  --teleop.type=omx_leader \
  --teleop.port=/dev/serial/by-id/usb-ROBOTIS_OpenRB-150_E743255D50323952582E3120FF07301D-if00 \
  --teleop.id=omx_leader_arm \
  --display_data=true \
  --dataset.repo_id=chun-hwan/omx-unload-left-v2 \
  --dataset.single_task="Move one item from the cart to the left basket and return to the waiting pose." \
  --dataset.fps=30 \
  --dataset.num_episodes=60 \
  --dataset.episode_time_s=30 \
  --dataset.reset_time_s=60 \
  --dataset.num_image_writer_processes=0 \
  --dataset.num_image_writer_threads_per_camera=4 \
  --dataset.streaming_encoding=false \
  --dataset.push_to_hub=true \
  --dataset.private=true 2>&1 | tee "/home/team2/omx_record_logs/left_v2_$(date +%Y%m%d_%H%M%S).log"
```

## 5. 중단 후 다시 시작 — 저장된 개수부터 60개까지

이전 녹화 프로세스와 업로드가 종료된 뒤 실행한다. 실제 저장 개수로 남은 수량을 계산한다. 중단됐던 **다음 미저장 에피소드의 PNG만 정리**해 이전 시도의 긴 꼬리 프레임이 재사용되지 않게 한다. 이미 저장된 관절 데이터·MP4는 그대로 둔다. v2를 아직 만들지 않았다면 4절부터 사용한다.

```bash
source /home/team2/venv/il/bin/activate
cd /home/team2/il_ws/src/lerobot

mkdir -p /home/team2/omx_record_logs
set -o pipefail

TARGET_EPISODES=60
CURRENT_EPISODES=$(python - <<'COUNT'
import json, shutil
from pathlib import Path
root = Path('/home/team2/.cache/huggingface/lerobot/chun-hwan/omx-unload-left-v2')
info = json.loads((root / 'meta/info.json').read_text())
n = info['total_episodes']
# 종료된 세션에서 저장되지 않은 다음 에피소드의 PNG만 정리한다.
for key, feature in info['features'].items():
    if feature['dtype'] in ('video', 'image'):
        pending = root / 'images' / key / f'episode-{n:06d}'
        if pending.is_dir():
            shutil.rmtree(pending)
print(n)
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
    --dataset.repo_id=chun-hwan/omx-unload-left-v2 \
    --dataset.single_task="Move one item from the cart to the left basket and return to the waiting pose." \
    --dataset.fps=30 \
    --dataset.num_episodes="$REMAINING_EPISODES" \
    --dataset.episode_time_s=30 \
    --dataset.reset_time_s=60 \
    --dataset.num_image_writer_processes=0 \
    --dataset.num_image_writer_threads_per_camera=4 \
    --dataset.streaming_encoding=false \
    --dataset.push_to_hub=true \
    --dataset.private=true 2>&1 | tee "/home/team2/omx_record_logs/left_v2_resume_$(date +%Y%m%d_%H%M%S).log"
else
  echo "이미 ${CURRENT_EPISODES}개 저장됨. 추가 녹화 없음."
fi
```

## 6. 저장 개수 확인과 이후 학습

```bash
source /home/team2/venv/il/bin/activate
cd /home/team2/il_ws/src/lerobot

python - <<'CHECK'
import json
from pathlib import Path
root = Path('/home/team2/.cache/huggingface/lerobot/chun-hwan/omx-unload-left-v2')
info = json.loads((root / 'meta/info.json').read_text())
print('왼쪽 v2 저장:', info['total_episodes'], '에피소드 /', info['total_frames'], '프레임')
CHECK

```

60개는 목표 수량이다. 실제 성공 시연·두 영상·관절 데이터 수와 HF 업로드 결과를 검수한 뒤 [README 14절](README.md#14-학습-중단과-데이터-추가-후-처리)의 **왼쪽 v2 학습 전체 명령**으로 5090 PC에서 새 학습을 시작한다. 데이터셋은 `chun-hwan/omx-unload-left-v2`, 모델은 `chun-hwan/omx-unload-left-act-v2`다.

기존 데이터 프레임 점검 결과는 [RECORDING_AUDIT_20261020.md](RECORDING_AUDIT_20261020.md)에 정리했다.
