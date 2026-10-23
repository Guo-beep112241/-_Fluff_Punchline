#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Ep1《第一个跟头》H3 Ref2VA 提示词生成器.

只写 episodes/ep01/prompts/shNN.md，不碰 script.md / storyboard.md / bible/ / docs/。
外形特征词逐字取自 bible/characters.md（FEATURES / EAR / BUILD 等常量）。
场景图作为 <Subject N>（场景也是 subject），并给单独的 retention_analysis 行。
"""
import pathlib, re, sys

OUT = pathlib.Path("/Users/guojiayuan/Movies/Xiaoliuer/episodes/ep01/prompts")

# --------------------------------------------------------------------------
# 逐字复用：bible/characters.md《外形特征词》
# --------------------------------------------------------------------------
FEATURES = ("a rounded soft puppy-like head with a broad round forehead, "
            "large round dark brown eyes set wide apart, "
            "a short broad muzzle, a large round black nose, "
            "small triangular ears held slightly outward, "
            "a medium-length soft pure white coat that lies flat and even, "
            "pink tongue lolling out")

EAR = ("Its ears are small and neat: small, neat triangular ears that sit close to the head, "
       "slightly folded forward at the tips, not large erect pointed ears and not big upright ears.")

EYES = ("The eyes are round and wide open rather than narrow and almond-shaped, "
        "and they stay wide open and round for the whole shot.")

COAT = ("The coat is clean pure white, not cream, not beige, not ivory and not yellow; "
        "only the inner ears, the muzzle and the belly carry a faint warm tint.")

CHEST = "Its chest fur is light, smooth and evenly spread, with no thick ruff and no lion-like mane."

BUILD = ("Its build is slim and youthful, with a narrow chest, a visible gap between the front legs, "
         "slender legs and slightly oversized paws; the front and hind paws turn slightly outward from "
         "the midline, a very subtle toe-out, with the hind feet splayed only a little, the splay is "
         "very slight and natural, not a wide bow-legged stance.")

MOOD = ("Its expression is open, young, earnest and a little eager, "
        "never majestic, proud, dignified, regal or stern.")

# 品种先验压制段（v4 必须写；杏仁眼放首位）
BRIEF = (
    "The target video is in realistic photographic style. The dog is the same individual young Samoyed "
    "as in the reference pictures, not the exaggerated show-dog version of the breed. The eyes are round "
    "and wide open rather than narrow and almond-shaped. The head is round and soft with a broad round "
    "forehead, not a broad sharp wedge. The muzzle is short and broad, not a long snout. The fur is "
    "medium-length and lies flat along the body, not a dense double coat, with no thick ruff and no "
    "lion-like mane, and the chest hair is light and evenly spread instead of clumped. The body is slim "
    "with a narrow chest and a clear gap of daylight between the front legs, not stocky and not a powerful "
    "build. The coat is clean pure white, not cream, not beige, not ivory and not yellow; only the inner "
    "ears, the muzzle and the belly carry a faint warm tint. Its ears are small, neat triangular ears that "
    "sit close to the head, slightly folded forward at the tips, not large erect pointed ears and not big "
    "upright ears. The expression is open, young and earnest, never majestic, proud, dignified or stern. "
    "The light is neutral daylight with the white balance locked, so the white coat stays white and the "
    "frame never turns warm.")

RETENTION_DOG = (
    "<Subject 1> (appears in [Shot 1]): fully_preserved - the same individual young white Samoyed, keeping "
    "the rounded soft head with the broad round forehead, the large round dark brown eyes set wide apart and "
    "held wide open, the short broad muzzle, the large round black nose, the small neat triangular ears that "
    "sit close to the head and fold slightly forward at the tips, the medium-length soft pure white coat that "
    "lies flat and even, the light unclumped chest fur, and the slim youthful build with a narrow chest, a "
    "visible gap between the front legs and slender legs.")

# --------------------------------------------------------------------------
# 四张场景图（实拍，10_工作素材/scenes/）—— 描述逐条对照照片
# --------------------------------------------------------------------------
SCENE_NOTICEBOARD = (
    "a fictional university teaching-building corridor wall - a vertical cork notice board in a slim aluminium "
    "frame, its surface covered with overlapping blank sheets of white, pale yellow, light blue and salmon "
    "paper held by small silver push pins, the sheets skewed at different angles and several corners curled "
    "away from the cork. Every sheet of paper is completely blank: no printing, no writing, no lettering and "
    "no readable text anywhere in the frame. Around it is a pale green-grey painted concrete block wall with "
    "visible block joints and scuffs, a black skirting band at the floor line, a grey polished concrete floor, "
    "and a fluorescent light panel in the dropped ceiling above.")

SCENE_CORRIDOR = (
    "a fictional university teaching-building corridor - cream off-white upper walls above a deep green painted "
    "wainscot with a black skirting line at the floor, a grey polished concrete floor with soft reflections, "
    "tall windows along the left side letting in flat daylight, a row of wooden classroom doors with frosted "
    "glass panes on the right, fluorescent tube lights on the ceiling, and a staircase landing at the far end. "
    "There is no readable text or signage anywhere in the corridor.")

SCENE_DORM = (
    "a fictional university dormitory, the camera almost touching the floor - a pale beige wood-grain laminate "
    "floor in sharp focus in the foreground with dust, loose hairs and small dark specks scattered on it, a "
    "grey-green painted metal bed leg standing in the middle distance with the edge of a bunk bed and a dark "
    "duvet on the right, and a blurred desk, chair, green curtain and dark backpack in the background. The "
    "depth of field is very shallow and there is no readable text or signage anywhere in the room.")

SCENE_REHEARSAL = (
    "a fictional university rehearsal room - a deep red maroon carpet with visible seams and a worn bald patch, "
    "worn cream walls with scuffs and flaking paint, a heavy black pleated curtain covering the back wall, a "
    "small metal-framed nesting table and a stack of plastic stools in the middle distance, and a tall window "
    "on the left throwing one hard shaft of light with visible dust motes in the air. There is no readable text "
    "anywhere in the room.")

SCENE_RET = ("fully_preserved - the room layout, the materials, the furniture placement, the light direction "
             "and the colour palette of the scene reference stay unchanged; the setting is presented as a "
             "fictional university interior and no real institution is identifiable.")

ROOMMATE = ("<Subject 3>: is the off-screen voice of a young male university dormitory roommate, heard only "
            "from outside the frame and never seen; a casual, slightly distracted young male voice.")
ROOMMATE_RET = ("<Subject 3>: fully_preserved - the off-screen voice stays the same young male dormitory "
                "roommate voice, heard only from outside the frame and never seen.")
JUDGE = ("<Subject 3>: is the off-screen voice of an adult male member of a university evaluation panel, heard "
         "only from outside the frame and never seen; a slow, businesslike, neutral adult male voice.")
JUDGE_RET = ("<Subject 3>: fully_preserved - the off-screen voice stays the same slow, businesslike adult male "
             "panel voice, heard only from outside the frame and never seen.")
PRESIDENT = ("<Subject 3>: is the off-screen voice of a senior male university student, the head of the "
             "crosstalk club, heard only through a phone voice message and never seen; a slightly compressed, "
             "narrow-band young male voice with phone-quality ambience.")
PRESIDENT_RET = ("<Subject 3>: fully_preserved - the off-screen voice stays the same narrow-band phone voice "
                 "message from the club president, heard only from the device and never seen.")

LIPS_CLOSED = "The on-screen dog's lips stay completely closed throughout; no lip movement is visible."


def plan(sh):
    """算出 <Picture N> / <Subject N> 的编号方案。"""
    pics = list(sh.get("pics", []))          # 狗的参考照 [dict]
    scene = sh.get("scene")                  # 场景图 dict
    vids = list(sh.get("vids", []))          # 动态参考 [dict]
    order = []                                # [(kind, dict)]
    if sh.get("empty"):
        order.append(("scene", scene))        # 空镜：只有场景图，不引任何定妆照
        dog_idx, scene_idx, human_idx = None, 1, None
    else:
        if pics:
            order.append(("dog", pics[0]))
        if scene:
            order.append(("scene", scene))
        for p in pics[1:]:
            order.append(("dog", p))
        dog_idx = 1
        scene_idx = 2 if scene else None
        human_idx = 3 if scene else 2
    dog_pics = [f"<Picture {i + 1}>" for i, (k, _) in enumerate(order) if k == "dog"]
    scene_pic = None
    for i, (k, item) in enumerate(order):
        if k == "scene":
            scene_pic = f"<Picture {i + 1}>"
    return dict(order=order, dog_pics=dog_pics, scene_pic=scene_pic,
                dog_idx=dog_idx, scene_idx=scene_idx, human_idx=human_idx, vids=vids)


def subject_defs(sh, P):
    out = []
    if sh.get("empty"):
        out.append(f"<Subject 1>: is {sh['scene']['desc']} From {P['scene_pic']}, fully_preserved - "
                   f"{sh['scene']['duty_en']}. The frame contains no animal and no person; it is an empty "
                   "establishing shot of the notice board, and every sheet of paper on the board stays "
                   "completely blank.")
    else:
        src = ", ".join(P["dog_pics"])
        out.append(f"<Subject 1>: is the young white Samoyed dog in {src} - the same individual dog in every "
                   "picture.")
        for lab, item in zip(P["dog_pics"], sh.get("pics", [])):
            out.append(f"From {lab}, fully_preserved - {item['duty_en']}")
        out.append(f"<Subject 1> has {FEATURES}. {EYES} {EAR} {COAT} {CHEST} {BUILD} {MOOD}")
        for i, v in enumerate(P["vids"]):
            out.append(f"<Video {i + 1}>: is a short motion-reference clip of the same young white Samoyed; its "
                       "original setting is not part of the target video.")
        if sh.get("scene"):
            out.append(f"<Subject 2>: is {sh['scene']['desc']} From {P['scene_pic']}, fully_preserved - "
                       f"{sh['scene']['duty_en']}")
        if sh.get("human"):
            out.append(sh["human"][0])
    return "\n".join(out)


def retention_defs(sh, P):
    out = []
    if sh.get("empty"):
        out.append("<Subject 1> (appears in [Shot 1]): fully_preserved - the cork notice board, the blank "
                   "coloured sheets, the painted concrete block wall, the black skirting band, the grey polished "
                   "concrete floor and the overhead fluorescent panel all stay as they are, and no animal and no "
                   "person enters the frame at any point.")
    else:
        out.append(RETENTION_DOG)
        if sh.get("scene"):
            out.append(f"<Subject 2> (appears in [Shot 1]): {SCENE_RET}")
    if sh.get("human"):
        out.append(sh["human"][1])
    for i, v in enumerate(P["vids"]):
        out.append(f"<Video {i + 1}> (appears in [Shot 1]): fully_preserved - {v['duty_en']}")
    return "\n".join(out)


def dialogue_block(sh, P):
    lines, sid = [], 0
    for item in sh.get("lines", []):
        kind, text = item[0], item[1]
        note = item[2] if len(item) > 2 else None
        sid += 1
        s = f"(S{sid})"
        if kind == "vo":
            lines.append(f"<Subject 1> {s} says in an off-screen voiceover: <d>[Chinese] {text}</d>")
            lines.append(note if note else LIPS_CLOSED)
        elif kind == "speak":
            lines.append(f"<Subject 1> {s} speaks: <d>[Chinese] {text}</d>")
            if note:
                lines.append(note)
        elif kind == "human":
            lines.append(f"<Subject 3> {s} speaks off screen: <d>[Chinese] {text}</d>")
    return "\n".join(lines)


def build_prompt(sh, P):
    body = sh["body"].replace("@SCENE@", f"<Subject {P['scene_idx']}>" if P["scene_idx"] else "<Subject 1>")
    body = body.replace("@DOG@", "<Subject 1>")
    parts = []
    parts.append("subject_definitions:\n" + subject_defs(sh, P))
    parts.append("summary:\n[reference generation] " + sh["summary"])
    parts.append("retention_analysis:\n" + retention_defs(sh, P))
    dd = "detailed_description:\n" + sh.get("brief", BRIEF) + "\n" + body
    if sh.get("lines"):
        dd += "\n" + dialogue_block(sh, P)
    parts.append(dd)
    parts.append("overall_soundscape:\n" + sh["sounds"])
    parts.append("non_diegetic_music:\n" + sh["music"])
    return "\n\n".join(parts) + "\n"


def write_shot(sh):
    P = plan(sh)
    prompt = build_prompt(sh, P)
    n_chars = len(prompt)
    assert n_chars <= 7000, (sh["n"], "prompt too long", n_chars)
    dd = prompt.split("detailed_description:\n", 1)[1].split("\n\noverall_soundscape:", 1)[0]
    wc = len(dd.split())
    assert 340 <= wc <= 520, (sh["n"], "detailed_description word count", wc)
    refs = []
    i = 0
    for kind, item in P["order"]:
        i += 1
        refs.append(f"- `<Picture {i}>` → `{item['file']}` — 职责：**{item['role']}**。{item['duty_cn']}")
    for j, v in enumerate(P["vids"]):
        refs.append(f"- `<Video {j + 1}>` → `{v['file']}` — 职责：**{v['role']}**。{v['duty_cn']}")
    md = []
    md.append(f"# ep01 / 镜 {sh['n']:02d}")
    md.append("")
    md.append(f"> {sh['note']}")
    md.append("")
    md.append("## 生成参数")
    md.append("- 模型：MiniMax-H3")
    md.append("- 模式：Ref2VA（多模态参考）")
    md.append(f"- 时长：{sh['dur']} 秒")
    md.append("- 画幅：9:16")
    md.append("- 分辨率：768P（试错）/ 2K（定稿）")
    md.append("")
    md.append("## 参考素材（按上传顺序编号）")
    md.append("`10_工作素材/characters/_curated/adult/` ＋ `10_工作素材/scenes/`"
              + (" ＋ `10_工作素材/habits/_curated/`" if P["vids"] else ""))
    md.extend(refs)
    md.append("")
    if sh.get("empty"):
        md.append("> ⚠️ **本镜是空镜**（分镜表：出镜角色＝无）。**只引场景图，不引任何小六二定妆照** —— "
                  "引了模型会把狗塞进空镜，镜01 与镜02 接不上。")
    else:
        md.append("> 场景图为实拍空景，**无人无动物**；定妆照里的背景（窗帘／木地板／楼顶／家居）**一律不入画**。"
                  "学校是**虚构**的，任何画面里都不得出现可辨认的校名、标识或文字。")
    if sh.get("blank_paper"):
        md.append("> ⚠️ **纸张/表格内容全部后期贴图**：本镜生成时纸面必须**完全空白**，不得出现任何文字或印刷内容。")
    md.append("")
    md.append("## 提示词")
    md.append("```")
    md.append(prompt.rstrip("\n"))
    md.append("```")
    md.append("")
    md.append("## 变更记录")
    md.append(f"- v1 2026-10-23 初稿 · Ep1 镜{sh['n']:02d}（{sh['tier']}）")
    md.append("")
    md.append("## 试错记录")
    md.append("<!-- 每轮生成后回填：哪个变体好、哪里不对、下次改什么。只能改一个变量。 -->")
    md.append("")
    md.append("| 轮次 | 唯一改动 | 看什么 |")
    md.append("|---|---|---|")
    md.append(f"| B1 | 基线生成 | {sh['watch']} |")
    md.append(f"| B2 | {sh['fix']} | {sh['watch2']} |")
    md.append("")
    md.append(f"**风险点**：{sh['risk']}")
    (OUT / f"sh{sh['n']:02d}.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    return n_chars, wc
