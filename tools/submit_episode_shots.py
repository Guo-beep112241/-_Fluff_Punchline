#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
批量提交 H3 生成镜头（Ep1 第 1 批：33 镜）

输入：episodes/ep01/prompts/sh*.md
输出：docs/video_tasks.json 登记 task_id + 20_生成结果/ep01/shots/ 待取回

脚本从每份 md 里解析四样东西：
  1. 提示词正文（第一个 ``` 代码块），校验是完整 Ref2VA 六段式且 ≤7000 字符
  2. 生成参数：时长（4–15 整数秒）、画幅、分辨率
  3. 参考图：`<Picture N>` → 文件名，按 N 排序即上传顺序
  4. 参考视频：`<Video N>` → 文件名（.mp4）

设计约束（都是踩过坑换来的，别改）：
  * 每提交一个就立刻落盘 task_id —— 中途失败时已经跑在平台上的任务绝不能丢，
    丢了只能重新提交，白花额度。
  * 存「实际提交的那一版」提示词原文 + sha256 —— 磁盘上的 md 可能在提交后被改写，
    那时磁盘版 ≠ 平台版，出了错复现不了。
  * task_id 重复直接拒绝覆盖 —— 说明平台返回了重复 id，先人工核对。
  * 临时 URL 一小时过期，提交前若已超 45 分钟就重新上传。

用法：
  python3 tools/submit_episode_shots.py --dry-run          # 只解析和校验，不提交
  python3 tools/submit_episode_shots.py --shots 01,02,04   # 只提交指定镜号
  python3 tools/submit_episode_shots.py --resolution 2K    # 覆盖 md 里的分辨率
  python3 tools/submit_episode_shots.py --limit 5          # 只跑前 5 个（试水）
"""

import argparse
import glob
import hashlib
import json
import os
import re
import subprocess
import sys
import time

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROMPT_DIR = os.path.join(PROJECT, "episodes/ep01/prompts")
TASKS_JSON = os.path.join(PROJECT, "docs/video_tasks.json")
ASSET_ROOT = os.path.join(PROJECT, "10_工作素材")
OUT_DIR = os.path.join(PROJECT, "20_生成结果/ep01/shots")
SNAP_DIR = os.path.join(PROMPT_DIR, "submitted")

# Ref2VA 六段式，缺一段就不是合法的提示词
SECTIONS = ["subject_definitions:", "summary:", "retention_analysis:",
            "detailed_description:", "overall_soundscape:", "non_diegetic_music:"]

IMAGE_EXT = (".jpg", ".jpeg", ".png", ".webp")
VIDEO_EXT = (".mp4", ".mov")

# 临时 URL 有效期约 1 小时，留足余量后重新上传
URL_TTL_MS = 45 * 60 * 1000


# ---------------------------------------------------------------- 解析

def extract_prompt(md_path):
    """取出第一个 ``` 代码块，并校验是完整 Ref2VA 六段式。"""
    txt = open(md_path, encoding="utf-8").read()
    blocks = re.findall(r"```\n(.*?)\n```", txt, re.S)
    if not blocks:
        raise ValueError("没有代码块：%s" % md_path)
    prompt = blocks[0].strip()
    missing = [s for s in SECTIONS if s not in prompt]
    if missing:
        raise ValueError("%s 不是完整六段式，缺：%s" % (os.path.basename(md_path), missing))
    if len(prompt) > 7000:
        raise ValueError("%s 提示词 %d 字符，超 H3 的 7000 上限"
                         % (os.path.basename(md_path), len(prompt)))
    return prompt


def parse_generation_params(txt):
    """从「## 生成参数」里抠出时长/画幅/分辨率。抠不到就交默认值。"""
    m = re.search(r"时长：\s*(\d+)\s*秒", txt)
    duration = int(m.group(1)) if m else 5
    m = re.search(r"分辨率：\s*([0-9A-Za-z]+)", txt)
    resolution = m.group(1) if m else "768P"
    m = re.search(r"画幅：\s*([0-9]+:[0-9]+)", txt)
    ratio = m.group(1) if m else "9:16"
    return duration, ratio, resolution


def parse_references(txt):
    """解析参考素材段。

    返回 (images, videos)，images 按 <Picture N> 的 N 升序 —— 这个顺序就是上传顺序，
    直接决定提示词里 <Picture 1> 指的是哪张图，不能乱。
    """
    sec = re.search(r"##\s*参考素材(.*?)(?=\n##\s|\Z)", txt, re.S)
    body = sec.group(1) if sec else txt

    images, videos = [], []
    for n, name in re.findall(r"`<Picture\s+(\d+)>`\s*→\s*`([^`]+)`", body):
        images.append((int(n), name))
    for n, name in re.findall(r"`<Video\s+(\d+)>`\s*→\s*`([^`]+)`", body):
        videos.append((int(n), name))

    images.sort(key=lambda x: x[0])
    videos.sort(key=lambda x: x[0])

    # 兜底：有些文件可能没用 <Picture N> 语法，只在正文里提了文件名
    if not images and not videos:
        for name in re.findall(r"`([^`]+\.(?:jpg|jpeg|png|webp|mp4|mov))`", body):
            (videos if name.lower().endswith(VIDEO_EXT) else images).append((0, name))

    return [i[1] for i in images], [v[1] for v in videos]


def parse_shot_title(txt):
    """取 md 的一级标题当这个镜的用途说明。"""
    m = re.search(r"^#\s+(.+)$", txt, re.M)
    return m.group(1).strip() if m else ""


def build_asset_index():
    """扫描 10_工作素材，建立 basename → 绝对路径 索引。"""
    idx = {}
    for root, _dirs, files in os.walk(ASSET_ROOT):
        for fn in files:
            if fn.lower().endswith(IMAGE_EXT + VIDEO_EXT):
                idx.setdefault(fn, os.path.join(root, fn))
    return idx


def discover_shots():
    """找出所有 sh*.md，按镜号排序。"""
    out = []
    for path in sorted(glob.glob(os.path.join(PROMPT_DIR, "sh*.md"))):
        m = re.search(r"sh(\d+)", os.path.basename(path))
        if not m:
            continue
        out.append((int(m.group(1)), path))
    out.sort(key=lambda x: x[0])
    return out


# ---------------------------------------------------------------- 外部调用

def upload(path):
    """上传本地文件，返回临时 URL。按扩展名选 mime。"""
    mime = "video/mp4" if path.lower().endswith(VIDEO_EXT) else "image/jpeg"
    out = subprocess.run(
        ["mcode-tools", "upload-temp-url", path, "--mime-type", mime],
        capture_output=True, text=True, timeout=300,
    )
    m = re.search(r'"temp_url"\s*:\s*"([^"]+)"', out.stdout)
    if not m:
        raise RuntimeError("上传失败 %s\n%s\n%s" % (path, out.stdout[-400:], out.stderr[-400:]))
    return m.group(1)


def submit(prompt, image_urls, video_urls, duration, ratio, resolution):
    args = {
        "model": "MiniMax-H3",
        "prompt": prompt,
        "duration": duration,
        "ratio": ratio,
        "resolution": resolution,
    }
    if image_urls:
        args["reference_images"] = [{"url": u} for u in image_urls]
    if video_urls:
        args["reference_videos"] = [{"url": u} for u in video_urls]

    args_file = "/tmp/h3_episode_submit_args.json"
    with open(args_file, "w", encoding="utf-8") as f:
        json.dump(args, f, ensure_ascii=False)

    out = subprocess.run(
        ["mcode-tools", "connector", "call", "connector__matrix__submit_video_generation",
         "--args-file", args_file],
        capture_output=True, text=True, timeout=600,
    )
    txt = out.stdout
    m = re.search(r'"task_id"\s*:\s*"?(\d+)"?', txt)
    if not m:
        raise RuntimeError("提交失败\n%s\n%s" % (txt[-1200:], out.stderr[-600:]))
    return m.group(1)


# ---------------------------------------------------------------- 任务登记

def load_tasks():
    with open(TASKS_JSON, encoding="utf-8") as f:
        return json.load(f)


def save_tasks(doc):
    """原子写。包装层 tasks 必须原样保留 —— 之前踩过被压扁的坑。"""
    if "tasks" not in doc:
        raise RuntimeError("video_tasks.json 缺 tasks 包装层，拒绝写入")
    tmp = TASKS_JSON + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=2)
    os.replace(tmp, TASKS_JSON)


def snapshot(prompt, key, stamp):
    """把实际提交的那一版提示词原样存盘 + sha256。"""
    os.makedirs(SNAP_DIR, exist_ok=True)
    path = os.path.join(SNAP_DIR, "%s_%s.txt" % (key, stamp))
    with open(path, "w", encoding="utf-8") as f:
        f.write(prompt + "\n")
    sha = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
    return os.path.relpath(path, PROJECT), sha


# ---------------------------------------------------------------- 主流程

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="只解析校验，不提交")
    ap.add_argument("--shots", help="只跑指定镜号，逗号分隔，如 01,02,04")
    ap.add_argument("--resolution", choices=["768P", "2K"], help="覆盖 md 里的分辨率")
    ap.add_argument("--limit", type=int, default=0, help="只跑前 N 个")
    ap.add_argument("--episode", default="ep01", help="集号，对应 episodes/<ep>/prompts")
    args = ap.parse_args()

    global PROMPT_DIR, OUT_DIR, SNAP_DIR
    PROMPT_DIR = os.path.join(PROJECT, "episodes", args.episode, "prompts")
    OUT_DIR = os.path.join(PROJECT, "20_生成结果", args.episode, "shots")
    SNAP_DIR = os.path.join(PROMPT_DIR, "submitted")

    wanted = None
    if args.shots:
        wanted = {int(x) for x in args.shots.split(",") if x.strip()}

    shots = discover_shots()
    if wanted is not None:
        shots = [(n, p) for n, p in shots if n in wanted]
    if args.limit:
        shots = shots[:args.limit]

    if not shots:
        print("没有找到 sh*.md（%s）" % PROMPT_DIR)
        return 1

    asset_idx = build_asset_index()

    # ---- 第一遍：解析 + 校验，一个都不提交 ----
    plan = []
    problems = []
    for num, path in shots:
        name = os.path.basename(path)
        try:
            txt = open(path, encoding="utf-8").read()
            prompt = extract_prompt(path)
            duration, ratio, resolution = parse_generation_params(txt)
            imgs, vids = parse_references(txt)

            if duration < 4 or duration > 15:
                raise ValueError("时长 %d 秒越界（4–15）" % duration)
            if args.resolution:
                resolution = args.resolution
            if resolution not in ("768P", "2K"):
                raise ValueError("分辨率 %s 不合法（H3 只支持 768P / 2K）" % resolution)

            if not imgs:
                raise ValueError("没解析到任何参考图")

            resolved_imgs, resolved_vids = [], []
            for fn in imgs:
                p = asset_idx.get(os.path.basename(fn))
                if not p:
                    raise ValueError("参考图找不到：%s" % fn)
                resolved_imgs.append(p)
            for fn in vids:
                p = asset_idx.get(os.path.basename(fn))
                if not p:
                    raise ValueError("参考视频找不到：%s" % fn)
                resolved_vids.append(p)

            if len(resolved_imgs) + len(resolved_vids) > 12:
                raise ValueError("参考素材合计 %d 个，超 H3 的 12 上限"
                                 % (len(resolved_imgs) + len(resolved_vids)))
            if len(resolved_imgs) > 9:
                raise ValueError("参考图 %d 张，超 9 上限" % len(resolved_imgs))
            if len(resolved_vids) > 3:
                raise ValueError("参考视频 %d 段，超 3 上限" % len(resolved_vids))

            plan.append({
                "num": num, "path": path, "prompt": prompt,
                "duration": duration, "ratio": ratio, "resolution": resolution,
                "images": resolved_imgs, "videos": resolved_vids,
                "title": parse_shot_title(txt),
                "key": "ep%s_sh%02d" % (args.episode.replace("ep", ""), num),
            })
        except Exception as e:  # noqa: BLE001
            problems.append((name, str(e)))

    print("解析 %d 份提示词，成功 %d 份，失败 %d 份" % (len(shots), len(plan), len(problems)))
    if problems:
        print("\n❌ 解析失败：")
        for name, err in problems:
            print("  %-16s %s" % (name, err))
    for p in plan:
        print("  镜%02d  %ds  %s  图%d 视频%d  提示词%d字符  %s"
              % (p["num"], p["duration"], p["resolution"],
                 len(p["images"]), len(p["videos"]), len(p["prompt"]), p["title"][:34]))

    if problems:
        print("\n有解析失败的镜，未提交。先修好再跑。")
        return 2
    if args.dry_run:
        print("\n（dry-run，未提交）")
        return 0

    # ---- 第二遍：真正提交 ----
    os.makedirs(OUT_DIR, exist_ok=True)
    doc = load_tasks()
    if "tasks" not in doc:
        print("❌ video_tasks.json 缺 tasks 包装层，中止")
        return 3

    # 参考素材只上传一次，多镜共用
    url_cache = {}
    uploaded_at = {}

    def get_url(path):
        now = int(time.time() * 1000)
        if path not in url_cache or now - uploaded_at.get(path, 0) > URL_TTL_MS:
            url_cache[path] = upload(path)
            uploaded_at[path] = now
            print("  ↑ 上传 %s" % os.path.basename(path))
        return url_cache[path]

    submitted = []
    try:
        for p in plan:
            img_urls = [get_url(i) for i in p["images"]]
            vid_urls = [get_url(v) for v in p["videos"]]

            task_id = submit(p["prompt"], img_urls, vid_urls,
                             p["duration"], p["ratio"], p["resolution"])
            if task_id in doc["tasks"]:
                raise RuntimeError(
                    "task_id %s 与已有记录重复（镜%02d），拒绝覆盖 —— "
                    "平台返回了重复 id，先人工核对再继续" % (task_id, p["num"]))

            now = int(time.time() * 1000)
            stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime(now / 1000))
            snap_path, sha = snapshot(p["prompt"], p["key"], stamp)
            out_name = "%s_v1_%s.mp4" % (p["key"], p["resolution"].lower())
            doc["tasks"][task_id] = {
                "model": "MiniMax-H3",
                "mode": "Ref2VA",
                "episode": args.episode,
                "shot": p["num"],
                "duration_s": p["duration"],
                "ratio": p["ratio"],
                "resolution": p["resolution"],
                "output_file": os.path.relpath(os.path.join(OUT_DIR, out_name), PROJECT),
                "purpose": p["title"],
                "submitted_at_ms": now,
                "submitted_at_cst": time.strftime("%Y-%m-%d %H:%M:%S CST", time.localtime(now / 1000)),
                "terminal_status": "submitted",
                "reference_images": [os.path.basename(i) for i in p["images"]],
                "reference_videos": [os.path.basename(v) for v in p["videos"]],
                "prompt_file": os.path.relpath(p["path"], PROJECT),
                "submitted_prompt_snapshot": snap_path,
                "submitted_prompt_sha256": sha,
                "last_query_at_ms": now,
                "last_query_at_cst": time.strftime("%Y-%m-%d %H:%M:%S CST", time.localtime(now / 1000)),
                "last_error": "",
                "delivery_retry_count": 0,
            }
            save_tasks(doc)
            submitted.append((p["num"], task_id))
            print("  ✅ 镜%02d task_id=%s（已落盘）" % (p["num"], task_id))
            time.sleep(2)
    except Exception as e:  # noqa: BLE001
        save_tasks(doc)
        print("\n⚠️ 中断：%s" % e)
        print("已成功提交并落盘的（照常取回，不要重新提交）：")
        for n, tid in submitted:
            print("   镜%02d %s" % (n, tid))
        return 4

    print("\n已登记 %d 个任务到 docs/video_tasks.json" % len(submitted))
    return 0


if __name__ == "__main__":
    sys.exit(main())
