# ep01 / 验证镜 V1（正面口播 · 🔴 高风险）

> 第 0 批 · 技术验证，不占任何一集。三镜场景/灯光/角色状态/台词一致，**唯一变量 = 脸朝向 + 嘴部遮挡 + lip-sync 措辞**。

## 生成参数
- 模型：MiniMax-H3 ｜ 模式：Ref2VA（多模态参考）
- 时长：5 秒 ｜ 画幅：9:16 ｜ 分辨率：768P（试错）

## 参考素材（按上传顺序编号）
目录：`10_工作素材/characters/_curated/adult/`
- `<Picture 1>` → `x6_adult_face_front_sharp_01.jpg` — 职责：**脸型五官与嘴部**（圆头、大圆眼、短宽口鼻、大黑鼻、张开的嘴与粉舌）。
- `<Picture 2>` → `x6_adult_lying_full_02.jpg` — 职责：**趴卧全身比例与毛色**（窄胸、细长腿、蓬松尾巴、纯白毛）。

> **V1 只用 2 张**：不引入 3/4 侧或低头/遮挡参考图——那正是待测变量。**场景无实景参考照**，为**虚构**宿舍地板，仅文字描述。

## 提示词（可直接提交）
```
subject_definitions:
<Subject 1>: is the young white Samoyed dog in <Picture 1> and <Picture 2> - the same individual dog in every picture. From <Picture 1>, fully preserved. From <Picture 2>, fully preserved. <Subject 1> has a rounded soft puppy-like head with a broad round forehead, large round dark brown eyes set wide apart, a short broad muzzle, a large round black nose, small triangular ears held slightly outward, a medium-length soft pure white coat that lies flat and even, pink tongue lolling out. The ears are small and neat: small, neat triangular ears that sit close to the head, slightly folded forward at the tips, not large erect pointed ears and not big upright ears. The coat is clean pure white, not cream and not yellow; only the inner ears, the muzzle and the belly carry a faint warm tint. Its chest fur is light, smooth and evenly spread, with no thick ruff and no mane. Its build is slim and youthful, with a narrow chest, a visible gap between the front legs, slender legs and slightly oversized paws; the front and hind paws turn slightly outward from the midline, a very subtle toe-out, with the hind feet splayed only a little. The expression is open, young, earnest and a little eager, never majestic, proud, dignified or stern.

summary:
[reference generation] A technical lip-sync test shot. The same young white Samoyed lies on a plain fictional dormitory floor in front of a low camera, lifts its head and looks straight into the lens while it speaks one short Mandarin line, so the mouth shapes can be checked frame by frame.

retention_analysis:
<Subject 1> (appears in [Shot 1]): fully_preserved - the same individual dog, keeping the rounded soft head with the broad round forehead, the large round dark brown eyes set wide apart and held wide open, the short broad muzzle, the large round black nose, the small neat triangular ears that sit close to the head and fold slightly forward at the tips, the medium-length soft pure white coat that lies flat and even, the light unclumped chest fur, and the slim youthful build with a narrow chest, a visible gap between the front legs and slender legs.

detailed_description:
The target video is in realistic photographic style. The dog is the same individual white Samoyed as in the reference pictures, not the exaggerated show-dog version of the breed. Its fur is soft, medium-length and lies flat along the body, not a heavy double coat; the neck and chest carry no thick ruff and no lion-like mane; the chest hair is light and evenly spread instead of clumped; the head is round and soft, not a broad sharp wedge; the eyes are round and wide open, not narrow and almond-shaped; the muzzle is short and broad, not a long snout; the body is slim with a narrow chest and a clear gap of daylight between the front legs, not stocky. The coat is clean pure white, not cream, not beige and not yellow; only the inner ears, the muzzle and the belly carry a faint warm tint. Its ears are small, neat triangular ears that sit close to the head, slightly folded forward at the tips, not large erect pointed ears and not big upright ears. The expression is open, young and earnest, never majestic, proud, dignified or stern. No heavy body volume, no fluffy chest mane, no rigid symmetrical stance.
[Shot 1] [Medium close-up, low camera at the dog's eye level, the head and upper chest filling the frame, the front paws just inside the bottom edge], [static locked camera, no camera movement]. A plain, generic, fictional dormitory floor: pale laminate floor, a blank off-white wall behind, a metal bed leg and a dark backpack blurred far in the background, no readable text or signage. Soft, even, neutral daylight fills the frame from a window off-frame to the left, no colour cast, with a soft shadow under the chest and paws. <Subject 1> lies on the floor in a sphinx pose in the centre of the frame, chest up, front paws stretched forward, hind legs stretched out behind, tail along the floor, and never changes spot during the shot. A thick, messy stack of loose white printed pages lies on the floor directly in front of its front paws, one black marker pen lying crosswise on top; the print is unreadable. <Subject 1> raises its head off the floor and turns it straight to the lens, the nose centred in the frame, both eyes looking into the camera, the whole short broad muzzle and the open mouth completely visible and unobstructed, the black nose and the pink tongue clearly readable. <Subject 1> speaks in a clear natural human teenage male voice, with accurate lip-sync to Mandarin Chinese, mouth opening and closing in sync with the words; the jaw works through clean rounded open-and-close shapes on every syllable, the lips part and close in time with the sound, and the pink tongue shows between them. The body stays still, the ears hold steady, the eyes never leave the lens, and the line ends with the mouth still slightly open.
<Subject 1> (S1) speaks: <d>[Chinese] 相声讲究说学逗唱。</d>

overall_soundscape:
Quiet indoor room tone with faint air movement. Soft padding paw sounds on the laminate floor. Light rustle of loose paper and a small scrape of a pen on the floor. Soft panting of a young dog close to the microphone. A light collar jingle.

non_diegetic_music:
None.
```

## 变更记录
- v1 2026-10-23 初稿 · 第 0 批口型验证镜 V1（🔴 正面口播）

## 试错记录
<!-- 每轮生成后回填。只能改一个变量。 -->

| 轮次 | 唯一改动 | 看什么 |
|---|---|---|
| A1 | 基线生成 | 口型是否跟上 8 字；是不是中文人声（不是犬吠/含混咕噜）；嘴部是否清晰 |
| A2 | 只改音色（加 `young, light, boyish`） | 音色能否解析成少年男声 |
| A3 | 只把 `[Medium close-up` 改 `[Tight close-up` | 嘴部像素够不够 |

**风险点**：备选嘴部参考 `x6_adult_face_front_tongue_01.jpg` 右下角有第二只狗的爪子，故未使用；A1 嘴太闭才加为 `<Picture 3>`。本镜是最高风险形态，**失败不阻塞 V2/V3**。
