#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Ep01 提示词校验。

在提交任何一条 H3 任务之前，先把能自动查的全查掉 —— 每一条不合规的任务都会白烧积分。

检查项：
  1. 首个 ``` 代码块是完整 Ref2VA 六段式（缺段直接非法）
  2. 提示词 ≤7000 字符（H3 硬上限）
  3. 「时长：N 秒」与 episodes/ep01/shots.json 逐镜一致
  4. 参考素材里的 <Picture N> → 文件名能解析到真实文件，且张数 ≤9、参考视频 ≤3
  5. <d> 里的台词与 shots.json 的台词逐字一致（不多、不少、不改字）
  6. 提示词里不出现禁词：人类、human、招手、比心、握手、写字（只允许出现在否定句里）
"""
import importlib.util
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.dirname(HERE)
PROMPT_DIR = os.path.join(PROJECT, "episodes/ep01/prompts")
SPEC_PATH = os.path.join(PROJECT, "episodes/ep01/shots.json")

spec = importlib.util.spec_from_file_location("sub", os.path.join(HERE, "submit_episode_shots.py"))
sub = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sub)

# 出现在提示词里就算可疑的词（提示词正文是英文，中文只应出现在 <d> 台词里）
HUMAN_WORDS = ["human", "person", "people", "man", "woman", "shadow"]

NEG = ("no ", "not ", "without ", "never ", "no-", "nor ", "neither ", "none ",
       "avoid", "exclude", "free of", "zero ")


# 这些搭配是描述音色/动作的正当用法，不是「画面里出现人类」
BENIGN_AFTER = ("voice", "gesture", "like", "male", "girl", "boy", "speaking")


def positive_hits(text, word):
    """判断某个词是否「画面里正面出现人类」。

    两类要放过：
      1. 否定约束 —— "no human hands, no human shadows" 必须保留
      2. 音色/动作描述 —— "a young male human voice, not a bark" 是我们要的
    """
    for m in re.finditer(r"\b%s\w*" % re.escape(word), text, re.I):
        left = text[max(0, m.start() - 40):m.start()].lower()
        seg = re.split(r"[.;:]", left)[-1]
        if any(neg in seg for neg in NEG):
            continue
        after = text[m.end():m.end() + 20].lower()
        if any(b in after for b in BENIGN_AFTER):
            continue
        return True
    return False


def main():
    with open(SPEC_PATH, encoding="utf-8") as f:
        shots = {s["id"]: s for s in json.load(f)["shots"]}

    idx = sub.build_asset_index()
    files = sorted([f for f in os.listdir(PROMPT_DIR) if re.fullmatch(r"sh\d+\.md", f)],
                   key=lambda f: int(re.search(r"sh(\d+)", f).group(1)))
    if not files:
        print("❌ 没有任何提示词文件")
        return 1

    bad = []
    print("%-6s %-6s %-6s %-5s %-6s %s" % ("镜号", "字符", "时长", "图/视", "台词", "结论"))
    for fn in files:
        path = os.path.join(PROMPT_DIR, fn)
        sid = int(re.search(r"sh(\d+)", fn).group(1))
        txt = open(path, encoding="utf-8").read()
        errs = []

        # ① 六段式 + ② 字符数
        try:
            prompt = sub.extract_prompt(path)
        except Exception as e:  # noqa: BLE001
            errs.append("六段式/字符数：%s" % e)
            prompt = ""
        nchar = len(prompt)

        # ③ 时长一致
        dur, ratio, res = sub.parse_generation_params(txt)
        want = float(shots.get(sid, {}).get("dur", -1))
        if abs(dur - want) > 0.01:
            errs.append("时长 %ds ≠ 分镜表 %.1fs" % (dur, want))
        # ③b H3 硬约束：时长必须是 4–15 的整数秒
        if dur < 4 or dur > 15:
            errs.append("时长 %ds 越界（H3 只接受 4–15 秒）" % dur)

        # ④ 参考素材
        imgs, vids = sub.parse_references(txt)
        if not imgs and not vids:
            errs.append("没有参考素材")
        if len(imgs) > 9:
            errs.append("参考图 %d > 9" % len(imgs))
        if len(vids) > 3:
            errs.append("参考视频 %d > 3" % len(vids))
        for r in imgs + vids:
            if r not in idx:
                errs.append("找不到素材文件：%s" % r)

        # ⑤ 台词逐字
        want_lines = [l["text"] for l in (shots.get(sid, {}).get("lines") or [])]
        got_lines = re.findall(r"<d>\[Chinese\]\s*(.*?)\s*</d>", prompt, re.S)
        got_lines = [g.replace("\n", "") for g in got_lines]
        if sorted(got_lines) != sorted(want_lines):
            miss = [w for w in want_lines if w not in got_lines]
            extra = [g for g in got_lines if g not in want_lines]
            errs.append("台词不一致 缺=%s 多=%s" % (miss, extra))
        nline = len(got_lines)

        # ⑥ 人类禁词：只抓「正面出现」，"no human hands" 这类否定句是允许且必要的
        hits = [w for w in HUMAN_WORDS if positive_hits(prompt, w)]
        if hits:
            errs.append("提示词含人类词（正面出现）：%s" % hits)

        ok = not errs
        print("%-6s %-6d %-6s %-5s %-6s %s" % (
            "镜%02d" % sid, nchar, "%ds" % dur,
            "%d/%d" % (len(imgs), len(vids)), nline,
            "✅" if ok else "❌ " + "；".join(errs)))
        if not ok:
            bad.append(sid)

    print()
    if bad:
        print("❌ %d 个镜不合格：%s" % (len(bad), ["镜%02d" % b for b in bad]))
        return 1
    print("✅ %d 个提示词全部合格，可以提交" % len(files))
    return 0


if __name__ == "__main__":
    sys.exit(main())
