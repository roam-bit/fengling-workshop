#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Crop/resize opaque L0 terrain art and quantize it to palette.hex."""

from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image, ImageStat


ROOT = Path(__file__).resolve().parent


def load_palette() -> list[tuple[int, int, int]]:
    colors: list[tuple[int, int, int]] = []
    for line in (ROOT / "palette.hex").read_text(encoding="utf-8").splitlines():
        h = line.strip().lstrip("#")
        if h:
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


def detect_horizontal_boundary(img: Image.Image) -> int:
    """Find the strongest horizontal luminance transition in the middle band."""
    gray = img.convert("L")
    rows: list[float] = []
    for y in range(gray.height):
        crop = gray.crop((gray.width // 10, y, gray.width * 9 // 10, y + 1))
        rows.append(ImageStat.Stat(crop).mean[0])
    lo, hi = int(gray.height * 0.22), int(gray.height * 0.62)
    best_y, best_delta = lo, -1.0
    window = max(3, gray.height // 120)
    for y in range(lo + window, hi - window):
        above = sum(rows[y - window:y]) / window
        below = sum(rows[y:y + window]) / window
        delta = abs(above - below)
        if delta > best_delta:
            best_y, best_delta = y, delta
    return best_y


def crop_to_aspect(img: Image.Image, width: int, height: int, boundary_y: int | None, target_boundary_y: int | None) -> Image.Image:
    src_w, src_h = img.size
    aspect = width / height
    if src_w / src_h > aspect:
        crop_h = src_h
        crop_w = round(crop_h * aspect)
        left = (src_w - crop_w) // 2
        top = 0
    else:
        crop_w = src_w
        crop_h = round(crop_w / aspect)
        left = 0
        if boundary_y is not None and target_boundary_y is not None:
            target_src_y = target_boundary_y / height * crop_h
            top = round(boundary_y - target_src_y)
            top = max(0, min(src_h - crop_h, top))
        else:
            top = (src_h - crop_h) // 2
    return img.crop((left, top, left + crop_w, top + crop_h))


def quantize_rgb(img: Image.Image) -> Image.Image:
    quantized = img.convert("RGB").quantize(palette=palette_image(load_palette()), dither=Image.Dither.NONE)
    return quantized.convert("RGB")


def process(args: argparse.Namespace) -> None:
    inp = Path(args.input)
    out = Path(args.output)
    img = Image.open(inp).convert("RGB")
    boundary = detect_horizontal_boundary(img) if args.align_fog else None
    cropped = crop_to_aspect(img, args.width, args.height, boundary, args.target_boundary_y)
    resized = cropped.resize((args.width, args.height), Image.Resampling.NEAREST)
    final = quantize_rgb(resized)
    out.parent.mkdir(parents=True, exist_ok=True)
    final.save(out)
    if boundary is None:
        print(f"done {out} {final.size}")
    else:
        print(f"done {out} {final.size} source_boundary_y={boundary}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("input")
    parser.add_argument("output")
    parser.add_argument("width", type=int)
    parser.add_argument("height", type=int)
    parser.add_argument("--align-fog", action="store_true")
    parser.add_argument("--target-boundary-y", type=int, default=200)
    process(parser.parse_args())


if __name__ == "__main__":
    main()
