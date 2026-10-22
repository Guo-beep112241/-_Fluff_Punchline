#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
H3 视频任务取回工具（只读查询 + 原子下载）

用途：MiniMax 平台的「资产交付」环节（生成 → 后处理 → 打包成可下载文件）故障时，
视频在服务端已生成但取不回。本脚本按 write-h3-prompts 技能的
「查询已有任务 → 原子下载 → 校验 → 改名 → 落盘状态」规范，把恢复动作变成一条命令。

安全边界（重要）：
  * 本脚本【永远不会】调用 submit_video_generation，不会产生任何新任务、不消耗额度。
  * 它只查询 docs/video_tasks.json 里已登记的 task_id。
  * 下载走 TLS 校验 + 跟随重定向，不使用 -k 之类的降级。
  * 校验不通过就删掉 .part 临时文件，绝不把半成品当成交付。

用法：
    python3 tools/recover_h3_video.py                  # 检查所有未完结任务
    python3 tools/recover_h3_video.py --task-id 455207129047466
    python3 tools/recover_h3_video.py --list           # 只看登记状态，不查询

退出码：0 = 至少交付了一个视频；1 = 仍未取回（平台还没恢复）
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
TASKS_JSON = PROJECT_ROOT / "docs" / "video_tasks.json"
QUERY_TOOL = "connector__matrix__query_video_generation"

# 视频文件最小合理体积（字节）。低于此值一律视为无效，避免交付空壳。
MIN_MP4_BYTES = 1024
USER_AGENT = "Xiaoliuer-H3-Recovery/1.0"


# ---------------------------------------------------------------- 工具函数

def log(msg):
    print(msg, flush=True)


def now_ms():
    return int(time.time() * 1000)


def cst_stamp():
    return time.strftime("%Y-%m-%d %H:%M:%S CST", time.localtime())


def run_query(task_id, model):
    """调用 Connector 查询已有任务。返回 (parsed_dict, raw_stdout)。"""
    args = json.dumps({"task_id": str(task_id), "model": model}, ensure_ascii=False)
    cmd = ["mcode-tools", "connector", "call", QUERY_TOOL, "--args", args]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    except FileNotFoundError:
        return None, "找不到 mcode-tools 命令（不在 PATH 上）"
    except subprocess.TimeoutExpired:
        return None, "查询超时（300s）"

    raw = (proc.stdout or "").strip()
    err = (proc.stderr or "").strip()
    if proc.returncode != 0:
        return None, (err or raw or "查询返回非零退出码 %d" % proc.returncode)

    # stdout 里可能夹带非 JSON 行，取最后一个能解析成对象的 JSON 文本段
    for line in reversed(raw.splitlines()):
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            return json.loads(line), None
        except json.JSONDecodeError:
            continue
    return None, raw or err or "无法从响应中解析 JSON"


def extract_download_url(payload):
    """从查询响应里找下载链接。字段名不固定，按多个候选键找第一个 https URL。"""
    candidates = ("download_url", "video_url", "file_url", "url", "download_url_list")
    stack = [payload]
    seen = set()
    while stack:
        node = stack.pop()
        if isinstance(node, dict):
            for key, value in node.items():
                if key in candidates and isinstance(value, str) and value.startswith("http"):
                    return value
                if isinstance(value, (dict, list)):
                    stack.append(value)
                elif key in candidates and isinstance(value, list):
                    stack.append(value)
        elif isinstance(node, list):
            for item in node:
                if isinstance(item, (dict, list)):
                    stack.append(item)
        elif isinstance(node, str) and node.startswith("http") and node not in seen:
            seen.add(node)
    return None


def validate_mp4(path):
    """校验：非空 + ISO-BMFF 魔数 + 含 moov/mdat 盒 + file 命令复核。"""
    problems = []
    try:
        size = path.stat().st_size
    except OSError as exc:
        return False, ["无法读取文件：%s" % exc], 0

    if size < MIN_MP4_BYTES:
        problems.append("文件过小（%d 字节，低于 %d），视为无效" % (size, MIN_MP4_BYTES))
        return False, problems, size

    try:
        with open(path, "rb") as handle:
            head = handle.read(16)
            handle.seek(0)
            data = handle.read()
    except OSError as exc:
        return False, ["读取失败：%s" % exc], size

    if head[4:8] != b"ftyp":
        problems.append("缺少 ISO-BMFF 魔数 ftyp（前 12 字节 = %r）" % head[:12])
    else:
        log("        brand = %s" % head[8:12].decode("ascii", "replace").strip())

    if b"moov" not in data and b"mdat" not in data:
        problems.append("未找到 moov/mdat 盒，可能不是完整的视频容器")

    if shutil.which("file"):
        try:
            described = subprocess.run(
                ["file", "-b", str(path)], capture_output=True, text=True, timeout=60
            ).stdout.strip()
            log("        file = %s" % described)
            if described and "ISO Media" not in described and "QuickTime" not in described:
                problems.append("file 命令未识别为 ISO/QuickTime 容器：%s" % described)
        except (subprocess.SubprocessError, OSError) as exc:
            log("        file 命令复核跳过：%s" % exc)

    return (not problems), problems, size


def download(url, dest_part):
    """带 TLS 校验、跟随重定向地下载。失败抛异常。"""
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=600) as response:
        final_url = response.geturl()
        with open(dest_part, "wb") as handle:
            shutil.copyfileobj(response, handle, length=1024 * 256)
    return final_url


def save_tasks(doc):
    """写回完整文档（必须保留外层 {"tasks": {...}} 包装层）。"""
    tmp = TASKS_JSON.with_name(TASKS_JSON.name + ".tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, TASKS_JSON)


# ---------------------------------------------------------------- 主流程

def handle_task(task_id, record, dry_run=False):
    model = record.get("model")
    out_rel = record.get("output_file")
    if not model or not out_rel:
        log("  [!] 登记记录不完整（缺 model 或 output_file），跳过")
        return False

    log("  查询 task_id = %s / model = %s" % (task_id, model))
    payload, error = run_query(task_id, model)
    if payload is None:
        record["last_error"] = "查询失败：%s" % error
        record["delivery_retry_count"] = int(record.get("delivery_retry_count", 0)) + 1
        record["last_query_at_ms"] = now_ms()
        record["last_query_at_cst"] = cst_stamp()
        log("  [x] 查询失败：%s" % error)
        return False

    code = payload.get("code")
    status = payload.get("status")
    message = payload.get("message", "")
    log("  响应：code=%s status=%s" % (code, status))

    record["last_query_at_ms"] = now_ms()
    record["last_query_at_cst"] = cst_stamp()

    url = extract_download_url(payload)
    if code != 200 or status != "succeeded" or not url:
        record["last_error"] = "code=%s status=%s — %s" % (code, status, message)
        record["delivery_retry_count"] = int(record.get("delivery_retry_count", 0)) + 1
        log("  [x] 仍未取回：%s" % message)
        return False

    if dry_run:
        log("  [dry-run] 拿到下载链接，未下载：%s" % url)
        return False

    final_path = PROJECT_ROOT / out_rel
    final_path.parent.mkdir(parents=True, exist_ok=True)
    part_path = final_path.with_suffix(final_path.suffix + ".part")

    log("  下载 → %s" % part_path.name)
    try:
        download(url, part_path)
    except Exception as exc:  # noqa: BLE001 - 网络异常种类多，统一记录
        record["last_error"] = "下载失败：%s" % exc
        if part_path.exists():
            part_path.unlink()
        log("  [x] 下载失败：%s" % exc)
        return False

    ok, problems, size = validate_mp4(part_path)
    if not ok:
        part_path.unlink()
        record["last_error"] = "校验不通过：" + "；".join(problems)
        log("  [x] 校验不通过：%s" % "；".join(problems))
        return False

    os.replace(part_path, final_path)
    record["terminal_status"] = "delivered"
    record["delivered_at_cst"] = cst_stamp()
    record["delivered_file"] = str(final_path)
    record["delivered_bytes"] = size
    record["last_error"] = ""
    log("  [OK] 交付成功：%s（%.1f MB）" % (out_rel, size / 1024 / 1024))
    return True


def main():
    parser = argparse.ArgumentParser(description="取回已提交的 H3 视频任务产物")
    parser.add_argument("--task-id", help="只处理指定 task_id（默认处理全部未完结任务）")
    parser.add_argument("--list", action="store_true", help="只打印登记状态，不查询")
    parser.add_argument("--dry-run", action="store_true", help="查询但不下载")
    args = parser.parse_args()

    if not TASKS_JSON.exists():
        log("找不到任务登记文件：%s" % TASKS_JSON)
        return 2

    tasks = json.loads(TASKS_JSON.read_text(encoding="utf-8")).get("tasks", {})
    if not tasks:
        log("登记文件里没有任务")
        return 2

    doc = {"tasks": tasks}

    if args.list:
        for task_id, record in tasks.items():
            log("%s  %-30s  %s  最后查询 %s" % (
                task_id, record.get("model", "?"),
                record.get("terminal_status", "?"),
                record.get("last_query_at_cst", "?")))
        return 0

    targets = [args.task_id] if args.task_id else list(tasks.keys())
    delivered_any = False
    changed = False
    skipped = 0

    for task_id in targets:
        record = tasks.get(task_id)
        if record is None:
            log("[!] 未登记的 task_id：%s" % task_id)
            continue
        if not args.task_id and record.get("terminal_status") in ("delivered", "timed_out", "failed"):
            log("[skip] %s 已是终态（%s）" % (task_id, record.get("terminal_status")))
            skipped += 1
            continue

        log("\n=== task %s ===" % task_id)
        if handle_task(task_id, record, dry_run=args.dry_run):
            delivered_any = True
        changed = True

    if changed and not args.dry_run:
        save_tasks(doc)
        log("\n已更新 %s" % TASKS_JSON)

    if delivered_any:
        log("\n结果：至少一个视频已取回并落地。")
        return 0
    if skipped and not changed:
        log("\n结果：所有任务都已是终态，无需再取回。")
        return 0
    log("\n结果：仍未取回。平台资产交付环节尚未恢复，请稍后再跑本脚本。")
    return 1


if __name__ == "__main__":
    sys.exit(main())
