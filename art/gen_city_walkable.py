#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Regenerate area_city walkable from explicit prop footprints."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
CHAPTERS = ROOT / "chapters.json"


def apply_footprint(grid: list[list[int]], prop: dict) -> None:
    if not prop.get("isObstacle"):
        return
    x0, y0 = prop["pos"]
    w, h = prop["size"]
    fp = int(prop.get("footprint") or h)
    y_start = y0 + h - fp
    for y in range(max(0, y_start), min(len(grid), y0 + h)):
        for x in range(max(0, x0), min(len(grid[0]), x0 + w)):
            grid[y][x] = 1


def main() -> None:
    data = json.loads(CHAPTERS.read_text(encoding="utf-8"))
    chapter = next(c for c in data["chapters"] if c["id"] == "area_city")
    room = chapter["room"]
    cols, rows = room["cols"], room["rows"]
    grid = [[0 for _ in range(cols)] for _ in range(rows)]
    for x in range(cols):
        grid[0][x] = 1
        grid[rows - 1][x] = 1
    for y in range(rows):
        grid[y][0] = 1
        grid[y][cols - 1] = 1
    for prop in chapter.get("props", []):
        apply_footprint(grid, prop)
    room["walkable"] = ["".join("1" if cell else "0" for cell in row) for row in grid]
    CHAPTERS.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"updated area_city walkable {cols}x{rows}")


if __name__ == "__main__":
    main()
