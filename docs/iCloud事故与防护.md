# iCloud 事故复盘与防护措施

> 2026-10-23 00:42–00:51 发生并已修复。这份文档记录**发生了什么、为什么会发生、现在怎么防护**。

---

## 一、发生了什么

用户把 `~/Movies` 移入了 iCloud Drive（macOS 的「本机迁移」机制）。移动后出现了三个问题：

| 现象 | 后果 |
|---|---|
| `~/Movies/Xiaoliuer` 变成一个**全新的空目录**，与云端副本 inode 不同 | 本地与云端成了两份独立数据，**云端被本地覆盖 = 那份文件永久消失** |
| 本地副本的 `.git/` 被 iCloud **整个删除** | 提交历史丢失（当时本地只有 1 次提交，已从云端找回） |
| 6 个**空目录**消失（`00_原片`、`20_生成结果`、`episodes` 等） | iCloud 不同步空文件夹，目录树被削平 |

**数据损失评估**：内容文件 **零丢失**。11 个内容文件全部存活；2 个关键 `.md`（`项目手册.md`、`制作方案.md`）和完整 git 提交 `ae9a309` 在云端副本中完好，已全部恢复。

---

## 二、为什么会发生

### 根因一：iCloud 的「本机迁移」会重建本地目录

`~/Movies` 被移进 `本机迁移/Movies` 后，macOS 在原位置重建了一个**空的新 `~/Movies`**。此后我写入 `~/Movies/Xiaoliuer/...` 的文件落进的是这个新目录，**与云端那份毫无关系**。

危险在于：如果 iCloud 接着把新目录上传，它会认为云端那些文件「本地已删除」，从而**把云端版本也删掉**。这正是数据分叉的典型死法。

### 根因二：`.git` 目录在 iCloud 里是危险的

`.git` 由大量小二进制对象文件组成，正好撞上 iCloud 的两个已知问题：

- iCloud 会把整个 `.git` 目录当成可清理对象删除
- 即使没删，`.git/objects` 里的对象被「释放资源」变成 `dataless` 占位符时，`git add` / `git fetch` 会直接 `fatal: mmap failed: Operation timed out`

**结论：在 iCloud 同步的目录里跑 git，本来就是个雷。**

### 根因三：空目录不参与同步

iCloud Drive 不存空目录。目录里没文件 → 同步时整棵子树消失。

---

## 三、现在的架构（已修复）

```
~/Movies/Xiaoliuer                                    → 符号链接
   └──► ~/Library/Mobile Documents/com~apple~CloudDocs/本机迁移/Movies/Xiaoliuer
                                                     ↑ 唯一真相源，在 iCloud 里
        ├── 00_原片/ 10_工作素材/ 20_生成结果/ …      （含 .gitkeep，不会再消失）
        ├── bible/ docs/ episodes/ prompts/
        └── .git  ──►  ~/.minimax/git-repos/xiaoliuer  ← 纯本地，iCloud 管不到
```

### 三条防护

**1. 单一真相源 + 符号链接**
`~/Movies/Xiaoliuer` 现在是符号链接，指向 iCloud 里的真实目录。
- 访达、终端、剪映照旧用 `~/Movies/Xiaoliuer`，路径不变
- 4 个 Agent 的 `default_workspace_dir` **一个字都不用改**（它们指向的是那个短路径）
- 不存在「本地一份云端一份」的分叉

**2. git 元数据完全迁出 iCloud**
`.git` 是个文本指针文件，真实数据在 `~/.minimax/git-repos/xiaoliuer`（纯本地，134 GB 空间充足）。
iCloud 永远碰不到它，git 也不会再 mmap 超时。

**3. 空目录补 `.gitkeep`**
每个结构性空目录里放一个 `.gitkeep`，让 iCloud 有东西可同步，目录树就不会被削平。

---

## 四、当前状态

```
提交历史：
  36d6b40  gitignore：忽略本地旧副本目录
  ef40ba7  占位素材 + 索引 + 角色圣经
  ae9a309  初始化：小六二短剧项目      ← 原始提交，从云端找回
```

- 40 个文件全部就位，工作区干净
- 本地磁盘从 55 GB 回到 **134 GB**（iCloud 迁移释放了空间）
- `~/Movies/Xiaoliuer_旧本地副本_可删/` 是迁移前的本地副本，内容已全部并入云端，**确认无误后可删**

---

## 五、以后要注意的

**别在 iCloud 目录里 `git init`。** 任何时候要在一个 iCloud 管理的文件夹里用 git，都用分离式：

```bash
git init --separate-git-dir=~/.minimax/git-repos/<项目名> <工作目录>
```

**别在同一路径下并行写本地和云端。** 如果发现 `~/Movies/Xiaoliuer` 变成了真实目录而不是符号链接，先查 `ls -ld` 的真实路径。

**空目录随时可能消失。** 结构目录里放 `.gitkeep`。

**iCloud 迁移前，先把项目里的东西备份一份。** 这次是运气好，云端恰好有完整副本。

---

## 六、踩过的坑（可复用的技术细节）

```bash
# 判断某文件是否被 iCloud「释放资源」（dataless 占位符）
python3 -c "import os; print(bool(os.lstat(p).st_flags & 0x40000000))"
```

```bash
# 批量驱逐用目录级调用，不要逐文件（逐文件会写大量失败记录，反而拖慢同步）
brctl evict ./某个目录
```

```bash
# 触发 iCloud 物化被释放的文件：直接读即可，brctl download 无效
cat <file> > /tmp/x
```

**注意**：`~/GitHub` 本身是 iCloud 的符号链接，不能拿来放 git 元数据。
