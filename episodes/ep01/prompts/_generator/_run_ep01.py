#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成 Ep1 全部 33 个提示词文件并跑一遍 QC。不修改除 prompts/ 外任何文件。"""
import sys, re, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent))

from _gen_ep01 import write_shot, FEATURES, EAR, BUILD, OUT
from _data_ep01 import SHOTS
from _data_ep01b import SHOTS_B

ALL = SHOTS + SHOTS_B
ORDER = ["subject_definitions", "summary", "retention_analysis", "detailed_description",
         "overall_soundscape", "non_diegetic_music"]

# ---- 台词基准：script.md §五 逐句台词表 ----
SCRIPT = pathlib.Path("/Users/guojiayuan/Movies/Xiaoliuer/episodes/ep01/script.md")
lines = []
for ln in SCRIPT.read_text(encoding="utf-8").splitlines():
    m = re.match(r"^\|\s*(\d{2})\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*([^|]*?)\s*\|\s*$", ln)
    if m:
        lines.append((m.group(1), m.group(3)))
valid_texts = {t for _, t in lines}

results = []
for sh in ALL:
    n_chars, wc = write_shot(sh)
    results.append((sh["n"], n_chars, wc))

print("=" * 78)
print(f"{'镜':>4} {'提示词字符':>10} {'detailed_words':>16}")
for n, c, w in results:
    print(f"{n:>4} {c:>10} {w:>16}")
cs = [c for _, c, _ in results]
ws = [w for _, _, w in results]
print("-" * 78)
print(f"文件数 {len(results)}｜最短 {min(cs)}｜最长 {max(cs)}｜平均 {sum(cs)//len(cs)}")
print(f"detailed_description 词数：最短 {min(ws)}｜最长 {max(ws)}｜平均 {sum(ws)//len(ws)}")
print(f"超 7000 字符的文件：{[n for n, c, _ in results if c > 7000]}")

# ---- QC ----
problems = []
for sh in ALL:
    f = OUT / f"sh{sh['n']:02d}.md"
    txt = f.read_text(encoding="utf-8")
    m = re.search(r"```\n(.*?)\n```", txt, re.S)
    if not m:
        problems.append(f"sh{sh['n']:02d}: 找不到提示词代码块")
        continue
    p = m.group(1)
    pos = [p.find(s + ":") for s in ORDER]
    if any(x < 0 for x in pos) or pos != sorted(pos):
        problems.append(f"sh{sh['n']:02d}: 六段式顺序错 {pos}")
    # 台词逐字核对
    for d in re.findall(r"<d>\[Chinese\] (.*?)</d>", p):
        if d not in valid_texts:
            problems.append(f"sh{sh['n']:02d}: 台词不在 script.md 表里 -> {d!r}")
    # 特征词逐字（空镜没有角色，跳过）
    if not sh.get("empty"):
        for word in (FEATURES, EAR, BUILD):
            if word not in p:
                problems.append(f"sh{sh['n']:02d}: 特征词缺失 -> {word[:50]}")
    # 口型等级措辞
    tier = sh["tier"]
    body = p.split("detailed_description:")[1]
    has_spoken = any(k[0] == "speak" for k in sh.get("lines", []))
    if tier.startswith("🟡") and has_spoken and "the mouth moves with the words" not in body:
        problems.append(f"sh{sh['n']:02d}: 🟡 缺 the mouth moves with the words")
    if "accurate lip-sync" in body:
        problems.append(f"sh{sh['n']:02d}: 出现了 accurate lip-sync（禁用）")
    if tier.startswith("🔴") and "the mouth hangs open and the tongue lolls out, panting heavily" not in body:
        problems.append(f"sh{sh['n']:02d}: 🔴 缺喘气式措辞")
    # 参考数量（去重标签）
    head = p.split("retention_analysis:")[0]
    npic = len(set(re.findall(r"<Picture \d+>", head)))
    nvid = len(set(re.findall(r"<Video \d+>", head)))
    if npic > 3:
        problems.append(f"sh{sh['n']:02d}: 参考图 {npic} 张 > 3")
    if nvid > 1:
        problems.append(f"sh{sh['n']:02d}: 参考视频 {nvid} 段 > 1")
    if npic + nvid > 4:
        problems.append(f"sh{sh['n']:02d}: 混合参考 {npic + nvid} 个 > 4")
    # 禁用词
    for bad in ("creamy", "beige", "almond-shaped eyes,", "large erect pointed ears and not big",
                "majestic stance", "a wide bow-legged stance only"):
        if bad in body and "not " not in body.split(bad)[0][-40:]:
            problems.append(f"sh{sh['n']:02d}: 可疑措辞 {bad}")
    # 人类不出画
    if sh["n"] in (18, 29) and re.search(r"a (man|woman|person) (stands|walks|appears) in the frame", body):
        problems.append(f"sh{sh['n']:02d}: 人类入画")
    # 屏幕不生成
    if sh["n"] in (14, 15, 31) and "no interface" not in body:
        problems.append(f"sh{sh['n']:02d}: 屏幕内容未声明为无")

print("=" * 78)
if problems:
    print(f"❌ QC 发现 {len(problems)} 个问题：")
    for p in problems:
        print("  -", p)
else:
    print("✅ QC 全部通过")
