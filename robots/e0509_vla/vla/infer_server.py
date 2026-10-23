#!/usr/bin/env python3
"""상주 추론 서버 (2026-10-21): 주문마다 SmolVLA 를 새로 올리던 15초를 없앤다.
연결마다 첫 줄 {"ckpt","task"} -> {"ready":...}, 그다음은 infer_worker.py 와 같은 요청/응답(JSON 한 줄씩).
모델은 처음 쓸 때 올리고 계속 들고 있다. 127.0.0.1 에서만 받는다.  ~/venv/il/bin/python infer_server.py [--preload ckpt task ...]"""
import os
os.environ.update(HF_HUB_OFFLINE="1", HF_DATASETS_OFFLINE="1", TOKENIZERS_PARALLELISM="false")
import json, socket, sys, threading, time
from pathlib import Path
import cv2, numpy as np, torch
from lerobot.configs.policies import PreTrainedConfig
from lerobot.policies.smolvla.modeling_smolvla import SmolVLAPolicy
from lerobot.policies.factory import make_pre_post_processors

MODELS = {}; gpu = threading.Lock()
def load(ckpt):
    if ckpt not in MODELS:
        p = Path(ckpt); t0 = time.monotonic()
        cfg = PreTrainedConfig.from_pretrained(p, local_files_only=True); cfg.device = "cuda"; cfg.push_to_hub = False
        pol = SmolVLAPolicy.from_pretrained(p, config=cfg, local_files_only=True); pol.eval()
        pre, post = make_pre_post_processors(cfg, pretrained_path=str(p))
        MODELS[ckpt] = (cfg, pol, pre, post, p.parent.name)
        print(f"모델 올림 {p.parent.name} {ckpt[-80:]} ({time.monotonic() - t0:.1f}s)", flush=True)
    return MODELS[ckpt]

def serve(conn):
    f = conn.makefile("rw", buffering=1, encoding="utf-8")
    try:
        hello = json.loads(f.readline())
        with gpu: cfg, pol, pre, post, step = load(hello["ckpt"])
        task = hello["task"]
        f.write(json.dumps({"ready": True, "model_step": step, "zero_noise": True, "task": task, "resident": True}) + "\n"); f.flush()
        for line in f:
            t0 = time.monotonic(); r = json.loads(line)
            im = cv2.imread(r["image"]); assert im is not None and im.shape == (480, 640, 3)
            raw = {"observation.state": torch.tensor(r["state"], dtype=torch.float32).unsqueeze(0),
                   "observation.images.overhead": torch.from_numpy(cv2.cvtColor(im, cv2.COLOR_BGR2RGB)).permute(2, 0, 1).float().div(255).unsqueeze(0),
                   "task": [task]}
            with gpu:
                torch.manual_seed(r.get("seed", 1510)); pol.reset()
                noise = torch.zeros((1, cfg.chunk_size, cfg.max_action_dim), device=cfg.device)   # infer_worker --zero-noise 와 같음
                with torch.no_grad(), torch.autocast("cuda", dtype=torch.bfloat16):
                    a = post(pol.predict_action_chunk(dict(pre(raw)), noise=noise)).detach().float().cpu().numpy()[0]
            f.write(json.dumps({"chunk": a.tolist(), "dt": time.monotonic() - t0}) + "\n"); f.flush()
    except Exception as e:
        print("연결 오류:", repr(e), flush=True)
    finally:
        try: f.close(); conn.close()
        except Exception: pass

def main():
    args = sys.argv[1:]
    if args[:1] == ["--preload"]:
        for c in args[1:]: load(c)
    s = socket.socket(); s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1); s.bind(("127.0.0.1", 8766)); s.listen(4)
    print("추론 서버 준비: 127.0.0.1:8766", flush=True)
    while True:
        c, _ = s.accept(); threading.Thread(target=serve, args=(c,), daemon=True).start()

if __name__ == "__main__":
    main()
