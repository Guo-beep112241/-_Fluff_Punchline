# ep01 / 验证镜 V2（3/4 侧脸口播 · 🟡 中风险）

> 第 0 批 · 技术验证，不占任何一集。三镜场景/灯光/角色状态/台词一致，**唯一变量 = 脸朝向 + 嘴部遮挡 + lip-sync 措辞**。

## 生成参数
- 模型：MiniMax-H3 ｜ 模式：Ref2VA（多模态参考）
- 时长：5 秒 ｜ 画幅：9:16 ｜ 分辨率：768P（试错）

## 参考素材（按上传顺序编号）
目录：`10_工作素材/characters/_curated/adult/`
- `<Picture 1>` → `x6_adult_face_front_sharp_01.jpg` — 职责：**脸型五官基准**（与 V1 同图同职责）。
- `<Picture 2>` → `x6_adult_lying_threequarter_01.jpg` — 职责：**3/4 侧头脸轮廓与转向角度**。
- `<Picture 3>` → `x6_adult_lying_full_02.jpg` — 职责：**趴卧全身比例与毛色**。

> **V2 不喂低头/遮挡参考图**（那是 V3 的变量）。**场景无实景参考照**，为**虚构**宿舍地板，仅文字描述。

## 提示词（可直接提交）
```
subject_definitions:
<Subject 1>: is the young white Samoyed dog in <Picture 1>, <Picture 2> and <Picture 3> - the same individual dog in every picture. From <Picture 1>, fully preserved. From <Picture 2>, fully preserved. From <Picture 3>, fully preserved. <Subject 1> has a rounded soft puppy-like head with a broad round forehead, large round dark brown eyes set wide apart, a short broad muzzle, a large round black nose, small triangular ears held slightly outward, a medium-length soft pure white coat that lies flat and even, pink tongue lolling out. The ears are small and neat: small, neat triangular ears that sit close to the head, slightly folded forward at the tips, not large erect pointed ears and not big upright ears. The coat is clean pure white, not cream and not yellow; only the inner ears, the muzzle and the belly carry a faint warm tint. Its chest fur is light, smooth and evenly spread, with no thick ruff and no mane. Its build is slim and youthful, with a narrow chest, a visible gap between the front legs, slender legs and slightly oversized paws; the front and hind paws turn slightly outward from the midline, a very subtle toe-out, with the hind feet splayed only a little. The expression is open, young, earnest and a little eager, never majestic, proud, dignified or stern.

summary:
[reference generation] A technical lip-sync test shot. The same young white Samoyed lies on a plain fictional dormitory floor in front of a low camera, lifts its head and turns it about forty-five degrees away from the lens while it speaks one short Mandarin line, so the mouth shapes can be checked frame by frame.

retention_analysis:
<Subject 1> (appears in [Shot 1]): fully_preserved - the same individual dog, keeping the rounded soft head with the broad round forehead, the large round dark brown eyes set wide apart and held wide open, the short broad muzzle, the large round black nose, the small neat triangular ears that sit close to the head and fold slightly forward at the tips, the medium-length soft pure white coat that lies flat and even, the light unclumped chest fur, and the slim youthful build with a narrow chest, a visible gap between the front legs and slender legs.

detailed_description:
The target video is in realistic photographic style. The dog is the same individual white Samoyed as in the reference pictures, not the exaggerated show-dog version of the breed. Its fur is soft, medium-length and lies flat along the body, not a heavy double coat; the neck and chest carry no thick ruff and no lion-like mane; the chest hair is light and evenly spread instead of clumped; the head is round and soft, not a broad sharp wedge; the eyes are round and wide open, not narrow and almond-shaped; the muzzle is short and broad, not a long snout; the body is slim with a narrow chest and a clear gap of daylight between the front legs, not stocky. The coat is clean pure white, not cream, not beige and not yellow; only the inner ears, the muzzle and the belly carry a faint warm tint. Its ears are small, neat triangular ears that sit close to the head, slightly folded forward at the tips, not large erect pointed ears and not big upright ears. The expression is open, young and earnest, never majestic, proud, dignified or stern. No heavy body volume, no fluffy chest mane, no rigid symmetrical stance.
[Shot 1] [Medium close-up, low camera at the dog's eye level, the head and upper chest filling the frame, the front paws just inside the bottom edge], [static locked camera, no camera movement]. A plain, generic, fictional dormitory floor: pale laminate floor, a blank off-white wall behind, a metal bed leg and a dark backpack blurred far in the background, no readable text or signage. Soft, even, neutral daylight fills the frame from a window off-frame to the left, no colour cast, with a soft shadow under the chest and paws. <Subject 1> lies on the floor in a sphinx pose in the centre of the frame, chest up, front paws stretched forward, hind legs stretched out behind, tail along the floor, and never changes spot during the shot. A thick, messy stack of loose white printed pages lies on the floor directly in front of its front paws, one black marker pen lying crosswise on top; the print is unreadable. <Subject 1> raises its head off the floor and turns it about forty-five degrees toward the left side of the frame, so the camera sees the right side of its face in three-quarter view: one eye fully visible, the other partly turned away, the short broad muzzle pointing across the frame instead of at the lens. The open mouth stays visible but is angled away from the camera. <Subject 1> speaks in a natural human teenage male voice, the mouth moves with the words; the jaw works through clean rounded open-and-close shapes, the lips part and close with the sound, the pink tongue shows between them. The eyes glance towards the camera while the head stays turned, the body stays still, and the line ends with the mouth still slightly open.
<Subject 1> (S1) speaks: <d>[Chinese] 相声讲究说学逗唱。</d>

overall_soundscape:
Quiet indoor room tone with faint air movement. Soft padding paw sounds on the laminate floor. Light rustle of loose paper and a small scrape of a pen on the floor. Soft panting of a young dog close to the microphone. A light collar jingle.

non_diegetic_music:
None.
```

## 变更记录
- v1 2026-10-23 初稿 · 第 0 批口型验证镜 V2（🟡 3/4 侧脸口播）

## 试错记录
<!-- 每轮生成后回填。只能改一个变量。 -->

| 轮次 | 唯一改动 | 看什么 |
|---|---|---|
| B1 | 基线生成 | 侧脸口型是否对上 8 字；舌头犬齿是否糊；是否中文人声 |
| B2 | 只把 `forty-five degrees` 改 `sixty degrees` | 转头角度对嘴部可见度的影响 |
| B3 | 只改音色（加 `young, light, boyish`） | 与 V1 同口径对比音色 |

**风险点**：`x6_adult_lying_threequarter_01.jpg` 实为**趴卧** 3/4 照（索引标「站」，实拍趴着），与本镜状态一致可用；狗被压更低则换 `x6_adult_face_threequarter_01.jpg`。
