"""초코송이 사진 4장 -> 면별로 반듯하게 펴서 한 장(atlas)으로. 모서리 좌표는 원본(2576px) 기준 눈대중."""
import cv2, numpy as np, sys
U = "photos/"   # 물건 사진 폴더 (초코송이 앞·옆·위)
S = 2.576   # 눈금 사진(1000px) -> 원본
faces = {   # 이름: (파일, [TL, TR, BR, BL] 눈금 사진 좌표, 출력 크기 w,h)
  "front": ("a94665eb-image.jpg", [(205, 15), (780, 40), (755, 915), (150, 860)], (850, 1200)),
  "back":  ("0fb4fa8c-image.jpg", [(270, 25), (830, 60), (780, 895), (205, 840)], (850, 1200)),
  "top":   ("fbac8c40-image.jpg", [(365, 40), (590, 75), (600, 890), (335, 885)], (350, 1200)),
  "end":   ("6c8a0f2e-image.jpg", [(60, 180), (890, 175), (885, 530), (65, 505)], (850, 350)),
}
atlas = np.zeros((1550, 2050, 3), np.uint8); atlas[:] = (40, 205, 245)   # 남는 곳은 노랑(BGR)
place = {"front": (0, 0), "back": (850, 0), "top": (1700, 0), "end": (0, 1200)}
for n, (f, pts, (w, h)) in faces.items():
    im = cv2.imread(U + f)
    src = np.float32([(x * S, y * S) for x, y in pts]); dst = np.float32([(0, 0), (w, 0), (w, h), (0, h)])
    out = cv2.warpPerspective(im, cv2.getPerspectiveTransform(src, dst), (w, h))
    x0, y0 = place[n]; atlas[y0:y0 + h, x0:x0 + w] = out
cv2.imwrite(sys.argv[1], atlas, [cv2.IMWRITE_JPEG_QUALITY, 90])
print("atlas", atlas.shape)
