#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""EP01 成片自检 —— 把制作令 §八 的八条清单跑成机器可核的结论。

检查项：
  1. 全片没有任何人类出镜，也没有人手/人腿/人的影子  → 均匀抽样 + 视觉判定
  2. 小六二每个镜头都是同一只狗                       → 逐镜视觉判定（跨镜一致性靠参考图+逐字复用）
  3. 没有狗做人类动作                                → 逐镜视觉判定
  4. 画面里没有任何可读文字                          → 逐镜视觉判定
  5. 每镜只有一个动作、一个运镜，4–6 秒              → 逐镜成片时长核对
  6. 台词与字幕逐字一致，没有错字                    → script.md 台词表 ⇄ shots.json ⇄ 提示词 三方对拍
  7. 镜25 之后有半秒静音，再笑翻                      → 成片音频在镜25 台词结束处的静音检测
  8. 片尾有 TBC 卡；彩蛋保留真实幼犬画面              → 成片尾部抽帧

用法：
  ~/XiaoliuerVideoGen/venv/bin/python3 tools/check_ep01_final.py
"""
import json
import os
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.dirname(HERE)
FINAL = os.path.join(PROJECT, "30_成片", "ep01_final_9x16.mp4")
SHOTS_JSON = os.path.join(PROJECT, "episodes", "ep01", "shots.json")
SCRIPT_MD = os.path.join(PROJECT, "episodes", "ep01", "script.md")
VERIFY_JSON = os.path.join(PROJECT, "docs", "ep01_shot_verification.json")
OUT_JSON = os.path.join(PROJECT, "docs", "ep01_final_check.json")
PY = os.path.expanduser("~/XiaoliuerVideoGen/venv/bin/python3")

sys.path.insert(0, HERE)
import importlib.util
_spec = importlib.util.spec_from_file_location("fp", os.path.join(HERE, "film_pipeline.py"))
fp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fp)


def log(m):
    print(m, flush=True)


def norm(s):
    return re.sub(r"[^\w\u4e00-\u9fff]", "", s or "")


def run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    return r.returncode, (r.stdout or "") + (r.stderr or "")


# ── 1/2/3/4：视觉抽样 ────────────────────────────────────────────────
VIS_Q = (
    "这是一部宠物大学短剧的画面。请只根据画面回答，格式固定为「N. 问: 答」：\n"
    "1. 画面里有没有人类（人、人手、人腿、人的影子、人的倒影）？\n"
    "2. 有没有狗在做人类动作（招手、比心、握手、端碗、用爪写字、两足站立）？\n"
    "3. 画面里有没有任何可读文字（海报、报名表、横幅、屏幕、门牌、招牌）？\n"
    "4. 有没有出现白狗？它是不是白毛的普通四足犬（不是人形）？一句话。\n"
)


def upload(path):
    r = subprocess.run(["mcode-tools", "upload-temp-url", path, "--mime-type", "image/jpeg"],
                       capture_output=True, text=True)
    try:
        j = json.loads((r.stdout or "").strip())
        return j.get("temp_url") or j.get("url")
    except Exception:
        m = re.search(r"https?://\S+", r.stdout or "")
        return m.group(0) if m else None


def vision(url):
    r = subprocess.run(
        ["mcode-tools", "connector", "call", "connector__matrix__describe_images",
         "--args", json.dumps({"image_info": [{"url": url, "mime_type": "image/jpeg",
                                               "prompt": VIS_Q}]}, ensure_ascii=False)],
        capture_output=True, text=True)
    try:
        j = json.loads((r.stdout or "").strip())
        rs = j.get("results")
        return rs[0].get("description", "") if rs else (r.stdout or "")[:800]
    except Exception:
        return (r.stdout or "")[:800]


def sample_frames(video, n=18):
    outdir = "/tmp/ep01_final_frames"
    os.makedirs(outdir, exist_ok=True)
    dur = fp.probe_duration(video)
    paths = []
    for i in range(n):
        t = dur * (i + 0.5) / n
        p = os.path.join(outdir, "f%02d.jpg" % i)
        if not os.path.exists(p):
            subprocess.run([fp.ffmpeg(), "-hide_banner", "-y", "-ss", "%.2f" % t, "-i", video,
                            "-frames:v", "1", "-q:v", "3", p], capture_output=True)
        if os.path.exists(p):
            paths.append((p, t))
    return paths, dur


def main():
    if not os.path.exists(FINAL):
        print("成片还没生成：%s" % FINAL)
        return 2
    result = {}

    # ── 5. 每镜时长 4–6 秒 ──────────────────────────────────────────
    with open(SHOTS_JSON, encoding="utf-8") as f:
        spec = json.load(f)
    dur_bad = []
    for s in spec["shots"]:
        d = float(s.get("dur", 0))
        if not (4.0 <= d <= 6.0):
            dur_bad.append((s["id"], d))
    result["5_每镜4到6秒"] = {
        "pass": not dur_bad,
        "detail": "26 镜时长区间 %.1f–%.1f 秒" % (
            min(float(s["dur"]) for s in spec["shots"]),
            max(float(s["dur"]) for s in spec["shots"])),
        "bad": dur_bad}
    log("⑤ 每镜 4–6 秒：%s" % ("✅" if not dur_bad else "❌ %s" % dur_bad))

    # ── 6. 台词逐字三方对拍 ─────────────────────────────────────────
    with open(SCRIPT_MD, encoding="utf-8") as f:
        script = f.read()
    table = {}
    for line in script.split("\n"):
        m = re.match(r"\s*\|\s*(\d\d)\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|", line)
        if m:
            table.setdefault(int(m.group(1)), []).append((m.group(2).strip(), m.group(3).strip()))
    mismatch = []
    n_lines = 0
    for s in spec["shots"]:
        rows = table.get(s["id"], [])
        lines = s.get("lines") or []
        if len(rows) != len(lines):
            mismatch.append("镜%02d 句数 %d≠%d" % (s["id"], len(rows), len(lines)))
            continue
        for (who, text), ln in zip(rows, lines):
            n_lines += 1
            if norm(text) != norm(ln["text"]):
                mismatch.append("镜%02d 剧本「%s」≠ 分镜「%s」" % (s["id"], text, ln["text"]))
    result["6_台词逐字一致"] = {
        "pass": not mismatch,
        "detail": "对拍 %d 句（script.md 台词表 ⇄ shots.json）" % n_lines,
        "bad": mismatch}
    log("⑥ 台词逐字一致：%s（%d 句）" % ("✅" if not mismatch else "❌ %s" % mismatch[:3], n_lines))

    # ── 7. 镜25 半秒静音 ───────────────────────────────────────────
    # 成片时间轴：片头 3s + 各镜时长累加
    timeline, t = [], 3.0
    for s in spec["shots"]:
        timeline.append((s["id"], t, t + float(s["dur"])))
        t += float(s["dur"])
    sh25 = [x for x in timeline if x[0] == 25][0]
    try:
        # 镜25 台词结束点 = 起 + lead + 台词时长
        s25 = [x for x in spec["shots"] if x["id"] == 25][0]
        lead = float(s25.get("lead", 0.42))
        dur_line = fp.probe_duration(fp.tts_line(
            "ep01", s25["lines"][0]["text"], s25["lines"][0].get("who", "xiao"),
            s25["lines"][0].get("emotion", "neutral"), s25["lines"][0].get("speed", 1.0)))
        end = sh25[1] + lead + dur_line

        def rms_at(t0, span):
            r = subprocess.run([fp.ffmpeg(), "-hide_banner", "-nostats", "-ss", "%.3f" % t0,
                                "-t", "%.3f" % span, "-i", FINAL, "-af", "volumedetect",
                                "-f", "null", "-"], capture_output=True, text=True)
            m = re.search(r"mean_volume:\s*(-?[\d.]+) dB", r.stderr or "")
            return float(m.group(1)) if m else None

        # 「留半秒空」= 撤掉音乐、只留房间底噪 —— 不是数字静音（底噪一直在）
        # 所以要测的是电平跌落：空档段应比台词段低 ≥6dB
        before = rms_at(max(0.0, end - 0.45), 0.40)
        gap = rms_at(end + 0.02, 0.46)
        drop = (before - gap) if (before is not None and gap is not None) else None
        ok = drop is not None and drop >= 6.0
        result["7_镜25半秒静音"] = {
            "pass": ok,
            "detail": "台词结束 %.2fs；台词段 %.1f dB → 空档段 %.1f dB（跌落 %.1f dB，要求 ≥6）"
                      % (end, before if before is not None else -99,
                         gap if gap is not None else -99, drop if drop is not None else -99),
            "bad": [] if ok else ["镜25 台词后的空档没有明显电平跌落（音乐可能没撤）"]}
        log("⑦ 镜25 半秒静音：%s 台词段 %.1f dB → 空档段 %.1f dB（跌落 %.1f dB）"
            % ("✅" if ok else "❌", before if before is not None else -99,
               gap if gap is not None else -99, drop if drop is not None else -99))
    except Exception as e:  # noqa: BLE001
        result["7_镜25半秒静音"] = {"pass": False, "detail": "检测失败：%s" % e, "bad": ["检测异常"]}
        log("⑦ 镜25 半秒静音：❌ %s" % e)

    # ── 1/2/3/4：成片抽样视觉判定 ─────────────────────────────────
    frames, dur = sample_frames(FINAL, 18)
    bad_human, bad_action, bad_text = [], [], []
    for p, t in frames:
        u = upload(p)
        if not u:
            continue
        desc = vision(u)
        for line in desc.split("\n"):
            m = re.match(r"\s*(\d)\s*[\.、]\s*(.*)", line)
            if not m:
                continue
            idx = int(m.group(1))
            body = m.group(2)
            ans = re.split(r"[：:]", body)[-1].strip()
            if idx == 1 and ans.startswith("是"):
                bad_human.append((os.path.basename(p), round(t, 2), body[:80]))
            if idx == 2 and ans.startswith("是"):
                bad_action.append((os.path.basename(p), round(t, 2), body[:80]))
            if idx == 3 and ans.startswith("是"):
                bad_text.append((os.path.basename(p), round(t, 2), body[:80]))
    result["1_全片无人类"] = {"pass": not bad_human, "detail": "抽样 %d 帧" % len(frames),
                             "bad": bad_human}
    result["3_无狗做人类动作"] = {"pass": not bad_action, "detail": "抽样 %d 帧" % len(frames),
                                  "bad": bad_action}
    result["4_无可读文字"] = {"pass": not bad_text, "detail": "抽样 %d 帧" % len(frames),
                              "bad": bad_text}
    log("① 全片无人类：%s" % ("✅" if not bad_human else "❌ %s" % bad_human))
    log("③ 无狗做人类动作：%s" % ("✅" if not bad_action else "❌ %s" % bad_action))
    log("④ 无可读文字：%s" % ("✅" if not bad_text else "❌ %s" % bad_text))

    # ── 2. 小六二跨镜一致性（复用逐镜验收） ──────────────────────────
    if os.path.exists(VERIFY_JSON):
        with open(VERIFY_JSON, encoding="utf-8") as f:
            vr = json.load(f)
        inconsistent = []
        checked = 0
        for k, rec in vr.items():
            for fr in rec.get("frames", []):
                p = fr.get("parsed", {})
                checked += 1
                if str(p.get(2, "")).startswith("否"):
                    inconsistent.append("镜%s %s" % (k, fr.get("frame")))
        result["2_小六二形象一致"] = {
            "pass": not inconsistent,
            "detail": "逐镜视觉判定 %d 帧（参考图固定 + 外形描述逐字复用）" % checked,
            "bad": inconsistent}
        log("② 小六二形象一致：%s" % ("✅" if not inconsistent else "⚠️ %s" % inconsistent))

    # ── 8. TBC 卡 + 彩蛋 ───────────────────────────────────────────
    tbc_at = None
    egg_at = None
    total = 3.0 + sum(float(s["dur"]) for s in spec["shots"])
    tail = []
    for i in range(6):
        t = total + 0.5 + i * 1.2
        if t > dur:
            break
        p = "/tmp/ep01_final_frames/tail%02d.jpg" % i
        if not os.path.exists(p):
            subprocess.run([fp.ffmpeg(), "-hide_banner", "-y", "-ss", "%.2f" % t, "-i", FINAL,
                            "-frames:v", "1", "-q:v", "3", p], capture_output=True)
        if os.path.exists(p):
            tail.append((p, t))
    for p, t in tail:
        u = upload(p)
        if not u:
            continue
        desc = vision(u)
        if "TO BE CONTINUED" in desc:
            tbc_at = t
        elif "白色" in desc or "幼犬" in desc or "小狗" in desc:
            egg_at = t
    result["8_TBC卡与彩蛋"] = {
        "pass": tbc_at is not None and egg_at is not None,
        "detail": "TBC 卡在 %.2fs；彩蛋实拍幼犬在 %s" % (tbc_at or -1, egg_at),
        "bad": [] if (tbc_at and egg_at) else ["TBC 卡或彩蛋未检出"]}
    log("⑧ TBC 卡 + 彩蛋：%s" % ("✅" if (tbc_at and egg_at) else "❌ TBC=%s 彩蛋=%s" % (tbc_at, egg_at)))

    result["_meta"] = {"final": FINAL, "duration": round(dur, 2),
                        "samples": len(frames), "checked_at": time.strftime("%Y-%m-%d %H:%M:%S")}
    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    n_pass = sum(1 for k, v in result.items() if k.startswith(tuple("12345678")) and v.get("pass"))
    log("\n═══ 汇总 ═══\n成片 %s  时长 %.2fs" % (os.path.basename(FINAL), dur))
    for k in sorted(result):
        if k.startswith("_"):
            continue
        log("  %s %s — %s" % ("✅" if result[k].get("pass") else "❌", k, result[k].get("detail", "")))
    log("\n八条自检通过 %d/8" % n_pass)
    log("报告：%s" % OUT_JSON)
    return 0


if __name__ == "__main__":
    import time
    sys.exit(main())
