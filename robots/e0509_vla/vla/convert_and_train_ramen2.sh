#!/usr/bin/env bash
# 10-22 저녁: 컵라면 재학습 (기존 51편 + 로봇 가까운 줄 10편). SmolVLA 만 (VLA 유지, ACT 생략). 로봇과 무관.
set -u
cd /home/omen/doosan_ws/vla_test
DS=/home/omen/doosan_ws/vla_test/datasets/ramen_auto_v2; NAME=ramen_auto_v2
LOG=/home/omen/doosan_ws/vla_test/train/convert_and_train_ramen2_$(date +%Y%m%d_%H%M).log
mkdir -p train
echo "[$(date +%H:%M)] 변환 시작" | tee -a "$LOG"
~/venv/il/bin/python -I convert_collect.py --object ramen --out "$DS" >> "$LOG" 2>&1
rc=$?; echo "[$(date +%H:%M)] 변환 종료 exit=$rc" | tee -a "$LOG"
if [ $rc -ne 0 ] || [ ! -f "$DS/meta/info.json" ]; then echo "변환 실패 -> 학습 안 함" | tee -a "$LOG"; exit 1; fi
OUT=/home/omen/doosan_ws/vla_test/train/$(date +%Y%m%d_%H%M)_$NAME
export HF_HUB_OFFLINE=1 HF_DATASETS_OFFLINE=1 TOKENIZERS_PARALLELISM=false
mkdir -p "$OUT"; echo "학습 폴더: $OUT" | tee -a "$LOG"
echo "[$(date +%H:%M)] SmolVLA 시작" | tee -a "$OUT/progress.txt" "$LOG"
~/venv/il/bin/python -I make_local_base.py "$DS" >> "$OUT/smolvla.log" 2>&1
~/venv/il/bin/lerobot-train --policy.path=/home/omen/doosan_ws/vla_test/models/smolvla_base_local \
  --dataset.repo_id=local/$NAME --dataset.root="$DS" \
  --rename_map="{\"observation.images.overhead\": \"observation.images.camera1\"}" \
  --batch_size=16 --steps=15000 --num_workers=16 --log_freq=100 --save_freq=5000 \
  --output_dir="$OUT/smolvla" --policy.device=cuda --policy.push_to_hub=false --wandb.enable=false >> "$OUT/smolvla.log" 2>&1
echo "[$(date +%H:%M)] SmolVLA 종료 exit=$?" | tee -a "$OUT/progress.txt" "$LOG"
