#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Remove #00ff00 chroma key, fit to target size, and quantize to palette.hex."""

from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image


ROOT = Path(__file__).resolve().parent
GREEN = (0, 255, 0)


def load_palette() -> list[tuple[int, int, int]]:
    colors: list[tuple[int, int, int]] = []
    for line in (ROOT / "palette.hex").read_text(encoding="utf-8").splitlines():
        h = line.strip().lstrip("#")
        if not h:
            continue
        colors.append((int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)))
    return colors


def palette_image(colors: list[tuple[int, int, int]]) -> Image.Image:
    flat: list[int] = []
    for c in colors:
        flat.extend(c)
    first = flat[:3]
    while len(flat) < 256 * 3:
        flat.extend(first)
    img = Image.new("P", (1, 1))
    img.putpalette(flat)
    return img


def is_green(pixel: tuple[int, int, int, int], tolerance: int) -> bool:
    r, g, b, a = pixel
    if a == 0:
        return True
    near_key = abs(r - GREEN[0]) <= tolerance and abs(g - GREEN[1]) <= tolerance and abs(b - GREEN[2]) <= tolerance
    green_dominant = g >= 145 and g > r * 1.35 and g > b * 1.35
    return near_key or green_dominant


def remove_green(img: Image.Image, tolerance: int) -> Image.Image:
    out = img.convert("RGBA")
    px = out.load()
    for y in range(out.height):
        for x in range(out.width):
            if is_green(px[x, y], tolerance):
                px[x, y] = (0, 255, 0, 0)
    return out


def bbox_alpha(img: Image.Image) -> tuple[int, int, int, int]:
    box = img.getchannel("A").getbbox()
    if not box:
        raise SystemExit("No non-green pixels found after chroma key removal")
    return box


def fit_sprite(img: Image.Image, width: int, height: int, padding: int, anchor: str) -> Image.Image:
    cropped = img.crop(bbox_alpha(img))
    max_w = max(1, width - padding * 2)
    max_h = max(1, height - padding * 2)
    scale = min(max_w / cropped.width, max_h / cropped.height)
    new_size = (max(1, round(cropped.width * scale)), max(1, round(cropped.height * scale)))
    resized = cropped.resize(new_size, Image.Resampling.NEAREST)
    out = Image.new("RGBA", (width, height), (0, 255, 0, 0))
    x = (width - resized.width) // 2
    y = height - padding - resized.height if anchor == "bottom" else (height - resized.height) // 2
    out.alpha_composite(resized, (x, max(0, y)))
    return out


def quantize_rgba(img: Image.Image, colors: list[tuple[int, int, int]]) -> Image.Image:
    alpha = img.getchannel("A")
    rgb = img.convert("RGB")
    quantized = rgb.quantize(palette=palette_image(colors), dither=Image.Dither.NONE).convert("RGBA")
    quantized.putalpha(alpha)
    px = quantized.load()
    ap = alpha.load()
    for y in range(quantized.height):
        for x in range(quantized.width):
            if ap[x, y] < 128:
                r, g, b, _ = px[x, y]
                px[x, y] = (r, g, b, 0)
    return quantized


def remove_banned_accents(img: Image.Image) -> Image.Image:
    """Keep batch 1 free of amber, red, and sickly anomaly greens."""
    remap = {
        (122, 61, 18): (74, 82, 94),
        (196, 118, 46): (136, 147, 160),
        (255, 176, 96): (207, 214, 224),
        (255, 208, 107): (207, 214, 224),
        (58, 64, 24): (28, 32, 38),
        (125, 138, 63): (136, 147, 160),
        (185, 196, 106): (207, 214, 224),
        (138, 42, 42): (74, 82, 94),
        (255, 122, 122): (207, 214, 224),
    }
    px = img.load()
    for y in range(img.height):
        for x in range(img.width):
            r, g, b, a = px[x, y]
            if a and (r, g, b) in remap:
                nr, ng, nb = remap[(r, g, b)]
                px[x, y] = (nr, ng, nb, a)
    return img


def process(args: argparse.Namespace) -> None:
    inp = Path(args.input)
    out = Path(args.output)
    img = Image.open(inp).convert("RGBA")
    if args.chroma:
        img = remove_green(img, args.tolerance)
        img = fit_sprite(img, args.width, args.height, args.padding, args.anchor)
    else:
        img = img.resize((args.width, args.height), Image.Resampling.NEAREST)
    final = remove_banned_accents(quantize_rgba(img, load_palette()))
    out.parent.mkdir(parents=True, exist_ok=True)
    final.save(out)
    print(f"done {out} {final.size}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("input")
    parser.add_argument("output")
    parser.add_argument("width", type=int)
    parser.add_argument("height", type=int)
    parser.add_argument("--chroma", action="store_true")
    parser.add_argument("--tolerance", type=int, default=28)
    parser.add_argument("--padding", type=int, default=1)
    parser.add_argument("--anchor", choices=("center", "bottom"), default="bottom")
    process(parser.parse_args())


if __name__ == "__main__":
    main()
