#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""可辨识语速上限实测。

问题：相声甲乙的台词密度高（镜09 42 字/6 秒），必须把语速推快，
但推太快就「糊」了 —— 观众听不清字，字幕也救不回来。

做法：
  1. 用 edge-tts 在若干档语速下生成同一批代表性长句
  2. 裁掉 edge-tts 自带的首尾静音（否则测的是静音不是语速）
  3. 用 MiniMax listen_audio 转写，算逐字准确率
  4. 打印「语速 → 字/秒 → 准确率」表，找出可用上限

用法：
  ~/XiaoliuerVideoGen/venv/bin/python3 tools/probe_speech_speed.py gen    # 只生成音频
  ~/XiaoliuerVideoGen/venv/bin/python3 tools/probe_speech_speed.py asr    # 只转写+算分
  ~/XiaoliuerVideoGen/venv/bin/python3 tools/probe_speech_speed.py all    # 全跑
"""
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

import importlib.util
spec = importlib.util.spec_from_file_location("fp", os.path.join(HERE, "film_pipeline.py"))
fp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fp)

OUT = "/tmp/spd"
EDGE_TTS = os.path.expanduser("~/XiaoliuerVideoGen/venv/bin/edge-tts")

# 代表性长句：覆盖最密的两镜 + 捧哏音色
SAMPLES = [
    ("S1_sh11_dougen", "dougen", "嘿！台词记得挺牢！那要是有人不会说相声能来吗？"),
    ("S2_sh14_dougen", "dougen", "说得太好了！想要上台说相声、交朋友的，抓紧报名！"),
    ("S3_sh13_penggen", "penggen", "不爱开心的！咱们相声社，就是来逗乐的！"),
]
SPEEDS = [1.0, 1.15, 1.3, 1.45, 1.6, 1.75, 1.9]

TRIM_AF = (
    "silenceremove=start_periods=1:start_duration=0.03:start_threshold=-50dB:start_silence=0.03,"
    "areverse,"
    "silenceremove=start_periods=1:start_duration=0.05:start_threshold=-50dB:start_silence=0.04,"
    "areverse"
)


def norm(s):
    """转写比对用的归一化：去掉所有标点/空白，只留字。"""
    return re.sub(r"[^\w\u4e00-\u9fff]", "", s or "")


def gen_one(label, who, text, speed, outdir):
    path = os.path.join(outdir, "%s_x%.2f.mp3" % (label, speed))
    if os.path.exists(path) and os.path.getsize(path) > 500:
        return path
    voice, rate, pitch = fp.VOICES[who]
    base = int(rate.replace("%", "").replace("+", ""))
    rate_pct = max(-30, min(90, int(round(base + (speed - 1.0) * 100))))
    cmd = [EDGE_TTS, "--voice", voice, "--rate=%+d%%" % rate_pct, "--pitch=" + pitch,
           "--text", text, "--write-media", path]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0 or not os.path.exists(path):
        raise RuntimeError("TTS 失败 %s: %s" % (path, r.stderr[-200:]))
    tmp = path + ".tmp.mp3"
    subprocess.run([fp.ffmpeg(), "-hide_banner", "-y", "-i", path, "-af", TRIM_AF,
                    "-c:a", "libmp3lame", "-q:a", "2", tmp], capture_output=True)
    if os.path.exists(tmp) and os.path.getsize(tmp) > 500:
        os.replace(tmp, path)
    elif os.path.exists(tmp):
        os.remove(tmp)
    return path


def cmd_gen():
    os.makedirs(OUT, exist_ok=True)
    rows = []
    for label, who, text in SAMPLES:
        for sp in SPEEDS:
            p = gen_one(label, who, text, sp, OUT)
            d = fp.probe_duration(p)
            rows.append(dict(label=label, who=who, text=text, speed=sp, path=p,
                             dur=round(d, 3), cps=round(len(norm(text)) / max(d, 0.01), 2)))
            print("  %-16s x%.2f  %.2fs  %.2f 字/秒" % (label, sp, d, rows[-1]["cps"]))
    with open(os.path.join(OUT, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=2)
    print("\n音频已生成：%s（共 %d 条）" % (OUT, len(rows)))


def upload(path):
    r = subprocess.run(["mcode-tools", "upload-temp-url", path, "--mime-type", "audio/mpeg"],
                       capture_output=True, text=True)
    txt = (r.stdout or "").strip()
    try:
        j = json.loads(txt)
    except Exception:
        # 有时候是 {"url": ...} 之外的形态，兜底正则
        m = re.search(r"https?://\S+", txt)
        if not m:
            raise RuntimeError("上传失败 %s: %s / %s" % (path, txt[:300], (r.stderr or "")[:300]))
        return m.group(0)
    for k in ("url", "temp_url", "download_url", "file_url", "data"):
        v = j.get(k)
        if isinstance(v, str) and v.startswith("http"):
            return v
    if isinstance(j.get("data"), dict):
        for k in ("url", "temp_url"):
            v = j["data"].get(k)
            if isinstance(v, str) and v.startswith("http"):
                return v
    raise RuntimeError("上传返回里找不到 URL: %s" % txt[:400])


def cmd_asr():
    mpath = os.path.join(OUT, "manifest.json")
    with open(mpath, encoding="utf-8") as f:
        rows = json.load(f)

    # 已有转写就复用
    cache_path = os.path.join(OUT, "asr.json")
    cache = {}
    if os.path.exists(cache_path):
        with open(cache_path, encoding="utf-8") as f:
            cache = json.load(f)

    for i, row in enumerate(rows, 1):
        key = "%s_x%.2f" % (row["label"], row["speed"])
        if key in cache:
            continue
        url = upload(row["path"])
        r = subprocess.run(
            ["mcode-tools", "connector", "call", "connector__matrix__listen_audio",
             "--args", json.dumps({"audio_info": {"url": url, "mime_type": "audio/mpeg"}},
                                  ensure_ascii=False)],
            capture_output=True, text=True)
        hyp = ""
        try:
            j = json.loads((r.stdout or "").strip())
            hyp = j.get("transcription") or ""
        except Exception:
            m = re.search(r'"transcription"\s*:\s*"((?:[^"\\]|\\.)*)"', r.stdout or "")
            hyp = m.group(1) if m else ""
        cache[key] = hyp
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)
        print("  [%d/%d] %s → %s" % (i, len(rows), key, (hyp or "(空)")[:40]))

    # 打分
    print("\n%-16s %-8s %-8s %-8s %-8s %s" % ("样本", "语速", "字/秒", "时长", "准确率", "转写"))
    print("─" * 100)
    by_speed = {}
    for row in rows:
        key = "%s_x%.2f" % (row["label"], row["speed"])
        hyp = norm(cache.get(key, ""))
        ref = norm(row["text"])
        if ref:
            hit = sum(1 for a, b in zip(ref, hyp) if a == b)
            acc = hit / len(ref)
        else:
            acc = 0.0
        row["asr"] = cache.get(key, "")
        row["acc"] = round(acc, 3)
        by_speed.setdefault(row["speed"], []).append(row)
        print("%-16s %-8.2f %-8.2f %-8.2f %-8.0f%% %s"
              % (row["label"], row["speed"], row["cps"], row["dur"], acc * 100, row["asr"][:26]))

    print("\n═══ 按语速档汇总 ═══")
    for sp in sorted(by_speed):
        rs = by_speed[sp]
        avg = sum(r["acc"] for r in rs) / len(rs)
        lo = min(r["acc"] for r in rs)
        avg_cps = sum(r["cps"] for r in rs) / len(rs)
        print("  语速×%.2f  平均 %.2f 字/秒  平均准确率 %5.1f%%  最低 %5.1f%%"
              % (sp, avg_cps, avg * 100, lo * 100))

    with open(os.path.join(OUT, "scored.json"), "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=2)


def main():
    what = sys.argv[1] if len(sys.argv) > 1 else "all"
    if what in ("gen", "all"):
        print("── 生成音频 ──")
        cmd_gen()
    if what in ("asr", "all"):
        print("── 转写打分 ──")
        cmd_asr()
    return 0


if __name__ == "__main__":
    sys.exit(main())
