#!/usr/bin/env python3
"""
临澜城地图根治(用户反馈:分辨率糟/穿模/难看)
①颗粒修复: raw v2(1672×941,内含≈4px艺术颗粒) → 两步法 NEAREST 采回原生(418×235) → ×2 整数放大(836×470) → 裁 832×464=52×29格
   (旧做法 1672→1024 非整数一步缩 = 1px/2px/3px 颗粒混杂 = "分辨率很糟糕"的根源)
②街道走真实暗区: 按格亮度/方差判街道,不再硬凿直线大街(旧做法穿楼=穿模根源)
③POI(大门/NPC/物件/出生点)全部钉在最大连通街区上,连通性由构造保证
用法: fix_city.py            → 打印 2 档阈值 ASCII 供挑选
      fix_city.py --commit A → 用 A 档写入 art/out + chapters.json
"""
import json
import sys
from pathlib import Path
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
TILE = 16
# v4(终版): 按规格卡重生成的真像素图(行程统计 1px=50%,与 ch4 同级)——整张 1:1 入库
# 1672×941 裁到 16 倍数 1664×928 = 104×58 格 ≈ 3.5×3.4 视口的大城
RAW = ROOT / 'art/raw/worldmap_v2_linlan_city_1024_prompt_source.png'
CROP = (1664, 928)
CROP_AT = (4, 6)
COLS, ROWS = CROP[0] // TILE, CROP[1] // TILE


def build_image():
    im = Image.open(RAW).convert('RGB')
    return im.crop((CROP_AT[0], CROP_AT[1], CROP_AT[0] + CROP[0], CROP_AT[1] + CROP[1]))


def tile_stats(im):
    """每格指标: dark30(暗占比) dark42(中暗占比) lum(均值) sat(饱和度均值) var(纹理方差) cyan"""
    px = im.load()
    st = {}
    for ty in range(ROWS):
        for tx in range(COLS):
            dark30 = dark42 = cyan = n = 0
            lums, sats = [], []
            for dy in range(0, TILE, 2):
                for dx in range(0, TILE, 2):
                    r, g, b = px[tx * TILE + dx, ty * TILE + dy]
                    l = (r + g + b) / 3
                    n += 1; lums.append(l)
                    sats.append(max(r, g, b) - min(r, g, b))
                    if l < 30: dark30 += 1
                    if l < 42: dark42 += 1
                    if g > 95 and b > 95 and g + b > r * 2.2: cyan += 1
            m = sum(lums) / n
            var = (sum((x - m) ** 2 for x in lums) / n) ** 0.5
            st[(tx, ty)] = {"d30": dark30 / n, "d42": dark42 / n, "lum": m,
                            "sat": sum(sats) / n, "var": var, "cyan": cyan}
    return st


def derive(st, frac_thr, _unused=None):
    g = [[1] * COLS for _ in range(ROWS)]
    # ① 主街:暗占比
    for (tx, ty), s in st.items():
        if s["d30"] >= frac_thr and s["cyan"] < 6:
            g[ty][tx] = 0
    def nbr8_open(x, y):
        return sum(1 for dx in (-1, 0, 1) for dy in (-1, 0, 1) if (dx or dy)
                   and 0 <= x + dx < COLS and 0 <= y + dy < ROWS and g[y + dy][x + dx] == 0)
    # ② 斑马线织补:亮但低饱和(白灰条纹)且八邻多为路 → 是路面标线不是建筑(用户图2)
    for _ in range(3):
        changed = False
        for ty in range(1, ROWS - 1):
            for tx in range(1, COLS - 1):
                s = st[(tx, ty)]
                if g[ty][tx] == 1 and s["sat"] < 26 and s["lum"] > 36 and s["cyan"] < 4 and nbr8_open(tx, ty) >= 5:
                    g[ty][tx] = 0; changed = True
        if not changed: break
    # ③ 庭院/广场生长:从街道种子向"平坦中暗低饱和地面"扩散;屋顶纹理密(var 高)不会被吃(用户图3)
    for _ in range(40):
        changed = False
        for ty in range(1, ROWS - 1):
            for tx in range(1, COLS - 1):
                if g[ty][tx] != 1: continue
                s = st[(tx, ty)]
                if s["d42"] >= 0.85 and s["sat"] < 20 and s["var"] < 14 and s["cyan"] < 4 \
                        and any(g[ty + dy][tx + dx] == 0 for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))):
                    g[ty][tx] = 0; changed = True
        if not changed: break
    # 去孤立噪点(四邻全堵的单格)
    for ty in range(1, ROWS - 1):
        for tx in range(1, COLS - 1):
            if g[ty][tx] == 0 and all(g[ty + dy][tx + dx] for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))):
                g[ty][tx] = 1
    for tx in range(COLS): g[0][tx] = g[ROWS - 1][tx] = 1
    for ty in range(ROWS): g[ty][0] = g[ty][COLS - 1] = 1
    return g


def components(g):
    seen, comps = set(), []
    for sy in range(ROWS):
        for sx in range(COLS):
            if g[sy][sx] == 0 and (sx, sy) not in seen:
                comp, q = {(sx, sy)}, [(sx, sy)]
                seen.add((sx, sy))
                while q:
                    x, y = q.pop()
                    for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                        nx, ny = x + dx, y + dy
                        if 0 <= nx < COLS and 0 <= ny < ROWS and g[ny][nx] == 0 and (nx, ny) not in seen:
                            seen.add((nx, ny)); comp.add((nx, ny)); q.append((nx, ny))
                comps.append(comp)
    return sorted(comps, key=len, reverse=True)


def show(g, label, marks=None):
    marks = marks or {}
    open_n = sum(1 for r in g for c in r if c == 0)
    print(f"\n--- {label} | 可走 {open_n}/{COLS*ROWS} ({open_n*100//(COLS*ROWS)}%) ---")
    for ty in range(ROWS):
        print(''.join(marks.get((tx, ty), '#' if g[ty][tx] else '.') for tx in range(COLS)))


im = build_image()
st = tile_stats(im)
VARIANTS = { "A": (0.66, None), "B": (0.62, None) }

if "--commit" not in sys.argv:
    for k, (ft, _) in VARIANTS.items():
        g = derive(st, ft)
        comps = components(g)
        main = comps[0] if comps else set()
        for ty in range(ROWS):
            for tx in range(COLS):
                if g[ty][tx] == 0 and (tx, ty) not in main: g[ty][tx] = 1
        show(g, f"{k} 暗占比>={ft} 主连通块={len(main)}格")
    sys.exit(0)

# ===== 提交模式 =====
variant = sys.argv[sys.argv.index("--commit") + 1]
ft, _ = VARIANTS[variant]
g = derive(st, ft)
main = components(g)[0]
for ty in range(ROWS):
    for tx in range(COLS):
        if g[ty][tx] == 0 and (tx, ty) not in main: g[ty][tx] = 1

# HQ 塔楼=最大青绿簇 → 大门=塔楼正下方最近街道格
# 总部塔楼占 1-9 行(中部车站带/底部广告牌青绿都很密,锚点必须限到塔楼行带)
cy_tiles = sorted(((tx, ty) for (tx, ty), s in st.items() if s["cyan"] >= 8 and ty < 10),
                  key=lambda t: -st[t]["cyan"])
assert cy_tiles, "找不到青绿簇(管理局总部)"
hx = sorted(t[0] for t in cy_tiles[:14])[len(cy_tiles[:14]) // 2]
hy = max(t[1] for t in cy_tiles[:14])
gate = None
for dy in range(1, 8):
    for ddx in (0, 1, -1, 2, -2, 3, -3):
        cand = (hx + ddx, hy + dy)
        if cand in main: gate = list(cand); break
    if gate: break
assert gate, "塔下找不到街道格做大门"

def neigh(p): return sum(1 for dx, dy in ((1,0),(-1,0),(0,1),(0,-1)) if (p[0]+dx, p[1]+dy) in main)
def far(p, pts, d): return all(abs(p[0]-q[0]) + abs(p[1]-q[1]) >= d for q in pts)

junctions = sorted(main, key=lambda p: -neigh(p))
spawn = next(list(p) for p in junctions if p[1] > ROWS * 2 // 3 and far(p, [tuple(gate)], 8))
npc1 = next(list(p) for p in junctions if p[1] < ROWS // 2 and far(p, [tuple(gate), tuple(spawn)], 7))
npc2 = next(list(p) for p in junctions if far(p, [tuple(gate), tuple(spawn), tuple(npc1)], 9))
# 物件=贴着街道的墙格(≥2 个街道邻居),取两个相距远的
walls = [p for p in ((tx, ty) for ty in range(1, ROWS-1) for tx in range(1, COLS-1))
         if g[p[1]][p[0]] == 1 and neigh(p) >= 2]
prop1 = next(p for p in walls if far(p, [tuple(gate)], 4) and abs(p[1]-spawn[1]) < 8)
prop2 = next(p for p in walls if far(p, [prop1, tuple(gate)], 8))

marks = {tuple(gate): 'G', tuple(spawn): 'S', tuple(npc1): 'N', tuple(npc2): 'N', prop1: 'P', prop2: 'P'}
show(g, f"提交 {variant} | G门 S生 N×2 P×2", marks)

# 落图
tmp = ROOT / 'art/out/_city_tmp.png'
im.save(tmp)
import subprocess
subprocess.run([sys.executable, str(ROOT / 'art/process_pixels.py'), str(tmp.relative_to(ROOT / 'art')), 'out/linlan_city.png', str(CROP[0]), str(CROP[1])], cwd=ROOT / 'art', check=True)
tmp.unlink()

# 落数据(只动 area_city 的几何与 POI,保留对话文本;顺手修三区 title 重复 + 林婆婆改陈伯配男性 sprite)
d = json.load(open(ROOT / 'chapters.json', encoding='utf-8'))
for c in d['chapters']:
    if c.get('area'): c['title'] = "区域地图"
ac = next(c for c in d['chapters'] if c['id'] == 'area_city')
ac['room'].update({"cols": COLS, "rows": ROWS, "walkable": [''.join(str(v) for v in row) for row in g], "spawn": spawn})
ac['gates'] = [{"at": gate, "to": "ch3", "label": "管理局总部"}]
for n in ac['npcs']:
    if n['id'] == 'patrol78': n['pos'] = npc1
    if n['id'] == 'citizen_lin':
        n['pos'] = npc2
        n['name'] = "陈伯"
        for node in n['dialogue']['nodes']:
            if node.get('speaker') == '林婆婆': node['speaker'] = '陈伯'
for p in ac['props']:
    if p['id'] == 'charge_post': p['pos'] = [prop1[0], prop1[1]]; p['size'] = [1, 1]
    if p['id'] == 'notice_screen': p['pos'] = [prop2[0], prop2[1]]; p['size'] = [1, 1]
open(ROOT / 'chapters.json', 'w', encoding='utf-8').write(json.dumps(d, ensure_ascii=False, separators=(',', ': ')) + '\n')
print(f"\n✓ 已写入: linlan_city.png {CROP} + area_city 数据(gate={gate} spawn={spawn} npc={npc1},{npc2} props={prop1},{prop2})")
