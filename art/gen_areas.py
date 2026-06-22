#!/usr/bin/env python3
"""
M3/M4 总装:生成 3 个区域大地图章节(临澜城/监测带/隔离栏段)写入 chapters.json
- 城市:行列亮度剖面取最暗带=大街(2格宽) + 总部广场 + 连通性兜底 carve
- 监测带:全旷野可走,两栋站楼+天线杆阻挡
- 隔离栏:上半(雾+栏)全封,院子可走,亮结构阻挡
全部 BFS 验证 spawn→所有大门/NPC/交互点连通,失败即报错不落盘
"""
import json
from pathlib import Path
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
TILE = 16


def tile_lum(path):
    im = Image.open(path).convert('RGB')
    px = im.load(); W, H = im.size
    cols, rows = W // TILE, H // TILE
    lum = [[0] * cols for _ in range(rows)]
    for ty in range(rows):
        for tx in range(cols):
            vals = [sum(px[tx * TILE + dx, ty * TILE + dy]) / 3
                    for dy in range(0, TILE, 2) for dx in range(0, TILE, 2)]
            lum[ty][tx] = sum(vals) / len(vals)
    return lum, cols, rows


def border(g):
    rows, cols = len(g), len(g[0])
    for tx in range(cols): g[0][tx] = g[rows - 1][tx] = 1
    for ty in range(rows): g[ty][0] = g[ty][cols - 1] = 1


def bfs(g, start):
    rows, cols = len(g), len(g[0])
    seen = {tuple(start)}; q = [tuple(start)]
    while q:
        x, y = q.pop()
        for dx, dy in ((1,0),(-1,0),(0,1),(0,-1)):
            nx, ny = x + dx, y + dy
            if 0 <= nx < cols and 0 <= ny < rows and g[ny][nx] == 0 and (nx, ny) not in seen:
                seen.add((nx, ny)); q.append((nx, ny))
    return seen


def carve_L(g, frm, to):
    """从 frm 到 to 凿 L 形走廊(先横后竖),保证连通"""
    x, y = frm
    while x != to[0]: g[y][x] = 0; x += 1 if to[0] > x else -1
    while y != to[1]: g[y][x] = 0; y += 1 if to[1] > y else -1
    g[to[1]][to[0]] = 0


def ensure_connected(g, spawn, pois, name):
    """所有 POI(含相邻可走格)从 spawn 可达;不可达就向最近可达格凿 L 廊"""
    for p in pois:
        g[p[1]][p[0]] = 0
    reach = bfs(g, spawn)
    for p in pois:
        if tuple(p) not in reach:
            best = min(reach, key=lambda r: abs(r[0]-p[0]) + abs(r[1]-p[1]))
            carve_L(g, p, list(best))
            reach = bfs(g, spawn)
    missing = [p for p in pois if tuple(p) not in reach]
    assert not missing, f"{name}: POI 不可达 {missing}"
    return g


def show(g, label, marks=None):
    marks = marks or {}
    print(f"\n--- {label} ---")
    for ty in range(len(g)):
        line = ""
        for tx in range(len(g[0])):
            line += marks.get((tx, ty), '#' if g[ty][tx] else '.')
        print(line)


# ============ 1) 临澜城 64×36 ============
lum, C, R = tile_lum(ROOT / 'art/out/linlan_city.png')
rowm = [sum(lum[ty]) / C for ty in range(R)]
colm = [sum(lum[ty][tx] for ty in range(R)) / R for tx in range(C)]

def pick_dark(profile, lo, hi, n, min_sep):
    idx = sorted(range(lo, hi), key=lambda i: profile[i])
    out = []
    for i in idx:
        if all(abs(i - o) >= min_sep for o in out):
            out.append(i)
            if len(out) == n: break
    return sorted(out)

h_aves = pick_dark(rowm, 4, R - 4, 3, 7)     # 3 条横向大街
v_aves = pick_dark(colm, 3, C - 3, 4, 10)    # 4 条纵向大街
print("临澜城 横街(行):", h_aves, " 纵街(列):", v_aves)

city = [[1] * C for _ in range(R)]
for ty in h_aves:
    for t in (ty, min(R - 2, ty + 1)):
        for tx in range(1, C - 1): city[t][tx] = 0
for tx in v_aves:
    for t in (tx, min(C - 2, tx + 1)):
        for ty in range(1, R - 1): city[ty][t] = 0
# 总部塔楼(亮簇 rows16-20, cols19-27)保持阻挡;南侧开广场
HQ = (19, 16, 27, 20)  # x0,y0,x1,y1
PLAZA = (18, 21, 29, 24)
for ty in range(PLAZA[1], PLAZA[3] + 1):
    for tx in range(PLAZA[0], PLAZA[2] + 1): city[ty][tx] = 0
for ty in range(HQ[1], HQ[3] + 1):
    for tx in range(HQ[0], HQ[2] + 1): city[ty][tx] = 1
border(city)
city_gate = [23, 21]            # 总部大门(广场北缘,塔楼南脚)
city_spawn = [v_aves[0] + 1, h_aves[-1]]  # 西南大街交叉口附近出生
city_npcs = {"patrol78": [v_aves[2], h_aves[0]], "citizen_lin": [21, 23]}
city_props = {"charge_post": (PLAZA[0], 22, 2, 2), "notice_screen": (27, 22, 2, 2)}
pois = [city_gate, city_spawn] + list(city_npcs.values()) + [[p[0], p[1]] for p in city_props.values()]
city = ensure_connected(city, city_spawn, pois, "临澜城")
# NPC 占格要可走(站位),交互 props 保持原格(热区邻接即可)
marks = {tuple(city_gate): 'G', tuple(city_spawn): 'S'}
for p in city_npcs.values(): marks[tuple(p)] = 'N'
show(city, "临澜城(G=总部门 S=出生 N=NPC)", marks)

# ============ 2) 监测带 48×27 ============
lum2, C2, R2 = tile_lum(ROOT / 'art/out/monitoring_belt.png')
belt = [[0] * C2 for _ in range(R2)]
def block_rect(g, x0, y0, x1, y1):
    for ty in range(max(0, y0), min(len(g) - 1, y1) + 1):
        for tx in range(max(0, x0), min(len(g[0]) - 1, x1) + 1): g[ty][tx] = 1
block_rect(belt, 6, 3, 16, 12)    # 3号站
block_rect(belt, 23, 15, 40, 22)  # 6号站
for (bx, by) in [(13, 2), (43, 15), (44, 15), (40, 16)]: belt[by][bx] = 1
for ty in range(R2):              # 高亮孤立结构兜底
    for tx in range(C2):
        if lum2[ty][tx] > 58: belt[ty][tx] = 1
border(belt)
belt_gates = {"ch1": [11, 13], "ch4": [31, 23]}
belt_spawn = [20, 13]
belt_props = {"antenna_array": (42, 14, 3, 3)}
pois = [belt_spawn] + list(belt_gates.values()) + [[42, 14]]
belt = ensure_connected(belt, belt_spawn, pois, "监测带")
show(belt, "监测带(G=站门 S=出生)", {tuple(v): 'G' for v in belt_gates.values()} | {tuple(belt_spawn): 'S'})

# ============ 3) 隔离栏段 60×30 ============
lum3, C3, R3 = tile_lum(ROOT / 'art/out/graymist_barrier.png')
edge = [[0] * C3 for _ in range(R3)]
for ty in range(0, 15):           # 雾墙+隔离栏:上半全封(看得见进不去)
    for tx in range(C3): edge[ty][tx] = 1
for ty in range(15, R3):          # 院子里亮结构(塔/设备)阻挡
    for tx in range(C3):
        if lum3[ty][tx] > 52: edge[ty][tx] = 1
border(edge)
edge_gate = [29, 15]              # 7号维护段大门(隔离栏正门下方)
edge_spawn = [29, 24]
edge_props = {"fogwall_w": (10, 12, 6, 3), "fogwall_e": (44, 12, 6, 3), "fence_sign": (33, 13, 3, 2)}
pois = [edge_spawn, edge_gate]
edge = ensure_connected(edge, edge_spawn, pois, "隔离栏段")
show(edge, "隔离栏段(G=维护段门 S=出生)", {tuple(edge_gate): 'G', tuple(edge_spawn): 'S'})

# ============ 写入 chapters.json ============
def wk(g): return [''.join(str(c) for c in row) for row in g]

d = json.load(open(ROOT / 'chapters.json', encoding='utf-8'))
d['chapters'] = [c for c in d['chapters'] if not c.get('area')]  # 幂等:清旧区域章

areas = [
 {"id":"area_city","area":True,"title":"区域 · 临澜城","name":"临澜城","place":"灰澜区 FS-01 · 距灰域 300km","locked":False,
  "hook":"管理局总部所在。人类与 AI 协同的市井日常——以及退役流程的起点。",
  "room":{"cols":64,"rows":36,"bgImage":"linlan_city","walkable":wk(city),"spawn":city_spawn},
  "gates":[{"at":city_gate,"to":"ch3","label":"管理局总部"}],
  "npcs":[
    {"id":"patrol78","name":"FS-7800 · 街面型","pos":city_npcs["patrol78"],"silent":True,"dialogue":{"start":0,"nodes":[
      {"speaker":"FS-7800 · 街面型","text":"「07 型。你的登记巡检区在缓冲带，不在主城。」","goto":1},
      {"speaker":"凤翎-07","text":"（它的光学组在我胸前的编号上停了 0.4 秒——比协议规定的识别时长，多了 0.3。）","goto":"end"}]}},
    {"id":"citizen_lin","name":"林婆婆","pos":city_npcs["citizen_lin"],"silent":True,"dialogue":{"start":0,"nodes":[
      {"speaker":"林婆婆","text":"「小七？今天不巡检啊。又来帮我代购降压贴？」","goto":1},
      {"speaker":"凤翎-07","text":"（她叫不出我的编号，只记得我是「小七」。在系统之外，我有一个不在册的名字。）","goto":"end"}]}}],
  "props":[
    {"id":"charge_post","name":"3号充电位","pos":[city_props["charge_post"][0],city_props["charge_post"][1]],"size":[2,2],"movable":False,"isObstacle":False,"isInteractable":True,"fromBg":True,"prompt":"a robot charging post with cyan status light","interactText":"（3 号充电位。我的专属位——上周起，名牌换成了 FS-7800-022。）"},
    {"id":"notice_screen","name":"市政公告屏","pos":[city_props["notice_screen"][0],city_props["notice_screen"][1]],"size":[2,2],"movable":False,"isObstacle":False,"isInteractable":True,"fromBg":True,"prompt":"a public holographic notice screen","interactText":"「公示：第 4 批旧型号单元退役回收名单已发布。」（我没有逐行去找我的编号。我直接知道它在第几行。）"}]},
 {"id":"area_belt","area":True,"title":"区域 · 灰域监测带","name":"灰域监测带 · 6号站群","place":"灰澜区 FS-01 · 距灰域 50km","locked":False,
  "hook":"两座监测站孤悬在荒原上，一条巡检路连着它们。",
  "room":{"cols":48,"rows":27,"bgImage":"monitoring_belt","walkable":wk(belt),"spawn":belt_spawn},
  "gates":[{"at":belt_gates["ch1"],"to":"ch1","label":"3号灰雾监测站"},{"at":belt_gates["ch4"],"to":"ch4","label":"6号灰域监测站"}],
  "npcs":[],
  "props":[
    {"id":"antenna_array","name":"中继天线阵","pos":[42,14],"size":[3,3],"movable":False,"isObstacle":False,"isInteractable":True,"fromBg":True,"prompt":"a relay antenna array on wasteland","interactText":"（天线在风里响。三号站的信号灯，比昨天又暗了一格。）"}]},
 {"id":"area_edge","area":True,"title":"区域 · 灰域边缘","name":"灰域 · 隔离栏段","place":"灰澜区 FS-01 · 距灰域 0km","locked":True,"requires":1,
  "lockHint":"需先核验 1 条异常线索",
  "hook":"隔离栏外就是雾墙。看得见，进不去。",
  "room":{"cols":60,"rows":30,"bgImage":"graymist_barrier","walkable":wk(edge),"spawn":edge_spawn},
  "gates":[{"at":edge_gate,"to":"ch2","label":"7号维护段"}],
  "npcs":[],
  "props":[
    {"id":"fogwall_w","name":"雾墙 · 西段","pos":[10,12],"size":[6,3],"movable":False,"isObstacle":False,"isInteractable":True,"fromBg":True,"prompt":"a wall of dense grey fog","interactText":"（雾墙没有「表面」。视线扎进去三米就被吃掉——像世界在那里没写完。）"},
    {"id":"fogwall_e","name":"雾墙 · 东段","pos":[44,12],"size":[6,3],"movable":False,"isObstacle":False,"isInteractable":True,"fromBg":True,"prompt":"a wall of dense grey fog","interactText":"（雾的流速恒定得不自然。十七天了，没有一次例外。）"},
    {"id":"fence_sign","name":"隔离栏警示牌","pos":[33,13],"size":[3,2],"movable":False,"isObstacle":False,"isInteractable":True,"fromBg":True,"prompt":"a warning sign on quarantine fence","interactText":"「FS-01 隔离栏 · 7 号段｜越界即注销」（条文的第一人称，从来不是我们。）"}]}
]
d['chapters'].extend(areas)
# worldmap 地点挂 area 入口
for loc in d['worldmapV2']['region']['locations']:
    loc['areaCh'] = {"linlan_city":"area_city","monitor_belt":"area_belt","graymist_edge":"area_edge"}[loc['id']]
open(ROOT / 'chapters.json', 'w', encoding='utf-8').write(json.dumps(d, ensure_ascii=False, separators=(',', ': ')) + '\n')
v = json.load(open(ROOT / 'chapters.json'))
print(f"\n✓ 写入完成: chapters={len(v['chapters'])} (含 3 区域章) | JSON valid")
