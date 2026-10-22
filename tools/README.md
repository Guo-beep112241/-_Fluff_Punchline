# tools/ — 自动化工具

## recover_h3_video.py

**用途**：H3 视频任务的一键取回。当 MiniMax 平台的「资产交付」环节（生成 → 后处理 → 打包成可下载文件）
故障时，视频在服务端已生成（`status: succeeded`）但拿不到文件。这个脚本把恢复动作变成一条命令。

**硬性安全边界**：

- 永远不会调用 `submit_video_generation`，不产生新任务、不消耗生成额度
- 只查询 `docs/video_tasks.json` 里已登记的 `task_id`
- 下载走 TLS 校验 + 跟随重定向，不用 `-k` 之类降级
- 先落 `<目标>.part`，校验通过才原子改名；校验失败删临时文件，**绝不交付半成品**
- 校验不通过时会保留旧文件不动（不破坏已有可用产物）

**用法**：

```bash
cd ~/Movies/Xiaoliuer

python3 tools/recover_h3_video.py            # 检查所有未完结任务
python3 tools/recover_h3_video.py --list     # 只看登记状态，不发任何请求
python3 tools/recover_h3_video.py --dry-run  # 查询并打印链接，但不下载
python3 tools/recover_h3_video.py --task-id 455207129047466
```

**退出码**：`0` = 取回成功或全部已是终态；`1` = 仍未取回（平台还没恢复）。

**校验做了什么**（本机没有 ffmpeg/ffprobe，所以用容器级判断）：

1. 文件体积 ≥ 1KB（低于此值一律判无效）
2. 第 4–8 字节等于 `ftyp`（ISO-BMFF 魔数，MP4/MOV 家族）
3. 容器内能找到 `moov` 或 `mdat` 盒
4. 用系统 `file` 命令复核，要求识别为 `ISO Media` / `QuickTime`

**状态回写**：脚本会自动更新 `docs/video_tasks.json` 里的
`last_query_at_ms` / `last_query_at_cst` / `last_error` / `delivery_retry_count` /
`terminal_status`（`delivered`）/ `delivered_file` / `delivered_bytes`。

**已知边界**：第 4 步只做容器级校验，不做逐帧解码校验。若要确认能正常播放，
下载后用剪映或 QuickTime 打开看一眼即可。
