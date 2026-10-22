#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
小六二 · 幼犬行为模组卷轴

把 7 段真实行为片段（`10_工作素材/habits/_curated/x6_puppy_*.mp4`）合成竖屏卷轴。

两个版本：
  x6_puppy_behavior_reel_model.mp4    —— 给 AI 模型：无字幕、无运镜
  x6_puppy_behavior_reel_labeled.mp4  —— 给人看：底部中文标注 + 轻微横移

用法：python3 tools/make_behavior_reel.py
"""

import os
import shutil
import subprocess
import sys

from PIL import Image, ImageDraw, ImageFont

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CLIPS = os.path.join(PROJECT, "10_工作素材", "habits", "_curated")
WORK = os.path.join(PROJECT, "10_工作素材", "_work", "behavior_reel")
OUTDIR = os.path.join(PROJECT, "20_生成结果", "ep01", "reference")
W, H, FPS = 1080, 1920, 24

# (文件名, 中文标注, 英文标注)
ORDER = [
    ("x6_puppy_stand_look_01",       "站立张望",   "STAND / LOOK AT CAMERA"),
    ("x6_puppy_stand_walk_02",       "站立行走",   "STAND / WALK SIDE"),
    ("x6_puppy_sit_04",              "坐姿",       "SIT"),
    ("x6_puppy_lying_toy_03",        "趴卧啃玩具", "LYING / TOY"),
    ("x6_puppy_walk_approach_05",    "走向镜头",   "WALK TO CAMERA"),
    ("x6_puppy_run_to_cam_06",       "跑向镜头",   "RUN TO CAMERA"),
    ("x6_puppy_carry_slipper_07",    "叼着拖鞋走", "CARRY SLIPPER"),
]

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


def label_strip(zh, en):
    strip = Image.new("RGB", (W, 168), (12, 12, 14))
    d = ImageDraw.Draw(strip)
    d.text((40, 26), zh, fill=(245, 245, 248), font=font(58))
    d.text((40, 104), en, fill=(150, 150, 160), font=font(30))
    return strip


def title_card():
    canvas = Image.new("RGB", (W, H), (16, 16, 19))
    d = ImageDraw.Draw(canvas)
    d.line([(80, 660), (400, 660)], fill=(255, 235, 120), width=4)
    d.text((80, 700), "小六二 · 幼犬行为模组", fill=(255, 235, 120), font=font(66))
    d.text((80, 800), "PUPPY BEHAVIOR REFERENCE", fill=(170, 170, 180), font=font(34))
    d.text((80, 880), "真实原始视频 · 无人物 · 真狗真动作", fill=(120, 120, 130), font=font(30))
    return canvas


def build_segments(ff, labeled):
    """每段片段：抽首帧 → 适配 1080x1920 → 逐段编码 → 拼接。"""
    segdir = os.path.join(WORK, "segs_%s" % ("L" if labeled else "M"))
    os.makedirs(segdir, exist_ok=True)
    for f in os.listdir(segdir):
        os.remove(os.path.join(segdir, f))

    # 片头
    card = title_card()
    cp = os.path.join(WORK, "title_%s.png" % ("L" if labeled else "M"))
    card.save(cp)

    segs = []
    items = [(cp, None, None)] + [(os.path.join(CLIPS, n + ".mp4"), zh, en)
                                   for n, zh, en in ORDER if os.path.exists(os.path.join(CLIPS, n + ".mp4"))]
    CLIP_SECS = 3.5
    for i, (src, zh, en) in enumerate(items):
        seg = os.path.join(segdir, "s%02d.mp4" % i)
        if src.endswith(".png"):
            # 片头：静止 2.5 秒
            subprocess.run([ff, "-y", "-loop", "1", "-t", "2.5", "-i", src, "-r", str(FPS),
                            "-vf", "scale=%d:%d,format=yuv420p" % (W, H),
                            "-c:v", "libx264", "-preset", "medium", "-crf", "20", seg],
                           check=True, capture_output=True)
        else:
            # 行为模组必须是【动态】的：直接用视频流，不能只取首帧。
            # 流程：等比适配到 1080x1752 → 补边 → 轻微横移推镜 → 叠加中文标注条
            band = 168 if labeled else 0
            fh = H - band
            if labeled:
                # 视频适配到 1080x1752 后贴到【顶部】，底部 168px 留给中文标注条
                base = ("scale=%d:%d:force_original_aspect_ratio=decrease,"
                        "pad=%d:%d:(ow-iw)/2:0:color=0x101014,fps=%d" % (W, fh, W, H, FPS))
                strip = os.path.join(WORK, "strip_%02d.png" % i)
                label_strip(zh, en).save(strip)
                cmd = [ff, "-y", "-i", src, "-i", strip, "-t", str(CLIP_SECS),
                       "-filter_complex",
                       "[0:v]%s[v];[v][1:v]overlay=0:%d,format=yuv420p" % (base, fh),
                       "-r", str(FPS)]
            else:
                base = ("scale=%d:%d:force_original_aspect_ratio=decrease,"
                        "pad=%d:%d:(ow-iw)/2:(oh-ih)/2:color=0x101014,fps=%d" % (W, H, W, H, FPS))
                cmd = [ff, "-y", "-i", src, "-t", str(CLIP_SECS),
                       "-vf", base + ",format=yuv420p", "-r", str(FPS)]
            cmd += ["-c:v", "libx264", "-preset", "medium", "-crf", "20", seg]
            subprocess.run(cmd, check=True, capture_output=True)
        segs.append(seg)

    lst = os.path.join(WORK, "list_%s.txt" % ("L" if labeled else "M"))
    with open(lst, "w") as fh:
        for s in segs:
            fh.write("file '%s'\n" % s)
    out = os.path.join(OUTDIR, "x6_puppy_behavior_reel_%s.mp4" % ("labeled" if labeled else "model"))
    subprocess.run([ff, "-y", "-f", "concat", "-safe", "0", "-i", lst,
                    "-c:v", "libx264", "-preset", "medium", "-crf", "20",
                    "-movflags", "+faststart", out], check=True, capture_output=True)
    return out


def main():
    os.makedirs(WORK, exist_ok=True)
    os.makedirs(OUTDIR, exist_ok=True)
    ff = ffmpeg_bin()
    for labeled in (False, True):
        p = build_segments(ff, labeled)
        print("  ✅ %s  (%.1f MB)" % (p, os.path.getsize(p) / 1e6))
    return 0


if __name__ == "__main__":
    sys.exit(main())
