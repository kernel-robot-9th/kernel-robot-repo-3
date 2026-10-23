#!/usr/bin/env python3
"""오프라인용 SmolVLA 기본 모델 폴더 만들기: 캐시된 smolvla_base(설정+가중치)에 전처리/후처리 설정을 붙인다.
정규화 통계는 학습 때 데이터셋 통계로 다시 덮인다(lerobot-train). 외부 다운로드 없음."""
import os
os.environ.update(HF_HUB_OFFLINE="1", HF_DATASETS_OFFLINE="1")
import json, sys
from pathlib import Path
from lerobot.configs.policies import PreTrainedConfig
from lerobot.policies.factory import make_pre_post_processors
from lerobot.datasets.lerobot_dataset import LeRobotDatasetMetadata

SRC = Path.home() / ".cache/huggingface/hub/models--lerobot--smolvla_base/snapshots/5e8d12a6e2975b0e5e5fce7c8caf47c371d257b6"
OUT = Path("/home/omen/doosan_ws/vla_test/models/smolvla_base_local")
DS = Path(sys.argv[1])
OUT.mkdir(parents=True, exist_ok=True)
for f in ("config.json", "model.safetensors"):
    if not (OUT / f).exists(): (OUT / f).symlink_to(SRC / f)
cfg = PreTrainedConfig.from_pretrained(SRC, local_files_only=True)
meta = LeRobotDatasetMetadata("local/" + DS.name, root=DS)
pre, post = make_pre_post_processors(cfg, dataset_stats=meta.stats)
pre.save_pretrained(OUT); post.save_pretrained(OUT)
print("만듦:", OUT, sorted(p.name for p in OUT.iterdir()))
