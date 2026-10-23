#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
新加入的侧面 / 背面照片 → 全身定妆照素材

两张新照都拍到了人（恒姐）：
  * 侧面照：恒姐的手搭在狗的肩背上，手压在毛里，裁不掉 → 用拉普拉斯扩散修补
  * 背面照：人的手臂 + 一条腿在画面最右缘，从右边整条裁掉即可

原则：狗本身【一像素都不改】，只清除人。
原片只读 —— 全部输出到 _curated/，_incoming/ 里的原件不动。

用法：python3 tools/prep_side_back_photos.py
"""

import os
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageOps

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(PROJECT, "10_工作素材/characters/_incoming/adult")
CUR = os.path.join(PROJECT, "10_工作素材/characters/_curated/adult")
WORK = os.path.join(PROJECT, "10_工作素材/_work")

CJK = "/System/Library/Fonts/Hiragino Sans GB.ttc"


def font(sz):
    try:
        return ImageFont.truetype(CJK, sz)
    except Exception:
        return ImageFont.load_default()


def inpaint_diffusion(img, region_box, hole_boxes, iters=1200):
    """拉普拉斯扩散修补：把 hole 区域按周边已知像素平滑地"长"出来。

    区域坐标全部是【原图/裁剪后图像】的绝对像素坐标。
    比「贴图 + 羽化」好的地方：没有矩形接缝，也没有残留的方块感。
    """
    x0, y0, x1, y1 = region_box
    reg = np.asarray(img.crop(region_box)).astype(np.float64) / 255.0
    h, w, _ = reg.shape

    hole = np.zeros((h, w), dtype=bool)
    for hx0, hy0, hx1, hy1 in hole_boxes:
        hole[hy0 - y0:hy1 - y0, hx0 - x0:hx1 - x0] = True

    known = ~hole
    cur = reg.copy()
    cur[hole] = reg[known].mean(axis=0)

    for _ in range(iters):
        pad = np.pad(cur, ((1, 1), (1, 1), (0, 0)), mode="edge")
        lap = (pad[:-2, 1:-1] + pad[2:, 1:-1] + pad[1:-1, :-2] + pad[1:-1, 2:]) / 4.0
        cur[hole] = lap[hole]

    out = img.copy()
    out.paste(Image.fromarray((cur * 255).round().astype("uint8")), (x0, y0))
    return out


def main():
    os.makedirs(CUR, exist_ok=True)
    os.makedirs(WORK, exist_ok=True)

    # ---------- 侧面照 ----------
    side = ImageOps.exif_transpose(Image.open(os.path.join(SRC, "8811792749790_.pic.jpg"))).convert("RGB")
    # 裁掉右侧的人（她的脸从 x≈790 开始），保留狗全身含四脚
    # 裁剪框 = 原图 (0, 690, 778, 1490) → 裁剪后 778x800
    side = side.crop((0, 690, 778, 1490))
    # 恒姐的手搭在狗的肩背上（原图 x≈520..592 / y≈890..984，裁剪后 y 平移 690）
    # → 裁剪后坐标 x 520..592 / y 200..294，扩散修补掉
    side = inpaint_diffusion(side, (480, 160, 640, 330), [(518, 198, 594, 294)])
    p_side = os.path.join(CUR, "x6_adult_stand_side_full_02.jpg")
    side.save(p_side, quality=96)
    print("  ✅ %s  %dx%d" % (os.path.basename(p_side), side.width, side.height))

    # ---------- 背面照 ----------
    back = ImageOps.exif_transpose(Image.open(os.path.join(SRC, "8821792749790_.pic.jpg"))).convert("RGB")
    # 人的手臂 + 一条腿在画面最右缘（原图 x≈730..768），整条裁掉即可，无需修补
    # 裁剪框 = 原图 (225, 640, 730, 1475) → 505x835
    back = back.crop((225, 640, 730, 1475))
    p_back = os.path.join(CUR, "x6_adult_stand_back_01.jpg")
    back.save(p_back, quality=96)
    print("  ✅ %s  %dx%d" % (os.path.basename(p_back), back.width, back.height))

    # ---------- 拼接检查图 ----------
    a = side.copy(); a.thumbnail((620, 620))
    b = back.copy(); b.thumbnail((620, 620))
    sheet = Image.new("RGB", (a.width + b.width + 30, max(a.height, b.height) + 60), (16, 16, 18))
    d = ImageDraw.Draw(sheet)
    sheet.paste(a, (10, 40)); sheet.paste(b, (a.width + 20, 40))
    d.text((10, 8), "新素材处理后：左=侧面（已扩散修补掉手） 右=背面（已裁掉人）", fill=(255, 230, 110), font=font(26))
    p_chk = os.path.join(WORK, "side_back_check.jpg")
    sheet.save(p_chk, quality=94)
    print("\n检查图: %s  %s" % (p_chk, sheet.size))
    return 0


if __name__ == "__main__":
    sys.exit(main())
