#!/usr/bin/env python3
"""
区域大地图 walkable 自动生成器(M3/M4 基建,可复用)
按 16px 格统计 亮度均值/方差/高亮像素占比 → 判别 可走(街道/空地) vs 阻挡(建筑/岩石/雾墙)
用法: /tmp/pil_venv/bin/python gen_walkable.py out/linlan_city.png [--mode city|belt|edge]
输出: 每档阈值一张 ASCII(#=阻挡 .=可走),供人工挑选;不直接写 chapters.json
"""
import sys
from PIL import Image

TILE = 16


def tile_stats(im):
    px = im.convert('RGB').load()
    W, H = im.size
    cols, rows = W // TILE, H // TILE
    stats = {}
    for ty in range(rows):
        for tx in range(cols):
            lums, bright, cyan = [], 0, 0
            for dy in range(0, TILE, 2):
                for dx in range(0, TILE, 2):
                    r, g, b = px[tx * TILE + dx, ty * TILE + dy]
                    l = (r + g + b) / 3
                    lums.append(l)
                    if l > 95: bright += 1
                    if g > 95 and b > 95 and g + b > r * 2.2: cyan += 1
            m = sum(lums) / len(lums)
            v = (sum((x - m) ** 2 for x in lums) / len(lums)) ** 0.5
            stats[(tx, ty)] = (m, v, bright, cyan)
    return stats, cols, rows


def grid_for(stats, cols, rows, lum_thr, var_thr):
    """阻挡 = 亮(均值>lum_thr) 或 纹理密(方差>var_thr) 或 有高亮/青绿结构"""
    g = []
    for ty in range(rows):
        row = []
        for tx in range(cols):
            m, v, bright, cyan = stats[(tx, ty)]
            blocked = (m > lum_thr) or (v > var_thr) or bright >= 6 or cyan >= 4
            row.append(1 if blocked else 0)
        g.append(row)
    # 边界一圈强制阻挡
    for tx in range(cols): g[0][tx] = g[rows - 1][tx] = 1
    for ty in range(rows): g[ty][0] = g[ty][cols - 1] = 1
    return g


def show(g, label):
    rows = len(g); cols = len(g[0])
    open_n = sum(1 for r in g for c in r if c == 0)
    print(f"\n--- {label} | 可走 {open_n}/{cols*rows} ({open_n*100//(cols*rows)}%) ---")
    for ty in range(rows):
        print(''.join('#' if g[ty][tx] else '.' for tx in range(cols)))


if __name__ == '__main__':
    path = sys.argv[1]
    im = Image.open(path)
    stats, cols, rows = tile_stats(im)
    ms = sorted(s[0] for s in stats.values())
    vs = sorted(s[1] for s in stats.values())
    print(f"{path}: {cols}x{rows} 格 | 亮度 p25={ms[len(ms)//4]:.0f} p50={ms[len(ms)//2]:.0f} p75={ms[len(ms)*3//4]:.0f} | 方差 p50={vs[len(vs)//2]:.0f} p75={vs[len(vs)*3//4]:.0f}")
    for (lt, vt, tag) in [
        (ms[len(ms)//2], vs[len(vs)*3//4], "A 中亮度+高方差"),
        (ms[len(ms)*3//5], vs[len(vs)*7//10], "B 偏松"),
        (ms[len(ms)*2//5], vs[len(vs)*3//5], "C 偏紧"),
    ]:
        show(grid_for(stats, cols, rows, lt, vt), f"{tag} lum>{lt:.0f} var>{vt:.0f}")
