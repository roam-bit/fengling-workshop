#!/usr/bin/env python3
# 拆件 v2:从整图抠出可移动物件 sprite + 生成"真正擦干净"的 clean 底图
# v1 的坑:擦除框 [11,5]5x4 比监测台实际像素小,左翼+底座溢出框外没擦掉 -> 拖开后露出"鬼影"
# v2:擦除框放大到完整包住监测台,且 sprite 从同一框抠(home 位无缝,拖开露干净地板),
#     并用全图扫描挑"最干净的地板块"做填充,擦完用 cyan 检测器验证残留=0。
from PIL import Image
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
TILE = 16
base = Image.open(BASE / 'art/out/graymist_localmap.png').convert('RGBA')
W, H = base.size
COLS, ROWS = W // TILE, H // TILE

# 监测台生成框(tile):宽松包住整台(含左翼/底座),实测屏幕簇 cols10.5-15.6 rows5-8,housing/base 到 col16/row9.25
BOX = (10, 4, 17, 10)  # col0,row0,col1,row1 (含起不含止) -> 7宽 x 6高
bx0, by0, bx1, by1 = [v * TILE for v in BOX]
bw, bh = bx1 - bx0, by1 - by0


def cyan_count(img, rx0, ry0, rx1, ry1):
    """统计区域内"青绿屏幕"像素(监测台残留检测器)"""
    px = img.convert('RGB').load()
    n = 0
    for y in range(ry0, ry1):
        for x in range(rx0, rx1):
            r, g, b = px[x, y]
            if g > 95 and b > 95 and g + b > r * 2.2 and r < 130:
                n += 1
    return n


# === 1) 挑"最干净的单块地板 tile"(16x16),平铺填充 -> 还原地板网格,无条纹/无设备/无雾 ===
px = base.convert('RGB').load()


def tile_score(tx, ty):
    """单个 16x16 tile 的"纯地板度"评分,越低越干净"""
    sx0, sy0 = tx * TILE, ty * TILE
    vals = []
    bad = 0
    for y in range(sy0, sy0 + TILE):
        for x in range(sx0, sx0 + TILE):
            r, g, b = px[x, y]
            vals.append((r + g + b) / 3)
            if g > 90 and b > 90 and g + b > r * 2.1 and r < 130:
                bad += 25                       # 青绿屏幕
            if g > 95 and r > 85 and b < 95 and g >= r:
                bad += 15                       # 黄绿病态条纹(异常标记)
            if max(r, g, b) > 160:
                bad += 6                        # 高光/琥珀设备
            if r > 105 and r > g + 25:
                bad += 6                        # 暖色锈/警示
    mean = sum(vals) / len(vals)
    var = sum((v - mean) ** 2 for v in vals) / len(vals)
    if mean < 24 or mean > 62:                  # 纯地板亮度区间
        bad += 300
    return bad + var * 0.12, mean


# 在监测台附近(局部亮度匹配)找最干净 tile,避开监测台框
best_tile, best_s, best_mean = None, 1e18, 0
for ty in range(2, ROWS - 2):
    for tx in range(5, COLS - 5):
        sx0, sy0 = tx * TILE, ty * TILE
        if sx0 < bx1 and sx0 + TILE > bx0 and sy0 < by1 and sy0 + TILE > by0:
            continue                            # 跳过监测台框
        s, mean = tile_score(tx, ty)
        if s < best_s:
            best_s, best_tile, best_mean = s, (tx, ty), mean
print(f'最干净地板 tile: {best_tile}  score={best_s:.1f}  亮度={best_mean:.1f}')

# === 2) 生成 clean 底图:监测台框用该 tile 平铺盖掉(seam 对齐 16px 网格,像地板原生延续)===
clean = base.copy()
ftile = base.crop((best_tile[0] * TILE, best_tile[1] * TILE,
                    best_tile[0] * TILE + TILE, best_tile[1] * TILE + TILE))
for ty in range(BOX[1], BOX[3]):
    for tx in range(BOX[0], BOX[2]):
        clean.paste(ftile, (tx * TILE, ty * TILE))
clean.save(BASE / 'art/out/graymist_localmap_clean.png')

# === 3) 抠 sprite:从同一框抠(含监测台+四周薄地板边,home 位无缝)===
sprite = base.crop((bx0, by0, bx1, by1))
sprite.save(BASE / 'art/out/prop_console_center.png')

# === 4) 验证:clean 在监测台框内的青绿残留应=0 ===
resid = cyan_count(clean, bx0, by0, bx1, by1)
in_sprite = cyan_count(sprite, 0, 0, bw, bh)
print(f'验证 -> clean 框内青绿残留: {resid}  (应=0)')
print(f'       sprite 内青绿(监测台屏幕): {in_sprite}  (应>0,说明屏幕在 sprite 里)')
print(f'chapters.json 应改: console_center pos=[{BOX[0]},{BOX[1]}] size=[{BOX[2]-BOX[0]},{BOX[3]-BOX[1]}]')
print('done' if resid == 0 and in_sprite > 0 else 'WARN: 残留未清干净或 sprite 没抓到屏幕')
