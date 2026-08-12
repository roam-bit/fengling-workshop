# AGENTS.md — 给 AI 编程工具的项目地图

> 你（Codex / Claude Code / Cursor 等）即将修改「凤翎工坊」。这份文件告诉你架构、改法和坑。**动手前先读完。**

## 这是什么

一个无构建的单文件网页应用：2D 像素叙事游戏《07 号调查员》+ 制作它的可视化编辑器「凤翎工坊」，两者都在 `index.html` 里。数据驱动——剧情、地图、NPC、对话、机制全部在 `chapters.json`，改内容通常**不需要碰代码**。

## 怎么跑 / 怎么验证

```bash
python3 server.py                 # 起本地服务(端口 8131,纯 Python 标准库,零 pip 依赖;Windows 用 python)
# 浏览器开 http://127.0.0.1:8131
python3 test/e2e_smoke.py         # E2E 冒烟(200+ 项确定性检查,需 server 先起着 + 本机装有 Chrome)
```

**铁律：**
1. **必须用 `server.py`，不能用 `python -m http.server`**——编辑器保存靠它的 `POST /api/save-chapter`，用 http.server 保存会静默失败。
2. **改了 `server.py` 必须重启 server** 才生效（前端 `index.html` 刷新即可）。
3. **交付前跑一遍 E2E**，全绿（退出码 0）才算完成。改坏了它会告诉你坏在哪组。

## 文件地图

| 文件 | 是什么 | 什么时候动它 |
|---|---|---|
| `index.html` | 全部前端：游戏运行时(Phaser) + 世界地图(纯 DOM) + 编辑器 + Landing。约 1 万行，单个 `<script>` IIFE | 改交互/UI/引擎行为 |
| `chapters.json` | **单一数据源**：章节/房间/NPC/对话树/触发器/线索/道具/语义层/全局设置 | 改剧情、地图内容、机制（优先用编辑器改，其次直接编辑它） |
| `server.py` | 静态服务 + 保存 API + `/api/command`(意图级编辑命令) + `/api/ai-command`(自然语言→命令，DeepSeek 可选) | 加后端能力、改保存逻辑 |
| `phaser.min.js` | Phaser 3 引擎（本地化，离线可跑） | 永远不动 |
| `test/e2e_smoke.py` | E2E 冒烟：headless Chrome + Python 断言 | 加了功能就补对应检查项 |
| `art/` | 美术管线：`out/`=游戏在用的量化素材；处理脚本 + 生图指南 | 换/加美术素材 |

## index.html 内部分区（搜这些注释定位）

- `===== 世界地图 v2` —— 澜洲大陆图（纯 DOM，非 Phaser）
- `RoomScene` —— 游戏房间：网格移动/碰撞/NPC/触发器解释器（`runActions`/`checkTriggers`）
- `===== 凤翎工坊 · 世界编辑器` —— `?edit=章节id` 的编辑器（`setupEditor`/`ED` 状态）
- `机制卡编辑器` —— 触发→条件→动作可视化（`openMechanicsPanel`）
- `NEW_TEMPLATES` —— 新建项目的起手式模板
- `buildLanding` —— 平台首页
- `BootScene` —— URL 参数路由（`?room=` `?edit=` `?play=` 等入口全在这）

## 数据模型速查（chapters.json）

```
chapters[] 每章 = 一个可进入的场景
  room: { cols, rows, spawn:[x,y], walkable:["1墙0走"字符串×rows] , bgImage?, semantics? }
  npcs[]: { id, name, pos, dialogue:{start,nodes[]}, dialogPages?[], behavior?(static/wander/patrol) }
    对话节点: { speaker, text, goto | choices:[{label,goto,outcome?}], do?:[指令] }
  props[]: { id, name, pos:[x,y], size:[w,h], movable?, sprite?, footprint?, isInteractable?, interactText?, givesItemId?, requiresItem?, actions? }
  triggers[]: { id, type:auto|enter|leave, at, area?, once?, conditions?, actions:[指令] }
  指令积木: text / choice / set / if / addClue / giveItem / teleport / fx / wait
  clues[]: { id, name, detail }   gates[]: { at, to, label, spawnAt?, requiresItem? }
```

规则：`walkable` 是编译产物（有 `semantics` 时以语义层为原始事实）；物件碰撞看 `footprint`（底部 N 行），遮挡深度=图像底边。玩家进度全在 localStorage（`fs01_*` 键），清 localStorage 即重置。

## 常见改法配方

| 想做什么 | 怎么做 |
|---|---|
| 改台词/对话分支 | 编辑器里点 NPC → Inspector 逐句改；或直接改 `chapters.json` 对应 `dialogue.nodes` |
| 加一个 NPC/物件/传送门 | `?edit=章节id` 拖拽添加，💾 保存（写回 chapters.json） |
| 加"走到某处触发剧情" | 编辑器左栏「⚡机制」→ 新建机制卡（当→如果→就） |
| 加一章新场景 | Landing「新建项目」选起手式模板；或参照现有章节在 `chapters.json` 里 append |
| 换美术 | 图放 `art/`，过 `art/process_pixels.py` 量化到 32 色母板再入 `art/out/`（直接用原图会色彩漂移） |
| 改世界地图 | `chapters.json` 的 `worldmapV2` + `buildWorldMap()` |

## 已知坑（血泪换的，别再踩）

1. **主脚本在 IIFE 里**：内联 `onclick="fn()"` 引用的函数必须挂到 `window`，否则 ReferenceError。
2. **E2E 探针匹配 DOM 时**，`--dump-dom` 会包含 `<script>` 源码里的模板字面量——断言前用 `dom.split("<script")[0]` 截渲染区，或用负向断言 `(?!\$\{)`。
3. **headless Chrome 里 RAF 会冻结**：虚拟时间下轮询等异步资源不可靠，用回调钩子；截图取证用 `?tp=x,y` 传送参数。
4. **URL 内部跳转一律用相对路径** `index.html?...`（不是 `/index.html?...`）——GitHub Pages 子路径部署下绝对路径会 404。
5. **`chapters.json` 手改后**：JSON 语法错会让全站白屏，改完先 `python3 -c "import json;json.load(open('chapters.json'))"` 验一下。server 每次保存自动滚动备份到 `backups/`（保留 20 份），改坏了可以从那恢复。
6. **角色尺寸档位**必须整除 48（24/48/96），否则立绘碎裂。
7. **AI 命令没配 key 时**自动降级到规则解析器——`.ai_key` 不存在是正常状态，不要因此报错。

## 边界（别做的事）

- 不要引入构建工具/npm/框架——"无构建、clone 即跑"是这个项目的定位，不是欠账。
- 不要把密钥写进代码或 commit（`.ai_key` 在 .gitignore 里，保持这样）。
- 不要动 `phaser.min.js` 和 `art/out/` 里已量化的素材。
