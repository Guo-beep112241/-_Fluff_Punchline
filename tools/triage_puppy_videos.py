#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
幼犬时期原始视频 — 抽帧初筛

对每个视频在 10%/35%/60%/85% 四个时间点抽帧，拼成「一行一段视频」的判读表，
人工过一遍就能标出：有没有人 / 什么姿势 / 值不值得深挖。

输出：
  10_工作素材/_work/puppy_frames/<video>_<i>.jpg   抽出的帧
  10_工作素材/_work/puppy_sheets/sheet_N.jpg      判读表（每张 6 段视频）

用法：python3 tools/triage_puppy_videos.py
"""

import os
import re
import subprocess
import sys

from PIL import Image, ImageDraw, ImageFont

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(PROJECT, "00_原片", "_待整理", "幼犬时期")
FRAMES = os.path.join(PROJECT, "10_工作素材", "_work", "puppy_frames")
SHEETS = os.path.join(PROJECT, "10_工作素材", "_work", "puppy_sheets")

PER_VIDEO = 4
PER_SHEET = 6
TILE_W = 300
TILE_H = 200
LABEL_H = 22

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


def extract(ff, path, t, out):
    cmd = [ff, "-y", "-ss", "%.2f" % t, "-i", path, "-frames:v", "1",
           "-vf", "scale=%d:-2" % TILE_W, "-q:v", "3", out]
    subprocess.run(cmd, capture_output=True)
    return os.path.exists(out)


def main():
    ff = ffmpeg_bin()
    os.makedirs(FRAMES, exist_ok=True)
    os.makedirs(SHEETS, exist_ok=True)
    vids = sorted(f for f in os.listdir(SRC) if f.lower().endswith((".mp4", ".mov")))
    print("共 %d 段视频\n" % len(vids))

    rows = []
    for i, v in enumerate(vids):
        stem = os.path.splitext(v)[0]
        path = os.path.join(SRC, v)
        dur = duration_of(ff, path)
        tiles = []
        for k, frac in enumerate((0.10, 0.35, 0.60, 0.85)):
            t = dur * frac
            out = os.path.join(FRAMES, "%s_%d.jpg" % (stem, k))
            if not os.path.exists(out):
                extract(ff, path, t, out)
            if os.path.exists(out):
                tiles.append((out, t))
        rows.append((v, dur, tiles))
        print("  [%2d/%d] %-32s %6.1fs  抽到 %d 帧" % (i + 1, len(vids), v, dur, len(tiles)))

    # 拼判读表：每行一段视频，4 列帧
    f_lab, f_sub = font(19), font(15)
    for s in range(0, len(rows), PER_SHEET):
        chunk = rows[s:s + PER_SHEET]
        W = TILE_W * PER_VIDEO + 130
        H = (TILE_H + LABEL_H) * len(chunk) + 46
        sheet = Image.new("RGB", (W, H), (18, 18, 20))
        d = ImageDraw.Draw(sheet)
        d.text((14, 12), "幼犬时期原始视频 · 判读表  #%d" % (s // PER_SHEET + 1),
               fill=(255, 230, 110), font=f_lab)
        for r, (name, dur, tiles) in enumerate(chunk):
            y = 46 + r * (TILE_H + LABEL_H)
            d.text((10, y + 4), name.replace("video_", "").replace(".mp4", ""),
                   fill=(225, 225, 235), font=f_lab)
            d.text((10, y + 26), "%.0fs" % dur, fill=(140, 140, 150), font=f_sub)
            for c, (fp, t) in enumerate(tiles):
                try:
                    im = Image.open(fp).convert("RGB")
                except Exception:
                    continue
                im.thumbnail((TILE_W, TILE_H))
                x = 130 + c * TILE_W
                sheet.paste(im, (x, y))
                d.text((x + 4, y + TILE_H - 2), "%ds" % t, fill=(255, 240, 150), font=f_sub)
        p = os.path.join(SHEETS, "sheet_%d.jpg" % (s // PER_SHEET + 1))
        sheet.save(p, quality=90)
        print("\n判读表 → %s  (%d 段)" % (p, len(chunk)))

    print("\n完成。共 %d 张判读表。" % len(range(0, len(rows), PER_SHEET)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
