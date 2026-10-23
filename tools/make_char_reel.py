#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
小六二 · 成年期定妆参考卷轴（角色参考视频）

为什么不用 AI 生成：
  本机是 MacBook Air M3 / 8GB 统一内存。实测（2026-10-23）：
  MPS 上 SDPA 没有真正的 flash kernel，注意力矩阵被完整物化；
  AnimateDiff 的时序注意力序列长 = 帧数 × 空间token，平方级膨胀，
  撞上 Metal 单 buffer 4GiB 硬上限。可用窗口仅 ~12000 token
  （= 16 帧只能跑 224×224），画质不可用。
  SVD-XT 在 HuggingFace 上是 gated 模型，无法下载。
  结论：本地无法产出有质量的视频，改为「真实素材合成」，保真度 100%。

产出两个版本：
  x6_adult_char_reel_model.mp4    —— 纯净版（无字、无运镜），给 AI 模型当参考输入
  x6_adult_char_reel_labeled.mp4  —— 标注版（中文角度/姿势标注 + 缓慢推镜），给人看

用法：
  python3 tools/make_char_reel.py
"""

import os
import shutil
import subprocess
import sys

from PIL import Image, ImageDraw, ImageFont, ImageOps

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CURATED = os.path.join(PROJECT, "10_工作素材", "characters", "_curated", "adult")
WORK = os.path.join(PROJECT, "10_工作素材", "_work", "reel")
OUTDIR = os.path.join(PROJECT, "20_生成结果", "ep01", "reference")
W, H, FPS = 1080, 1920, 24

CJK = "/System/Library/Fonts/Hiragino Sans GB.ttc"


def font(size):
    try:
        return ImageFont.truetype(CJK, size)
    except Exception:
        return ImageFont.load_default()


def ffmpeg_bin():
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        exe = shutil.which("ffmpeg")
        if exe:
            return exe
    raise SystemExit("找不到 ffmpeg：装 imageio-ffmpeg 或把 ffmpeg 放进 PATH")


# 顺序 = 分镜逻辑：全身形态 → 面部 → 坐姿 → 趴卧
ORDER = [
    ("x6_adult_stand_front_01",        "全身 · 正面站立",        "STAND / FRONT"),
    ("x6_adult_lying_threequarter_01", "全身 · 3/4 侧趴卧",     "LYING / 3-4"),
    ("x6_adult_stand_side_01",         "全身 · 正侧站",          "STAND / PROFILE"),
    ("x6_adult_face_front_sharp_01",   "面部 · 正面（最清晰）",  "FACE / FRONT"),
    ("x6_adult_face_threequarter_01",  "面部 · 3/4 侧",          "FACE / 3-4"),
    ("x6_adult_face_front_01",         "面部 · 正面",            "FACE / FRONT"),
    ("x6_adult_face_front_tongue_01",  "面部 · 正面吐舌",        "FACE / FRONT"),
    ("x6_adult_lying_half_01",           "趴卧抬头 · 半身",        "LYING"),
    ("x6_adult_lying_full_02",         "趴卧 · 全身吐舌",        "LYING / FULL"),
    ("x6_adult_lying_full_01",         "趴卧 · 全身",            "LYING / FULL"),
    ("x6_adult_lying_chin_down_01",    "趴 · 下颌贴地",          "LYING / CHIN DOWN"),
    ("x6_adult_lying_onback_01",       "趴卧 · 仰躺",            "LYING / ON BACK"),
    ("x6_adult_lying_head_01",         "趴卧 · 俯视头部",        "LYING / HEAD"),
    ("x6_adult_lying_face_01",         "趴卧 · 俯视面部",        "LYING / FACE"),
]

SECTIONS = [
    ("全身形态", "FULL BODY FORM"),
    ("面部特征", "FACE / IDENTIFICATION"),
    ("坐姿", "SITTING"),
    ("趴卧", "LYING DOWN"),
]


def fit_canvas(img, label_zh=None, label_en=None):
    """把照片 contain 到 1080x1920 深色画布；可选底部标注条。"""
    bg = (22, 22, 25)
    band = 0 if label_zh is None else 168
    canvas = Image.new("RGB", (W, H - band), bg)
    im = ImageOps.exif_transpose(img).convert("RGB")
    scale = min((W - 40) / im.width, (H - band - 40) / im.height)
    im = im.resize((int(im.width * scale), int(im.height * scale)), Image.LANCZOS)
    canvas.paste(im, ((W - im.width) // 2, ((H - band) - im.height) // 2))
    if band:
        strip = Image.new("RGB", (W, band), (12, 12, 14))
        d = ImageDraw.Draw(strip)
        d.text((40, 28), label_zh, fill=(245, 245, 248), font=font(58))
        d.text((40, 104), label_en, fill=(150, 150, 160), font=font(30))
        canvas = Image.concat(Image.new("RGB", (1, 1)), canvas) if False else canvas
        out = Image.new("RGB", (W, H), bg)
        out.paste(canvas, (0, 0))
        out.paste(strip, (0, H - band))
        return out
    return canvas


def title_card(zh, en, sub=None):
    canvas = Image.new("RGB", (W, H), (16, 16, 19))
    d = ImageDraw.Draw(canvas)
    d.text((80, 700), zh, fill=(255, 235, 120), font=font(72))
    d.text((80, 800), en, fill=(170, 170, 180), font=font(34))
    if sub:
        d.text((80, 880), sub, fill=(120, 120, 130), font=font(30))
    d.line([(80, 660), (400, 660)], fill=(255, 235, 120), width=4)
    return canvas


def build_pngs():
    os.makedirs(WORK, exist_ok=True)
    seq = []
    for i, (name, zh, en) in enumerate(ORDER):
        src = os.path.join(CURATED, name + ".jpg")
        if not os.path.exists(src):
            print("  跳过（缺失）: %s" % name)
            continue
        for labeled in (True, False):
            img = Image.open(src)
            canvas = fit_canvas(img, zh if labeled else None, en if labeled else None)
            p = os.path.join(WORK, "%s_%02d.jpg" % ("L" if labeled else "M", i))
            canvas.save(p, quality=94)
            seq.append((p, labeled))
        print("  ✓ %-32s %s" % (name, zh))

    # 片头（两个版本各一张，各自排在自己序列的第 0 位）
    for labeled in (True, False):
        card = title_card(
            "小六二 · 成年期定妆参考",
            "XIAO LIU ER — ADULT CHARACTER REFERENCE",
            "真人物理照片 · 未经 AI 修改" if labeled else None,
        )
        p = os.path.join(WORK, "%s_title.jpg" % ("L" if labeled else "M"))
        card.save(p, quality=94)
        seq.insert(0, (p, labeled))
    return seq


def concat_model(seq, out_path):
    """纯净版：concat demuxer + fps 滤镜，静止画面、无运镜。"""
    ff = ffmpeg_bin()
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    lst = os.path.join(WORK, "list_M.txt")
    with open(lst, "w") as fh:
        for p, lab in seq:
            if lab:
                continue
            fh.write("file '%s'\n" % p)
            fh.write("duration 1.8\n")
        fh.write("file '%s'\n" % seq[0][0])
    cmd = [ff, "-y", "-f", "concat", "-safe", "0", "-i", lst,
           "-vf", "fps=%d,format=yuv420p" % FPS,
           "-c:v", "libx264", "-preset", "medium", "-crf", "20",
           "-movflags", "+faststart", out_path]
    subprocess.run(cmd, check=True, capture_output=True)
    return out_path


def concat_labeled(seq, out_path):
    """标注版：逐段生成（慢速横移推镜）后再拼接。

    不能直接对 concat demuxer 用 zoompan —— zoompan 会重置时间戳，
    把每张图 1.8 秒的停留压成 1 帧（实测成片只有 0.67 秒）。
    """
    ff = ffmpeg_bin()
    segdir = os.path.join(WORK, "segments")
    os.makedirs(segdir, exist_ok=True)
    for f in os.listdir(segdir):
        os.remove(os.path.join(segdir, f))

    segs = []
    for i, (p, lab) in enumerate([x for x in seq if x[1]]):
        seg = os.path.join(segdir, "seg_%03d.mp4" % i)
        # 放大 12% 再横向缓慢移动：轻微运镜，够看清细节，又不会教模型大幅运镜
        # 放大倍数取 1.1 且用精确整数（1188x2112 = 1080x1920 x 1.1），
        # 否则 SAR 会有千分级偏差，播放器里画面被拉一点点
        vf = ("scale=1188:2112,crop=%d:%d:x='(iw-ow)*t/1.8':y='(ih-oh)/2',fps=%d,format=yuv420p"
              % (W, H, FPS))
        subprocess.run([ff, "-y", "-loop", "1", "-t", "1.8", "-i", p, "-vf", vf,
                        "-r", str(FPS), "-c:v", "libx264", "-preset", "medium", "-crf", "20", seg],
                       check=True, capture_output=True)
        segs.append(seg)

    lst = os.path.join(WORK, "list_L.txt")
    with open(lst, "w") as fh:
        for s in segs:
            fh.write("file '%s'\n" % s)
    cmd = [ff, "-y", "-f", "concat", "-safe", "0", "-i", lst,
           "-c:v", "libx264", "-preset", "medium", "-crf", "20",
           "-movflags", "+faststart", out_path]
    subprocess.run(cmd, check=True, capture_output=True)
    return out_path


def main():
    print("渲染分镜 PNG…")
    seq = build_pngs()
    print("\n合成 model 版（纯净、无运镜）…")
    p1 = concat_model(seq, os.path.join(OUTDIR, "x6_adult_char_reel_model.mp4"))
    print("合成 labeled 版（中文标注 + 缓慢横移）…")
    p2 = concat_labeled(seq, os.path.join(OUTDIR, "x6_adult_char_reel_labeled.mp4"))
    for p in (p1, p2):
        print("  ✅ %s  (%.1f MB)" % (p, os.path.getsize(p) / 1e6))
    return 0


if __name__ == "__main__":
    sys.exit(main())
