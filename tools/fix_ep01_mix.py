"""EP01 音层层级修正（字段级回写 shots.json，不整份覆盖）。

问题：各镜 bgm_gain=0.16 → 音乐在混音内落到 -37.0 dB，
而房间底噪也在 -37.0 dB —— 音乐被底噪完全掩蔽，等于没铺音乐。

修正目标（按 -16 LUFS 成片倒推）：
    对白 ≈ -23 dB  >  音乐 ≈ -32 dB  >  房间底噪 ≈ -37 dB
    音乐 = 对白 - 9dB，底噪 = 对白 - 14dB

做法：
  1) 默认 bgm_gain 0.16 → 0.30（→ -31.6 dB）；镜25 0.22 → 0.30；
     镜26 0.30 → 0.40（制作令要求「镜26 笑翻时音乐放大」）
  2) 底噪 amb_gain 逐镜设为 0.75（→ -38.5 dB），让底噪真正退到背景

用法：~/XiaoliuerVideoGen/venv/bin/python3 tools/fix_ep01_mix.py
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import film_pipeline as fp  # noqa: E402

EP = "ep01"
PATH = os.path.join(fp.PROJECT, "episodes", EP, "shots.json")

# 镜25：撤掉音乐的半秒空之前，音乐要够响才听得出「被撤走」
# 镜26：笑翻时音乐放大，比镜25 再高
BGM_GAIN = {25: 0.30, 26: 0.40}
DEFAULT_BGM_GAIN = 0.30
AMB_GAIN = 0.75

doc = json.load(open(PATH, encoding="utf-8"))
changed = []
for s in doc["shots"]:
    sid = s["id"]
    want_bgm = BGM_GAIN.get(sid, DEFAULT_BGM_GAIN)
    if s.get("bgm_gain") != want_bgm:
        changed.append("镜%02d bgm_gain %s → %s" % (sid, s.get("bgm_gain"), want_bgm))
        s["bgm_gain"] = want_bgm
    if s.get("amb_gain") != AMB_GAIN:
        changed.append("镜%02d amb_gain %s → %s" % (sid, s.get("amb_gain"), AMB_GAIN))
        s["amb_gain"] = AMB_GAIN

# 镜25 的半秒空：台词结束 2.25s，留半秒 → [2.25, 2.75]（已正确，保留）
s25 = [x for x in doc["shots"] if x["id"] == 25][0]
if s25.get("bgm_gap") != [2.25, 2.75]:
    changed.append("镜25 bgm_gap %s → [2.25, 2.75]" % s25.get("bgm_gap"))
    s25["bgm_gap"] = [2.25, 2.75]

# 镜26 音乐放大 → 同时给音效「笑声」让位（sfx_at 0.9 已是笑翻点，保留）
s26 = [x for x in doc["shots"] if x["id"] == 26][0]
if s26.get("sfx_at") != [0.9]:
    changed.append("镜26 sfx_at %s → [0.9]" % s26.get("sfx_at"))
    s26["sfx_at"] = [0.9]

with open(PATH, "w", encoding="utf-8") as f:
    json.dump(doc, f, ensure_ascii=False, indent=2)
    f.write("\n")

print("字段级回写完成，共 %d 处：" % len(changed))
for c in changed:
    print("  " + c)
