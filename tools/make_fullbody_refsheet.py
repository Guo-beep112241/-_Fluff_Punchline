#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
小六二 · 全身定妆照（竖版参考图）

六个格子，全部来自真实素材（不经过 AI 重绘，保证「一模一样」）：
  ① 正面全身   — 真实照片
  ② 3/4 侧全身 — 真实照片
  ③ 正侧全身   — 新增照片，已补掉人（恒姐的手）
  ④ 背面全身   — 新增照片，已补掉人与牵引绳
  ⑤ 脸部特写   — 取自已确认的 H3 定妆视频 v1（用户确认「最终定妆就用这个脸」）
  ⑥ 坐姿       — 真实照片

用法：python3 tools/make_fullbody_refsheet.py
"""

import os
import shutil
import subprocess
import sys

from PIL import Image, ImageDraw, ImageFont, ImageOps

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CUR = os.path.join(PROJECT, "10_工作素材/characters/_curated/adult")
V1_VIDEO = os.path.join(PROJECT, "10_工作素材/habits/_curated/x6_adult_char_ref_stand_turn_01.mp4")
WORK = os.path.join(PROJECT, "10_工作素材/_work")
OUT = os.path.join(PROJECT, "20_生成结果/ep01/reference/x6_adult_fullbody_refsheet.jpg")

CELL_W, CELL_H = 540, 960
LABEL_H = 96
CJK = "/System/Library/Fonts/Hiragino Sans GB.ttc"


def font(sz):
    try:
        return ImageFont.truetype(CJK, sz)
    except Exception:
        return ImageFont.load_default()


def ffmpeg_bin():
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return shutil.which("ffmpeg")


def extract_v1_face():
    """从已确认的 v1 定妆视频里抽一帧脸（转头到 3/4 的那一刻最像）。"""
    raw = os.path.join(WORK, "v1_face_frame.jpg")
    out = os.path.join(WORK, "v1_face_frame_white.jpg")
    if os.path.exists(out):
        return out
    ff = ffmpeg_bin()
    subprocess.run([ff, "-y", "-ss", "2.6", "-i", V1_VIDEO, "-frames:v", "1",
                    "-vf", "scale=1200:-2", raw], check=True, capture_output=True)
    # v1 的毛色偏黄（提示词误写 creamy-white 所致），做白平衡校正：
    # 保留用户已确认的【脸部结构】，去掉错误的黄。饱和度 ×0.46 + 补一点暖调。
    import colorsys
    im = Image.open(raw).convert("RGB"); W, H = im.size
    fixed = Image.new("RGB", (W, H)); sp, dp = im.load(), fixed.load()
    for y in range(H):
        for x in range(W):
            r, g, b = sp[x, y]
            h, s, v = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)
            rr, gg, bb = colorsys.hsv_to_rgb(h, s * 0.46, min(1.0, v * 1.08))
            dp[x, y] = (min(255, int(rr * 255 * 1.04)),
                        min(255, int(gg * 255 * 1.01)),
                        min(255, int(bb * 255 * 0.99)))
    fixed.save(out, quality=96)
    return out


def main():
    os.makedirs(WORK, exist_ok=True)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)

    panels = [
        (os.path.join(CUR, "x6_adult_stand_front_01.jpg"),      "正面全身",   "FRONT / STANDING"),
        (os.path.join(CUR, "x6_adult_lying_threequarter_01.jpg"), "3/4 侧趴卧", "3-4 LYING"),
        (os.path.join(CUR, "x6_adult_stand_side_full_02.jpg"),  "正侧全身",   "PROFILE"),
        (os.path.join(CUR, "x6_adult_stand_back_01.jpg"),       "背面全身",   "BACK / TAIL"),
        (extract_v1_face(),                                    "脸部（定妆版）", "FACE — APPROVED v1"),
        (os.path.join(CUR, "x6_adult_lying_half_01.jpg"),         "趴卧抬头",   "LYING / HEAD UP"),
    ]

    COLS = 2
    rows = (len(panels) + COLS - 1) // COLS
    W = COLS * CELL_W
    H = rows * (CELL_H + LABEL_H)
    sheet = Image.new("RGB", (W, H), (14, 14, 16))
    d = ImageDraw.Draw(sheet)
    f_zh, f_en = font(40), font(22)

    for i, (path, zh, en) in enumerate(panels):
        if not os.path.exists(path):
            print("  [缺失] %s" % path); continue
        im = ImageOps.exif_transpose(Image.open(path)).convert("RGB")
        im.thumbnail((CELL_W - 8, CELL_H - 8))
        cx, cy = (i % COLS) * CELL_W, (i // COLS) * (CELL_H + LABEL_H)
        sheet.paste(im, (cx + (CELL_W - im.width) // 2, cy + (CELL_H - im.height) // 2))
        d.rectangle([cx, cy + CELL_H, cx + CELL_W, cy + CELL_H + LABEL_H], fill=(22, 22, 26))
        d.text((cx + 18, cy + CELL_H + 10), zh, fill=(245, 245, 250), font=f_zh)
        d.text((cx + 18, cy + CELL_H + 56), en, fill=(140, 140, 152), font=f_en)
        d.rectangle([cx, cy, cx + CELL_W - 1, cy + CELL_H + LABEL_H - 1], outline=(48, 48, 54))
        print("  ✅ %-14s %s" % (zh, os.path.basename(path)))

    sheet.save(OUT, quality=94)
    print("\n全身定妆照: %s  %dx%d" % (OUT, W, H))
    return 0


if __name__ == "__main__":
    sys.exit(main())
