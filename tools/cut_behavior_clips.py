#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
小六二 · 幼犬时期行为模组片段（从真实原始视频剪出）

所有片段都经过逐帧判读，**不含任何人物**（含人片段已剔除，见 docs/asset_index_puppy.csv）。
这是保真度最高的行为参考 —— 真狗、真动作，不是 AI 生成的。

输出：
  10_工作素材/habits/_curated/x6_puppy_<模组>_<序号>.mp4   原始片段（模型用，保留原画幅）

用法：python3 tools/cut_behavior_clips.py
"""

import os
import subprocess
import sys

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(PROJECT, "00_原片", "_待整理", "幼犬时期")
OUT = os.path.join(PROJECT, "10_工作素材", "habits", "_curated")

# (源文件, 起点秒, 终点秒, 输出名, 模组说明)
CLIPS = [
    ("video_20250613_181952.mp4", 62, 73, "x6_puppy_stand_look_01.mp4",
     "站立张望 — 走廊尽头，正面看镜头"),
    ("video_20250603_202320.mp4", 143, 163, "x6_puppy_stand_walk_02.mp4",
     "站立/行走 — 横屏，侧面全身，笼内"),
    ("video_20250606_095447.mp4", 0, 28, "x6_puppy_lying_toy_03.mp4",
     "趴卧啃玩具 — 全身，竖屏"),
    ("video_20250606_095447.mp4", 103, 123, "x6_puppy_sit_04.mp4",
     "坐姿 — 前爪直立，嘴张开"),
    ("video_20250612_150327.mp4", 23, 29, "x6_puppy_walk_approach_05.mp4",
     "走向镜头 — 狗由远及近走向镜头"),
    ("video_20250607_135237.mp4", 93, 101, "x6_puppy_run_to_cam_06.mp4",
     "跑向镜头 — 客厅，快速接近并跑过镜头"),
    ("video_20250612_150327.mp4", 14, 23, "x6_puppy_carry_slipper_07.mp4",
     "叼着拖鞋走 — 额外收获的剧情向素材"),
]


def ffmpeg_bin():
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        import shutil
        return shutil.which("ffmpeg")


def main():
    ff = ffmpeg_bin()
    os.makedirs(OUT, exist_ok=True)
    for src, start, end, name, desc in CLIPS:
        sp = os.path.join(SRC, src)
        if not os.path.exists(sp):
            print("  [缺失] %s" % src)
            continue
        out = os.path.join(OUT, name)
        cmd = [ff, "-y", "-ss", str(start), "-to", str(end), "-i", sp,
               "-c:v", "libx264", "-preset", "medium", "-crf", "20",
               "-pix_fmt", "yuv420p", "-an", "-movflags", "+faststart", out]
        subprocess.run(cmd, check=True, capture_output=True)
        size = os.path.getsize(out) / 1e6
        print("  ✅ %-34s %s→%ss  %.1f MB  (%s)" % (name, start, end, size, desc))
    return 0


if __name__ == "__main__":
    sys.exit(main())
