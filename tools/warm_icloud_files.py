#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
预热：把被 iCloud 卸载（dataless）的素材文件下载实体化。

背景
----
项目目录在 iCloud 上、体积大，iCloud 会持续把本地副本卸载成「云端占位符」。
占位符的 stat 大小是 0，读取会触发下载，**但可能阻塞几十秒到几分钟**。
工作脚本（卷轴、批量上传）撞上时就会表现成「卡住不动」，很难判断是死锁还是在下载。

本脚本把这件事从工作流程里剥出来：
- 逐个检测 dataless 文件
- 逐个读取一遍，把下载触发掉
- 读完之后再读就是瞬时的

用法
----
    python3 tools/warm_icloud_files.py              # 预热 10_工作素材 与 20_生成结果
    python3 tools/warm_icloud_files.py --check      # 只报告，不读
    python3 tools/warm_icloud_files.py --dir <path> # 指定目录

判据
----
dataless 占位符：os.lstat(p).st_flags & 0x40000000 为真（本地零占用）
"""

import argparse
import os
import sys
import time

DATALESS_FLAG = 0x40000000
DEFAULT_DIRS = ["10_工作素材", "20_生成结果", "docs", "bible", "episodes", "tools"]


def is_dataless(path):
    try:
        return bool(os.lstat(path).st_flags & DATALESS_FLAG)
    except (OSError, AttributeError):
        return False


def scan(dirs):
    out = []
    for d in dirs:
        if not os.path.isdir(d):
            continue
        for root, _sub, files in os.walk(d):
            for fn in files:
                p = os.path.join(root, fn)
                if is_dataless(p):
                    out.append(p)
    return out


def warm(path, timeout=None):
    """读一遍，把下载触发掉。返回 (是否成功, 耗时秒)。"""
    t0 = time.time()
    try:
        with open(path, "rb") as f:
            while True:
                chunk = f.read(1 << 20)
                if not chunk:
                    break
        return True, time.time() - t0
    except Exception as e:
        return False, "%s（%.1fs）" % (e, time.time() - t0)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", action="append", default=None, help="要预热的目录，可重复")
    ap.add_argument("--check", action="store_true", help="只报告，不读")
    ap.add_argument("--timeout", type=float, default=600, help="单文件最长等待秒数")
    args = ap.parse_args()

    dirs = args.dir or DEFAULT_DIRS
    files = scan(dirs)
    print("扫描 %s" % "、".join(dirs))
    if not files:
        print("✅ 没有被卸载的文件")
        return 0
    print("发现 %d 个被卸载的文件：" % len(files))
    for p in files:
        print("  - %s" % p)

    if args.check:
        print("\n（--check 模式，未触发下载）")
        return 0

    print("\n开始预热（逐个读取触发下载）…")
    ok = fail = 0
    for i, p in enumerate(files, 1):
        good, detail = warm(p, args.timeout)
        if good:
            ok += 1
            print("  [%d/%d] ✅ %-62s %.1fs" % (i, len(files), os.path.basename(p), detail))
        else:
            fail += 1
            print("  [%d/%d] ❌ %-62s %s" % (i, len(files), os.path.basename(p), detail))
    print("\n预热完成：成功 %d，失败 %d" % (ok, fail))
    left = scan(dirs)
    print("剩余 dataless：%d" % len(left))
    for p in left:
        print("  - %s" % p)
    return 0 if not left else 1


if __name__ == "__main__":
    sys.exit(main())
