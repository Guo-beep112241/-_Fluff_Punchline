#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
安全提交并推送（iCloud 工作树专用）。

为什么不用 `git add -A && git commit && git push` 一把梭：
本项目的工作树在 iCloud 上，有三个反复踩到的坑，这脚本逐个绕开。

坑一：**`git status` 会永久挂死。**
    它会全量扫描工作树，遇到 iCloud 占位符（dataless）就卡在 read() 上。
    实测在 6.9GB 媒体目录上跑 3 分半没返回。
    → 本脚本一律用 `git diff-index --name-status HEAD`，不碰 status。

坑二：**`git add -A` 会被已跟踪的 dataless 文件卡死。**
    目录被 .gitignore 排除没关系，但只要某个**已跟踪**的文件是占位符，
    git 就必须读它来比对内容 → 永久阻塞，还会留下 index.lock。
    → 本脚本提交前先扫描已跟踪文件里的 dataless，有就报出来并跳过。

坑三：**`git diff-index` 会把 iCloud 改写文件导致的 stat 变化报成「M 已修改」。**
    它是管道命令，只比对 stat 不做内容比对，所以全量误报。
    实测 79 个文件全报 M，逐个哈希核对后内容其实完全一致。
    → 本脚本用「直接算 blob 哈希」跟 HEAD 比，给出真实差异。

用法：
  python3 tools/safe_commit_push.py --dry-run       # 只体检不提交
  python3 tools/safe_commit_push.py -m "提交信息"     # 体检通过则提交并推送
  python3 tools/safe_commit_push.py --skip-push     # 只提交不推送
"""

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GIT_DIR = os.path.expanduser("~/.minimax/git-repos/xiaoliuer")
DATALESS_FLAG = 0x40000000


def git(*args, **kw):
    cmd = ["git", "--git-dir", GIT_DIR] + list(args)
    return subprocess.run(cmd, capture_output=True, text=True,
                          timeout=kw.get("timeout", 300), cwd=PROJECT)


def tracked_files():
    r = git("ls-tree", "-r", "-z", "--name-only", "HEAD")
    return [p for p in r.stdout.split("\0") if p]


def is_dataless(path):
    try:
        return bool(os.lstat(path).st_flags & DATALESS_FLAG)
    except OSError:
        return False


def blob_hash(path):
    """算 git blob 哈希（blob <len>\\0 + 内容）。"""
    data = open(path, "rb").read()
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def check_tracked():
    """扫描已跟踪文件里的 dataless —— 这是 add 会挂死的根因。"""
    bad = []
    for p in tracked_files():
        if is_dataless(p):
            bad.append(p)
    return bad


def real_diff():
    """用直接哈希算出真实差异（绕开 diff-index 的 stat 噪音）。"""
    head = git("rev-parse", "HEAD").stdout.strip()
    changed, unread = [], []
    for p in tracked_files():
        if is_dataless(p):
            unread.append(p)
            continue
        r = git("rev-parse", "HEAD:" + p)
        if r.returncode != 0:
            changed.append((p, "新增/不在 HEAD"))
            continue
        want = r.stdout.strip()
        try:
            got = blob_hash(p)
        except OSError as e:
            unread.append("%s (%s)" % (p, type(e).__name__))
            continue
        if got != want:
            changed.append((p, "内容不同"))
    return head, changed, unread


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-m", "--message", help="提交信息")
    ap.add_argument("--dry-run", action="store_true", help="只体检")
    ap.add_argument("--skip-push", action="store_true", help="只提交不推送")
    args = ap.parse_args()

    if not os.path.isdir(GIT_DIR):
        print("❌ 找不到 git 目录：%s" % GIT_DIR)
        return 1

    print("=== 体检 ===")

    # 1. 已跟踪文件里的 dataless —— add 的致命伤
    bad = check_tracked()
    if bad:
        print("❌ 有 %d 个已跟踪文件是 iCloud 占位符，git add 会永久挂死：" % len(bad))
        for p in bad[:20]:
            print("   ⚠️ ", p)
        print("\n   处置：把它们从版本控制摘除 ——")
        print("   git --git-dir=%s update-index --force-remove '<路径>'" % GIT_DIR)
        print("   （不动磁盘、不读内容；这些文件本来就是重复的旧副本）")
        return 2
    print("✅ 已跟踪文件里没有 dataless")

    # 2. 真实差异
    head, changed, unread = real_diff()
    if unread:
        print("⚠️ %d 个已跟踪文件读不了（dataless 或权限）：" % len(unread))
        for p in unread[:10]:
            print("   ", p)
    print("✅ 内容层面的真实改动：%d 个" % len(changed))
    for p, why in changed[:30]:
        print("   M  %s  (%s)" % (p, why))

    # 3. 未跟踪的新文件（只列，不展开 ignored 目录）
    r = git("ls-files", "--others", "--exclude-standard")
    new = [p for p in r.stdout.splitlines() if p.strip()]
    print("✅ 未跟踪的新文件：%d 个" % len(new))
    for p in new[:30]:
        print("   A  ", p)

    if args.dry_run:
        print("\n（dry-run，未提交）")
        return 0

    if not args.message:
        print("\n❌ 需要 -m 提交信息（或用 --dry-run 只体检）")
        return 1
    if not changed and not new:
        print("\n没有可提交的内容")
        return 0

    # 4. add（此时没有 tracked dataless，不会挂死）
    print("\n=== git add -A ===")
    t0 = time.time()
    r = git("add", "-A", timeout=1800)
    if r.returncode != 0:
        print("❌ add 失败：\n%s\n%s" % (r.stdout[-500:], r.stderr[-500:]))
        return 3
    print("✅ add 完成（%.0f 秒）" % (time.time() - t0))

    # 5. commit
    r = git("commit", "-m", args.message, timeout=600)
    if r.returncode != 0:
        print("❌ commit 失败：\n%s\n%s" % (r.stdout[-800:], r.stderr[-500:]))
        return 4
    new_head = git("rev-parse", "HEAD").stdout.strip()
    print("✅ commit 成功：%s → %s" % (head[:8], new_head[:8]))

    # 6. push
    if args.skip_push:
        print("\n（--skip-push，未推送）")
        return 0
    print("\n=== push ===")
    r = git("push", "origin", "main", timeout=3600)
    print(r.stdout.strip() or r.stderr.strip()[-800:])
    if r.returncode != 0:
        print("❌ push 失败")
        return 5
    print("✅ push 成功")
    return 0


if __name__ == "__main__":
    sys.exit(main())
