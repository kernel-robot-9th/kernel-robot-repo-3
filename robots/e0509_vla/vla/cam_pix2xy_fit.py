import sys, json, glob, cv2, numpy as np
sys.path.insert(0, "/home/omen/doosan_ws/vla_test"); import bag_vision as b
P, X = [], []
for m in sorted(glob.glob("collect/20261019_*/ep*/meta.json")):
    d = json.load(open(m)); ep = m[:-10]
    fr = sorted(glob.glob(ep + "/frames/*.jpg"))
    if not fr or not d.get("snack_xy"): continue
    r = b.bag_region(cv2.imread(fr[0]))
    if r is None: continue
    P.append(r[2]); X.append(d["snack_xy"])
P, X = np.array(P), np.array(X)
A = np.c_[P, np.ones(len(P))]; W, *_ = np.linalg.lstsq(A, X, rcond=None); json.dump(W.tolist(), open("/home/omen/doosan_ws/vla_test/cam_pix2xy.json", "w"))
res = np.linalg.norm(A @ W - X, axis=1); print(f"맞춤 {len(P)}편, 오차 중앙값 {np.median(res):.0f}mm 최대 {res.max():.0f}mm")
r = b.bag_region(cv2.imread(sys.argv[1])); c = np.r_[r[2], 1] @ W
print("이번 새우깡 위치 추정: x%.0f y%.0f (픽셀 %.0f,%.0f)" % (c[0], c[1], *r[2]))
