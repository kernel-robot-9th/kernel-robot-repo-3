#!/usr/bin/env bash
# 수집 데이터로 SmolVLA -> ACT 를 차례로 학습 (GPU 하나라 동시에 안 돌림). 로봇과 무관.
#   bash train_overnight.sh <데이터셋 폴더>
set -u
DS=${1:?데이터셋 폴더}; NAME=$(basename "$DS"); OUT=/home/omen/doosan_ws/vla_test/train/$(date +%Y%m%d_%H%M)_$NAME
export HF_HUB_OFFLINE=1 HF_DATASETS_OFFLINE=1 TOKENIZERS_PARALLELISM=false
mkdir -p "$OUT"; cd /home/omen/doosan_ws/vla_test
echo "[$(date +%H:%M)] SmolVLA 시작" | tee -a "$OUT/progress.txt"
~/venv/il/bin/python -I make_local_base.py "$DS" >> "$OUT/smolvla.log" 2>&1
~/venv/il/bin/lerobot-train --policy.path=/home/omen/doosan_ws/vla_test/models/smolvla_base_local \
  --dataset.repo_id=local/$NAME --dataset.root="$DS" \
  --rename_map='{"observation.images.overhead": "observation.images.camera1"}' \
  --batch_size=16 --steps=15000 --num_workers=16 --log_freq=100 --save_freq=5000 \
  --output_dir="$OUT/smolvla" --policy.device=cuda --policy.push_to_hub=false --wandb.enable=false >> "$OUT/smolvla.log" 2>&1
echo "[$(date +%H:%M)] SmolVLA 종료 exit=$?" | tee -a "$OUT/progress.txt"
echo "[$(date +%H:%M)] ACT 시작" | tee -a "$OUT/progress.txt"
~/venv/il/bin/lerobot-train --policy.type=act --policy.chunk_size=50 --policy.n_action_steps=50 \
  --dataset.repo_id=local/$NAME --dataset.root="$DS" \
  --batch_size=16 --steps=20000 --num_workers=16 --log_freq=100 --save_freq=5000 \
  --output_dir="$OUT/act" --policy.device=cuda --policy.push_to_hub=false --wandb.enable=false >> "$OUT/act.log" 2>&1
echo "[$(date +%H:%M)] ACT 종료 exit=$?" | tee -a "$OUT/progress.txt"
