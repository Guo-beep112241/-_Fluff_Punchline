#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Ep01 配音时长达标校准。

问题：分镜表给的每镜时长（4–6 秒）是硬约束，但甲乙的相声台词按正常语速塞不下
（镜09 42 字/6 秒 = 7 字/秒，镜11 40 字/6 秒）。

做法：
  1. 实测每句 TTS 时长（edge-tts，本地免费，已裁掉首尾静音）
  2. 算每镜的「可用语速预算」= 镜长 − 尾部留白 − (句数−1)×抢白间隔
  3. 反算需要的语速倍率，回写 shots.json 的 lines[].speed
     —— 上限用「字/秒」而不是倍率：ASR 实测 7.3 字/秒以上就开始糊
     （tools/probe_speech_speed.py，7.87 字/秒时「台词记得挺牢」被听成
       「台词记得挺好」/「那要是有的人不会」）
  4. 到顶了还是塞不下 → 收紧抢白间隔（负 gap = 真抢白，相声本来就压着说）
  5. 再塞不下 → 报「需要多长」，交人工决定

不改动台词内容 —— 台词是制作令里逐字锁死的，只能调语速和节奏。
"""
import importlib.util
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

spec = importlib.util.spec_from_file_location("fp", os.path.join(HERE, "film_pipeline.py"))
fp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fp)

EP = "ep01"
SPEC_PATH = os.path.join(PROJECT, "episodes", EP, "shots.json")

# 可辨识语速上限（字/秒）。来源：tools/probe_speech_speed.py 的 ASR 转写实测。
#   6.62 字/秒 → 100% 准确
#   7.25 字/秒 → 偶发错字（牢→好）
#   7.87 字/秒 → 明显糊（那要是有人 → 那要是有的人）
CPS_CAP = 7.30
# edge-tts rate 自身钳在 +90%，等价于 dougen 约 8.1 字/秒；这里再压一道保险
MAX_SPEED = 1.75
# 抢白间隔下限（负值 = 后一句压着前一句尾巴进）
GAP_MIN = -0.30


# 抢白间隔 / 尾部留白 / 第一句入点：多句的镜收紧，单句的镜留呼吸
def rhythm(n):
    if n >= 3:
        # 四句连着的镜：负 gap = 真抢白
        return dict(gap=-0.18, pad=0.45, lead=0.28)
    if n == 2:
        return dict(gap=0.10, pad=0.50, lead=0.30)
    return dict(gap=0.30, pad=0.85, lead=0.42)


def load():
    with open(SPEC_PATH, encoding="utf-8") as f:
        return json.load(f)


def save(d):
    """只回写本脚本自己管的字段（语速 + 节奏），其余字段重新从磁盘读，不覆盖别人的并发修改。"""
    fresh = load()
    by_id = {s["id"]: s for s in fresh["shots"]}
    for s in d["shots"]:
        t = by_id.get(s["id"])
        if not t:
            continue
        for k in ("gap", "pad", "lead"):
            if k in s:
                t[k] = s[k]
        t["dur"] = s["dur"]
        for ln, src in zip(t.get("lines") or [], s.get("lines") or []):
            ln["speed"] = src.get("speed", ln.get("speed", 1.0))
            if "speed_base" in src:
                ln["speed_base"] = src["speed_base"]
    with open(SPEC_PATH, "w", encoding="utf-8") as f:
        json.dump(fresh, f, ensure_ascii=False, indent=2)
        f.write("\n")


def clear_tts():
    ad = fp.audio_dir(EP)
    if not os.path.isdir(ad):
        return
    for fn in os.listdir(ad):
        if fn.endswith(".mp3") or fn.endswith(".mp3.trimmed") or fn.endswith(".tmp.mp3"):
            os.remove(os.path.join(ad, fn))


def n_chars(s):
    return len(re.sub(r"[^\w\u4e00-\u9fff]", "", s or ""))


def measure(d):
    """返回 {shot_id: [每句时长]}"""
    out = {}
    for s in d["shots"]:
        durs = []
        for ln in s.get("lines") or []:
            p = fp.tts_line(EP, ln["text"], ln.get("who", "xiao"),
                            ln.get("emotion", "neutral"), ln.get("speed", 1.0))
            durs.append(fp.probe_duration(p))
        out[s["id"]] = durs
    return out


def budget_of(s, n):
    return s["dur"] - s["pad"] - (n - 1) * s["gap"]


def main():
    rounds = int(sys.argv[1]) if len(sys.argv) > 1 else 5
    d = load()

    # 节奏默认值：手工调过的 gap/pad/lead 不覆盖
    for s in d["shots"]:
        for k, v in rhythm(len(s.get("lines") or [])).items():
            s.setdefault(k, v)
        # 语速从「基准」重算，避免上一轮顶到上限的残留值粘住
        for ln in s.get("lines") or []:
            ln["speed"] = float(ln.get("speed_base", 1.0))

    need_more = []
    for it in range(rounds):
        clear_tts()
        m = measure(d)
        changed = False
        report = []
        for s in d["shots"]:
            durs = m[s["id"]]
            n = len(durs)
            if not n:
                continue
            budget = budget_of(s, n)
            cur = sum(durs)
            if cur <= budget + 0.02:
                continue
            chars = sum(n_chars(l["text"]) for l in s["lines"])
            cps = chars / max(cur, 0.01)
            if cps < CPS_CAP - 0.05:
                # 还不到语速上限 → 提速，但不超过 CPS_CAP
                f = min(cur / budget, CPS_CAP / cps)
                for ln in s["lines"]:
                    old = float(ln.get("speed", 1.0))
                    ln["speed"] = round(min(MAX_SPEED, old * f), 3)
                changed = True
                report.append("镜%02d 提速 ×%.2f（当前 %.1f 字/秒）" % (s["id"], f, cps))
            else:
                # 已到语速上限 → 收紧抢白间隔（负 gap = 真抢白）
                ng = round(s["gap"] - 0.06, 3)
                if ng > GAP_MIN:
                    s["gap"] = ng
                    changed = True
                    report.append("镜%02d 抢白间隔 → %.2fs" % (s["id"], ng))
                else:
                    need_more.append((s["id"], s["dur"], cur, budget))
        print("── 第 %d 轮 ──" % (it + 1))
        for line in report:
            print("   " + line)
        if not changed:
            break
        save(d)

    # 终检
    clear_tts()
    m = measure(d)
    print("\n═══ 终检 ═══")
    ok = True
    hard = []
    for s in d["shots"]:
        durs = m[s["id"]]
        n = len(durs)
        if not n:
            continue
        budget = budget_of(s, n)
        cur = sum(durs)
        chars = sum(n_chars(l["text"]) for l in s["lines"])
        cps = chars / max(cur, 0.01)
        flag = "OK " if cur <= budget + 0.02 else "超!"
        if cur > budget + 0.02:
            ok = False
        if cps > CPS_CAP + 0.05:
            hard.append(s["id"])
        print("  %s 镜%02d %.1fs  台词%.2fs/预算%.2fs  字%d  %.1f字/秒  语速%s"
              % (flag, s["id"], s["dur"], cur, budget, chars, cps,
                 ",".join(str(l.get("speed", 1.0)) for l in s["lines"])))
    save(d)
    if hard:
        print("\n⚠️ 超过 %.1f 字/秒 的镜（听不清风险）：%s" % (CPS_CAP, hard))
    if need_more:
        print("\n❌ 即使顶到语速上限也塞不下的镜（需要加长镜长）：")
        for sid, dur, cur, budget in need_more:
            print("   镜%02d  当前 %.1fs  台词 %.2fs  预算 %.2fs  → 需要 ≈%.1fs"
                  % (sid, dur, cur, budget, cur + budget - dur))
    print("\n%s" % ("✅ 全部达标" if ok else "❌ 仍有超出的镜，需要加长镜长或改台词"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
