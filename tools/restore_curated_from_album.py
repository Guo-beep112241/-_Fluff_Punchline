#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
从本地相册还原被 iCloud 卸载的精选照片。

背景
----
iCloud 会把项目目录里的文件卸载成「云端占位符」（dataless），读取会无限阻塞。
但**原始照片在 `~/Pictures/六二成年照/` 里，是本地盘，不会被卸载**。
精选目录（`_curated/adult/`）里的绝大多数照片只是「复制 + 重命名」，没有二次处理，
所以可以直接从相册按源 ID 还原。

前提：源文件与精选文件字节数一致（=纯复制），才还原。
不一致的（做过裁剪/修补的）跳过并单独报告，避免用错素材。

用法
----
    python3 tools/restore_curated_from_album.py            # 检查并还原
    python3 tools/restore_curated_from_album.py --check    # 只报告
"""

import argparse
import os
import shutil
import sys

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CURATED = os.path.join(PROJECT, "10_工作素材/characters/_curated/adult")
ALBUM = os.path.expanduser("~/Pictures/六二成年照")
DATALESS = 0x40000000

# 精选文件名 → 源文件名（一一对应，见 docs/asset_index_adult.csv）
MAP = {
    "x6_adult_face_front_tongue_01.jpg": "8351792693080_.pic_hd.jpg",
    "x6_adult_face_threequarter_01.jpg": "8361792693081_.pic_hd.jpg",
    "x6_adult_lying_half_01.jpg": "8371792693084_.pic_hd.jpg",
    "x6_adult_lying_full_01.jpg": "8401792693086_.pic_hd.jpg",
    "x6_adult_stand_side_01.jpg": "8411792693087_.pic_hd.jpg",
    "x6_adult_face_front_01.jpg": "8431792693088_.pic_hd.jpg",
    "x6_adult_lying_full_02.jpg": "8621792693105_.pic_hd.jpg",
    "x6_adult_stand_front_01.jpg": "8631792693106_.pic_hd.jpg",
    "x6_adult_lying_threequarter_01.jpg": "8641792693107_.pic_hd.jpg",
    "x6_adult_lying_head_01.jpg": "8551792693099_.pic_hd.jpg",
    "x6_adult_lying_face_01.jpg": "8561792693101_.pic_hd.jpg",
    "x6_adult_lying_onback_01.jpg": "8601792693104_.pic_hd.jpg",
    "x6_adult_lying_chin_down_01.jpg": "8611792693105_.pic_hd.jpg",
    # 以下两张在 _curated 里做过二次处理（去人 / 裁边），不在这张映射里
}


def is_dataless(p):
    try:
        return bool(os.lstat(p).st_flags & DATALESS)
    except OSError:
        return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()

    if not os.path.isdir(ALBUM):
        print("❌ 找不到相册目录：%s" % ALBUM)
        return 1

    print("相册：%s（%d 个文件）" % (ALBUM, len(os.listdir(ALBUM))))
    targets = []
    for dst_name, src_name in MAP.items():
        dst = os.path.join(CURATED, dst_name)
        src = os.path.join(ALBUM, src_name)
        if not os.path.exists(dst):
            continue
        if not is_dataless(dst):
            continue
        if not os.path.exists(src):
            print("  ⚠️ %-40s 源文件缺失：%s" % (dst_name, src_name))
            continue
        s_size = os.lstat(src).st_size
        # 精选文件被卸载时 size 仍是云端真实大小，可以直接比对
        d_size = os.lstat(dst).st_size
        if s_size != d_size:
            print("  ⚠️ %-40s 尺寸不符（相册 %d / 云端 %d），跳过——可能做过二次处理"
                  % (dst_name, s_size, d_size))
            continue
        targets.append((dst, src))

    if not targets:
        print("✅ 精选目录里没有被卸载的照片（或都已可读）")
    for dst, src in targets:
        print("  - %-40s ← %s" % (os.path.basename(dst), os.path.basename(src)))

    if args.check:
        print("\n（--check 模式，未还原）")
        return 0

    print("\n还原中…")
    ok = 0
    for dst, src in targets:
        try:
            os.chmod(dst, 0o644)
            shutil.copyfile(src, dst)          # 覆盖写，占位符会被替换成实体
            if is_dataless(dst):
                os.remove(dst)
                shutil.copyfile(src, dst)
            ok += 1
            print("  ✅ %-40s %d 字节" % (os.path.basename(dst), os.lstat(dst).st_size))
        except Exception as e:
            print("  ❌ %-40s %s" % (os.path.basename(dst), e))
    print("\n还原 %d / %d" % (ok, len(targets)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
