#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
幼犬视频第二轮：细粒度定位（每 3 秒一帧）

第一轮每段只抽 4 帧，只能判断「有没有人」；这一轮对候选段密集抽帧，
用来精确定位「哪几秒是干净的、狗在做什么动作」，供后续剪出行为模组片段。

用法：python3 tools/triage_puppy_videos_dense.py
"""

import os
import re
import subprocess
import sys

from PIL import Image, ImageDraw, ImageFont

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(PROJECT, "00_原片", "_待整理", "幼犬时期")
OUT = os.path.join(PROJECT, "10_工作素材", "_work", "puppy_dense")

# 第一轮判读后的候选段（挑无人物、全身可见、动作有变化的）
CANDIDATES = [
    "video_20250603_202320.mp4",   # 横屏，笼中但全身可见，站立/走动/进食
    "video_20250605_090233.mp4",   # 横屏，全身，食盆边
    "video_20250605_124308.mp4",   # 垫子上走动
    "video_20250606_095447.mp4",   # 竖屏，走/趴/啃玩具
    "video_20250613_120157.mp4",   # 桌下走动
    "video_20250613_181938.mp4",   # 走动/嗅地
    "video_20250609_145444.mp4",   # 走动
    "video_20250613_181952.mp4",   # 跑向镜头
    "video_20250612_150327.mp4",   # 跑/走
    "video_20250604_132007.mp4",   # 垫子上
    "video_20250607_135237.mp4",   # 狗窝里
    "video_20250610_175927.mp4",   # 围栏特写
]

STEP = 3          # 每 3 秒一帧
COLS = 8          # 每行 8 帧
TILE_W, TILE_H = 220, 150
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
        import shutil
        return shutil.which("ffmpeg")


def duration_of(ff, path):
    out = subprocess.run([ff, "-hide_banner", "-i", path], capture_output=True, text=True).stderr
    m = re.search(r"Duration: (\d+):(\d+):(\d+\.\d+)", out)
    if not m:
        return 0.0
    h, mi, s = m.groups()
    return int(h) * 3600 + int(mi) * 60 + float(s)


def main():
    ff = ffmpeg_bin()
    os.makedirs(OUT, exist_ok=True)
    f_lab, f_small = font(18), font(15)

    for v in CANDIDATES:
        path = os.path.join(SRC, v)
        if not os.path.exists(path):
            print("缺失:", v)
            continue
        stem = os.path.splitext(v)[0]
        dur = duration_of(ff, path)
        times = list(range(0, int(dur), STEP))
        tiles = []
        for t in times:
            out = os.path.join(OUT, "%s_%04d.jpg" % (stem, t))
            if not os.path.exists(out):
                subprocess.run([ff, "-y", "-ss", str(t), "-i", path, "-frames:v", "1",
                                "-vf", "scale=%d:-2" % TILE_W, "-q:v", "4", out],
                               capture_output=True)
            if os.path.exists(out):
                tiles.append((out, t))
        if not tiles:
            continue

        rows = (len(tiles) + COLS - 1) // COLS
        W = COLS * TILE_W + 10
        H = rows * (TILE_H + 20) + 40
        sheet = Image.new("RGB", (W, H), (16, 16, 18))
        d = ImageDraw.Draw(sheet)
        d.text((12, 10), "%s   总长 %.0fs   每 %ds 一帧" % (stem, dur, STEP),
               fill=(255, 230, 110), font=f_lab)
        for i, (fp, t) in enumerate(tiles):
            im = Image.open(fp).convert("RGB")
            im.thumbnail((TILE_W, TILE_H))
            x = (i % COLS) * TILE_W
            y = 40 + (i // COLS) * (TILE_H + 20)
            sheet.paste(im, (x, y))
            d.text((x + 4, y + TILE_H - 1), "%ds" % t, fill=(255, 240, 150), font=f_small)
        p = os.path.join(OUT, "%s_dense.jpg" % stem)
        sheet.save(p, quality=88)
        print("  %-32s %3d 帧 → %s" % (v, len(tiles), os.path.basename(p)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
