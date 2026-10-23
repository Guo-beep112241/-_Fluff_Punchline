#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
提交 H3 验证镜头（第 0 批 · 口型验证）

V1 / V2 / V3 三镜：同一句台词、同一场景、同一角色状态，
唯一变量 = 脸朝向 + 嘴部遮挡 + lip-sync 措辞。
这 3 个镜决定全季 188 个镜头的台词策略，必须在批量生成前跑完。

用法：
  python3 tools/submit_verify_shots.py            # 提交 3 个
  python3 tools/submit_verify_shots.py --dry-run  # 只打印参数，不提交
"""

import json
import os
import re
import subprocess
import sys
import time

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CUR = os.path.join(PROJECT, "10_工作素材/characters/_curated/adult")
TASKS_JSON = os.path.join(PROJECT, "docs/video_tasks.json")
P = os.path.join(PROJECT, "episodes/ep01/prompts")
OUT_DIR = os.path.join(PROJECT, "20_生成结果/ep01/verify")

# 每个验证镜：提示词文件 → 参考图（顺序即 <Picture 1..N>）→ 输出名
SHOTS = [
    {
        "key": "verify_v1_front",
        "md": "verify_v1_front.md",
        "out": "ep01_verify_v1_front_768p.mp4",
        "images": [
            "x6_adult_face_front_sharp_01.jpg",
            "x6_adult_lying_full_02.jpg",
        ],
        "purpose": "第0批口型验证 V1 — 正面直视镜头说中文（🔴 高风险）",
    },
    {
        "key": "verify_v2_threequarter",
        "md": "verify_v2_threequarter.md",
        "out": "ep01_verify_v2_threequarter_768p.mp4",
        "images": [
            "x6_adult_face_front_sharp_01.jpg",
            "x6_adult_stand_threequarter_01.jpg",
            "x6_adult_lying_full_02.jpg",
        ],
        "purpose": "第0批口型验证 V2 — 3/4 侧脸说中文（🟡 中风险）",
    },
    {
        "key": "verify_v3_mouth_covered",
        "md": "verify_v3_mouth_covered.md",
        "out": "ep01_verify_v3_mouth_covered_768p.mp4",
        "images": [
            "x6_adult_lying_head_01.jpg",
            "x6_adult_lying_full_02.jpg",
        ],
        "purpose": "第0批口型验证 V3 — 嘴部被笔与纸堆遮挡（🟢 低风险）",
    },
]


def extract_prompt(md_path):
    """从 md 的 ``` 代码块里取出提示词正文。"""
    txt = open(md_path, encoding="utf-8").read()
    blocks = re.findall(r"```\n(.*?)\n```", txt, re.S)
    if not blocks:
        raise SystemExit("no code block in %s" % md_path)
    return blocks[0].strip()


def upload(path):
    """上传本地文件，返回临时 URL。"""
    out = subprocess.run(
        ["mcode-tools", "upload-temp-url", path, "--mime-type", "image/jpeg"],
        capture_output=True, text=True, timeout=300,
    )
    m = re.search(r'"temp_url"\s*:\s*"([^"]+)"', out.stdout)
    if not m:
        raise SystemExit("upload failed for %s:\n%s\n%s" % (path, out.stdout[-500:], out.stderr[-500:]))
    return m.group(1)


def submit(prompt, image_urls, duration, resolution):
    args = {
        "model": "MiniMax-H3",
        "prompt": prompt,
        "duration": duration,
        "ratio": "9:16",
        "resolution": resolution,
        "reference_images": [{"url": u} for u in image_urls],
    }
    args_file = "/tmp/h3_submit_args.json"
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
        raise SystemExit("submit failed:\n%s\n%s" % (txt[-1500:], out.stderr[-800:]))
    return m.group(1), txt


def load_tasks():
    with open(TASKS_JSON, encoding="utf-8") as f:
        return json.load(f)


def save_tasks(doc):
    tmp = TASKS_JSON + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=2)
    os.replace(tmp, TASKS_JSON)


def main():
    dry = "--dry-run" in sys.argv
    os.makedirs(OUT_DIR, exist_ok=True)
    doc = load_tasks()
    if "tasks" not in doc:
        raise SystemExit("video_tasks.json 缺 tasks 包装层")

    # 参考图只上传一次，多镜共用
    needed = []
    for s in SHOTS:
        for img in s["images"]:
            if img not in needed:
                needed.append(img)
    print("需要上传 %d 张参考图" % len(needed))
    if dry:
        for s in SHOTS:
            p = extract_prompt(os.path.join(P, s["md"]))
            print("--- %s --- prompt %d 字符 / %d 张图 / 输出 %s"
                  % (s["key"], len(p), len(s["images"]), s["out"]))
        return 0

    urls = {}
    for img in needed:
        urls[img] = upload(os.path.join(CUR, img))
        print("  ↑ %s" % img)

    # 每提交一个就立刻落盘 —— 中途失败时，已经跑在平台上的 task_id 绝不能丢
    # （丢了就再也找不回那个任务，只能重新提交，白花额度）
    submitted = []
    try:
        for s in SHOTS:
            prompt = extract_prompt(os.path.join(P, s["md"]))
            if len(prompt) > 7000:
                raise SystemExit("%s prompt 超 7000 字符（%d）" % (s["key"], len(prompt)))
            task_id, raw = submit(prompt, [urls[i] for i in s["images"]], 5, "768P")
            if task_id in doc["tasks"]:
                raise SystemExit(
                    "task_id %s 与已有记录重复（%s），拒绝覆盖 —— 说明平台返回了重复 id，"
                    "先人工核对再继续" % (task_id, s["key"]))
            now = int(time.time() * 1000)
            doc["tasks"][task_id] = {
                "model": "MiniMax-H3",
                "mode": "Ref2VA",
                "duration_s": 5,
                "ratio": "9:16",
                "resolution": "768P",
                "output_file": os.path.relpath(os.path.join(OUT_DIR, s["out"]), PROJECT),
                "purpose": s["purpose"],
                "submitted_at_ms": now,
                "submitted_at_cst": time.strftime("%Y-%m-%d %H:%M:%S CST", time.localtime(now / 1000)),
                "terminal_status": "submitted",
                "reference_images": [os.path.splitext(i)[0] for i in s["images"]],
                "prompt_file": os.path.relpath(os.path.join(P, s["md"]), PROJECT),
                "notes": "第0批技术验证。V1/V2/V3 台词完全相同（相声讲究说学逗唱。），"
                         "场景与角色状态一致，唯一变量 = 脸朝向 + 嘴部遮挡 + lip-sync 措辞。"
                         "结果决定全季台词策略：🔴正面 / 🟡3-4侧 / 🟢嘴部遮挡。",
                "last_query_at_ms": now,
                "last_query_at_cst": time.strftime("%Y-%m-%d %H:%M:%S CST", time.localtime(now / 1000)),
                "last_error": "",
                "delivery_retry_count": 0,
            }
            save_tasks(doc)
            submitted.append((s["key"], task_id))
            print("  ✅ %-22s task_id=%s（已落盘）" % (s["key"], task_id))
            time.sleep(2)
    except SystemExit as e:
        save_tasks(doc)
        print("\n⚠️ 中断：%s" % e)
        print("已成功提交并落盘的（可以照常取回，不要重新提交）：")
        for k, tid in submitted:
            print("   %-22s %s" % (k, tid))
        raise

    print("\n已登记 %d 个任务到 docs/video_tasks.json" % len(submitted))
    return 0


if __name__ == "__main__":
    sys.exit(main())
