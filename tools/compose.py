#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""compose — 本地合成首帧（零调用、零额度）

云端图像额度耗尽后的替代方案：
  真实照片抠出小六二 → 按景别/机位规则放进场景锚点图 → 统一调色 + 接触阴影 + 颗粒 + 暗角

定位：这是"拼贴绘本"式的画面语言，不是假装写实合成；
      统一调色、颗粒、暗角的作用是让拼贴看起来是有意为之的风格，而不是穿帮。

用法：
  python3 tools/compose.py --ep ep01            # 只补缺失的首帧
  python3 tools/compose.py --ep ep01 --force    # 全部重做
  python3 tools/compose.py --ep ep01 --shots 3,4 --preview
"""
import argparse
import json
import math
import os
import sys

import numpy as np
from PIL import Image, ImageFilter, ImageDraw

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

SCENES = {
    "noticeboard": "scene_campus_noticeboard_01.jpg",
    "corridor": "scene_campus_corridor_01.jpg",
    "dorm": "scene_dorm_floor_01.jpg",
    "rehearsal": "scene_rehearsal_room_01.jpg",
    "lecture": "scene_lecture_hall_01.jpg",
    "theatre": "scene_theatre_stage_01.jpg",
    "home": "scene_livingroom_01.jpg",
    "campus": "scene_campus_path_01.jpg",
    "field": "scene_campus_field_01.jpg",
    "gate": "scene_campus_gate_01.jpg",
    "booth": "scene_club_booth_01.jpg",
    "dormhall": "scene_dorm_hall_01.jpg",
}

W, H = 1080, 1920

# 抠图质量可靠的几张（人工看过）：只有这些参与"放进场景"的拼贴，其余一律整幅真照片
CUTOUT_OK = {
    "x6_adult_stand_front_01.jpg",
    "x6_adult_stand_side_full_02.jpg",
    "x6_adult_lying_full_02.jpg",
}
CUT_DIR = os.path.join(PROJECT, "10_工作素材", "characters", "_curated", "adult_cut")


# ---------------------------------------------------------------- 抠图（缓存）

def cutout(ref_path):
    """真实照片 → RGBA 抠图（缓存到 adult_cut/）。"""
    os.makedirs(CUT_DIR, exist_ok=True)
    base = os.path.splitext(os.path.basename(ref_path))[0]
    out = os.path.join(CUT_DIR, base + ".png")
    if os.path.exists(out):
        return Image.open(out).convert("RGBA")
    from rembg import remove, new_session
    session = new_session("isnet-general-use")
    im = Image.open(ref_path).convert("RGB")
    # 太大的图先缩一下，抠图快很多，边缘反而更干净
    if max(im.size) > 2000:
        s = 2000 / max(im.size)
        im = im.resize((int(im.width * s), int(im.height * s)), Image.LANCZOS)
    res = remove(im, session=session, alpha_matting=False)
    # 硬阈值去半透明暗边，再羽化 —— rembg 的软边会带一圈原背景的脏灰
    a = np.array(res.getchannel("A")).astype(np.uint8)
    a = np.where(a > 96, 255, 0).astype(np.uint8)
    res.putalpha(Image.fromarray(a).filter(ImageFilter.GaussianBlur(1.4)))
    res = trim_alpha(res)
    res.save(out)
    return res


def trim_alpha(im):
    """裁掉四周全透明区域，让后续定位稳定。"""
    a = np.array(im.getchannel("A"))
    ys, xs = np.where(a > 12)
    if len(xs) == 0:
        return im
    return im.crop((xs.min(), ys.min(), xs.max() + 1, ys.max() + 1))


# ---------------------------------------------------------------- 场景

def load_scene(scene, grade="neutral"):
    p = os.path.join(PROJECT, "10_工作素材", "scenes", SCENES[scene])
    if not os.path.exists(p):
        # 场景锚点还没生成：用一张中性灰底，保证流水线不中断
        im = Image.new("RGB", (1080, 1920), (58, 56, 54))
        return im
    im = Image.open(p).convert("RGB")
    s = max(W / im.width, H / im.height)
    im = im.resize((math.ceil(im.width * s), math.ceil(im.height * s)), Image.LANCZOS)
    left = (im.width - W) // 2
    top = (im.height - H) // 2
    im = im.crop((left, top, left + W, top + H))
    if grade == "cool":
        im = Image.blend(im, Image.new("RGB", im.size, (210, 225, 240)), 0.10)
    elif grade == "warm":
        im = Image.blend(im, Image.new("RGB", im.size, (255, 235, 210)), 0.10)
    elif grade == "night":
        a = np.array(im).astype(np.float32)
        a *= np.array([0.55, 0.62, 0.78], dtype=np.float32)
        im = Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))
    return im


# ---------------------------------------------------------------- 构图规则

def infer_layout(shot, ref_name):
    """从景别/机位/姿态推一个构图：返回 (宽度占比, 中心x, 底边y)。"""
    p = (shot.get("frame_prompt") or "")
    ref = (ref_name or "").lower()

    if "特写" in p:
        w_frac, y_bottom = 1.15, 1.05
    elif "近景" in p:
        w_frac, y_bottom = 0.95, 1.00
    elif "全景" in p:
        w_frac, y_bottom = 0.55, 0.90
    else:
        w_frac, y_bottom = 0.75, 0.95

    if "俯拍" in p or "俯" in p:
        w_frac *= 0.85
        y_bottom = 0.80
    if "低机位" in p or "贴地" in p:
        y_bottom = min(1.02, y_bottom + 0.05)

    if "face" in ref:
        w_frac *= 1.15
    if "lying" in ref:
        w_frac *= 0.95
        y_bottom = min(1.0, y_bottom)
    if "stand_back" in ref:
        w_frac *= 0.9

    cx = 0.5
    if "画面左侧" in p or "画面左下" in p:
        cx = 0.36
    elif "画面右侧" in p or "画面右下" in p:
        cx = 0.64
    return w_frac, cx, y_bottom


def shadow_under(size, dog_box, strength=0.55):
    """dog_box=(x0,y0,x1,y1) 在 1080x1920 画布上的包围盒 → 一张软阴影层。"""
    x0, y0, x1, y1 = dog_box
    w = max(40, int((x1 - x0) * 0.95))
    h = max(24, int((y1 - y0) * 0.16))
    layer = Image.new("L", (W, H), 0)
    d = ImageDraw.Draw(layer)
    cx = (x0 + x1) // 2
    cy = int(y1 - h * 0.25)
    d.ellipse([cx - w // 2, cy - h // 2, cx + w // 2, cy + h // 2], fill=int(255 * strength))
    layer = layer.filter(ImageFilter.GaussianBlur(max(6, h // 3)))
    return layer


def match_color(dog, scene_crop):
    """把狗的亮度/色温往场景里拉一点，避免"贴上去的白片"。"""
    da = np.array(dog.convert("RGB")).astype(np.float32)
    a = np.array(dog.getchannel("A")).astype(np.float32) / 255.0
    mask = a > 0.5
    if mask.sum() < 100:
        return dog
    dm = da[mask].mean(axis=0)
    sm = np.array(scene_crop.convert("RGB")).astype(np.float32).reshape(-1, 3)
    sm = sm.mean(axis=0)
    # 只做温和的通道增益（±18%），保留狗本身的白毛
    gain = np.clip(sm / (dm + 1e-3), 0.82, 1.18)
    out = da * gain
    # 亮度对齐：让狗的平均亮度接近场景亮度（最多 12%）
    dl = dm.mean()
    sl = sm.mean()
    k = float(np.clip(sl / (dl + 1e-3), 0.88, 1.12))
    out = out * k
    return Image.fromarray(np.clip(out, 0, 255).astype(np.uint8)).convert("RGBA").convert("RGB"), gain


def finish(img, scene):
    """统一质感：颗粒 + 轻微暗角 + 轻微柔光，让拼贴像同一次拍摄。"""
    a = np.array(img).astype(np.float32)
    # 极轻的 bloom
    blur = np.array(img.filter(ImageFilter.GaussianBlur(6))).astype(np.float32)
    a = a * 0.92 + blur * 0.08
    # 暗角
    yy, xx = np.mgrid[0:a.shape[0], 0:a.shape[1]]
    cx, cy = a.shape[1] / 2, a.shape[0] / 2
    r = np.sqrt(((xx - cx) / cx) ** 2 + ((yy - cy) / cy) ** 2)
    vig = np.clip(1.0 - 0.28 * np.clip(r - 0.55, 0, 2) ** 1.6, 0.55, 1.0)[..., None]
    a = a * vig
    # 颗粒
    rng = np.random.default_rng(abs(hash(scene)) % 2 ** 32)
    grain = rng.normal(0, 3.2, a.shape[:2])[..., None]
    a = a + grain
    return Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))


def full_photo_frame(ref_path, out_path):
    """特写/近景：直接用真实照片整幅构图（不抠图、不拼接），只做调色与质感。"""
    im = Image.open(ref_path).convert("RGB")
    s = max(W / im.width, H / im.height)
    im = im.resize((math.ceil(im.width * s), math.ceil(im.height * s)), Image.LANCZOS)
    left = (im.width - W) // 2
    # 脸部照片：构图上偏一点，把眼睛放在上三分之一
    top = int((im.height - H) * 0.42)
    im = im.crop((left, top, left + W, top + H))
    finish(im, "photo").save(out_path, "PNG")
    return out_path, "photo"


def compose_one(shot, out_path):
    refs = shot.get("refs") or []
    scene_img = load_scene(shot["scene"],
                           grade="cool" if shot["scene"] in ("corridor", "lecture", "noticeboard") else "neutral")
    if not refs:
        finish(scene_img, shot["scene"]).save(out_path, "PNG")
        return out_path, "plate"

    ref = os.path.join(PROJECT, refs[0])
    p = shot.get("frame_prompt") or ""
    is_face = "face" in os.path.basename(ref).lower()
    close = ("特写" in p) or ("近景" in p)

    # 脸部特写、或这张照片抠不干净 → 整幅真照片（拼贴在特写下必然穿帮）
    if is_face or os.path.basename(ref) not in CUTOUT_OK:
        return full_photo_frame(ref, out_path)

    dog = cutout(ref)
    if "俯拍" in p:
        base_h = 0.34 * H
    elif "全景" in p:
        base_h = 0.30 * H
    elif close:
        base_h = 0.46 * H
    else:
        base_h = 0.40 * H
    base_h = max(0.26 * H, min(0.52 * H, base_h))
    th = int(base_h)
    s = th / dog.height
    tw = int(dog.width * s)
    cx = 0.5 + (0.13 if "右侧" in p else -0.13 if "左侧" in p else 0.0)
    floor = 0.86 if "俯拍" not in p else 0.70
    x = int(W * cx - tw / 2)
    y = int(H * floor - th)
    dog_layer = dog.resize((tw, th), Image.LANCZOS)

    # 颜色匹配到落地处的地面
    crop = scene_img.crop((max(0, x), max(0, y + th - int(0.10 * th)),
                           min(W, x + tw), min(H, y + th))).convert("RGB")
    rgb, _g = match_color(dog_layer, crop)

    base = scene_img.convert("RGBA")
    # 接触阴影：宽而软，落在脚下方
    sh = Image.new("L", (W, H), 0)
    d = ImageDraw.Draw(sh)
    ew, eh = int(tw * 1.15), max(30, int(th * 0.22))
    cxs, cys = int(W * cx), int(H * floor - eh * 0.28)
    d.ellipse([cxs - ew // 2, cys - eh // 2, cxs + ew // 2, cys + eh // 2], fill=110)
    sh = sh.filter(ImageFilter.GaussianBlur(max(14, eh // 2)))
    dark = Image.new("RGBA", (W, H), (14, 12, 10, 255))
    dark.putalpha(sh)
    base = Image.alpha_composite(base, dark)

    dd = rgb.convert("RGBA")
    dd.putalpha(dog_layer.getchannel("A"))
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    layer.paste(dd, (x, y), dd)
    out = Image.alpha_composite(base, layer).convert("RGB")
    finish(out, shot["scene"]).save(out_path, "PNG")
    return out_path, "compose"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ep", required=True)
    ap.add_argument("--shots", default="")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--preview", action="store_true")
    a = ap.parse_args()

    spec = json.load(open(os.path.join(PROJECT, "episodes", a.ep, "shots.json"), encoding="utf-8"))
    outdir = os.path.join(PROJECT, "20_生成结果", a.ep, "frames")
    os.makedirs(outdir, exist_ok=True)
    wanted = set(int(x) for x in a.shots.split(",")) if a.shots else None

    n = 0
    for s in spec["shots"]:
        if wanted and s["id"] not in wanted:
            continue
        out = os.path.join(outdir, "sh%02d.png" % s["id"])
        if os.path.exists(out) and not a.force:
            continue
        p, how = compose_one(s, out)
        n += 1
        print("  %s 镜%02d %s" % (how, s["id"], os.path.basename(p)))
    print("合成 %d 张（%s）" % (n, a.ep))
    return 0


if __name__ == "__main__":
    sys.exit(main())
