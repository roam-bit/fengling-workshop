#!/usr/bin/env python3
# 底图模式确定性验证(可复用):连通性 BFS + 碰撞对齐 + 数据检查
# 用法:cd <项目根> && /tmp/pil_venv/bin/python art/verify_bgmode.py [ch_id=ch4]
import sys, json
from collections import deque
from pathlib import Path
try: from PIL import Image
except ImportError: print("缺 PIL: python3 -m venv /tmp/pil_venv && /tmp/pil_venv/bin/pip install pillow"); sys.exit(1)

BASE = Path(__file__).resolve().parent.parent
CH_ID = sys.argv[1] if len(sys.argv) > 1 else 'ch4'
d = json.load(open(BASE / 'chapters.json'))
ch = next((c for c in d['chapters'] if c['id'] == CH_ID), None)
if not ch: print(f"找不到 {CH_ID}"); sys.exit(1)
room = ch['room']; walk = room.get('walkable')
if not walk: print(f"{CH_ID} 不是底图模式(无 walkable)"); sys.exit(0)
COLS, ROWS = room['cols'], room['rows']
grid = [[1 if c == '1' else 0 for c in row] for row in walk]
npcs = ch.get('npcs', []); spawn = room['spawn']
print(f"=== 验证 {CH_ID} · {ch.get('name', '')} · 底图={room.get('bgImage')} ===\n")

print('1. 走位连通性(从 spawn BFS)')
def nb(x, y):
    for dx, dy in ((1,0),(-1,0),(0,1),(0,-1)):
        nx, ny = x+dx, y+dy
        if 0 <= nx < COLS and 0 <= ny < ROWS: yield nx, ny
reach = [[False]*COLS for _ in range(ROWS)]
q = deque([tuple(spawn)]); reach[spawn[1]][spawn[0]] = True
while q:
    x, y = q.popleft()
    for nx, ny in nb(x, y):
        if not reach[ny][nx] and grid[ny][nx] == 0: reach[ny][nx] = True; q.append((nx, ny))
for n in npcs:
    nx, ny = n['pos']
    adj = [(x, y) for x, y in nb(nx, ny) if grid[y][x] == 0 and reach[y][x]]
    print(f"  {n['name']:10s}(col{nx},row{ny}): {'可走到对话' if adj else '✗ 走不到!'}  站位{adj}")
floor = sum(r.count(0) for r in grid); reached = sum(sum(r) for r in reach)
dead = [(x, y) for y in range(ROWS) for x in range(COLS) if grid[y][x] == 0 and not reach[y][x]]
print(f"  可走 {floor} 格,spawn 实际可达 {reached} 格,死区 {len(dead)} 格")
if dead: print(f"    死区(空气墙嫌疑): {dead[:25]}")
print()

print('2. 碰撞与底图实体对齐(扫青绿=屏幕/橙=核聚变)')
img_path = BASE / 'art/out' / (room['bgImage'] + '.png')
if not img_path.exists(): print(f"  ⚠️ 底图缺失: {img_path}")
else:
    img = Image.open(img_path).convert('RGB'); px = img.load()
    feats = []
    for gy in range(ROWS):
        for gx in range(COLS):
            cy = og = 0
            for y in range(gy*16, gy*16+16):
                for x in range(gx*16, gx*16+16):
                    r, g, b = px[x, y]
                    if g > r+22 and b > r+12 and g > 105: cy += 1
                    elif r > g+28 and g > b+18 and r > 135: og += 1
            if cy > 4: feats.append((gx, gy, '青绿屏'))
            elif og > 4: feats.append((gx, gy, '橙光'))
    miss = [(x, y, t) for x, y, t in feats if walk[y][x] != '1']
    print(f"  特征实体格 {len(feats)},被墙覆盖 {len(feats)-len(miss)},未覆盖 {len(miss)}")
    for x, y, t in miss: print(f"    [未覆盖] {t} col{x} row{y}")
print()

print('3. 数据检查')
print(f"  walkable: {len(walk)} 行 × {len(walk[0])} 列")
print(f"  spawn {spawn} 可走={grid[spawn[1]][spawn[0]]==0}")
for n in npcs:
    flags = []
    if n.get('noSprite'): flags.append('noSprite')
    if n.get('silent'): flags.append('silent')
    if n.get('dockSize'): flags.append(f"dockSize={n['dockSize']}")
    print(f"  {n['id']:12s} pos{n['pos']}  {' '.join(flags) or '-'}")
