#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
把 AI 生成的图片「像素化 + 统一到项目 32 色母板」，让多张素材风格一致。

为什么要它：AI 生图常出「假像素」（看着像素、其实是高清图带渐变/抗锯齿），
而且每张色调各飘各的。这个脚本强制：最近邻缩放 + 量化到 32 色母板 + 保留透明。

用法：
  1) 只需装一次依赖：   pip3 install pillow
  2) 把 AI 生成的原图放进  ip-map/art/raw/
  3) 运行（在 ip-map/art 目录下）：
       python3 process_pixels.py raw/输入.png out/输出.png 16 24
     最后两个数字 = 目标 宽 高（像素）。不写宽高则只量化、不缩放。
  4) out/ 里的图就是能塞进游戏、风格统一的素材。
"""
import sys
import os

try:
    from PIL import Image
except ImportError:
    print("缺少 Pillow。请先运行：  pip3 install pillow")
    sys.exit(1)

# 32 色母板（与 palette.hex 一致）
PALETTE_HEX = [
    "06080c", "0a0e15", "0f131c", "121620", "1a2130", "232c3d", "2b333f", "3a4452",
    "2a5f57", "3f8e80", "6fd3c4", "7a3d12", "c4762e", "ffb060", "3a4018", "7d8a3f",
    "b9c46a", "3a5f8f", "8fb8ff", "9aa6b5", "d8e0ea", "8a2a2a", "ff7a7a", "000000",
    "1c2026", "4a525e", "5a6577", "8893a0", "cfd6e0", "eaeef5", "ffd06b", "3f8e80",
]


def build_palette_image():
    """构造一张 PIL 调色板图（256 槽，前 32 槽是母板，其余用第一个色填满）。"""
    flat = []
    for h in PALETTE_HEX:
        flat += [int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)]
    first = flat[:3]
    while len(flat) < 256 * 3:
        flat += first
    pal_img = Image.new("P", (1, 1))
    pal_img.putpalette(flat)
    return pal_img


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(0)

    inp, outp = sys.argv[1], sys.argv[2]
    if not os.path.exists(inp):
        print("找不到输入文件：", inp)
        sys.exit(1)

    img = Image.open(inp).convert("RGBA")
    alpha = img.split()[3]
    rgb = img.convert("RGB")

    # 可选：最近邻缩放到目标像素尺寸
    if len(sys.argv) >= 5:
        w, h = int(sys.argv[3]), int(sys.argv[4])
        rgb = rgb.resize((w, h), Image.NEAREST)
        alpha = alpha.resize((w, h), Image.NEAREST)

    # 量化到母板（关掉抖动，硬边像素）
    pal_img = build_palette_image()
    quantized = rgb.quantize(palette=pal_img, dither=Image.Dither.NONE).convert("RGBA")

    # 把原来的透明区还原（alpha<128 的像素设为全透明）
    quantized.putalpha(alpha)
    px = quantized.load()
    ap = alpha.load()
    for y in range(quantized.height):
        for x in range(quantized.width):
            if ap[x, y] < 128:
                r, g, b, _ = px[x, y]
                px[x, y] = (r, g, b, 0)

    out_dir = os.path.dirname(outp)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    quantized.save(outp)
    print("完成：", outp, "  尺寸:", quantized.size)


if __name__ == "__main__":
    main()
