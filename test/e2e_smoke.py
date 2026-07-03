#!/usr/bin/env python3
"""
凤翎工坊 · E2E 冒烟测试(一条命令跑完整功能链路)
=================================================
为什么有这个:我反复"验了一部分就说全 done"(同根因已 5 次),每次都靠用户手动验收兜底。
这个脚本把"交付前的全链路验证"自动化——机器验功能对不对,用户只验美术/手感。

覆盖咬过我们的几类 bug:
  Group FILE  数据/资源完整性(chapters.json 合法 + walkable 维度 + 资源存在)
  Group PIXEL 拆件鬼影(clean 底图擦除区无残留 + sprite 含本体)        ← 鬼影 bug
  Group LOAD  各场景加载无 JS 报错 + 渲染对视图(landing/worldmap/room/editor)
  Group DRAG  编辑器拖动→数据更新(prop + npc 都测)                    ← prop 拖不动 bug
  Group SAVE  全链路 拖动→保存→落盘 chapters.json(非破坏:自动备份还原) ← prop 存不上 bug

用法:  python3 server.py   # 另开一个终端先跑起 server
       /tmp/pil_venv/bin/python test/e2e_smoke.py     # PIL 在 venv 里(像素检查需要)
       (没 PIL 也能跑,PIXEL 组会自动跳过并标 WARN)
退出码:全过=0,有失败=1(可接 CI / pre-commit)
"""
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
BASE = os.environ.get("E2E_BASE", "http://localhost:8131")
TILE = 16

results = []  # (group, name, ok|None, detail)  None=WARN/skip


def rec(group, name, ok, detail=""):
    results.append((group, name, ok, detail))


def ns():
    return time.time_ns()


# ---------- 浏览器辅助 ----------
def dump_dom(url, budget=4500):
    try:
        r = subprocess.run(
            [CHROME, "--headless=new", "--disable-gpu", "--no-sandbox",
             "--virtual-time-budget=%d" % budget, "--dump-dom", url],
            capture_output=True, text=True, timeout=70)
        return r.stdout or ""
    except Exception as e:
        return "DUMP_ERROR " + str(e)


def parse_e2eout(dom):
    m = re.search(r"E2EOUT (\{[^<]*\})", dom)
    return json.loads(m.group(1)) if m else None


def parse_simdrag(dom):
    # (?!\$\{) 排除源码模板字面量(里面含 "PASS" 字样,会造成探针未触发时的假通过)
    m = re.search(r"SIMDRAG pid=(?!\$\{)[^<]*", dom)
    return m.group(0).strip() if m else None


def server_up():
    import urllib.request
    try:
        urllib.request.urlopen(BASE + "/chapters.json?_=%d" % ns(), timeout=5).read()
        return True
    except Exception:
        return False


# ---------- Group FILE ----------
def g_file():
    try:
        d = json.loads((ROOT / "chapters.json").read_text(encoding="utf-8"))
        rec("FILE", "chapters.json 合法 JSON", True)
    except Exception as e:
        rec("FILE", "chapters.json 合法 JSON", False, str(e))
        return None
    for c in d.get("chapters", []):
        cid = c.get("id")
        room = c.get("room", {})
        ok = bool(cid and c.get("title") and room.get("cols") and room.get("rows") and room.get("spawn"))
        rec("FILE", f"{cid} 必需字段(title/cols/rows/spawn)", ok)
        w = room.get("walkable")
        if w:
            dim_ok = len(w) == room["rows"] and all(len(r) == room["cols"] for r in w)
            rec("FILE", f"{cid} walkable 维度 {room['cols']}x{room['rows']}", dim_ok,
                "" if dim_ok else f"实际 {len(w)}行x{len(w[0]) if w else 0}列")
    # 资源存在(底图 + 所有 sprite)
    for c in d.get("chapters", []):
        room = c.get("room", {})
        if room.get("bgImage"):
            p = ROOT / "art/out" / (room["bgImage"] + ".png")
            rec("FILE", f"{c['id']} 底图 {room['bgImage']}.png 存在", p.exists() and p.stat().st_size > 0)
        for pr in c.get("props", []):
            if pr.get("sprite"):
                p = ROOT / "art/out" / (pr["sprite"] + ".png")
                rec("FILE", f"{c['id']} 物件 sprite {pr['sprite']}.png 存在", p.exists() and p.stat().st_size > 0)
    # 可交互物件:至少有一个 prop 勾了 isInteractable 且填了 interactText(否则"可交互"是空壳)
    inter = [pr for c in d.get("chapters", []) for pr in c.get("props", []) if pr.get("isInteractable") and (pr.get("interactText") or "").strip()]
    rec("FILE", "存在可交互物件(isInteractable+interactText)", len(inter) > 0, f"{len(inter)} 个" if inter else "无")
    # ch1-3 不再是"空盒子":每章 ≥3 个带 interactText 的物件(对话点名的物证落地)
    for cid in ("ch1", "ch2", "ch3"):
        cc = next((c for c in d["chapters"] if c["id"] == cid), {})
        ip = [p for p in cc.get("props", []) if p.get("isInteractable") and (p.get("interactText") or "").strip()]
        rec("FILE", f"{cid} 线框物件 ≥3(空盒子修复)", len(ip) >= 3, f"{len(ip)} 个")
        has_clue_action = any(a.get("type") == "addClue" for p in cc.get("props", []) for a in (p.get("actions") or []))
        has_revisit = any(n.get("dialogPages") for n in cc.get("npcs", []))
        rec("FILE", f"{cid} 内容密度:线索+触发器+回访对话", bool(cc.get("clues") and cc.get("triggers") and has_clue_action and has_revisit))
    ch3 = next((c for c in d["chapters"] if c["id"] == "ch3"), {})
    finale = next((t for t in ch3.get("triggers", []) if t.get("id") == "tr_ch3_tonight_finale"), None)
    rec("FILE", "今夜终局:minClues 条件+完结动作", bool(finale and finale.get("conditions", {}).get("minClues") and len(finale.get("actions", [])) >= 4))
    # 第二种创作模式:eventDemo 事件树完整
    nodes = d.get("eventDemo", {}).get("events", {}).get("nodes", [])
    rec("FILE", "第二模式 eventDemo 事件树完整", len(nodes) >= 3, f"{len(nodes)} 节点")
    # 世界地图 v2 数据完整性
    w2 = d.get("worldmapV2", {})
    fogs = w2.get("fogRegions", [])
    locs = w2.get("region", {}).get("locations", [])
    rec("FILE", "worldmapV2 战雾 8 区 + 地点 3 个", len(fogs) == 8 and len(locs) == 3, f"fog={len(fogs)} loc={len(locs)}")
    if w2:
        ok_img = (ROOT / "art/out" / (w2.get("mapImage", "") + ".png")).exists()
        rec("FILE", "澜洲大陆图资源存在", ok_img)
        ch_ids = {c["id"] for c in d.get("chapters", [])}
        bad = [f["ch"] for l in locs for f in l.get("facilities", []) if f["ch"] not in ch_ids]
        thumbs_ok = all((ROOT / "art/out" / (l["thumb"] + ".png")).exists() for l in locs)
        rec("FILE", "地点设施→章节映射有效 + 缩略图存在", not bad and thumbs_ok, f"坏映射:{bad}" if bad else "")
    return d


# ---------- Group PIXEL(拆件鬼影)----------
def cyan_count(px, x0, y0, x1, y1):
    n = 0
    for y in range(y0, y1):
        for x in range(x0, x1):
            r, g, b = px[x, y][:3]
            if g > 95 and b > 95 and g + b > r * 2.2 and r < 130:
                n += 1
    return n


def g_pixel(d):
    try:
        from PIL import Image
    except Exception:
        rec("PIXEL", "拆件鬼影检查(需 PIL)", None, "PIL 不可用,跳过;用 /tmp/pil_venv/bin/python 跑可启用")
        return
    if not d:
        return
    ch4 = next((c for c in d["chapters"] if c["id"] == "ch4"), None)
    if not ch4:
        return
    console = next((p for p in ch4.get("props", []) if p["id"] == "console_center"), None)
    if not console or not ch4["room"].get("bgImage"):
        return
    px0, py0 = console["pos"]
    sw, sh = console["size"]
    clean = Image.open(ROOT / "art/out" / (ch4["room"]["bgImage"] + ".png")).convert("RGB").load()
    # clean 底图监测台框内不应有青绿屏幕残留(鬼影)
    resid = cyan_count(clean, px0 * TILE, py0 * TILE, (px0 + sw) * TILE, (py0 + sh) * TILE)
    rec("PIXEL", "clean 底图擦除区无监测台残留(青绿=0)", resid == 0, f"残留 {resid} 像素")
    # sprite 应含监测台屏幕(青绿>0)
    spr = Image.open(ROOT / "art/out" / (console["sprite"] + ".png")).convert("RGB")
    sp = spr.load()
    in_spr = cyan_count(sp, 0, 0, spr.width, spr.height)
    rec("PIXEL", "监测台 sprite 含屏幕(青绿>0)", in_spr > 0, f"{in_spr} 像素")


# ---------- Group LOAD(场景加载无报错)----------
def g_load():
    scenes = [
        ("landing", f"{BASE}/index.html?e2e=1&_={ns()}", "landing", 4500),
        ("worldmap", f"{BASE}/index.html?e2e=1&skip-landing=1&_={ns()}", "worldmap", 4500),
        ("room ch1", f"{BASE}/index.html?e2e=1&room=ch1&_={ns()}", "room", 20000),
        ("room ch4", f"{BASE}/index.html?e2e=1&room=ch4&_={ns()}", "room", 20000),
        ("editor ch4", f"{BASE}/index.html?e2e=1&edit=ch4&_={ns()}", "editor", 12000),
    ]
    for label, url, want_view, budget in scenes:
        dom = dump_dom(url, budget)
        out = parse_e2eout(dom)
        if not out:
            rec("LOAD", f"{label} 加载探针", False, "未拿到 E2EOUT(页面没起来?)")
            continue
        view_ok = out.get("view") == want_view
        errs = out.get("errors", [])
        rec("LOAD", f"{label} 渲染对视图({want_view})", view_ok, "" if view_ok else f"实际 view={out.get('view')}")
        rec("LOAD", f"{label} 无 JS 加载错误", len(errs) == 0, "" if not errs else "; ".join(errs[:3]))


# ---------- Group DRAG(拖动→数据)----------
def g_drag():
    cases = [("prop console_center", "console_center", "18,5"),
             ("npc se12", "se12", "20,9")]
    # 大门(传送口)可拖:在监测带编辑器里拖 6号站大门
    dom_g = dump_dom(f"{BASE}/index.html?edit=area_belt&simdrag=ch4:36,20&_={ns()}", 5500)
    sg = parse_simdrag(dom_g)
    rec("DRAG", "大门(传送口) 拖动→at 更新", bool(sg and "PASS" in sg), sg or "无 SIMDRAG 输出")
    for label, uid, target in cases:
        dom = dump_dom(f"{BASE}/index.html?edit=ch4&simdrag={uid}:{target}&_={ns()}", 4500)
        sd = parse_simdrag(dom)
        ok = bool(sd and "PASS" in sd)
        rec("DRAG", f"{label} 拖动→pos 更新", ok, sd or "无 SIMDRAG 输出")


# ---------- Group INTERACT(可交互物件:走近触发 interactText)----------
def parse_simact(dom, pid):
    m = re.search(r"SIMACT " + re.escape(pid) + r"[^<]*", dom)  # 用已解析的 pid 匹配,避开源码里的 ${simact} 模板
    return m.group(0) if m else None


def g_interact():
    # 房间 Phaser 启动在 headless 里时序 flaky;重试至多 2 次,给慢启动留余量
    sa = None
    for _ in range(2):
        dom = dump_dom(f"{BASE}/index.html?room=ch4&simact=dock_slots&_={ns()}", 15000)
        sa = parse_simact(dom, "dock_slots")
        if sa and "PASS" in sa:
            break
    ok = bool(sa and "PASS" in sa)
    rec("INTERACT", "可交互物件 走近→空格→弹出 interactText", ok, sa or "无 SIMACT 输出(房间没起来?)")
    # tile 模式房间(线框物件)也要能触发
    sb = None
    for _ in range(2):
        dom = dump_dom(f"{BASE}/index.html?room=ch3&simact=interview_table&_={ns()}", 15000)
        m = re.search(r"SIMACT interview_table[^<]*", dom)
        if m and "PASS" in m.group(0): sb = m.group(0); break
        if m: sb = m.group(0)
    rec("INTERACT", "sprite物件(ch3 约谈桌) 触发独白", bool(sb and "PASS" in sb), sb or "无输出")
    # 隔离栏段雾墙热区(批次2卡要求:noSprite 热区在新底图下仍可触发,"看得见进不去"的叙事承载)
    sc = None
    for _ in range(2):
        dom = dump_dom(f"{BASE}/index.html?room=area_edge&simact=fogwall_w&_={ns()}", 15000)
        m = re.search(r"SIMACT fogwall_w[^<]*", dom)
        if m and "PASS" in m.group(0): sc = m.group(0); break
        if m: sc = m.group(0)
    rec("INTERACT", "雾墙热区(area_edge) 触发独白", bool(sc and "PASS" in sc), sc or "无输出")
    # 地貌语义层(压街警告的前提):城市必须识别出路网 ON,荒地必须正确判 OFF(防误报)
    # (?!\$\{) 避开源码模板字面量——parse_simdrag 同款坑
    dom = dump_dom(f"{BASE}/index.html?edit=area_city&streetprobe=1&_={ns()}", 9000)
    m = re.search(r"STREETMASK (?!\$\{)(ON|OFF)[^<]*", dom)
    rec("INTERACT", "地貌语义:临澜城路网识别 ON", bool(m and m.group(1) == "ON"), m.group(0) if m else "无探针输出")
    dom = dump_dom(f"{BASE}/index.html?edit=area_belt&streetprobe=1&_={ns()}", 9000)
    m = re.search(r"STREETMASK (?!\$\{)(ON|OFF)[^<]*", dom)
    rec("INTERACT", "地貌语义:监测带荒地判 OFF(防误报)", bool(m and m.group(1) == "OFF"), m.group(0) if m else "无探针输出")


# ---------- Group AREA(区域大地图:数据/连通/镜头跟随/大门)----------
def g_area(d):
    areas = [c for c in d.get("chapters", []) if c.get("area")]
    rec("AREA", "3 个区域章存在(city/belt/edge)", len(areas) == 3, f"{[a['id'] for a in areas]}")
    for a in areas:
        room = a["room"]
        w = room["walkable"]
        dim_ok = len(w) == room["rows"] and all(len(r) == room["cols"] for r in w)
        img_ok = (ROOT / "art/out" / (room["bgImage"] + ".png")).exists()
        gates_ok = all(any(c["id"] == g["to"] for c in d["chapters"]) for g in a.get("gates", []))
        rec("AREA", f"{a['id']} 数据完整(walkable维度/底图/大门映射)", dim_ok and img_ok and gates_ok)
        fp_bad = []
        for p in a.get("props", []):
            if not p.get("isObstacle"):
                continue
            x0, y0 = p["pos"]
            sw, sh = p["size"]
            fp = int(p.get("footprint") or sh)
            for yy in range(y0 + sh - fp, y0 + sh):
                for xx in range(x0, x0 + sw):
                    if not (0 <= xx < room["cols"] and 0 <= yy < room["rows"]):
                        continue
                    if w[yy][xx] != "1":
                        fp_bad.append(f"{p['id']}@{xx},{yy}")
        rec("AREA", f"{a['id']} isObstacle footprint 全写入 walkable", not fp_bad, ";".join(fp_bad[:8]))
        if a.get("id") == "area_edge":
            locked = all(set(row) == {"1"} for row in w[:13])
            rec("AREA", "area_edge 雾区 rows0-12 全封锁", locked)
        # BFS:出生点 → 所有大门/NPC/交互点footprint邻格 连通
        grid = [[1 if ch == "1" else 0 for ch in row] for row in w]
        sx, sy = room["spawn"]
        seen = {(sx, sy)}; q = [(sx, sy)]
        while q:
            x, y = q.pop()
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                nx, ny = x + dx, y + dy
                if 0 <= nx < room["cols"] and 0 <= ny < room["rows"] and grid[ny][nx] == 0 and (nx, ny) not in seen:
                    seen.add((nx, ny)); q.append((nx, ny))
        bad = []
        for g in a.get("gates", []):
            if tuple(g["at"]) not in seen: bad.append("gate:" + g["to"])
        for n in a.get("npcs", []):
            # NPC 站位本身占格,可达=其位或邻格在 seen
            px, py = n["pos"]
            near = {(px, py), (px+1, py), (px-1, py), (px, py+1), (px, py-1)}
            if not (near & seen): bad.append("npc:" + n["id"])
        for p in a.get("props", []):
            if p.get("isInteractable"):
                x0, y0 = p["pos"]; x1, y1 = x0 + p["size"][0] - 1, y0 + p["size"][1] - 1
                ring = {(x, y0-1) for x in range(x0-1, x1+2)} | {(x, y1+1) for x in range(x0-1, x1+2)} | \
                       {(x0-1, y) for y in range(y0-1, y1+2)} | {(x1+1, y) for y in range(y0-1, y1+2)} | \
                       {(x, y) for y in range(y0, y1+1) for x in range(x0, x1+1)}
                if not (ring & seen): bad.append("prop:" + p["id"])
        rec("AREA", f"{a['id']} BFS:出生点→大门/NPC/交互点全连通", not bad, ";".join(bad))
    # 镜头跟随(headless RAF 会冻结,探针自带同步 centerOn;重试抗 flaky)
    cam = None
    for _ in range(3):
        dom = dump_dom(f"{BASE}/index.html?room=area_city&camprobe=1&_={ns()}", 15000)
        m = re.search(r"CAMPROBE big=(?:true|false)[^<]*", dom)
        if m: cam = m.group(0); break
    rec("AREA", "镜头跟随:大地图传送→相机滚动+夹紧", bool(cam and "PASS" in cam), cam or "探针未触发")
    # 大门:监测带走进 6号站 → 切到 ch4
    gate = None
    for _ in range(3):
        dom = dump_dom(f"{BASE}/index.html?room=area_belt&simgate=ch4&_={ns()}", 15000)
        m = re.search(r"SIMGATE target=ch4[^<]*", dom)
        if m: gate = m.group(0); break
    rec("AREA", "大门:走上门格→进入设施场景", bool(gate and "PASS" in gate), gate or "探针未触发")
    props = None
    for _ in range(3):
        dom = dump_dom(f"{BASE}/index.html?room=area_city&propsprobe=charge_post,notice_screen&_={ns()}", 15000)
        m = re.search(r"PROPSPROBE [^<]*", dom)
        if m:
            props = m.group(0)
            break
    rec("AREA", "area_city 可交互 sprite 进入渲染列表", bool(props and "PASS" in props), props or "探针未触发")


# ---------- Group WORLDMAP(世界地图 v2:澜洲大陆+战雾+地点+面板)----------
def g_worldmap():
    dom = dump_dom(f"{BASE}/index.html?skip-landing=1&_={ns()}", 5000)
    fog = len(re.findall(r'class="wm2-fog"', dom))
    locs = len(re.findall(r'class="wm2-loc[" ]', dom))
    has_map = 'wm2-map' in dom and 'worldmap_lanzhou' in dom
    rec("WORLDMAP", "大陆图渲染 + 8 战雾标签 + 3 地点徽章", has_map and fog == 8 and locs == 3, f"map={has_map} fog={fog} loc={locs}")
    dom2 = dump_dom(f"{BASE}/index.html?skip-landing=1&wmsel=linlan_city&_={ns()}", 5500)
    ok2 = ("临澜城" in dom2 and "dt-fac" in dom2 and "管理局总部" in dom2)
    rec("WORLDMAP", "地点档案面板(缩略图/设施/人物)打开", ok2)
    dom3 = dump_dom(f"{BASE}/index.html?skip-landing=1&wmregion=1&_={ns()}", 5500)
    ok3 = ("关键历史节点" in dom3 and "灰澜区" in dom3)
    rec("WORLDMAP", "区域档案面板(主线/历史节点)打开", ok3)
    # × 关闭回归(closeDetail 必须挂 window,主脚本在 IIFE 里)
    dom4 = dump_dom(f"{BASE}/index.html?skip-landing=1&wmsel=linlan_city&simclose=1&_={ns()}", 6000)
    m4 = re.search(r"SIMCLOSE [^<]*", dom4)
    rec("WORLDMAP", "面板 × 关闭→面板收起+地图回中+无JS错误", bool(m4 and "PASS" in m4.group(0)), m4.group(0) if m4 else "无 SIMCLOSE 输出")


# ---------- Group EVENT(第二种创作模式:播放器 + 编辑器)----------
def g_event():
    dom = dump_dom(f"{BASE}/index.html?event=1&_={ns()}", 4500)
    m = re.search(r'id="evText"[^>]*>([^<]+)', dom)
    has_text = bool(m and m.group(1).strip())
    has_choice = 'id="evChoices"' in dom and ("继续" in dom or "结束" in dom or "branch" in dom)
    rec("EVENT", "事件主导模式 加载→渲染场景文字+推进按钮", has_text and has_choice,
        (m.group(1)[:22] if m else "无 evText"))
    # 事件编辑器:加载出 IDE 视图(节点列表+Inspector)
    dom2 = dump_dom(f"{BASE}/index.html?editevent=1&e2e=1&_={ns()}", 5000)
    out2 = parse_e2eout(dom2)
    ok2 = bool(out2 and out2.get("view") == "eventedit" and not out2.get("errors"))
    has_cards = "eve-card" in dom2 and "EVENT EDITOR" in dom2
    rec("EVENT", "事件编辑器 加载(视图+节点卡片+无JS错误)", ok2 and has_cards,
        "" if ok2 else f"probe={out2}")
    # 编辑器改文案→保存→落盘(备份还原)
    path = ROOT / "chapters.json"
    backup = path.read_text(encoding="utf-8")
    try:
        dom3 = dump_dom(f"{BASE}/index.html?editevent=1&simevsave=1&_={ns()}", 6500)
        sv = re.search(r"EVSAVE [^<]*", dom3)
        disk = json.loads(path.read_text(encoding="utf-8"))
        marked = disk.get("eventDemo", {}).get("events", {}).get("nodes", [{}])[0].get("text", "").startswith("【E2E】")
        ok3 = bool(sv and "PASS" in sv.group(0) and marked)
        rec("EVENT", "事件编辑器 改文案→保存→落盘 chapters.json", ok3,
            f"{sv.group(0) if sv else '无EVSAVE'} disk标记={marked}")
    finally:
        path.write_text(backup, encoding="utf-8")
        restored = not json.loads(path.read_text(encoding="utf-8"))["eventDemo"]["events"]["nodes"][0]["text"].startswith("【E2E】")
        rec("EVENT", "事件树测试后已还原", restored)


# ---------- Group GAMEPLAY(M5:NPC行为/条件对话页/触发器)----------
def g_gameplay(d):
    if not d:
        return
    # 数据层:behavior 取值合法 + patrol waypoints 全可走 + wander range 合法
    for c in d.get("chapters", []):
        w = c.get("room", {}).get("walkable")
        for n in c.get("npcs", []):
            b = n.get("behavior")
            if not b:
                continue
            rec("GAMEPLAY", f"{c['id']}/{n['id']} behavior 取值合法", b in ("static", "wander", "patrol"), b)
            if b == "patrol":
                wps = n.get("waypoints", [])
                bad = []
                if w:
                    bad = [wp for wp in wps if not (0 <= wp[1] < len(w) and 0 <= wp[0] < len(w[0]) and w[wp[1]][wp[0]] == "0")]
                rec("GAMEPLAY", f"{c['id']}/{n['id']} 巡逻路径点全可走", len(wps) >= 2 and not bad,
                    f"{len(wps)}点 坏点:{bad}" if bad else f"{len(wps)} 点")
    # 数据层:触发器 schema(id/at/type/actions 必填,type 合法)
    trig_n = 0
    for c in d.get("chapters", []):
        for t in c.get("triggers", []):
            trig_n += 1
            ok = bool(t.get("id") and t.get("at") and t.get("type") in ("enter", "leave", "auto") and isinstance(t.get("actions"), list) and t["actions"])
            rec("GAMEPLAY", f"{c['id']} 触发器 {t.get('id','?')} schema 完整", ok)
    rec("GAMEPLAY", "演示触发器存在(ch4 auto + edge enter)", trig_n >= 2, f"{trig_n} 个")
    # 数据层:条件页各自有节点；首次 dialogue 是统一兜底，不要求复制一份无条件末页
    for c in d.get("chapters", []):
        for n in c.get("npcs", []):
            pages = n.get("dialogPages")
            if pages:
                all_dlg = all(p.get("dialogue", {}).get("nodes") for p in pages)
                base_ok = bool(n.get("dialogue", {}).get("nodes"))
                rec("GAMEPLAY", f"{c['id']}/{n['id']} dialogPages 各页有节点+首次对话兜底", base_ok and all_dlg)
    # 行为探针:patrol/wander NPC 在虚拟时间内真的移动了(重试抗 flaky)
    for label, room, npc in [("patrol(FS-7800)", "area_city", "patrol78"), ("wander(陈伯)", "area_city", "citizen_lin")]:
        pr = None
        for _ in range(2):
            dom = dump_dom(f"{BASE}/index.html?room={room}&npcprobe={npc}&_={ns()}", 15000)
            m = re.search(r"NPCPROBE (?!\$\{)" + re.escape(npc) + r"[^<]*", dom)
            if m and "PASS" in m.group(0):
                pr = m.group(0); break
            if m: pr = m.group(0)
        rec("GAMEPLAY", f"NPC {label} 行为驱动:离开出生格", bool(pr and "PASS" in pr), pr or "探针未触发")
    # 触发器探针:ch4 auto 开场 + edge enter 走近雾墙
    for label, url_part, tid in [("auto(ch4 开场)", "room=ch4", "tr_ch4_arrival"), ("enter(edge 雾墙)", "room=area_edge", "tr_edge_fog_west")]:
        tr = None
        for _ in range(2):
            dom = dump_dom(f"{BASE}/index.html?{url_part}&simtrig={tid}&_={ns()}", 15000)
            m = re.search(r"SIMTRIG (?!\$\{)" + re.escape(tid) + r"[^<]*", dom)
            if m and "PASS" in m.group(0):
                tr = m.group(0); break
            if m: tr = m.group(0)
        rec("GAMEPLAY", f"触发器 {label} 真实链路触发", bool(tr and "PASS" in tr), tr or "探针未触发")
    # 点击寻路:监测带出生点(3,17) → 相邻可走格(4,17)
    tap = None
    for _ in range(2):
        dom = dump_dom(f"{BASE}/index.html?room=area_belt&tapto=4,17&_={ns()}", 9000)
        m = re.search(r"TAPMOVE (?!\$\{)[^<]*", dom)
        if m and "PASS" in m.group(0): tap = m.group(0); break
        if m: tap = m.group(0)
    rec("GAMEPLAY", "点击目标格→BFS 自动寻路到达", bool(tap and "PASS" in tap), tap or "探针未触发")
    # 条件对话页探针:SE-12 默认页 vs flag 后再访页
    pg1 = None
    for _ in range(2):
        dom = dump_dom(f"{BASE}/index.html?room=ch4&simpage=se12&_={ns()}", 15000)
        m = re.search(r"SIMPAGE (?!\$\{)se12[^<]*", dom)
        if m: pg1 = m.group(0); break
    ok1 = bool(pg1 and "PASS" in pg1 and "待机灯亮着" in pg1)
    rec("GAMEPLAY", "条件对话页:无 flag → 默认页(原对话)", ok1, pg1 or "探针未触发")
    pg2 = None
    for _ in range(2):
        dom = dump_dom(f"{BASE}/index.html?room=ch4&setflag=se12_met&simpage=se12&_={ns()}", 15000)
        m = re.search(r"SIMPAGE (?!\$\{)se12[^<]*", dom)
        if m: pg2 = m.group(0); break
    ok2 = bool(pg2 and "PASS" in pg2 and "没有再抬头" in pg2)
    rec("GAMEPLAY", "条件对话页:flag 满足 → 切再访页", ok2, pg2 or "探针未触发")
    # ---- M6 调查日志 + 道具钥匙闭环 ----
    # 数据层:clues schema + requiresItem 必须有人给(钥匙闭环不能死锁)
    all_clues = [(c["id"], cl) for c in d.get("chapters", []) for cl in c.get("clues", [])]
    for cid, cl in all_clues:
        rec("GAMEPLAY", f"{cid} 线索 {cl.get('id','?')} schema(id/name/detail)", bool(cl.get("id") and cl.get("name") and cl.get("detail")))
    rec("GAMEPLAY", "演示线索 ≥2(气闸标签+雾边线)", len(all_clues) >= 2, f"{len(all_clues)} 条")
    givers = {p.get("givesItemId") for c in d.get("chapters", []) for p in c.get("props", []) if p.get("givesItemId")}
    needers = [(c["id"], p["id"], p["requiresItem"]) for c in d.get("chapters", []) for p in c.get("props", []) if p.get("requiresItem")]
    needers += [(c["id"], "gate→" + g["to"], g["requiresItem"]) for c in d.get("chapters", []) for g in c.get("gates", []) if g.get("requiresItem")]
    orphan = [n for n in needers if n[2] not in givers]
    rec("GAMEPLAY", "钥匙闭环:每个 requiresItem 都有物件给出(无死锁)", not orphan, str(orphan) if orphan else f"{len(needers)} 处门锁/{len(givers)} 种钥匙")
    # 探针:补给箱给道具 → 气闸门锁定/解锁双分支 → addClue 落日志
    sa = None
    for _ in range(2):
        dom = dump_dom(f"{BASE}/index.html?room=area_belt&simact=crate&_={ns()}", 15000)
        m = re.search(r"SIMACT crate[^<]*", dom)
        if m and "PASS" in m.group(0): sa = m.group(0); break
        if m: sa = m.group(0)
    rec("GAMEPLAY", "道具:补给箱交互→获得值守密卡", bool(sa and "PASS" in sa and "inv=keycard_belt" in sa), sa or "探针未触发")
    sb = None
    for _ in range(2):
        dom = dump_dom(f"{BASE}/index.html?room=ch4&simact=airlock_gate&_={ns()}", 15000)
        m = re.search(r"SIMACT airlock_gate[^<]*", dom)
        if m: sb = m.group(0); break
    rec("GAMEPLAY", "钥匙门:无密卡→锁定提示(红灯)", bool(sb and "PASS" in sb and "红灯" in sb and "clues=-" in sb), sb or "探针未触发")
    sc = None
    for _ in range(2):
        dom = dump_dom(f"{BASE}/index.html?room=ch4&giveitem=keycard_belt&simact=airlock_gate&simadvance=1&_={ns()}", 15000)
        m = re.search(r"SIMACT airlock_gate[^<]*", dom)
        if m and "clue_airlock" in m.group(0): sc = m.group(0); break
        if m: sc = m.group(0)
    rec("GAMEPLAY", "钥匙门:有密卡→解锁文本+addClue 落日志", bool(sc and "PASS" in sc and "clues=clue_airlock" in sc), sc or "探针未触发")
    # 调查日志 UI:空档案=N 张待揭露占位;预置线索=名称+详情上卡
    dom = dump_dom(f"{BASE}/index.html?skip-landing=1&journal=1&_={ns()}", 6500)
    locked = len(re.findall(r'class="rec-card clue-locked"', dom))
    rec("GAMEPLAY", "调查日志:空档案显示全部待揭露占位", locked == len(all_clues) and "调查日志" in dom, f"占位 {locked}/{len(all_clues)}")
    dom = dump_dom(f"{BASE}/index.html?skip-landing=1&journal=1&preclue=clue_fogline&_={ns()}", 6500)
    ok_j = ("雾的边线从未移动" in dom and "它在保持" in dom and len(re.findall(r'class="rec-card clue-locked"', dom)) == len(all_clues) - 1)
    rec("GAMEPLAY", "调查日志:已揭露卡显示名称+可展开详情", ok_j)
    # server 行为字段存盘往返(非破坏:备份还原)
    path = ROOT / "chapters.json"
    backup = path.read_text(encoding="utf-8")
    try:
        import urllib.request
        req = urllib.request.Request(f"{BASE}/api/save-chapter",
            data=json.dumps({"chapterId": "area_city", "patch": {"npcs": [{"id": "citizen_lin", "pos": [66, 54], "behavior": "wander", "range": 4}]}}).encode(),
            headers={"Content-Type": "application/json"}, method="POST")
        out = json.loads(urllib.request.urlopen(req, timeout=10).read())
        disk = json.loads(path.read_text(encoding="utf-8"))
        nn = next(n for c in disk["chapters"] if c["id"] == "area_city" for n in c["npcs"] if n["id"] == "citizen_lin")
        ok = out.get("ok") and nn.get("behavior") == "wander" and nn.get("range") == 4
        rec("GAMEPLAY", "NPC 行为 编辑器patch→server→落盘", ok, f"disk behavior={nn.get('behavior')} range={nn.get('range')}")
        # 台词编辑器写入通道:dialogue + 条件回访页一并 merge，不丢其他 NPC 字段
        original = next(n for c in disk["chapters"] if c["id"] == "ch1" for n in c["npcs"] if n["id"] == "qinwang")
        dialogue = json.loads(json.dumps(original["dialogue"]))
        dialogue["nodes"][0]["text"] = "【E2E】创作者改写的第一句台词"
        pages = json.loads(json.dumps(original.get("dialogPages") or []))
        req2 = urllib.request.Request(f"{BASE}/api/save-chapter",
            data=json.dumps({"chapterId": "ch1", "patch": {"npcs": [{"id": "qinwang", "dialogue": dialogue, "dialogPages": pages}]}}).encode(),
            headers={"Content-Type": "application/json"}, method="POST")
        out2 = json.loads(urllib.request.urlopen(req2, timeout=10).read())
        disk2 = json.loads(path.read_text(encoding="utf-8"))
        qin = next(n for c in disk2["chapters"] if c["id"] == "ch1" for n in c["npcs"] if n["id"] == "qinwang")
        rec("GAMEPLAY", "NPC 台词编辑 dialogue+dialogPages→server→落盘", bool(out2.get("ok") and qin["dialogue"]["nodes"][0]["text"].startswith("【E2E】") and qin.get("dialogPages") == pages))
    finally:
        path.write_text(backup, encoding="utf-8")
        rest = json.loads(path.read_text(encoding="utf-8"))
        rn = next(n for c in rest["chapters"] if c["id"] == "area_city" for n in c["npcs"] if n["id"] == "citizen_lin")
        bn = next(n for c in json.loads(backup)["chapters"] if c["id"] == "area_city" for n in c["npcs"] if n["id"] == "citizen_lin")
        rec("GAMEPLAY", "行为字段测试后已还原", rn == bn)


# ---------- Group AICMD(M7:/api/command 意图级命令 + AI 命令层,非破坏)----------
def _post_json(url, payload):
    import urllib.request
    req = urllib.request.Request(url, data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read())
    except Exception as e:
        try:
            return json.loads(e.read())  # 422 等带 body 的错误响应
        except Exception:
            return {"ok": False, "error": str(e)}


def g_aicmd():
    path = ROOT / "chapters.json"
    backup = path.read_text(encoding="utf-8")
    try:
        # ① place_prop clone:落盘 + footprint 烧录 + BFS 仍连通
        r = _post_json(f"{BASE}/api/command", {"intent": "place_prop", "chapterId": "area_city",
                                               "params": {"type": "广场报刊亭", "near": "陈伯"}})
        ok1 = r.get("ok") and r.get("action") == "clone" and r.get("pos")
        disk = json.loads(path.read_text(encoding="utf-8"))
        c = next(x for x in disk["chapters"] if x["id"] == "area_city")
        newp = next((p for p in c["props"] if p["id"] == r.get("propId")), None)
        burned = False
        if newp and newp.get("isObstacle"):
            x0, y0 = newp["pos"]; sw, sh = newp["size"]; fp = int(newp.get("footprint") or sh)
            w = c["room"]["walkable"]
            burned = all(w[y][x] == "1" for y in range(y0 + sh - fp, y0 + sh) for x in range(x0, x0 + sw))
        rec("AICMD", "place_prop:意图→搜合法位→落盘+烧录", bool(ok1 and newp and burned), str(r)[:90])
        # ② set_npc_behavior patrol:自动生成环线 + 落盘
        r2 = _post_json(f"{BASE}/api/command", {"intent": "set_npc_behavior", "chapterId": "area_city",
                                                "params": {"npc": "陈伯", "behavior": "patrol"}})
        disk2 = json.loads(path.read_text(encoding="utf-8"))
        lin = next(n for x in disk2["chapters"] if x["id"] == "area_city" for n in x["npcs"] if n["id"] == "citizen_lin")
        ok2 = r2.get("ok") and lin.get("behavior") == "patrol" and len(lin.get("waypoints", [])) >= 4
        rec("AICMD", "set_npc_behavior:巡逻+自动环线生成+落盘", bool(ok2), str(r2)[:90])
        # ③ move 模式:挪动已有物件
        r3 = _post_json(f"{BASE}/api/command", {"intent": "place_prop", "chapterId": "area_city",
                                                "params": {"type": r.get("propId"), "near": "管理局总部", "mode": "move"}})
        rec("AICMD", "place_prop move:挪动已有物件", bool(r3.get("ok") and r3.get("action") == "move"), str(r3)[:90])
        # ④ 自然语言(规则解析兜底):游走
        r4 = _post_json(f"{BASE}/api/ai-command", {"text": "让陈伯随便走走", "chapterId": "area_city"})
        rec("AICMD", "ai-command:说人话→意图→执行(规则兜底)", bool(r4.get("ok") and r4.get("behavior") == "wander"),
            f"engine={r4.get('engine')} {str(r4)[:70]}")
        # ⑤ 防呆:不存在的物件 → 友好报错带词汇表
        r5 = _post_json(f"{BASE}/api/command", {"intent": "place_prop", "chapterId": "area_city",
                                                "params": {"type": "火箭发射台", "near": "陈伯"}})
        rec("AICMD", "防呆:未知物件→报错列出可用词汇", bool(not r5.get("ok") and "可用" in r5.get("error", "")), str(r5.get("error", ""))[:70])
        # ⑥ 编辑器 UI 链路:?aicmd= 探针(输入框→API→热更新,一次性守卫防循环克隆)
        from urllib.parse import quote
        ai = None
        for _ in range(2):
            dom = dump_dom(f"{BASE}/index.html?edit=area_city&aicmd={quote('在出生点旁边放一个广场报刊亭')}&_={ns()}", 9000)
            m = re.search(r"AICMD ok=(?!\$\{)[^<]*", dom)
            if m and "PASS" in m.group(0): ai = m.group(0); break
            if m: ai = m.group(0)
        rec("AICMD", "编辑器 AI 命令输入框→API→热更新", bool(ai and "PASS" in ai), ai or "探针未触发")
        disk3 = json.loads(path.read_text(encoding="utf-8"))
        c3 = next(x for x in disk3["chapters"] if x["id"] == "area_city")
        kiosks = [p["id"] for p in c3["props"] if p["id"].startswith("kiosk")]
        rec("AICMD", "热更新无循环克隆(aicmd 一次性守卫)", len(kiosks) <= len([p for p in c["props"] if p["id"].startswith("kiosk")]) + 1, str(kiosks))
    finally:
        path.write_text(backup, encoding="utf-8")
        rec("AICMD", "chapters.json 测试后已还原", path.read_text(encoding="utf-8") == backup)


# ---------- Group SEMANTIC(M8:语义层=原始事实,walkable=编译产物)----------
def g_semantic(d):
    # 数据层:已烘焙图的 walkable 必须 == compile(ground+props) ——"编译产物"的确定性铁证
    def compile_room(c):
        sem = c["room"].get("semantics")
        if not sem or not sem.get("ground"):
            return None
        w = [list(r) for r in sem["ground"]]
        for p in c.get("props", []):
            if not p.get("isObstacle"):
                continue
            x0, y0 = p["pos"]; sw, sh = p["size"]
            fp = int(p.get("footprint") or sh)
            for y in range(y0 + sh - fp, y0 + sh):
                for x in range(x0, x0 + sw):
                    if 0 <= y < len(w) and 0 <= x < len(w[0]):
                        w[y][x] = "1"
        return ["".join(r) for r in w]
    baked = [c for c in d.get("chapters", []) if c.get("room", {}).get("semantics")]
    rec("SEMANTIC", "至少一张图已烘焙语义层(临澜城)", any(c["id"] == "area_city" for c in baked), str([c["id"] for c in baked]))
    for c in baked:
        sem = c["room"]["semantics"]
        dims = len(sem["ground"]) == c["room"]["rows"] and all(len(r) == c["room"]["cols"] for r in sem["ground"])
        rec("SEMANTIC", f"{c['id']} semantics.ground 维度合法", dims)
        if sem.get("roads"):
            rdims = len(sem["roads"]) == c["room"]["rows"] and all(len(r) == c["room"]["cols"] for r in sem["roads"])
            rec("SEMANTIC", f"{c['id']} semantics.roads 维度合法+非空", rdims and sum(r.count("1") for r in sem["roads"]) > 0)
        comp = compile_room(c)
        rec("SEMANTIC", f"{c['id']} walkable == 编译产物(ground+footprint)", comp == c["room"]["walkable"],
            "不一致" if comp != c["room"]["walkable"] else "")
    # API 层(非破坏):污染一格 → compile 修复;无语义图 → compile 给友好拒绝
    path = ROOT / "chapters.json"
    backup = path.read_text(encoding="utf-8")
    try:
        disk = json.loads(backup)
        c = next(x for x in disk["chapters"] if x["id"] == "area_city")
        sx, sy = c["room"]["spawn"]
        w = [list(r) for r in c["room"]["walkable"]]
        w[sy][sx + 1] = "1"  # 模拟鬼影/脏数据
        c["room"]["walkable"] = ["".join(r) for r in w]
        path.write_text(json.dumps(disk, ensure_ascii=False, separators=(",", ": ")) + "\n", encoding="utf-8")
        r = _post_json(f"{BASE}/api/command", {"intent": "compile_walkable", "chapterId": "area_city"})
        disk2 = json.loads(path.read_text(encoding="utf-8"))
        c2 = next(x for x in disk2["chapters"] if x["id"] == "area_city")
        fixed = c2["room"]["walkable"][sy][sx + 1] == "0"
        rec("SEMANTIC", "compile_walkable:脏数据(模拟鬼影)被编译修正", bool(r.get("ok") and fixed), str(r)[:70])
        r2 = _post_json(f"{BASE}/api/command", {"intent": "compile_walkable", "chapterId": "area_belt"})
        rec("SEMANTIC", "无语义层图:compile 友好拒绝(fallback 不破坏)", bool(not r2.get("ok") and "烘焙" in r2.get("error", "")), str(r2.get("error", ""))[:60])
        # 手动保存 walkable → ground 同步(语义层不被手编辑甩开)
        w3 = [list(r) for r in c2["room"]["walkable"]]
        w3[sy + 1][sx] = "1"
        r3 = _post_json(f"{BASE}/api/save-chapter", {"chapterId": "area_city", "patch": {"walkable": ["".join(r) for r in w3], "spawn": [sx, sy]}})
        disk3 = json.loads(path.read_text(encoding="utf-8"))
        g3 = next(x for x in disk3["chapters"] if x["id"] == "area_city")["room"]["semantics"]["ground"]
        rec("SEMANTIC", "手动保存 walkable→ground 同步", bool("semantics.ground" in (r3.get("applied") or []) and g3[sy + 1][sx] == "1"), str(r3.get("applied")))
    finally:
        path.write_text(backup, encoding="utf-8")
        rec("SEMANTIC", "chapters.json 测试后已还原", path.read_text(encoding="utf-8") == backup)
    # 编辑器链路:simbake 探针(烘焙按钮→浏览器街道识别→落盘,测后还原)
    backup2 = path.read_text(encoding="utf-8")
    try:
        bk = None
        for _ in range(2):
            dom = dump_dom(f"{BASE}/index.html?edit=area_city&simbake=1&_={ns()}", 18000)
            m = re.search(r"SIMBAKE (?!\$\{)ground[^<]*", dom)
            if m and "PASS" in m.group(0) and "roads=0cells" not in m.group(0):
                bk = m.group(0); break
            if m: bk = m.group(0)
        rec("SEMANTIC", "编辑器「烘焙语义」按钮:浏览器识别街道→落盘", bool(bk and "PASS" in bk and "roads=0cells" not in bk), bk or "探针未触发")
    finally:
        path.write_text(backup2, encoding="utf-8")


# ---------- Group PUBLISH(F7:发布门 + 只读分享链接 + 订阅 mock,非破坏)----------
def g_publish():
    # 发布门:ch4(完整场景)应通过校验并生成 ?play 链接
    pub = None
    for _ in range(2):
        dom = dump_dom(f"{BASE}/index.html?edit=ch4&simpublish=1&_={ns()}", 9000)
        m = re.search(r"SIMPUBLISH mode=1[^<]*", dom)
        if m and "PASS" in m.group(0): pub = m.group(0); break
        if m: pub = m.group(0)
    rec("PUBLISH", "发布门:完整场景通过校验+出项目级分享链接", bool(pub and "PASS" in pub and "play=project" in pub), pub or "探针未触发")
    # 发布门:坏大门(出生点走不到)应被拦下,不出链接
    bad = None
    for _ in range(2):
        dom = dump_dom(f"{BASE}/index.html?edit=ch4&simpublish=brokengate&_={ns()}", 9000)
        m = re.search(r"SIMPUBLISH mode=brokengate[^<]*", dom)
        if m and "PASS" in m.group(0): bad = m.group(0); break
        if m: bad = m.group(0)
    rec("PUBLISH", "发布门:大门不可达→拦下不出链接", bool(bad and "PASS" in bad and "link=none" in bad), bad or "探针未触发")
    # 读者分享链接 ?play=chId:只读模式(藏创作者入口+只读角标)
    rd = None
    for _ in range(2):
        dom = dump_dom(f"{BASE}/index.html?play=ch4&readerprobe=1&_={ns()}", 15000)
        m = re.search(r"READERMODE [^<]*", dom)
        if m and "PASS" in m.group(0): rd = m.group(0); break
        if m: rd = m.group(0)
    rec("PUBLISH", "只读分享链接:藏编辑器入口+只读角标", bool(rd and "PASS" in rd), rd or "探针未触发")
    # 项目级分享链接:先落世界地图,不是把读者锁在单房间里
    rp = None
    for _ in range(2):
        dom = dump_dom(f"{BASE}/index.html?play=project&readerprobe=1&_={ns()}", 9000)
        m = re.search(r"READERPROJECT [^<]*", dom)
        if m and "PASS" in m.group(0): rp = m.group(0); break
        if m: rp = m.group(0)
    rec("PUBLISH", "项目级分享链接:只读世界地图为入口", bool(rp and "PASS" in rp), rp or "探针未触发")
    # 订阅定价区:3 档(免费/Pro¥49/IP¥199)+ 价值主张文案 + 留邮箱
    dom = dump_dom(f"{BASE}/index.html?skip-hero=1&_={ns()}", 5000)
    body = dom.split("<script")[0]  # 排除 <script> 里 buildLanding 源码的模板字面量(同 simdrag 探针的坑)
    plans = len(re.findall(r'class="lp-plan[" ]', body))  # 精确:lp-plan" 或 lp-plan featured,排除 lp-plan-name
    ok = plans == 3 and "¥49" in body and "¥199" in body and "读者永远免费" in body and "lpJoinWaitlist" in body
    rec("PUBLISH", "订阅定价区:3档+留邮箱渲染", ok, f"plans={plans} ¥49={'¥49' in body} ¥199={'¥199' in body}")
    # 免费层拦截:额度满→点新建被拦+引导升级(不落盘)
    up = None
    for _ in range(2):
        dom = dump_dom(f"{BASE}/index.html?simupgrade=1&_={ns()}", 7000)
        m = re.search(r"SIMUPGRADE [^<]*", dom)
        if m and "PASS" in m.group(0): up = m.group(0); break
        if m: up = m.group(0)
    rec("PUBLISH", "免费层拦截:额度满→引导升级Pro(不落盘)", bool(up and "PASS" in up), up or "探针未触发")


# ---------- Group SAVE(全链路 拖→存→落盘,非破坏)----------
def console_pos_on_disk():
    d = json.loads((ROOT / "chapters.json").read_text(encoding="utf-8"))
    ch4 = next(c for c in d["chapters"] if c["id"] == "ch4")
    return next(p["pos"] for p in ch4["props"] if p["id"] == "console_center")


def g_save():
    path = ROOT / "chapters.json"
    backup = path.read_text(encoding="utf-8")
    try:
        before = console_pos_on_disk()
        dom = dump_dom(f"{BASE}/index.html?edit=ch4&simdrag=console_center:19,5&simsave=1&_={ns()}", 5500)
        sd = parse_simdrag(dom)
        after = console_pos_on_disk()
        moved_disk = after != before
        ok = bool(sd and "PASS" in sd and "SAVED-to-disk" in sd and moved_disk)
        rec("SAVE", "prop 拖动→保存→落盘 chapters.json", ok, f"disk {before}->{after} | {sd}")
    finally:
        path.write_text(backup, encoding="utf-8")
        restored = console_pos_on_disk()
        bch4 = next(c for c in json.loads(backup)["chapters"] if c["id"] == "ch4")
        orig = next(p["pos"] for p in bch4["props"] if p["id"] == "console_center")
        rec("SAVE", "chapters.json 测试后已还原", restored == orig, f"还原为 {restored}")
    # 角色尺寸工作台:全局 settings 存盘往返(POST settings → 落盘 → 还原)
    backup2 = path.read_text(encoding="utf-8")
    try:
        import urllib.request
        req = urllib.request.Request(f"{BASE}/api/save-chapter",
            data=json.dumps({"settings": {"actorSize": 96, "npcSizes": {"qinwang": 24}}}).encode(),
            headers={"Content-Type": "application/json"}, method="POST")
        out = json.loads(urllib.request.urlopen(req, timeout=10).read())
        on_disk = json.loads(path.read_text(encoding="utf-8")).get("settings", {})
        ok = out.get("ok") and on_disk.get("actorSize") == 96 and on_disk.get("npcSizes", {}).get("qinwang") == 24
        rec("SAVE", "角色尺寸工作台 settings 存盘往返", ok, f"applied={out.get('applied')} disk={on_disk}")
    finally:
        path.write_text(backup2, encoding="utf-8")
        rest = json.loads(path.read_text(encoding="utf-8")).get("settings", {})
        rec("SAVE", "settings 测试后已还原", rest == json.loads(backup2).get("settings", {}), f"还原为 {rest}")


def main():
    print("=" * 64)
    print(" 凤翎工坊 · E2E 冒烟测试")
    print("=" * 64)
    if not server_up():
        print("✗ server 没跑起来:先在另一终端 `python3 server.py`(不是 http.server)")
        sys.exit(2)

    d = g_file()
    g_pixel(d)
    g_load()
    g_drag()
    g_interact()
    g_area(d)
    g_worldmap()
    g_event()
    g_gameplay(d)
    g_aicmd()
    g_semantic(d)
    g_publish()
    g_save()

    # 报告
    groups = {}
    for g, n, ok, detail in results:
        groups.setdefault(g, []).append((n, ok, detail))
    fails = 0
    warns = 0
    for g in ["FILE", "PIXEL", "LOAD", "DRAG", "INTERACT", "AREA", "WORLDMAP", "EVENT", "GAMEPLAY", "AICMD", "SEMANTIC", "PUBLISH", "SAVE"]:
        if g not in groups:
            continue
        print(f"\n[{g}]")
        for n, ok, detail in groups[g]:
            if ok is None:
                mark = "⚠ WARN"
                warns += 1
            elif ok:
                mark = "✓ PASS"
            else:
                mark = "✗ FAIL"
                fails += 1
            line = f"  {mark}  {n}"
            if detail and (ok is not True):
                line += f"   — {detail}"
            print(line)
    total = sum(1 for _, _, ok, _ in results if ok is not None)
    passed = sum(1 for _, _, ok, _ in results if ok is True)
    print("\n" + "=" * 64)
    print(f" 结果:{passed}/{total} 通过 · {fails} 失败 · {warns} 跳过/警告")
    print("=" * 64)
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
