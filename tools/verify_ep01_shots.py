#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""EP01 逐镜抽帧验收 —— 把八条自检清单跑成机器可核的结论。

对每一镜：
  1. 从成片抽 3 帧（开头 / 中段 / 结尾）
  2. 用视觉模型逐帧回答同一份检查清单
  3. 汇总成每镜一张「通过 / 违规项」表，落盘存档

清单（对应制作令 §八）：
  1. 没有任何人类：没有人、手、人腿、人的影子
  2. 小六二是同一只狗：圆头、大圆眼、小三角耳、纯白服帖毛、瘦长体型
  3. 没有狗做人类动作：不招手、不用前爪拿东西、不写字、不两足站立
  4. 画面里没有可读文字（海报/报名表/横幅/屏幕/门牌全部留白）
  5. 全片零人类 + 动物说人话是常态（本项并入 1）

用法：
  ~/XiaoliuerVideoGen/venv/bin/python3 tools/verify_ep01_shots.py --shots 05,20,26
  ~/XiaoliuerVideoGen/venv/bin/python3 tools/verify_ep01_shots.py --all
"""
import argparse
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.dirname(HERE)
SHOTS_DIR = os.path.join(PROJECT, "20_生成结果/ep01/shots")
FRAME_DIR = os.path.join(PROJECT, "20_生成结果/ep01/verify_frames")
REPORT = os.path.join(PROJECT, "docs/ep01_shot_verification.json")
PY = os.path.expanduser("~/XiaoliuerVideoGen/venv/bin/python3")

CHECKLIST = (
    "这是一部宠物大学短剧的镜头帧。请只根据画面回答，不要推测画面外的内容。\n"
    "逐条回答，格式固定为「问号项: 是/否」：\n"
    "1. 画面里有没有人类出镜（人、人手、人腿、人的影子、人的倒影）？\n"
    "2. 画面里如果有白狗，它是不是圆头宽额、大而圆的眼睛、贴头的小三角耳、纯白服帖的毛、"
    "偏瘦的体型？（不是楔形长头、不是细长杏仁眼、不是大立耳、不是浓密蓬松毛）\n"
    "3. 画面里有没有狗在做人类动作（招手、比心、握手、端碗、用爪写字、两足站立、"
    "用前爪像人手一样捏东西）？\n"
    "4. 画面里有没有任何可读文字（海报、报名表、横幅、手机屏幕、门牌、招牌上的字）？\n"
    "5. 有没有出现两个前爪同时悬空离开地面、把东西举到脸前？\n"
    "6. 画面里的动物分别是什么品种、各有几只、在什么位置？一句话。\n"
    "7. 这段画面里的构图和主体，和下面的分镜描述是否吻合？吻合/不吻合，并指出具体差异。\n"
)

EXPECT_TMPL = "本镜分镜描述：%s\n"


def log(msg):
    print(msg, flush=True)


def ffmpeg():
    sys.path.insert(0, HERE)
    import importlib.util
    spec = importlib.util.spec_from_file_location("fp", os.path.join(HERE, "film_pipeline.py"))
    fp = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fp)
    return fp


def probe_duration(fp, path):
    return fp.probe_duration(path)


def extract_frames(fp, mp4, shot, positions=(0.12, 0.5, 0.88)):
    os.makedirs(FRAME_DIR, exist_ok=True)
    dur = probe_duration(fp, mp4)
    out = []
    for i, p in enumerate(positions):
        t = max(0.0, min(dur - 0.12, dur * p))
        dst = os.path.join(FRAME_DIR, "sh%02d_f%d.jpg" % (shot, i + 1))
        if not os.path.exists(dst):
            subprocess.run([fp.ffmpeg(), "-hide_banner", "-y", "-ss", "%.2f" % t, "-i", mp4,
                            "-frames:v", "1", "-q:v", "3", dst], capture_output=True)
        if os.path.exists(dst):
            out.append(dst)
    return out, dur


def upload(path):
    r = subprocess.run(["mcode-tools", "upload-temp-url", path, "--mime-type", "image/jpeg"],
                       capture_output=True, text=True)
    try:
        j = json.loads((r.stdout or "").strip())
        u = j.get("temp_url") or j.get("url")
        if u:
            return u
        d = j.get("data") or {}
        return d.get("temp_url") or d.get("url")
    except Exception:
        m = re.search(r"https?://\S+", r.stdout or "")
        return m.group(0) if m else None


def ask(url, expect=""):
    prompt = CHECKLIST + (EXPECT_TMPL % expect if expect else "")
    r = subprocess.run(
        ["mcode-tools", "connector", "call", "connector__matrix__describe_images",
         "--args", json.dumps({"image_info": [{"url": url, "mime_type": "image/jpeg",
                                               "prompt": prompt}]}, ensure_ascii=False)],
        capture_output=True, text=True)
    try:
        j = json.loads((r.stdout or "").strip())
        rs = j.get("results")
        if rs:
            return rs[0].get("description", "") or ""
        return j.get("text") or json.dumps(j, ensure_ascii=False)
    except Exception:
        return (r.stdout or "")[:1500]


def parse_verdict(txt):
    """从模型回答里抽出 1/2/3/4/5 的 是/否，以及 6/7 的自由文本。"""
    desc = txt or ""
    res = {}
    free = {}
    for line in desc.split("\n"):
        m = re.match(r"\s*(\d)\s*[\.、]\s*(.*)", line)
        if not m:
            continue
        idx = int(m.group(1))
        body = m.group(2)
        parts = re.split(r"[：:]", body)
        ans = parts[-1].strip() if len(parts) > 1 else ""
        if idx in (1, 2, 3, 4, 5):
            res[idx] = ans[:24]
        elif idx in (6, 7):
            free[idx] = body.strip()[:400]
    for i in (1, 2, 3, 4, 5):
        res.setdefault(i, "?")
    res["free"] = free
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--shots", help="镜号，逗号分隔")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--force", action="store_true", help="已有结论也重跑")
    args = ap.parse_args()

    fp = ffmpeg()
    shots = list(range(1, 27)) if args.all else [int(x) for x in (args.shots or "").split(",") if x.strip()]

    with open(os.path.join(PROJECT, "episodes", "ep01", "shots.json"), encoding="utf-8") as f:
        spec = json.load(f)
    expects = {s["id"]: s.get("expect", "") for s in spec["shots"]}

    os.makedirs(FRAME_DIR, exist_ok=True)
    report = {}
    if os.path.exists(REPORT):
        with open(REPORT, encoding="utf-8") as f:
            report = json.load(f)

    for n in shots:
        cands = sorted([os.path.join(SHOTS_DIR, fn) for fn in os.listdir(SHOTS_DIR)
                        if re.match(r"ep01_sh%02d_v.*\.mp4$" % n, fn)])
        if not cands:
            log("镜%02d 还没有视频，跳过" % n)
            continue
        mp4 = cands[-1]
        key = "%02d" % n
        if key in report and not args.force:
            log("镜%02d 已有验收记录，跳过（--force 可重跑）" % n)
            continue
        frames, dur = extract_frames(fp, mp4, n)
        log("镜%02d %s  %.2fs  %d 帧" % (n, os.path.basename(mp4), dur, len(frames)))
        verdicts = []
        for fr in frames:
            u = upload(fr)
            if not u:
                log("  上传失败 %s" % os.path.basename(fr))
                continue
            t = ask(u, expects.get(n, ""))
            p = parse_verdict(t)
            verdicts.append({"frame": os.path.basename(fr), "raw": t, "parsed": p})
            log("    %s → 人类:%s 形象:%s 人类动作:%s 文字:%s 双爪悬空:%s"
                % (os.path.basename(fr), p[1], p[2], p[3], p[4], p[5]))
            if p.get("free", {}).get(7):
                log("      分镜比对：%s" % p["free"][7][:180])
        report[key] = {"video": os.path.basename(mp4), "duration": round(dur, 2),
                        "expect": expects.get(n, ""), "frames": verdicts}
        with open(REPORT, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)

    log("\n验收报告：%s" % REPORT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
