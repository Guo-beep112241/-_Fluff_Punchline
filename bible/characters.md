# 角色圣经 — 小六二

> 最后更新：2026-10-23 17:30　｜　状态：**真实照片版**（依据 30 张实拍照片逐张判读后重写）
> 特征词来源：`_curated/adult/` 14 张精选实拍照
> 判读记录：`docs/asset_index_adult.csv`

---

## 小六二 · 成年

**参考图**（H3 Ref2VA，按上传顺序编号）：
| 编号 | 文件 | 职责 |
|---|---|---|
| `<Picture 1>` | `x6_adult_stand_front_01.jpg` | 全身正面站立（体型 / 四肢 / 脸） |
| `<Picture 2>` | `x6_adult_face_front_sharp_01.jpg` | 面部正面特写（五官） |
| `<Picture 3>` | `x6_adult_stand_threequarter_01.jpg` | 全身 3/4 侧 |
| `<Picture 4>` | `x6_adult_stand_side_01.jpg` | 全身正侧 |
| `<Picture 5>` | `x6_adult_face_threequarter_01.jpg` | 面部 3/4 侧 |

### 外形特征词（提示词里逐字复用，不要用同义词替换）

```
a rounded soft puppy-like head with a broad round forehead,
large round dark brown eyes set wide apart,
a short broad muzzle, a large round black nose,
small triangular ears held slightly outward,
a medium-length soft pure white coat that lies flat and even,
pink tongue lolling out
```

### 关键判据（每条都对应一次翻车）

| 判据 | 说明 | **必须避免的写法** |
|---|---|---|
| **头是圆的** | 额头宽而圆，颅骨圆钝，没有楔形收窄 | ❌ `wedge-shaped head` / `broad wedge` / `muzzle` 尖瘦 |
| **眼睛大而圆** | 深棕近黑、眼距宽，眼神幼态，**睁圆** | ❌ `almond-shaped eyes` / `narrow eyes` / `sharp gaze` |
| **口鼻短而宽** | 鼻梁短，嘴部宽厚 | ❌ `long snout` / `refined muzzle` |
| **毛量适中、服帖** | 中等长度、微微蓬松、顺着身体躺平 | ❌ `dense double-coat` / `thick fur` / `heavy ruff` / `fluffy mane` / `voluminous` |
| **前胸毛平顺** | 胸毛轻薄均匀，不结团、不起鬃 | ❌ `thick chest ruff` / `lion-like mane` / `clumped chest fur` |
| **毛色是白，不是米黄** ⚠️ | 主体是**纯白**；只有耳内、口鼻、腹部有一点点暖奶油色 | ❌ `creamy-white` / `cream-coloured` / `beige` / `ivory` —— v1 写成 creamy，结果整只狗偏黄 |
| **体型偏瘦窄胸** | 胸窄、**两前腿之间有缝**、腿细长、爪子略大 | ❌ `stocky` / `broad chest` / `massive` / `powerful build` / `thick legs` |
| **站姿松垮微前倾** | 重心偏一边、**一只前爪略外撇**、头略低，不是四腿笔直 | ❌ `standing squarely` / `rigid posture` / `alert stance` / `proud pose` |
| **气质幼态活泼** | 好奇、亲人、玩心重、有点急切 | ❌ `majestic` / `proud` / `dignified` / `regal` / `serious` / `stately` |
| **标志表情** | 嘴张开、粉色舌头伸出 | ❌ `closed mouth` / `serious expression` |
| **轻微外八** ⚠️ | 站立与行走时，**前后脚掌都略微朝外撇**（从正面看前脚外翻、从背面看两只后脚明显外撇）。**只是轻微**，不是明显的外八 | ❌ `toes pointing straight forward` / `feet parallel` / ❌ `wide bow-legged stance` / `exaggerated splay` |

> **外八的准确描述**（这是小六二的招牌体态，生成运动镜头必须写进去）：
> `the front and hind paws turn slightly outward from the midline, a very subtle toe-out, with the hind feet splayed only a little`
> 强调「轻微」：`the splay is very slight and natural, not a wide bow-legged stance`
>
> **证据**：2026-05-01 天台新拍的两张（`x6_adult_stand_side_full_02` 侧面 / `x6_adult_stand_back_01` 背面）
> 都能清楚看到后脚外撇。侧面照尤其明显：两只前脚掌都略微朝外。
>
> ⚠️ **外八是容易被忽略的部位** —— 不写模型就默认「标准平行站姿」，
> 生成出来的小六二会显得很规矩、很假。

### 已确认项

| 项 | 结论 |
|---|---|
| **最终定妆脸部** | **H3 定妆视频 v1 的脸**（task `455456579522981`）—— 用户 2026-10-23 17:55 确认「很像了，最终定妆就用这个脸部样子」。已抽帧存 `10_工作素材/_work/v1_face_frame_white.jpg`（做过白平衡校正去掉 v1 偏黄的问题，**脸型结构未动**） |
| **毛色** | **纯白**。2026-05-01 天台户外照在自然光下确认为白色 → 印证 v1 偏黄是提示词误写 `creamy-white` 所致，v2 已改为 `pure white` |
| **真实毛量** | 背部和侧面毛**蓬松但服帖**，长度中等；不是 v0 那种炸开的浓密双层毛，也没有鬃毛团 |
| **真实体型** | 偏瘦长、胸薄、腿修长；从侧面看躯干长、四肢修长，不是厚重敦实的标准萨摩耶 |
| **尾巴** | 极大、蓬松、竖起，尾毛很长；从正后方看几乎挡住整个身体 |
| **轻微外八（已生成验证）** | **H3 v3 定妆视频（task `455465099944357`）已成功生成出轻微外八**：四只脚掌的脚趾都能看到略微向外张，但没有变成罗圈腿。走路镜头的步态自然、四爪着地 |
| **耳朵（⚠️ 未解决）** | v2/v3 生成出来的耳朵**比真实小六二大一些、立得更开**（真实小六二耳朵更小、更贴、尖端略向前折）。v4 提示词需补：`small, neat triangular ears that sit close to the head, slightly folded forward at the tips`，并否定 `large erect pointed ears` / `big upright ears` |
| **毛色定量基准** | 额头毛 R−B：真实照片 +14.2 / H3 v2 +19.7 / H3 v3 +17.4 → **v3 没有比 v2 更黄**，暖偏主要来自场景灯光（暖色窗帘 + 木地板），不是提示词回退 |

> **根因说明**：生成模型对「萨摩耶」有很强的品种先验 —— 浓密双层毛、宽楔形头、杏仁眼、威严感。
> 真实小六二几乎每一条都与之相反。所以提示词里**必须显式反向描述**，
> 只靠参考图不够，文字要正面按压住品种先验。
>
> **v1 的教训**：`creamy-white` 这个词是我从占位图沿用的，结果整只狗发黄。
> 特征词必须**逐条从真实照片核对**，不能凭印象写近义描述。

### 性格档案（待补）

真实的性格档案来自日常视频 —— 怎么表达高兴、怎么表达不满、有没有招牌动作：

- 表达高兴：_待补_（幼犬视频里已知：吐舌头、歪头、跑向镜头、叼东西走）
- 表达不满：_待补_
- 招牌动作：_待补_

---

## 小六二 · 幼犬

**当前素材**：幼犬时期真实视频 34 段（`00_原片/_待整理/幼犬时期/`），
已剪出 7 段行为模组（`10_工作素材/habits/_curated/`）。

**参考图**：幼犬期**没有照片**，只有视频。
若要生成幼犬镜头，参考输入用视频片段（`reference_videos`）而非图片。

### 与成年的关键差异（成长线靠这个区分）

| 部位 | 成年 | 幼犬 |
|---|---|---|
| 脸 | 圆但轮廓明确 | 更圆、更扁 |
| 眼 | 大圆眼 | 更大更圆，眼距更宽 |
| 耳 | 小三角立起 | 尚未立起、低垂 |
| 毛 | 中等长度服帖 | 更蓬松更稀 |
| 体型 | 偏瘦、四肢修长 | 紧凑圆滚、腿短 |
| 鼻 | 大而黑 | 相对小 |

### 待补

幼犬期真实照片到位后，重写本节并补幼犬定妆图。
