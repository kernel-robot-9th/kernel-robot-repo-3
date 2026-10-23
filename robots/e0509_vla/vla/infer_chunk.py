#!/usr/bin/env python3
"""SmolVLA(새우깡, best step 5250) 행동 묶음 추론. ROS/로봇 import 없음.

사용 (LeRobot 가상환경): ~/venv/il/bin/python infer_chunk.py <request.json> <out.json>
request: {"image": 경로, "state": [8개], "seeds": [..]}
out:     {"chunks": {seed: 50x11}, ...}
"""
import os
os.environ.update(HF_HUB_OFFLINE="1", HF_DATASETS_OFFLINE="1", TOKENIZERS_PARALLELISM="false")
import json, sys, time
from pathlib import Path
import cv2, numpy as np, torch
from lerobot.configs.policies import PreTrainedConfig
from lerobot.policies.smolvla.modeling_smolvla import SmolVLAPolicy
from lerobot.policies.factory import make_pre_post_processors

RUN = Path("/home/omen/doosan_ws/work/offline_tests/shrimp_dense_30ep_18000_20261015_001")
TASK = "새우깡을 지정된 위치로 옮겨 놓아."      # 학습 때 쓴 지시문 그대로

req = json.loads(Path(sys.argv[1]).read_text())
t0 = time.monotonic()
best = json.loads((RUN / "best_checkpoint.json").read_text())
ckpt = Path(best["checkpoint"])
cfg = PreTrainedConfig.from_pretrained(ckpt, local_files_only=True); cfg.device = "cuda"; cfg.push_to_hub = False
policy = SmolVLAPolicy.from_pretrained(ckpt, config=cfg, local_files_only=True, strict=True); policy.eval()
pre, post = make_pre_post_processors(cfg, dataset_stats=json.loads((RUN / "train_only_stats.json").read_text()))
t_load = time.monotonic() - t0

im = cv2.imread(req["image"]); assert im is not None and im.shape == (480, 640, 3), "이미지 640x480 아님"
state = req["state"]; assert len(state) == 8 and np.isfinite(state).all()
raw = {"observation.state": torch.tensor(state, dtype=torch.float32).unsqueeze(0),
       "observation.images.overhead": torch.from_numpy(cv2.cvtColor(im, cv2.COLOR_BGR2RGB)).permute(2, 0, 1).float().div(255).unsqueeze(0),
       "task": [TASK]}
batch = pre(raw)
chunks = {}
for seed in req.get("seeds", [1510, 1511, 1512, 1513, 1514]):
    torch.manual_seed(seed); policy.reset()
    with torch.no_grad(), torch.autocast("cuda", dtype=torch.bfloat16):
        a = post(policy.predict_action_chunk(dict(batch))).detach().float().cpu().numpy()[0]
    assert a.shape == (50, 11) and np.isfinite(a).all()
    chunks[str(seed)] = a.tolist()
Path(sys.argv[2]).write_text(json.dumps({"model_step": best["step"], "checkpoint": str(ckpt), "task": TASK,
                                         "load_s": t_load, "total_s": time.monotonic() - t0, "chunks": chunks}))
print(f"추론 완료: 모델 로드 {t_load:.1f}s, 총 {time.monotonic() - t0:.1f}s, seed {len(chunks)}개")
