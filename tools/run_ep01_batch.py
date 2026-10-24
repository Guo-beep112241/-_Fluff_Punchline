#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""EP01 逐镜投产驱动（带并发闸门）。

平台约束（实测踩到的）：
  * MiniMax 同时只允许 3 个「已提交但未查收」的视频任务，多一个就返回
    429 "video generation limit reached ... a slot frees up once a task is
    confirmed finished"。
  * 所以「查询」本身就是释放槽位的动作 —— 查完一个确认完成，槽位才让出来。
  * H3 单条 15–30 分钟。

策略：生产者/消费者循环
  1. 查收所有已提交任务（顺带释放槽位）
  2. 只要在飞任务 < 3 且还有待投镜，就投下一个
  3. 投到 429 就退回来等待下一轮

用法：
  python3 tools/run_ep01_batch.py --all --skip-existing
  python3 tools/run_ep01_batch.py --shots 05,20,26
"""
import argparse
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.dirname(HERE)
TASKS_JSON = os.path.join(PROJECT, "docs", "video_tasks.json")
PY = os.path.expanduser("~/XiaoliuerVideoGen/venv/bin/python3")

MAX_INFLIGHT = 3          # 平台硬上限
SUBMIT_RETRY = 40         # 单镜最多重试几次


def log(msg):
    print("[%s] %s" % (time.strftime("%H:%M:%S"), msg), flush=True)


def load_tasks():
    with open(TASKS_JSON, encoding="utf-8") as f:
        return json.load(f).get("tasks", {})


def run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True, cwd=PROJECT)
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def shot_of(rec):
    try:
        return int(rec.get("shot") or 0)
    except Exception:
        return 0


def current_signature(sid):
    """当前这一镜的「版本签名」= 提示词正文 sha256 + 参考素材文件名列表。

    只比提示词正文是不够的：换参考图时正文一个字没动，sha256 相同，
    驱动会把「用旧参考图生成的」当成「当前版本已交付」而跳过重拍。
    """
    import hashlib
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "sub", os.path.join(HERE, "submit_episode_shots.py"))
    sub = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(sub)
    path = os.path.join(PROJECT, "episodes", "ep01", "prompts", "sh%02d.md" % sid)
    if not os.path.exists(path):
        return None
    try:
        txt = open(path, encoding="utf-8").read()
        prompt = sub.extract_prompt(path)
        # 参考素材段在代码块外面，必须用整份 md 解析（与提交脚本同口径）
        imgs, vids = sub.parse_references(txt)
    except Exception:
        return None
    if not prompt:
        return None
    h = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
    return (h, tuple(os.path.basename(x) for x in imgs), tuple(os.path.basename(x) for x in vids))


def ep01_state():
    """返回 (在飞任务数, 已交付镜号集合, 已提交镜号集合)

    只认「当前版本」的任务 —— 旧 33 镜结构留下的同号 task（镜01/镜02）
    镜号相同但提示词/参考图不同，不算已交付，否则会漏投。
    """
    tasks = load_tasks()
    inflight = 0
    delivered = set()
    submitted = set()
    for tid, rec in tasks.items():
        if rec.get("episode") != "ep01" or rec.get("model") != "MiniMax-H3":
            continue
        s = shot_of(rec)
        if not s:
            continue
        sig = current_signature(s)
        if not sig:
            continue
        want_sha, want_imgs, want_vids = sig
        if rec.get("submitted_prompt_sha256") != want_sha:
            continue
        got_imgs = tuple(rec.get("reference_images") or [])
        got_vids = tuple(rec.get("reference_videos") or [])
        if got_imgs != want_imgs or got_vids != want_vids:
            continue          # 参考图换了 → 这一镜要重拍
        if rec.get("terminal_status") == "delivered":
            delivered.add(s)
        else:
            submitted.add(s)
            inflight += 1
    return inflight, delivered, submitted


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--shots", help="镜号，逗号分隔")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--skip-existing", action="store_true", help="跳过已提交过的镜")
    ap.add_argument("--interval", type=int, default=25, help="轮询间隔秒")
    ap.add_argument("--timeout", type=int, default=9000, help="总时长上限秒")
    args = ap.parse_args()

    shots = list(range(1, 27)) if args.all else [int(x) for x in (args.shots or "").split(",") if x.strip()]
    if not shots:
        print("没指定镜号")
        return 2

    t_start = time.time()
    queue = list(shots)
    tries = {}

    while True:
        # 1) 查收所有任务：既取回成片，也释放平台槽位
        rc, out = run([PY, "tools/recover_h3_video.py"])
        inflight, delivered, submitted = ep01_state()

        # 2) 清掉已交付的队列头
        while queue and queue[0] in delivered:
            done = queue.pop(0)
            log("✅ 镜%02d 已交付（队列剩 %d）" % (done, len(queue)))
        if not queue:
            break

        # 3) 补投：只要槽位够就投
        if inflight < MAX_INFLIGHT:
            n = queue[0]
            if n in submitted:
                # 已经投过了（上一轮提交成功但没记进这轮）—— 不能出队，
                # 必须等它真的取回，否则这一镜会永远停在旧版本
                time.sleep(args.interval)
                continue
            rc, out = run([PY, "tools/submit_episode_shots.py", "--shots", "%02d" % n])
            m = None
            for line in (out or "").splitlines():
                if "task_id=" in line:
                    m = line.strip()
            if "429" in (out or "") or "limit reached" in (out or ""):
                tries[n] = tries.get(n, 0) + 1
                log("⏳ 镜%02d 撞并发上限（槽位 %d/%d），等下一轮" % (n, inflight, MAX_INFLIGHT))
                time.sleep(args.interval)
                continue
            if rc != 0 or not m:
                tries[n] = tries.get(n, 0) + 1
                log("❌ 镜%02d 提交失败（第 %d 次）：%s" % (n, tries[n], (out or "")[-400:]))
                if tries[n] >= SUBMIT_RETRY:
                    return 1
                time.sleep(args.interval)
                continue
            queue.pop(0)
            log("🚀 镜%02d 已提交：%s（在飞 %d）" % (n, m, inflight + 1))
            time.sleep(3)   # 让平台先落任务，避免连续提交撞闸
        else:
            time.sleep(args.interval)

        if time.time() - t_start > args.timeout:
            log("❌ 总时长超时")
            return 1

    log("全部完成：已交付 %s" % sorted(delivered))
    return 0


if __name__ == "__main__":
    sys.exit(main())
