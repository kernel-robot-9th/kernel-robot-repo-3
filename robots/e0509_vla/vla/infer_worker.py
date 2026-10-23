#!/usr/bin/env python3
"""모델을 한 번만 올려두는 추론 워커. 표준입력으로 요청 JSON 한 줄, 표준출력으로 응답 JSON 한 줄.
ROS/로봇 import 없음.  ~/venv/il/bin/python infer_worker.py"""
import os
os.environ.update(HF_HUB_OFFLINE="1", HF_DATASETS_OFFLINE="1", TOKENIZERS_PARALLELISM="false")
import json, sys, time
ZERO_NOISE = "--zero-noise" in sys.argv   # 시작 잡음 0: 계획이 매끄러워짐 (Codex 오프라인 비교: 방향 반전 25/27/24 -> 0/1/0)
# 라이브러리가 stdout 에 안내문을 찍어 응답 줄과 섞인다. 응답 통로만 따로 잡고 나머지는 stderr 로.
PROTO = sys.stdout
sys.stdout = sys.stderr
from pathlib import Path
import cv2, numpy as np, torch
from lerobot.configs.policies import PreTrainedConfig
from lerobot.policies.smolvla.modeling_smolvla import SmolVLAPolicy
from lerobot.policies.factory import make_pre_post_processors

RUN = Path("/home/omen/doosan_ws/work/offline_tests/shrimp_dense_30ep_18000_20261015_001")
TASK = "새우깡을 지정된 위치로 옮겨 놓아."
CKPT = next((sys.argv[i + 1] for i, x in enumerate(sys.argv) if x == "--ckpt"), None)
TASK = next((sys.argv[i + 1] for i, x in enumerate(sys.argv) if x == "--task"), TASK)
if CKPT:   # 2026-10-19 자동수집 모델: 체크포인트에 전처리(카메라 이름 바꾸기 + 정규화)가 같이 저장돼 있음
    ckpt = Path(CKPT); step = ckpt.parent.name
    cfg = PreTrainedConfig.from_pretrained(ckpt, local_files_only=True); cfg.device = "cuda"; cfg.push_to_hub = False
    policy = SmolVLAPolicy.from_pretrained(ckpt, config=cfg, local_files_only=True); policy.eval()
    pre, post = make_pre_post_processors(cfg, pretrained_path=str(ckpt))
else:      # 10-16 코덱스 학습 모델
    best = json.loads((RUN / "best_checkpoint.json").read_text()); ckpt = Path(best["checkpoint"]); step = best["step"]
    cfg = PreTrainedConfig.from_pretrained(ckpt, local_files_only=True); cfg.device = "cuda"; cfg.push_to_hub = False
    policy = SmolVLAPolicy.from_pretrained(ckpt, config=cfg, local_files_only=True, strict=True); policy.eval()
    pre, post = make_pre_post_processors(cfg, dataset_stats=json.loads((RUN / "train_only_stats.json").read_text()))
print(json.dumps({"ready": True, "model_step": step, "zero_noise": ZERO_NOISE, "task": TASK}), file=PROTO, flush=True)
for line in sys.stdin:
    t0 = time.monotonic()
    r = json.loads(line)
    im = cv2.imread(r["image"]); assert im is not None and im.shape == (480, 640, 3)
    raw = {"observation.state": torch.tensor(r["state"], dtype=torch.float32).unsqueeze(0),
           "observation.images.overhead": torch.from_numpy(cv2.cvtColor(im, cv2.COLOR_BGR2RGB)).permute(2, 0, 1).float().div(255).unsqueeze(0),
           "task": [TASK]}
    torch.manual_seed(r.get("seed", 1510)); policy.reset()
    noise = torch.zeros((1, cfg.chunk_size, cfg.max_action_dim), device=cfg.device) if ZERO_NOISE else None
    with torch.no_grad(), torch.autocast("cuda", dtype=torch.bfloat16):
        a = post(policy.predict_action_chunk(dict(pre(raw)), noise=noise)).detach().float().cpu().numpy()[0]
    print(json.dumps({"chunk": a.tolist(), "dt": time.monotonic() - t0}), file=PROTO, flush=True)
