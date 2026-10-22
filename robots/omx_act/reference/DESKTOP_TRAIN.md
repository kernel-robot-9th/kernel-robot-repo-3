# 데스크톱에서 받기와 첫 ACT 학습

현재 진행(2026-10-20): 새 팔·8종 기준 왼쪽 v2는 로컬 60개·30,617프레임, 오른쪽 v2는 60개·28,962프레임 저장을 확인했다. 다운로드한 왼쪽 v2 5만·10만 모델 평가는 [LEFT_V2_EVAL.md](LEFT_V2_EVAL.md)를 따른다. 아래 66개 확인·v1 첫 학습 명령은 기존 작업 참고다. 새 v2 수집·학습은 [왼쪽 문서](LEFT_RERECORD.md), [오른쪽 문서](RIGHT_RERECORD.md)를 따르며 기존 v1과 합치지 않는다. 시연 검수·HF 업로드는 저장 개수 확인과 별도다.

Ubuntu Linux 또는 Ubuntu WSL2의 Bash 기준이다. RTX 5090 드라이버가 설치돼 있고 `nvidia-smi`에서 GPU가 보여야 한다. 데스크톱에서의 설치와 실제 학습은 아직 실행하지 않았다.

현재 녹화 PC의 왼쪽 데이터는 66에피소드·37,012프레임이다. 최종 HF 업로드 개수와 성공 시연 여부를 확인한 뒤 학습한다. 특히 `episode_index=35`는 실패 의심 시연으로 검수 대상이다. 아래 기본 명령은 HF 데이터셋 전체를 사용하며 자동으로 실패 시연을 삭제하거나 제외하지 않는다.

## 1. GitHub 로그인과 프로젝트 받기 — 처음 한 번

비공개 저장소이므로 데스크톱에서도 Git 인증이 필요하다. Chrome 로그인과 Git CLI 인증은 따로다. 아래 로그인은 터미널에 표시되는 절차를 직접 완료한다.

```bash
sudo apt-get update
sudo apt-get install -y git gh python3-venv ffmpeg build-essential

gh auth login --hostname github.com --git-protocol https --web
gh auth setup-git

git clone https://github.com/rheffi/omx-imitation-project.git "$HOME/omx_imitation_project"
cd "$HOME/omx_imitation_project"
```

이미 이 프로젝트를 받았다면 아래 블록으로 갱신한다.

```bash
cd "$HOME/omx_imitation_project"
git pull --ff-only
```

## 2. 같은 LeRobot 소스와 학습 환경 설치 — 처음 한 번

학습 코드는 GitHub 프로젝트 폴더와 별도로 `$HOME/omx_imitation_training/lerobot`에 설치한다. 녹화 PC와 같은 LeRobot 커밋을 고정하고, 현재 손목 시작 목표값 수정 패치도 함께 적용한다. 패치와 해당 소스의 라이선스는 `patches/`에 있다.

Python 3.10~3.12 환경을 사용한다. 아래 `python3 --version`이 이 범위인지 확인한다. CUDA 빌드는 녹화 PC에서 확인한 PyTorch 2.10.0 / CUDA 12.8 조합이다. 데스크톱의 드라이버 호환 여부는 다음 절의 실제 CUDA 연산으로 확인한다.

```bash
python3 --version
python3 -m venv "$HOME/venv/omx_train"
source "$HOME/venv/omx_train/bin/activate"
python -m pip install --upgrade pip

PROJECT_DIR="$HOME/omx_imitation_project"
LEROBOT_DIR="$HOME/omx_imitation_training/lerobot"
mkdir -p "$HOME/omx_imitation_training"

git clone --filter=blob:none --no-checkout https://github.com/huggingface/lerobot.git "$LEROBOT_DIR"
git -C "$LEROBOT_DIR" checkout 8fff0fde7c79f23a93d845d1a50e985de01f8b8a

git -C "$LEROBOT_DIR" apply --check "$PROJECT_DIR/patches/omx-wrist-start-position.patch" &&
git -C "$LEROBOT_DIR" apply "$PROJECT_DIR/patches/omx-wrist-start-position.patch"

python -m pip install torch==2.10.0 torchvision==0.25.0 --index-url https://download.pytorch.org/whl/cu128
python -m pip install -c "$PROJECT_DIR/requirements-training.txt" -e "${LEROBOT_DIR}[dynamixel]"
python -m pip check
```

이 절의 clone·가상환경 생성·패치 적용은 첫 설치용이다. 설치 후 학습을 재시작할 때는 다음 절부터 실행한다.

## 3. HF 로그인과 RTX 5090 확인

Hugging Face는 녹화 데이터·모델 저장소다. GitHub와 별도로 `chun-hwan` 계정의 비공개 데이터셋을 읽고 모델을 올릴 권한이 필요하다. 토큰은 로그인 입력에만 사용한다.

```bash
source "$HOME/venv/omx_train/bin/activate"
hf auth login
hf auth whoami
nvidia-smi

python - <<'CUDA'
import torch
print("torch:", torch.__version__)
print("CUDA build:", torch.version.cuda)
print("CUDA available:", torch.cuda.is_available())
if not torch.cuda.is_available():
    raise SystemExit("CUDA 사용 불가: 드라이버와 PyTorch 설치를 확인하세요.")
print("GPU:", torch.cuda.get_device_name(0))
x = torch.ones((4, 4), device="cuda")
print("CUDA 연산 결과:", (x @ x).sum().item())
CUDA
```

## 4. HF 데이터가 66개까지 올라왔는지 확인

녹화 PC의 업로드가 끝난 뒤 실행한다. 아래 결과가 66개·37,012프레임인지 확인한다. 기존 학습 캐시가 있다면 캐시의 메타데이터도 최신 HF 저장본과 일치하는지 확인한다.

```bash
source "$HOME/venv/omx_train/bin/activate"

python - <<'DATA'
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
print("에피소드:", info["total_episodes"])
print("프레임:", info["total_frames"])
print("FPS:", info["fps"])
DATA
```

## 5. 왼쪽 ACT 첫 학습 — 전체 복붙 명령

학습 시작 시 HF에서 데이터셋과 영상이 내려받아진다. 로봇팔·카메라·장치 포트는 학습 PC에 연결하지 않아도 된다. 배치 16, 100,000스텝은 첫 실행 설정이며, 학습 시간과 실제 성공률은 아직 측정하지 않았다.

```bash
source "$HOME/venv/omx_train/bin/activate"
cd "$HOME/omx_imitation_training/lerobot"

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

최종 체크포인트:

```text
~/omx_imitation_training/outputs/omx_left_act_v1/checkpoints/last/pretrained_model/
```

HF 모델: `chun-hwan/omx-unload-left-act-v1`. 위 명령에는 모델 저장소의 비공개 설정을 별도로 지정하지 않았으므로 원하는 공개 범위는 HF에서 확인한다.

## 6. 학습이 중단됐을 때 — 전체 복붙 명령

```bash
source "$HOME/venv/omx_train/bin/activate"
cd "$HOME/omx_imitation_training/lerobot"

lerobot-train \
  --config_path="$HOME/omx_imitation_training/outputs/omx_left_act_v1/checkpoints/last/pretrained_model/train_config.json" \
  --resume=true
```

## 7. 학습이 끝난 다음

모델이 HF에 올라오면 OMX 연결 노트북에서 [README 15절](README.md#15-실제-팔에서-첫-평가)의 왼쪽 실제 팔 평가 명령을 사용한다. 오른쪽 녹화·학습·평가와 추가 수집 명령도 README에 전체 명령으로 정리돼 있다.
