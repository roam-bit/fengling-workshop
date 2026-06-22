# 07号调查员 · 美术生成包（M4 用）

目标：用 AI 生成一套**风格统一、贴合 IP、能截图惊艳**的像素素材，替换现在的占位色块。
风格锚点：**Signalis 的冷峻设施感（骨）+ OMORI 的明暗双层（结构）**，沿用项目现有冷色调。

---

## 一、32 色母板（圣经，所有图都量化到这套色）

> 为什么要锁母板：AI 生图最大的翻车点是「十张图色调各飘各的」。先定死这 32 色，
> 生成后用 `process_pixels.py` 一键量化到它，十张来源不同的图会瞬间像一套。
> 导入文件见同目录 `palette.hex`（aseprite / photopea / lospec 都能导入）。

| 用途 | 色值 |
|---|---|
| **冷蓝灰**（地形/墙/背景，8档） | `#06080c` `#0a0e15` `#0f131c` `#121620` `#1a2130` `#232c3d` `#2b333f` `#3a4452` |
| **青绿**（系统/AI秩序/UI，3档） | `#2a5f57` `#3f8e80` `#6fd3c4` |
| **琥珀**（主角凤翎·全画面唯一暖色，3档） | `#7a3d12` `#c4762e` `#ffb060` |
| **病态黄绿**（异常侵染·占比<5%，3档） | `#3a4018` `#7d8a3f` `#b9c46a` |
| **冷蓝**（人类NPC秦望，2档） | `#3a5f8f` `#8fb8ff` |
| **惨白**（新型号FS-7800，2档） | `#9aa6b5` `#d8e0ea` |
| **红警**（危险/异常警示，2档） | `#8a2a2a` `#ff7a7a` |
| **中性**（黑白灰，6档） | `#000000` `#1c2026` `#4a525e` `#5a6577` `#8893a0` `#cfd6e0` |
| **高光**（文字/点缀，3档） | `#eaeef5` `#ffd06b` `#2a5f57` |

**色彩叙事（很重要，别破坏）**：整张画面是冷的、低饱和的（克制的日常巡检）；
**主角琥珀是唯一的暖色** = 凤翎「系统里唯一活着、不属于这套规则」的那一点（呼应觉醒暗线）；
**病态黄绿只在异常处小面积点睛**（<5%），大了就廉价。

---

## 二、提示词母版（每张图只改 `[主体]`，其余恒定）

把下面这段存好，每次生成只替换 `[主体]`：

```
pixel art, top-down view, 16-bit retro game sprite, [主体],
strict limited palette: dark blue-grey (#06080c #0f131c #2b333f #3a4452), cyan system glow (#6fd3c4), warm amber (#ffb060), sickly yellow-green (#b9c46a) only for anomalies,
cold dim sci-fi facility mood, Signalis-inspired bleak atmosphere, OMORI-like clean readability,
no dithering, hard pixel edges, 1:1 pixel density, no anti-aliasing, no gradients,
transparent background, single centered sprite
```

---

## 三、要生成的素材清单（ch2「隔离栏异常」优先，先做透一篇）

> 顺序建议：先做 ①凤翎定妆照 调到满意 → 当全局风格参考(reference)喂给后面每一张，保证一致。

| # | 素材 | 填进 `[主体]` 的描述 | 目标尺寸 |
|---|---|---|---|
| ① | **凤翎·正面** | `a worn outdated industrial robot inspector unit, humanoid, rounded boxy amber chassis, slightly battered panels, a single small cyan indicator light on its chest, lonely and dignified, facing the camera (front view)` | 16×24 |
| ②③④ | 凤翎·背面/左/右 | 同上，把 `facing the camera (front view)` 换成 `seen from behind (back view)` / `facing left (side view)` / `facing right (side view)` | 16×24 |
| ⑤ | **秦望**（人类操作员） | `a calm tired middle-aged human field operator in a cold blue-grey uniform, 40s, experienced, facing the camera` | 16×24 |
| ⑥ | **FS-7800**（新型号） | `a brand-new sleek pale-white robot inspector unit, perfectly symmetrical and clean chassis, no wear, cold and impersonal, faint white glow, facing the camera` | 16×24 |
| ⑦ | **隔离栏地面**（tileset） | `a 4x4 tileset of an industrial quarantine-barrier maintenance floor, matte dark blue-grey metal panels, faint warning stripe accents, subtle grid seams, worn` | 64×64（含16个16px格） |
| ⑧ | **缓冲带地面**（tileset，给ch1/顶层） | `a 4x4 tileset of a dim metal facility floor, matte dark blue-grey panels, subtle grid seams, industrial` | 64×64 |
| ⑨ | **调查点道具** | `small top-down props on transparent background: a damaged barrier section, a terminal screen glowing with cyan text, a thermal-imaging monitor` | 各 16×16 |
| ⑩ | **异常特效层** | `eerie anomaly overlays on transparent background: a small sickly yellow-green glow, a scanline tear, a 1px-misaligned grid fragment, a faint floating old serial number "12-OUT", subtle and unsettling` | 任意 |

> NPC/主角：demo 阶段**不做逐帧行走动画**，每个方向一张静帧即可（撞墙停的逻辑已经有了，不需要动画也成立）。

---

## 四、保证「十张图像一套」的关键一步（别省）

AI 生图常出「假像素」（看着像素、其实是高清图带渐变）。每张生成后都跑一遍量化脚本：

```bash
# 第一次先装 Pillow（只需一次）
pip3 install pillow

# 把 AI 生成的原图放进 art/raw/，然后：
cd path/to/fengling-workshop/art   # 改成你 clone 后的项目目录
python3 process_pixels.py raw/fengling_front.png out/fengling_front.png 16 24
#                          ↑输入                  ↑输出              ↑宽 ↑高(像素)
```

脚本会：**最近邻缩放到目标像素尺寸 + 强制量化到 32 色母板 + 保留透明背景**。
处理后的 `out/*.png` 才是能塞进游戏、且风格统一的素材。

---

## 五、落地顺序（你最在乎时间）

1. 先生成 **①凤翎正面**，调到你满意 → 这是风格基准
2. 以它为 reference 生成 ②③④ 三个方向 + ⑤秦望 + ⑥FS-7800
3. 生成 ⑦隔离栏地面 tileset + ⑨调查点道具 + ⑩异常特效
4. 全部过一遍 `process_pixels.py`
5. 把 `out/` 里的素材发我，我替换 ch2 的占位色块 → 出精美一篇
6. ch1 暂时继续用色块（或套同一底色），**不要两篇同时做，避免返工**

---

# 🏗️ 生图系统 v2 · 分层生成（2026-06-11 起新地图用这套）

> 根因:整图一次生成+像素推断碰撞=空气墙/穿模。新范式:**地貌和物体分开生成**,碰撞=显式脚印,零推断。

## 模板 A · 地貌层（纯地形,默认全可走）
尺寸=目标尺寸或整数倍(16 的倍数);**画面里不许出现任何建筑/设备/角色**:
```
pixel art, top-down view, 16-bit retro game terrain map, [地形主体:如 cold cracked wasteland with faint patrol paths / dark asphalt street network with plazas],
true 1:1 pixel density, no anti-aliasing, no upscaling, GROUND ONLY — absolutely no buildings, no structures, no characters, no props,
strict limited palette: dark blue-grey (#06080c #0f131c #2b333f #3a4452), subtle texture variation, cold dim Signalis mood
```
入库:`process_pixels.py` 量化 → 行程统计 1px≥45% → 直接全图可走,不跑碰撞推断。

## 模板 B · 物件层（建筑/设备单体,纯绿幕底）
一次一个物体,生成后用编辑器摆放。⚠️ **别写 TRANSPARENT BACKGROUND**——用户的生图工具不输出真透明 PNG(历史素材全是绿幕后期抠的,raw/ 下 *_chromakey.png 为证),写透明只会无限重 roll(2026-06-11 审查 P0):
```
pixel art, top-down slightly angled view, 16-bit retro game building sprite, [单体:如 a small monitoring station with cyan screen glow, entrance door at bottom],
true 1:1 pixel density, no anti-aliasing, entrance door 24-32 pixels tall (scale anchor),
solid pure green background (#00FF00), background must be one flat green color, single isolated structure only, no ground, no shadow baked in,
strict limited palette: dark blue-grey body, cyan (#6fd3c4) lights only, no warm colors
```
(选纯绿不选品红:主体大量 cyan 灯,纯绿和 cyan 色距足够抠色不误伤;**琥珀禁用于物件**——琥珀=凤翎专属全画面唯一暖色,2026-06-11 审查后与 CLAUDE.md 美术方向对齐,删掉旧版"1-2 窗点"豁免)
入库校验三连:①抠绿后 alpha 干净(边缘无绿边/青绿灯没被误抠) ②量化 32 色 ③行程统计。抠绿用 `art/chromakey.py`。
**风格对齐技巧**:生成时把地貌图(模板 A 产物)作为**风格参考(sref)**喂给工具,别用垫图/重绘模式(会把地面画进物件)。

## 模板 C · 角色（现有,不变）
见上文「提示词母版」。

## 数据契约（引擎侧,下次编码会话落地后启用）
- 物件 prop 新增 `footprint`(碰撞脚印,通常=底部 2-3 行格) ≠ `size`(图像框)
- 引擎 y-sort:角色 y < 物件基线 → 物件盖住角色(楼有"身后")
- 编辑器摆放物件=拖 sprite,碰撞自动=footprint,不再刷格推断
