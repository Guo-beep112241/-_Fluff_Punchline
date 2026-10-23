#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""mx — MiniMax connector 轻封装（TTS / 图片 / 视频 / 下载）

只做三件事：
  1. call <tool> --args <json>   调 connector，返回原始 JSON
  2. asset <node_id> <out_path>  取短链并下载到本地（含 TLS、原子落盘）
  3. tts / img / video           常用动作的便捷封装

不改动 00_原片/，所有产物由调用方指定路径。
"""
import argparse
import json
import os
import subprocess
import sys
import tempfile

MCODE = os.path.expanduser("~/.minimax/bin/mcode-tools")


def call(tool, args, timeout=900):
    fd, path = tempfile.mkstemp(suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(args, f, ensure_ascii=False)
        out = subprocess.run(
            [MCODE, "connector", "call", tool, "--args-file", path],
            capture_output=True, text=True, timeout=timeout,
        )
    finally:
        os.unlink(path)
    txt = (out.stdout or "").strip()
    try:
        return json.loads(txt)
    except Exception:
        return {"code": -1, "raw": txt[-2000:], "stderr": (out.stderr or "")[-1000:]}


def asset_url(node_id):
    out = subprocess.run([MCODE, "get-asset-url", str(node_id)],
                         capture_output=True, text=True, timeout=180)
    txt = (out.stdout or "").strip()
    try:
        doc = json.loads(txt)
    except Exception:
        raise RuntimeError("get-asset-url 失败: %s %s" % (txt[:400], out.stderr[-300:]))
    for k in ("url", "download_url", "temp_url", "asset_url"):
        if doc.get(k):
            return doc[k]
    if isinstance(doc.get("data"), dict):
        for k in ("url", "download_url", "temp_url", "asset_url"):
            if doc["data"].get(k):
                return doc["data"][k]
    raise RuntimeError("get-asset-url 无 url 字段: %s" % json.dumps(doc)[:400])


def download(url, out_path):
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    part = out_path + ".part"
    subprocess.run(["curl", "-fsSL", "--retry", "3", "--max-time", "900",
                    "-o", part, url], check=True)
    size = os.path.getsize(part)
    if size < 1024:
        os.unlink(part)
        raise RuntimeError("下载文件过小（%d 字节）：%s" % (size, out_path))
    os.replace(part, out_path)
    return size


def upload(path, mime=None):
    if mime is None:
        mime = "video/mp4" if path.lower().endswith((".mp4", ".mov")) else "image/jpeg"
    out = subprocess.run([MCODE, "upload-temp-url", path, "--mime-type", mime],
                         capture_output=True, text=True, timeout=600)
    doc = json.loads((out.stdout or "").strip() or "{}")
    url = doc.get("temp_url") or (doc.get("data") or {}).get("temp_url")
    if not url:
        raise RuntimeError("上传失败 %s: %s" % (path, (out.stdout or "")[-400:]))
    return url


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("call")
    p.add_argument("tool")
    p.add_argument("--args", default="{}")

    p = sub.add_parser("asset")
    p.add_argument("node_id")
    p.add_argument("out")

    p = sub.add_parser("tts")
    p.add_argument("text")
    p.add_argument("out")
    p.add_argument("--voice", default="male-qn-qingse")
    p.add_argument("--emotion", default="neutral")
    p.add_argument("--speed", type=float, default=1.0)
    p.add_argument("--pitch", type=int, default=0)

    p = sub.add_parser("img")
    p.add_argument("prompt")
    p.add_argument("out")
    p.add_argument("--ratio", default="9:16")
    p.add_argument("--res", default="1K")
    p.add_argument("--inputs", nargs="*", default=[])

    p = sub.add_parser("upload")
    p.add_argument("path")

    a = ap.parse_args()

    if a.cmd == "call":
        print(json.dumps(call(a.tool, json.loads(a.args)), ensure_ascii=False, indent=2))
        return 0

    if a.cmd == "asset":
        url = asset_url(a.node_id)
        n = download(url, a.out)
        print(json.dumps({"ok": True, "out": a.out, "bytes": n}, ensure_ascii=False))
        return 0

    if a.cmd == "upload":
        print(upload(a.path))
        return 0

    if a.cmd == "tts":
        r = call("connector__matrix__synthesize_speech", {
            "text": a.text, "voice_id": a.voice, "emotion": a.emotion,
            "speed": a.speed, "pitch": a.pitch,
            "output_file": os.path.basename(a.out),
        })
        if r.get("code") not in (0, None):
            print(json.dumps(r, ensure_ascii=False))
            return 1
        n = download(asset_url(r["node_id"]), a.out)
        print(json.dumps({"ok": True, "out": a.out, "bytes": n,
                          "node_id": r["node_id"]}, ensure_ascii=False))
        return 0

    if a.cmd == "img":
        req = {"prompt": a.prompt, "aspect_ratio": a.ratio, "resolution": a.res,
               "output_file": os.path.basename(a.out)}
        if a.inputs:
            req["input_urls"] = [upload(p) for p in a.inputs]
        r = call("connector__matrix__generate_image", {"requests": [req]})
        if r.get("code") not in (0, None):
            print(json.dumps(r, ensure_ascii=False))
            return 1
        item = (r.get("success_items") or [{}])[0]
        n = download(asset_url(item["node_id"]), a.out)
        print(json.dumps({"ok": True, "out": a.out, "bytes": n,
                          "node_id": item["node_id"]}, ensure_ascii=False))
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
