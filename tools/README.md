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

---

## prep_side_back_photos.py

**用途**：把新拍的两张成年照片（侧面 / 背面）里的人物清掉，产出可用的定妆参考照。

| 源文件 | 人 | 处理 |
|---|---|---|
| `8811792749790_.pic.jpg`（侧面） | 恒姐的手搭在狗肩背上 | 裁掉右侧（x≥778）→ 对手的包围盒做**拉普拉斯扩散修补** → 778×800 |
| `8821792749790_.pic.jpg`（背面） | 手臂 + 一条腿在画面最右缘 | 从右侧整条裁掉（原图 x≥730）→ 505×835 |

**原片只读**：只读 `_incoming/adult/`，所有产物写到 `_curated/adult/`，原件不动。

**为什么用扩散修补而不是贴图**：试过「取一块附近的毛 + 羽化贴上去」，
换四种取样源都能看出矩形接缝；而且羽化遮罩如果用「大半径高斯模糊」做，
中心值只有 220/255，合成后是半透明叠加 —— 手只被淡化、没被替换。
拉普拉斯扩散把待删区域按周边已知像素平滑地"长"出来，无接缝、无方块感。

```bash
cd ~/Movies/Xiaoliuer
~/XiaoliuerVideoGen/venv/bin/python tools/prep_side_back_photos.py
```

> 需要 numpy（本机在 `~/XiaoliuerVideoGen/venv`），不需要 opencv。

---

## make_fullbody_refsheet.py

**用途**：把 6 张真实素材拼成一张竖版「全身定妆照」参考图。

格子：正面全身 / 3-4 侧全身 / 正侧全身 / 背面·尾与后腿 / 脸部（定妆版 v1）/ 坐姿。

- 第 5 格取自 **H3 定妆视频 v1** 抽帧（用户已确认用这个脸），做了白平衡校正去掉 v1 的偏黄，**脸型结构不动**
- 输出 `20_生成结果/ep01/reference/x6_adult_fullbody_refsheet.jpg`（1080×3168）

```bash
cd ~/Movies/Xiaoliuer
~/XiaoliuerVideoGen/venv/bin/python tools/make_fullbody_refsheet.py
```

> 依赖 `prep_side_back_photos.py` 的产出，**先把照片处理干净再跑这个**。

---

## 其他脚本

| 脚本 | 用途 |
|---|---|
| `make_char_reel.py` | 成年照片 → 静态参考卷轴（给模型看，无字幕） |
| `make_behavior_reel.py` | 幼犬行为模组 → 动态参考卷轴 |
| `triage_puppy_videos.py` | 幼犬原始视频批量抽帧，人物/可用性初判 |
| `triage_puppy_videos_dense.py` | 对候选段做加密抽帧复核 |
| `cut_behavior_clips.py` | 按时间点剪出 7 个行为模组片段 |

---

## 通用约定

1. **原片只读** —— 所有脚本只读 `00_原片/` 和 `_incoming/`，产物一律写到 `_curated/` 或 `20_生成结果/`
2. **文件名自我表意** —— `x6_adult_<姿态>_<序号>` / `x6_puppy_<行为>_<序号>`
3. **写状态的脚本先在临时副本验证** —— 改 `docs/video_tasks.json` 之类会读写的脚本，
   先在 `/tmp` 副本上用 mock 跑通成功与失败两条路径，再碰真实文件
4. **iCloud 项目目录上不要跑 `git status` / `git ls-files`** —— 会全量扫描工作树，
   被卸载的文件会让它永久挂起。用 `git add -A` + `git diff-index --name-status HEAD` + `git ls-tree -r --name-only HEAD`。
   修复脚本：`~/XiaoliuerVideoGen/scripts/git_icloud_repair.py`
