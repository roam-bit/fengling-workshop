# 灰域监测站 · 设计包（设定 + 生图提示词 + 交互方案）

> 多智能体协作产出。你照「生图提示词」用 codex 生成，放进 `art/raw/`，喊我集成。

---

## 一、设定卡（这个站是什么）

- **名称**：灰域监测站（编号建议 **6号** 或 9号，落在已有「3号灰雾监测站」「7号隔离栏维护段」之间，巡检动线上相邻一站）
- **位置**：异常区最外层「灰域」边缘、缓冲带交界弧线上——比 3 号站更贴近迷雾。世界图上摆在异常区黑洞**左下侧弧带、ch1 与 ch3 之间**
- **职责**：灰域边缘的「读数岗」——监测迷雾浓度 / 信号干扰 / 读数偏移 / 越界征兆。一句话：*站在文明这侧、背对总部、脸贴着雾，替所有人先听见异常*
- **布局（左暖右冷的危险梯度）**：
  - 左 2/3 = 人类守得住的监测厅（核聚变单元暖光、主控台、休眠槽）
  - 右 1/3 = 灰域迷雾侵入边缘（全景观察窗、破损墙板渗雾、气密门）
- **核心悬疑钩子**（精华）：
  - 一句话（世界图档案）：**「休眠位多停了一台早该不存在的旧单元，电量却是满的。」**
  - 真线索（对话后记入私人记录）：**「第5号休眠槽停着一台已注销的同型号单元（编号牌被刮去），待机电量 100%——但近三个月的充电日志里，没有任何一次给它供电的记录。」**
  - 机理：*满电=被维护过，日志空白=没人在册地碰过它* → 和「退役表早7分钟」「12-OUT被谁唤起」同构=**一条不在册的手先动过这里**；更深一层是**身份恐怖**：那台和凤翎同型号的旧单元，是凤翎照见的「一个已注销的自己」
- **NPC**：SE-12——蹲在第5号休眠槽里的同型号休眠旧单元，半唤醒、冷峻碎句，是钩子的「会说话的物证」
- **4 个可交互点**（走近触发）：主监测终端 / 灰域观察窗 / 破损墙板（雾入侵）/ 越界痕迹（耳室里的旧编号碎片）

---

## 二、生图提示词（复制去 codex 生图，放 `art/raw/`）

> 全部已套 32 色母板 + Signalis 冷峻设施感。建议都生成 2× 尺寸再降采样（硬边更干净）。

### ① 局部地图底图 → 存 `raw/graymist_localmap.png`（必出，448×240，建议生 896×480）
```
pixel art, top-down view, 16-bit, a full interior floor plan of a small grey-field anomaly monitoring station inside a sci-fi buffer-zone facility, rectangular room enclosed by thick metal walls, LEFT side warmer and safer with a sealed fusion reactor cell glowing dim amber (#c4762e) in the lower-left corner and a row of robot docking bays recessed into the left wall (one dock bay empty, others dark), CENTER a large four-panel monitoring console desk with faint cyan data glow (#6fd3c4), RIGHT side colder and dangerous: an entire wall replaced by a reinforced grey-field observation window looking out into rolling black fog, a half-open double airlock gate in the lower-right corner leaking thin mist, the right third of the floor creeping with faint mist and a thin wet streak on the floor, a left-to-right gradient from warm safe interior to cold fog-invaded edge, walkable central corridor, strict limited palette: dark blue-grey #06080c #0f131c #2b333f #3a4452, cyan #6fd3c4, amber #ffb060, sickly yellow-green #b9c46a for the fog glow only and under 5 percent of the image, cold dim sci-fi facility, Signalis-inspired bleak, lonely night-shift mood, no people, no dithering, hard pixel edges, no anti-aliasing, no gradients
```

### ② 世界图 logo · 已激活态 → 存 `raw/graymist_logo.png`（必出，48×48，透明背景）
```
pixel art, top-down view, 16-bit, a tiny map icon of a grey-field anomaly monitoring station on a sci-fi tactical-display map, a small dark blue-grey facility block #2b333f with a thin cyan outline #6fd3c4 and a glowing cyan sensor core dot on its roof, a thin cyan radar sweep arc extending from one side toward the bottom (the fog side), the bottom edge of the block touched by a 2-3px sickly yellow-green fog stain #b9c46a (under 5 percent), a faint dashed cyan fence ring around half the station, transparent background, monitoring-screen HUD style, strict limited palette dark blue-grey #06080c #0f131c #2b333f, cyan #6fd3c4, sickly yellow-green #b9c46a for fog only, cold dim sci-fi facility, Signalis-inspired bleak, no dithering, hard pixel edges, no anti-aliasing, no gradients, single centered icon
```
> 三态（盲区/已探索/当前）由现有 CSS 框自动上色，**只需出这 1 张**；盲区态可直接用现有「NO SIGNAL」框，不必出图。

### ③ SE-12 休眠单元（物证 NPC）→ 存 `raw/se12_dormant.png`（48×48，透明背景）
```
pixel art, top-down view, 16-bit, a worn outdated industrial robot inspector unit identical in model to the protagonist but powered into standby sleep, humanoid rounded boxy amber chassis dimmed and desaturated toward #7a3d12, head bowed in dormant mode, a single cyan standby indicator light #6fd3c4 on its chest fully lit at 100 percent charge, its serial nameplate scratched out and smeared with a faint sickly yellow-green stain #b9c46a, lonely and uncanny like a discarded twin, facing the camera front view, transparent background, strict limited palette dark blue-grey #06080c #0f131c #2b333f, cyan #6fd3c4, amber #ffb060 #7a3d12, sickly yellow-green #b9c46a only on the nameplate stain, cold dim sci-fi facility, Signalis-inspired bleak, no dithering, hard pixel edges, no anti-aliasing, no gradients, single centered sprite
```

### ④（可选）灰域观察窗道具 → 存 `raw/prop_observation_window.png`（32×32）
```
pixel art, top-down view, 16-bit, a small reinforced observation window prop set into a metal facility wall, looking out onto rolling black fog with faint sickly yellow-green glow #b9c46a seeping through, a thin cyan data readout strip #6fd3c4 along the window frame, fog line pressing against the sill, transparent background, strict limited palette dark blue-grey #06080c #0f131c #2b333f, cyan #6fd3c4, sickly yellow-green #b9c46a for fog glow only, cold dim sci-fi facility, Signalis-inspired bleak, no dithering, hard pixel edges, no anti-aliasing, no gradients, single centered prop
```

---

## 三、交互方案（我集成时怎么做，给你了解）

**核心原则：画像归画像、碰撞归数据**（互不耦合，改地图=改数据不重出图）

1. **局部地图**：你的 `graymist_localmap.png` 当 Phaser **背景底图**（替代现在一格格铺的 tile）；玩家能不能走，由 `chapters.json` 里一份 **walkable 网格数据**（0 可走/1 墙，28×15）决定——和现在房间一个尺寸，碰撞与画面 1:1 对齐
2. **世界图 logo**：往 **DOM 世界图**加（不是 Phaser）。现有 `.wm-loc` 的三态状态机（盲区/已探索/当前）**免费可用**，我只把方块换成你的 `graymist_logo.png`
3. **新地点**：`chapters.json` **append** 一个新 chapter（名称/世界图坐标/logo/局部地图画像路径/walkable数据/可交互点），**不动现有 3 篇剧情**
4. **可交互点**（终端/观察窗/破损/越界痕迹）：走近触发，复用现有 NPC「曼哈顿距离=1」逻辑，零新代码

## 四、我的默认建议（你生图时若想改，告诉我）
- 作为**独立新地点 ch4** append（有自己的对话+线索，计入「凤翎私人记录」），初始 locked、`requires:1`（探过一篇才显影）→ 既扩地图密度，又不打乱现有主线
- 命名 **6号灰域监测站**（编号你定）
- 只升级**这一篇**用「画像底图」模式验证，其余 3 篇继续用 tile（不同时改，避免返工）
- 世界图坐标放在比 ch1 更靠异常区内侧的环带（呼应「灰域边缘」）
