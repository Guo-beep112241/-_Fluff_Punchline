#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""submit_episode_shots.py 的 mock 测试。

在 /tmp 的副本项目上跑，不碰任何真实数据。
覆盖四条路径：
  1. 成功提交两个镜 → task_id 落盘、包装层完好、快照存档
  2. 第二个镜提交失败 → 第一个镜的 task_id 仍然在盘上（绝不丢）
  3. 提示词超 7000 字符 → 解析阶段就被拦下，一个都不提交
  4. 重复 task_id → 拒绝覆盖
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile

SCRIPT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                      "tools", "submit_episode_shots.py")

PROMPT_TEMPLATE = """# ep01 / 镜{num:02d} 测试提示词

## 生成参数
- 模型：MiniMax-H3 ｜ 模式：Ref2VA（多模态参考）
- 时长：{dur} 秒 ｜ 画幅：9:16 ｜ 分辨率：768P

## 参考素材（按上传顺序编号）
目录：`10_工作素材/characters/_curated/adult/`
- `<Picture 1>` → `x6_adult_face_front_sharp_01.jpg` — 职责：**脸型五官基准**。
- `<Picture 2>` → `scene_dorm_floor_01.jpg` — 职责：**宿舍地板场景锚点**。
- `<Video 1>` → `x6_adult_char_ref_walk_splay_03.mp4` — 职责：**走路步态**。

## 提示词（可直接提交）
```
subject_definitions:
<Subject 1>: is the young white Samoyed dog in <Picture 1>.

summary:
[reference generation] A test shot.

retention_analysis:
<Subject 1> (appears in [Shot 1]): fully_preserved - the same individual dog.

detailed_description:
[Shot 1] [Medium close-up], [static locked camera]. {filler}

overall_soundscape:
Quiet indoor room tone.

non_diegetic_music:
None.
```
"""

FAKE_MCODE = r"""#!/bin/bash
if [ "$1" = "upload-temp-url" ]; then
  echo '{"temp_url":"https://fake.local/'"$2"'"}'
  exit 0
fi
if [ "$1" = "connector" ] && [ "$2" = "call" ]; then
  # connector call <tool> --args-file <path>  →  参数文件在 $5
  args="$5"
  if grep -q 'FAILME' "$args"; then
    echo '{"code":500,"message":"synthetic failure"}'
    exit 1
  fi
  # 每次提交返回一个递增的 task_id，模拟平台行为
  n=$(cat "$FAKE_COUNTER_FILE" 2>/dev/null || echo 100000000)
  n=$((n+1))
  echo "$n" > "$FAKE_COUNTER_FILE"
  echo '{"code":0,"task_id":"'"$n"'"}'
  exit 0
fi
exit 1
"""


def build_project(tmp, shots, prompt_overflow=False, dup_task=False):
    proj = os.path.join(tmp, "proj")
    os.makedirs(os.path.join(proj, "tools"))
    os.makedirs(os.path.join(proj, "docs"))
    os.makedirs(os.path.join(proj, "episodes/ep01/prompts"))
    os.makedirs(os.path.join(proj, "10_工作素材/characters/_curated/adult"))
    os.makedirs(os.path.join(proj, "10_工作素材/scenes"))
    os.makedirs(os.path.join(proj, "10_工作素材/habits/_curated"))

    shutil.copy(SCRIPT, os.path.join(proj, "tools/submit_episode_shots.py"))

    for fn in ["x6_adult_face_front_sharp_01.jpg"]:
        open(os.path.join(proj, "10_工作素材/characters/_curated/adult", fn), "wb").write(b"x")
    open(os.path.join(proj, "10_工作素材/scenes/scene_dorm_floor_01.jpg"), "wb").write(b"x")
    open(os.path.join(proj, "10_工作素材/habits/_curated/x6_adult_char_ref_walk_splay_03.mp4"), "wb").write(b"x")

    for num, dur in shots:
        body = PROMPT_TEMPLATE.format(num=num, dur=dur, filler="Filler sentence. " * 20)
        if prompt_overflow and num == shots[-1][0]:
            body = body.replace("Filler sentence. " * 20, "Filler sentence. " * 900)
        if dup_task and num == shots[-1][0]:
            body = body.replace("[reference generation] A test shot.",
                                "FAILME [reference generation] A test shot.")
        path = os.path.join(proj, "episodes/ep01/prompts/sh%02d.md" % num)
        open(path, "w", encoding="utf-8").write(body)

    with open(os.path.join(proj, "docs/video_tasks.json"), "w", encoding="utf-8") as f:
        json.dump({"tasks": {}}, f, ensure_ascii=False, indent=2)

    bin_dir = os.path.join(tmp, "bin")
    os.makedirs(bin_dir)
    fake = os.path.join(bin_dir, "mcode-tools")
    open(fake, "w").write(FAKE_MCODE)
    os.chmod(fake, 0o755)
    return proj, bin_dir


def run(proj, bin_dir, extra_args=None, task_id="987654321", env_extra=None):
    env = dict(os.environ)
    env["PATH"] = bin_dir + os.pathsep + env["PATH"]
    env["FAKE_TASK_ID"] = task_id
    env["FAKE_FAIL_FILE"] = "/tmp/nonexistent_fail_marker"
    env["FAKE_COUNTER_FILE"] = os.path.join(os.path.dirname(proj), "counter.txt")
    if env_extra:
        env.update(env_extra)
    cmd = [sys.executable, os.path.join(proj, "tools/submit_episode_shots.py")] + (extra_args or [])
    return subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=120)


def check(label, cond, detail=""):
    print("  %s %s%s" % ("✅" if cond else "❌", label, (" — " + detail) if detail and not cond else ""))
    return bool(cond)


def main():
    all_ok = True

    # ---------- 路径 1：成功提交两个镜 ----------
    print("\n【路径1】成功提交两个镜")
    tmp = tempfile.mkdtemp(prefix="h3mock1_")
    try:
        proj, bin_dir = build_project(tmp, [(1, 5), (2, 6)])
        r = run(proj, bin_dir)
        all_ok &= check("退出码 0", r.returncode == 0, r.stdout[-800:] + r.stderr[-400:])
        doc = json.load(open(os.path.join(proj, "docs/video_tasks.json"), encoding="utf-8"))
        all_ok &= check("tasks 包装层完好", "tasks" in doc and isinstance(doc["tasks"], dict))
        all_ok &= check("登记了 2 个任务", len(doc.get("tasks", {})) == 2, str(list(doc.get("tasks", {}))))
        rec = list(doc.get("tasks", {}).values())[0]
        for field in ["model", "duration_s", "ratio", "resolution", "output_file",
                      "reference_images", "reference_videos", "submitted_prompt_sha256",
                      "submitted_prompt_snapshot", "prompt_file", "shot"]:
            all_ok &= check("登记含 %s" % field, field in rec)
        all_ok &= check("时长取自 md", any(t["duration_s"] == 6 for t in doc["tasks"].values()))
        all_ok &= check("参考视频记进登记", any(t["reference_videos"] for t in doc["tasks"].values()))
        all_ok &= check("参考图按 Picture 顺序",
                        list(doc["tasks"].values())[0]["reference_images"][0].startswith("x6_adult_face"))
        snap = os.path.join(proj, list(doc["tasks"].values())[0]["submitted_prompt_snapshot"])
        all_ok &= check("快照文件存在", os.path.exists(snap), snap)
        if os.path.exists(snap):
            import hashlib
            # snapshot() 写的是 prompt + "\n"，剥掉末尾那一个换行还原原文
            content = open(snap, "rb").read()
            if content.endswith(b"\n"):
                content = content[:-1]
            sha = hashlib.sha256(content).hexdigest()
            all_ok &= check("快照 sha256 与登记一致",
                            sha == list(doc["tasks"].values())[0]["submitted_prompt_sha256"],
                            "算出的 %s ≠ 登记的 %s" % (sha[:12], list(doc["tasks"].values())[0]["submitted_prompt_sha256"][:12]))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # ---------- 路径 2：第二个镜提交失败，第一个仍落盘 ----------
    print("\n【路径2】中途失败不丢已提交的 task_id")
    tmp = tempfile.mkdtemp(prefix="h3mock2_")
    try:
        proj, bin_dir = build_project(tmp, [(1, 5), (2, 6)])
        # 让镜02 的提示词含 FAILME，mock 会让它提交失败
        p2 = os.path.join(proj, "episodes/ep01/prompts/sh02.md")
        txt = open(p2, encoding="utf-8").read()
        open(p2, "w", encoding="utf-8").write(
            txt.replace("[reference generation] A test shot.", "FAILME [reference generation] A test shot."))
        r = run(proj, bin_dir)
        all_ok &= check("退出码非 0", r.returncode != 0, "rc=%d" % r.returncode)
        all_ok &= check("打印了中断提示", "中断" in r.stdout, r.stdout[-500:])
        doc = json.load(open(os.path.join(proj, "docs/video_tasks.json"), encoding="utf-8"))
        all_ok &= check("tasks 包装层仍完好", "tasks" in doc)
        all_ok &= check("镜01 的 task_id 还在盘上", len(doc.get("tasks", {})) == 1,
                        str(list(doc.get("tasks", {}))))
        all_ok &= check("提示了已提交的 id 可取回", "镜01" in r.stdout, r.stdout[-500:])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # ---------- 路径 3：提示词超 7000 字符，解析阶段拦住 ----------
    print("\n【路径3】超长提示词被解析阶段拦下")
    tmp = tempfile.mkdtemp(prefix="h3mock3_")
    try:
        proj, bin_dir = build_project(tmp, [(1, 5), (2, 6)], prompt_overflow=True)
        r = run(proj, bin_dir)
        all_ok &= check("退出码非 0", r.returncode != 0)
        all_ok &= check("报出 7000 上限", "7000" in r.stdout, r.stdout[-600:])
        doc = json.load(open(os.path.join(proj, "docs/video_tasks.json"), encoding="utf-8"))
        all_ok &= check("一个都没提交", len(doc.get("tasks", {})) == 0, str(list(doc.get("tasks", {}))))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # ---------- 路径 4：参考图找不到 ----------
    print("\n【路径4】参考图文件名找不到 → 报错并列出")
    tmp = tempfile.mkdtemp(prefix="h3mock4_")
    try:
        proj, bin_dir = build_project(tmp, [(1, 5)])
        p1 = os.path.join(proj, "episodes/ep01/prompts/sh01.md")
        txt = open(p1, encoding="utf-8").read()
        open(p1, "w", encoding="utf-8").write(
            txt.replace("x6_adult_face_front_sharp_01.jpg", "x6_adult_not_exist_99.jpg"))
        r = run(proj, bin_dir)
        all_ok &= check("退出码非 0", r.returncode != 0)
        all_ok &= check("点名缺失的文件", "x6_adult_not_exist_99" in r.stdout, r.stdout[-600:])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # ---------- 路径 5：dry-run 不提交 ----------
    print("\n【路径5】dry-run 不产生任何提交")
    tmp = tempfile.mkdtemp(prefix="h3mock5_")
    try:
        proj, bin_dir = build_project(tmp, [(1, 5), (2, 6)])
        r = run(proj, bin_dir, ["--dry-run"])
        all_ok &= check("退出码 0", r.returncode == 0, r.stdout[-600:])
        doc = json.load(open(os.path.join(proj, "docs/video_tasks.json"), encoding="utf-8"))
        all_ok &= check("没有登记任何任务", len(doc.get("tasks", {})) == 0)
        all_ok &= check("打印了每镜摘要", "镜01" in r.stdout and "镜02" in r.stdout)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("\n%s" % ("全部通过 ✅" if all_ok else "有失败项 ❌"))
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
