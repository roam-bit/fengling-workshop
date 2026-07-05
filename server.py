#!/usr/bin/env python3
"""
凤翎工坊 · 本地开发 server
- 既 serve 静态文件(替代 python -m http.server)
- 又支持 POST /api/save-chapter 写回 chapters.json(编辑器一键保存的后端)

用法: cd 项目根 && python3 server.py
默认 8131 端口,与原 launch.json 兼容
"""
import http.server
import socketserver
import fcntl
import functools
import json
import os
import shutil
import sys
import threading
import time
from collections import defaultdict, deque
from pathlib import Path

PORT = int(os.environ.get('PORT', 8131))
ROOT = Path(__file__).resolve().parent
BACKUP_DIR = ROOT / 'backups'
BACKUP_KEEP = 20
AI_RATE_LIMIT = 8
AI_RATE_WINDOW = 60
_CHAPTERS_THREAD_LOCK = threading.RLock()
_AI_RATE_LOCK = threading.Lock()
_AI_REQUESTS = defaultdict(deque)


def chapters_write_lock(fn):
    """Serialize every chapters.json read-modify-write across threads and processes."""
    @functools.wraps(fn)
    def wrapped(*args, **kwargs):
        with _CHAPTERS_THREAD_LOCK:
            lock_path = ROOT / '.chapters.lock'
            with lock_path.open('a+', encoding='utf-8') as lock_file:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
                try:
                    return fn(*args, **kwargs)
                finally:
                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
    return wrapped


def create_rolling_backup(path):
    """Keep the last 20 valid pre-write snapshots instead of one fragile .bak."""
    if not path.exists():
        return
    BACKUP_DIR.mkdir(exist_ok=True)
    stamp = time.strftime('%Y%m%d-%H%M%S') + f'-{time.time_ns() % 1_000_000_000:09d}'
    shutil.copyfile(path, BACKUP_DIR / f'chapters-{stamp}.json')
    backups = sorted(BACKUP_DIR.glob('chapters-*.json'), key=lambda p: p.stat().st_mtime_ns, reverse=True)
    for old in backups[BACKUP_KEEP:]:
        old.unlink(missing_ok=True)


def write_json_atomic(path, data):
    """Write-and-replace prevents a crash from leaving a half-written JSON file."""
    tmp = path.with_name(f'.{path.name}.{os.getpid()}.{threading.get_ident()}.tmp')
    try:
        with tmp.open('w', encoding='utf-8') as f:
            f.write(json.dumps(data, ensure_ascii=False, separators=(',', ': ')) + '\n')
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def ai_request_allowed(client_ip):
    now = time.monotonic()
    with _AI_RATE_LOCK:
        q = _AI_REQUESTS[client_ip]
        while q and now - q[0] >= AI_RATE_WINDOW:
            q.popleft()
        if len(q) >= AI_RATE_LIMIT:
            return False, max(1, int(AI_RATE_WINDOW - (now - q[0])))
        q.append(now)
        return True, 0


class Handler(http.server.SimpleHTTPRequestHandler):
    def do_POST(self):
        if self.path == '/api/save-chapter':
            return self._save_chapter()
        if self.path == '/api/command':
            return self._api_command()
        if self.path == '/api/ai-command':
            return self._api_ai_command()
        return self._json(404, {'ok': False, 'error': 'route not found'})

    # ===== M7 /api/command:意图级命令注册表(编辑器 UI ∥ AI 命令层 = 同一套 API 的两个客户端) =====
    # 设计铁律:AI/客户端只表达"意图"(放什么、在谁附近),坐标搜索/合法性验证/碰撞烧录全归这里。
    def _api_command(self):
        try:
            length = int(self.headers.get('Content-Length', 0))
            body = json.loads(self.rfile.read(length))
        except Exception as e:
            return self._json(400, {'ok': False, 'error': f'bad json: {e}'})
        result = execute_command(body)
        return self._json(200 if result.get('ok') else 422, result)

    # ===== M7 /api/ai-command:自然语言→意图(DeepSeek 优先,无 key/失败自动降级规则解析) =====
    def _api_ai_command(self):
        try:
            length = int(self.headers.get('Content-Length', 0))
            body = json.loads(self.rfile.read(length))
        except Exception as e:
            return self._json(400, {'ok': False, 'error': f'bad json: {e}'})
        text = (body.get('text') or '').strip()
        ch_id = body.get('chapterId')
        if not text or not ch_id:
            return self._json(400, {'ok': False, 'error': 'missing text/chapterId'})
        allowed, retry_after = ai_request_allowed(self.client_address[0])
        if not allowed:
            return self._json(429, {'ok': False, 'error': f'AI 命令过于频繁，请 {retry_after} 秒后再试', 'retryAfter': retry_after})
        data = load_chapters()
        ch = next((c for c in data.get('chapters', []) if c.get('id') == ch_id), None)
        if not ch:
            return self._json(404, {'ok': False, 'error': f'chapter {ch_id} not found'})
        intent, engine, err = parse_intent(text, ch)
        if not intent:
            return self._json(422, {'ok': False, 'engine': engine, 'error': err or '没听懂这句话。试试:「把市集大棚放到管理局总部附近」「让陈伯巡逻」'})
        intent['chapterId'] = ch_id
        result = execute_command(intent)
        result['engine'] = engine
        result['intent'] = {k: v for k, v in intent.items() if k != 'chapterId'}
        return self._json(200 if result.get('ok') else 422, result)

    @chapters_write_lock
    def _save_chapter(self):
        try:
            length = int(self.headers.get('Content-Length', 0))
            body = json.loads(self.rfile.read(length))
        except Exception as e:
            return self._json(400, {'ok': False, 'error': f'bad json: {e}'})

        ch_id = body.get('chapterId')
        patch = body.get('patch', {})
        event_patch = body.get('eventDemo')  # 事件模式编辑器:整树替换 eventDemo(含 events.nodes/branchOutcomes)
        create = body.get('createChapter')   # 新建空白项目:追加一章(Landing「新建空白项目」最小闭环)
        settings_body = body.get('settings')  # 全局设置(角色尺寸工作台):不挂章节
        if not ch_id and not isinstance(event_patch, dict) and not isinstance(create, dict) and not isinstance(settings_body, dict):
            return self._json(400, {'ok': False, 'error': 'missing chapterId'})
        # 空 patch 早退,不动文件(避免误触发重格式化)
        if not isinstance(event_patch, dict) and not isinstance(create, dict) and not isinstance(settings_body, dict) \
                and (not patch or not any(k in patch for k in ('walkable', 'spawn', 'actorSize', 'npcs', 'props', 'gates'))):
            return self._json(200, {'ok': True, 'chapterId': ch_id, 'applied': [], 'noop': True})

        chapters_path = ROOT / 'chapters.json'
        if not chapters_path.exists():
            return self._json(500, {'ok': False, 'error': 'chapters.json missing'})

        # 写前滚动备份(保留最近 20 份，连续误保存也能回退)
        try:
            create_rolling_backup(chapters_path)
        except Exception:
            pass  # 备份失败不阻塞保存

        # 用文本级 surgical patch:只改 ch 内的 walkable/spawn/npcs[].pos,保留原始排版/缩进/紧凑度
        try:
            raw = chapters_path.read_text(encoding='utf-8')
            data = json.loads(raw)
        except Exception as e:
            return self._json(500, {'ok': False, 'error': f'parse chapters.json failed: {e}'})

        # 新建章节路径:校验 id 唯一 + room.walkable 存在后追加
        if isinstance(create, dict):
            cid = create.get('id')
            if not cid or any(c.get('id') == cid for c in data.get('chapters', [])):
                return self._json(400, {'ok': False, 'error': 'createChapter: id 缺失或已存在'})
            if not isinstance(create.get('room'), dict) or 'walkable' not in create['room']:
                return self._json(400, {'ok': False, 'error': 'createChapter: room.walkable 缺失'})
            data['chapters'].append(create)
            try:
                write_json_atomic(chapters_path, data)
            except Exception as e:
                return self._json(500, {'ok': False, 'error': f'write failed: {e}'})
            return self._json(200, {'ok': True, 'applied': ['createChapter'], 'chapterId': cid, 'savedAt': int(time.time() * 1000)})

        # 全局设置路径(角色尺寸工作台):浅合并写 data['settings'],与章节 patch 互斥
        settings_patch = body.get('settings')
        if isinstance(settings_patch, dict):
            allowed = {k: v for k, v in settings_patch.items() if k in ('actorSize', 'npcSizes')}
            if not allowed:
                return self._json(400, {'ok': False, 'error': 'settings: 无可识别字段'})
            cur = data.get('settings', {})
            cur.update(allowed)
            # actorSize=0 → 删键回引擎默认;npcSizes 里值=0 同理
            if cur.get('actorSize') == 0:
                cur.pop('actorSize', None)
            if 'npcSizes' in cur:
                cur['npcSizes'] = {k: v for k, v in cur['npcSizes'].items() if v}
                if not cur['npcSizes']:
                    cur.pop('npcSizes')
            if cur:
                data['settings'] = cur
            else:
                data.pop('settings', None)
            try:
                write_json_atomic(chapters_path, data)
            except Exception as e:
                return self._json(500, {'ok': False, 'error': f'write failed: {e}'})
            return self._json(200, {'ok': True, 'applied': ['settings'], 'savedAt': int(time.time() * 1000)})

        # 事件树整替路径:校验最小结构后写回,与章节 patch 互斥
        if isinstance(event_patch, dict):
            nodes = event_patch.get('events', {}).get('nodes')
            if not isinstance(nodes, list) or not nodes:
                return self._json(400, {'ok': False, 'error': 'eventDemo.events.nodes 缺失或为空'})
            data['eventDemo'] = event_patch
            try:
                write_json_atomic(chapters_path, data)
            except Exception as e:
                return self._json(500, {'ok': False, 'error': f'write failed: {e}'})
            return self._json(200, {'ok': True, 'applied': ['eventDemo'], 'savedAt': int(time.time() * 1000)})

        target = next((c for c in data.get('chapters', []) if c.get('id') == ch_id), None)
        if not target:
            return self._json(404, {'ok': False, 'error': f'chapter {ch_id} not found'})

        # 用 in-memory patch + 紧凑序列化(JSON 紧凑模式回写,不展开数组)
        room = target.setdefault('room', {})
        applied = []
        if 'walkable' in patch:
            room['walkable'] = patch['walkable']; applied.append('walkable')
            # M8:有语义层的图,手刷的墙/可走要同步回 ground(语义层是原始事实,不能被手编辑甩开)
            if isinstance(room.get('semantics'), dict) and room['semantics'].get('ground'):
                room['semantics']['ground'] = derive_ground(target, patch['walkable'])
                applied.append('semantics.ground')
        if 'spawn' in patch:
            room['spawn'] = patch['spawn']; applied.append('spawn')
        if 'actorSize' in patch:
            # 章节设置:角色尺寸档位(0/缺省=默认档,引擎按 bgImage 自选)
            v = patch['actorSize']
            if v:
                room['actorSize'] = v
            else:
                room.pop('actorSize', None)
            applied.append('actorSize')
        if 'npcs' in patch:
            existing = {n['id']: n for n in target.get('npcs', [])}
            for p_npc in patch['npcs']:
                nid = p_npc.get('id')
                if nid and nid in existing:
                    if 'pos' in p_npc:
                        existing[nid]['pos'] = p_npc['pos']
                    if 'dialogue' in p_npc:
                        existing[nid]['dialogue'] = p_npc['dialogue']
                    if 'dialogPages' in p_npc:
                        existing[nid]['dialogPages'] = p_npc['dialogPages']
                    for k in ('dockSize', 'noSprite', 'silent'):
                        if k in p_npc:
                            existing[nid][k] = p_npc[k]
                    # M5 NPC 行为:static 时删键保持数据干净;wander 存 range;patrol 存 waypoints
                    if 'behavior' in p_npc:
                        b = p_npc['behavior']
                        if b == 'wander':
                            existing[nid]['behavior'] = b
                            if p_npc.get('range'):
                                existing[nid]['range'] = p_npc['range']
                            existing[nid].pop('waypoints', None)  # 换行为时清掉不适用的参数
                        elif b == 'patrol':
                            existing[nid]['behavior'] = b
                            if isinstance(p_npc.get('waypoints'), list):
                                existing[nid]['waypoints'] = p_npc['waypoints']
                            existing[nid].pop('range', None)
                        else:  # static/未知 → 删键保持数据干净
                            for k in ('behavior', 'range', 'waypoints'):
                                existing[nid].pop(k, None)
            target['npcs'] = list(existing.values())
            applied.append('npcs')
        if 'props' in patch:
            # props 按 id merge:patch 键覆盖、盘上未知旧键保留(防编辑器白名单静默吃掉未来新字段——审查 P2)
            existing_p = {p.get('id'): dict(p) for p in target.get('props', [])}
            merged = []
            for pp in patch['props']:
                base = existing_p.get(pp.get('id'), {})
                base.update(pp)
                # 空串/None = 编辑器明确清空该字段 → 删键(merge 模式下唯一的删除通道)
                merged.append({k: v for k, v in base.items() if v not in ('', None)})
            target['props'] = merged
            applied.append('props')
        if 'gates' in patch and isinstance(patch['gates'], list) and patch['gates']:
            # 大门按 to 合并:位置/门牌名可改,目标设施与未知键保留
            existing_g = {g.get('to'): dict(g) for g in target.get('gates', [])}
            target['gates'] = [{**existing_g.get(g.get('to'), {}), **g} for g in patch['gates']]
            applied.append('gates')

        try:
            # 紧凑写回(无 indent),保持文件小、便于 git diff
            write_json_atomic(chapters_path, data)
        except Exception as e:
            return self._json(500, {'ok': False, 'error': f'write failed: {e}'})

        return self._json(200, {
            'ok': True,
            'chapterId': ch_id,
            'applied': applied,
            'savedAt': int(time.time() * 1000),
        })

    def do_OPTIONS(self):
        origin = self.headers.get('Origin')
        if origin and not self._same_origin(origin):
            return self._json(403, {'ok': False, 'error': 'cross-origin request denied'})
        self.send_response(204)
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()

    def _same_origin(self, origin):
        host = self.headers.get('Host', '')
        return bool(host) and origin.rstrip('/') in (f'http://{host}', f'https://{host}')

    def end_headers(self):
        # 开发期一律 no-cache(治"浏览器强缓存"老毛病)
        self.send_header('Cache-Control', 'no-store, no-cache, must-revalidate, max-age=0')
        self.send_header('Pragma', 'no-cache')
        self.send_header('Expires', '0')
        origin = self.headers.get('Origin')
        if origin and self._same_origin(origin):
            self.send_header('Access-Control-Allow-Origin', origin)
            self.send_header('Vary', 'Origin')
        super().end_headers()

    def _json(self, code, payload):
        body = json.dumps(payload, ensure_ascii=False).encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        sys.stderr.write(f'[凤翎工坊] {self.address_string()} - {fmt % args}\n')


# ============================================================
# M7 命令引擎:place_prop / set_npc_behavior(/api/command 的执行层)
# ============================================================
def load_chapters():
    return json.loads((ROOT / 'chapters.json').read_text(encoding='utf-8'))


def write_chapters(data):
    path = ROOT / 'chapters.json'
    try:
        create_rolling_backup(path)
    except Exception:
        pass
    write_json_atomic(path, data)


def _grid_of(room):
    return [[1 if ch == '1' else 0 for ch in row] for row in room['walkable']]


def _bfs_reach(grid, start):
    cols, rows = len(grid[0]), len(grid)
    sx, sy = start
    if not (0 <= sx < cols and 0 <= sy < rows) or grid[sy][sx] == 1:
        return set()
    seen = {(sx, sy)}
    q = [(sx, sy)]
    while q:
        x, y = q.pop()
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            nx, ny = x + dx, y + dy
            if 0 <= nx < cols and 0 <= ny < rows and grid[ny][nx] == 0 and (nx, ny) not in seen:
                seen.add((nx, ny))
                q.append((nx, ny))
    return seen


def _conn_ok(ch, grid):
    """出生点 → 所有大门 + NPC(邻格) + 可交互物件(环) 连通"""
    room = ch['room']
    seen = _bfs_reach(grid, room['spawn'])
    if not seen:
        return False, 'spawn 被堵死'
    for g in ch.get('gates', []):
        if tuple(g['at']) not in seen:
            return False, f"大门 {g.get('label', g.get('to'))} 不可达"
    for n in ch.get('npcs', []):
        px, py = n['pos']
        if not ({(px, py), (px + 1, py), (px - 1, py), (px, py + 1), (px, py - 1)} & seen):
            return False, f"NPC {n.get('name', n.get('id'))} 不可达"
    for p in ch.get('props', []):
        if p.get('isInteractable'):
            x0, y0 = p['pos']
            x1, y1 = x0 + p['size'][0] - 1, y0 + p['size'][1] - 1
            ring = {(x, y0 - 1) for x in range(x0 - 1, x1 + 2)} | {(x, y1 + 1) for x in range(x0 - 1, x1 + 2)} | \
                   {(x0 - 1, y) for y in range(y0 - 1, y1 + 2)} | {(x1 + 1, y) for y in range(y0 - 1, y1 + 2)} | \
                   {(x, y) for y in range(y0, y1 + 1) for x in range(x0, x1 + 1)}
            if not (ring & seen):
                return False, f"交互点 {p.get('name', p.get('id'))} 不可达"
    return True, ''


def street_mask_of(room):
    """地貌语义:逐 16px 格亮度提取街道(与编辑器 deriveStreetMask 同算法);无 PIL/无底图返回 None"""
    if not room.get('bgImage'):
        return None
    try:
        from PIL import Image
    except Exception:
        return None
    img_path = ROOT / 'art' / 'out' / (room['bgImage'] + '.png')
    if not img_path.exists():
        return None
    try:
        from PIL import Image
        img = Image.open(img_path).convert('RGB')
        cols, rows = room['cols'], room['rows']
        t = round(img.width / cols)
        px = img.load()
        lum = []
        for gy in range(rows):
            row = []
            for gx in range(cols):
                s = n = 0
                for yy in range(2, t, 5):
                    for xx in range(2, t, 5):
                        r, g, b = px[gx * t + xx, gy * t + yy]
                        s += (r + g + b) / 3
                        n += 1
                row.append(s / max(n, 1))
            lum.append(row)
        flat = sorted(v for r in lum for v in r)
        med = flat[len(flat) // 2]
        p10 = flat[len(flat) // 10]
        th = med - (med - p10) * 0.45
        mask = [[1 if v < th else 0 for v in r] for r in lum]
        frac = sum(map(sum, mask)) / (cols * rows)
        avenue = any(sum(r) > cols * 0.6 for r in mask) or \
            any(sum(mask[y][x] for y in range(rows)) > rows * 0.6 for x in range(cols))
        return mask if (0.08 < frac < 0.35 and avenue) else None
    except Exception:
        return None


def _norm(s):
    return (s or '').strip().replace('·', '').replace(' ', '').lower()


def resolve_template(data, ch, query):
    """物件模板解析:当前章 id 精确 → 名称包含 → 全项目兜底。返回模板 prop dict"""
    q = _norm(query)
    if not q:
        return None
    pools = [ch.get('props', [])] + [c.get('props', []) for c in data['chapters'] if c is not ch]
    for pool in pools:
        for p in pool:
            if _norm(p.get('id')) == q:
                return p
    for pool in pools:
        for p in pool:
            nm = _norm(p.get('name'))
            if nm and (q in nm or nm in q):
                return p
    return None


def resolve_landmark(ch, query):
    """地标解析 → 中心格坐标:大门(label/to) / NPC(id/名) / 物件(id/名) / 出生点"""
    q = _norm(query)
    if not q:
        return None, None
    if q in ('spawn', '出生点', '起点', '入口'):
        return tuple(ch['room']['spawn']), '出生点'
    for g in ch.get('gates', []):
        if q in _norm(g.get('label')) or _norm(g.get('to')) == q:
            return tuple(g['at']), '大门 ' + g.get('label', '')
    for n in ch.get('npcs', []):
        if _norm(n.get('id')) == q or q in _norm(n.get('name')) or _norm(n.get('name')) in q:
            return tuple(n['pos']), 'NPC ' + n.get('name', '')
    for p in ch.get('props', []):
        nm = _norm(p.get('name'))
        if _norm(p.get('id')) == q or (nm and (q in nm or nm in q)):
            cx = p['pos'][0] + p['size'][0] // 2
            cy = p['pos'][1] + p['size'][1] // 2
            return (cx, cy), p.get('name', '')
    return None, None


def _rect_overlap(ax, ay, aw, ahh, bx, by, bw, bh):
    return ax < bx + bw and bx < ax + aw and ay < by + bh and by < ay + ahh


def find_spot(data, ch, tpl, near_xy, exclude_id=None):
    """从地标螺旋向外搜物件落点:不出界/不叠物件/不盖门·NPC·出生点/不压街(>12%)/烧录后全图连通"""
    room = ch['room']
    cols, rows = room['cols'], room['rows']
    sw, sh = tpl['size']
    fp = int(tpl.get('footprint') or sh)
    grid0 = _grid_of(room)
    street = street_mask_of(room)
    others = [p for p in ch.get('props', []) if p.get('id') != exclude_id]
    keep_clear = {tuple(g['at']) for g in ch.get('gates', [])} | {tuple(n['pos']) for n in ch.get('npcs', [])} | {tuple(room['spawn'])}
    lx, ly = near_xy
    cands = []
    for d in range(1, max(cols, rows)):
        ring = []
        for dx in range(-d, d + 1):
            for dy in (-d, d):
                ring.append((lx + dx - sw // 2, ly + dy - sh // 2))
        for dy in range(-d + 1, d):
            for dx in (-d, d):
                ring.append((lx + dx - sw // 2, ly + dy - sh // 2))
        cands.extend(ring)
        if len(cands) > 1400:
            break
    tried = 0
    for (x0, y0) in cands:
        if not (0 <= x0 and 0 <= y0 and x0 + sw <= cols and y0 + sh <= rows):
            continue
        if any(_rect_overlap(x0, y0, sw, sh, p['pos'][0], p['pos'][1], p['size'][0], p['size'][1]) for p in others):
            continue
        cells = {(x, y) for y in range(y0, y0 + sh) for x in range(x0, x0 + sw)}
        if cells & keep_clear:
            continue
        if street:
            pressed = sum(street[y][x] for (x, y) in cells if y < rows and x < cols)
            if pressed / (sw * sh) > 0.12:
                continue
        # 模拟烧录 footprint → BFS 全图连通(性价比:几何过滤后才做)
        tried += 1
        if tried > 220:
            break
        grid = [r[:] for r in grid0]
        for y in range(y0 + sh - fp, y0 + sh):
            for x in range(x0, x0 + sw):
                grid[y][x] = 1
        ok, _why = _conn_ok(ch, grid)
        if ok:
            return (x0, y0)
    return None


def _burn(room, x0, y0, sw, sh, fp, val):
    w = [list(r) for r in room['walkable']]
    for y in range(y0 + sh - fp, y0 + sh):
        for x in range(x0, x0 + sw):
            if 0 <= y < len(w) and 0 <= x < len(w[0]):
                w[y][x] = val
    room['walkable'] = [''.join(r) for r in w]


def cmd_place_prop(data, ch, params):
    tpl_q = params.get('type') or params.get('object') or ''
    tpl = resolve_template(data, ch, tpl_q)
    if not tpl:
        return {'ok': False, 'error': f'不认识物件「{tpl_q}」。可用:' + '、'.join(sorted({p["name"] for p in ch.get("props", [])}))}
    mode = params.get('mode') or 'clone'
    near_q = params.get('near') or ''
    if params.get('at'):
        near_xy, near_label = tuple(params['at']), '指定坐标'
    else:
        near_xy, near_label = resolve_landmark(ch, near_q)
        if not near_xy:
            vocab = [g.get('label', '') for g in ch.get('gates', [])] + [n.get('name', '') for n in ch.get('npcs', [])] + ['出生点']
            return {'ok': False, 'error': f'找不到地标「{near_q}」。本图地标:' + '、'.join(v for v in vocab if v) + '(也可用物件名)'}
    room = ch['room']
    fp = int(tpl.get('footprint') or tpl['size'][1])
    # move 模式:物件必须在本章;先清旧 footprint(避开其它物件占格)再找新位
    target = None
    if mode == 'move':
        target = next((p for p in ch.get('props', []) if p.get('id') == tpl.get('id')), None)
        if target is None or not target.get('movable'):
            return {'ok': False, 'error': f'「{tpl_q}」不是本图里可移动的物件(嵌底图的环境结构挪不了)'}
        x0, y0 = target['pos']
        sw, sh = target['size']
        other_cells = set()
        for p in ch.get('props', []):
            if p is target or not p.get('isObstacle'):
                continue
            pfp = int(p.get('footprint') or p['size'][1])
            for y in range(p['pos'][1] + p['size'][1] - pfp, p['pos'][1] + p['size'][1]):
                for x in range(p['pos'][0], p['pos'][0] + p['size'][0]):
                    other_cells.add((x, y))
        w = [list(r) for r in room['walkable']]
        for y in range(y0 + sh - fp, y0 + sh):
            for x in range(x0, x0 + sw):
                if (x, y) not in other_cells and 0 <= y < len(w) and 0 <= x < len(w[0]):
                    w[y][x] = '0'
        room['walkable'] = [''.join(r) for r in w]
    spot = find_spot(data, ch, tpl, near_xy, exclude_id=(target or {}).get('id'))
    if not spot:
        if mode == 'move' and target:  # 找不到位就把旧 footprint 烧回去,不能留洞
            _burn(room, target['pos'][0], target['pos'][1], target['size'][0], target['size'][1], fp, '1')
        return {'ok': False, 'error': f'{near_label}附近找不到合法位(不压街/不叠物件/不堵路)——换个地标试试'}
    x0, y0 = spot
    if mode == 'move':
        target['pos'] = [x0, y0]
        if target.get('isObstacle'):
            _burn(room, x0, y0, target['size'][0], target['size'][1], fp, '1')
        cw = compile_walkable_room(ch)  # M8:有语义层就重编译(确定性,天然无残留)
        if cw:
            room['walkable'] = cw
        write_chapters(data)
        return {'ok': True, 'action': 'move', 'propId': target['id'], 'name': target.get('name'), 'pos': [x0, y0], 'near': near_label}
    # clone:复用 duplicateProp 的 id 约定 {模板id}_{n}
    base_id = tpl.get('id', 'prop')
    n = 2
    while any(p.get('id') == f'{base_id}_{n}' for p in ch.get('props', [])):
        n += 1
    new_id = f'{base_id}_{n}' if any(p.get('id') == base_id for p in ch.get('props', [])) else base_id
    new_prop = {k: v for k, v in tpl.items() if k not in ('pos', 'id')}
    new_prop['id'] = new_id
    new_prop['pos'] = [x0, y0]
    new_prop['movable'] = True
    ch.setdefault('props', []).append(new_prop)
    if new_prop.get('isObstacle'):
        _burn(room, x0, y0, new_prop['size'][0], new_prop['size'][1], int(new_prop.get('footprint') or new_prop['size'][1]), '1')
    cw = compile_walkable_room(ch)  # M8:有语义层就重编译(确定性,天然无残留)
    if cw:
        room['walkable'] = cw
    write_chapters(data)
    return {'ok': True, 'action': 'clone', 'propId': new_id, 'name': new_prop.get('name'), 'pos': [x0, y0], 'near': near_label}


def _auto_patrol_loop(ch, pos, span=5):
    """围着 NPC 当前位置找一圈可走的矩形巡逻环(四角+四边全可走)"""
    grid = _grid_of(ch['room'])
    cols, rows = len(grid[0]), len(grid)

    def ok_rect(x0, y0, x1, y1):
        if not (0 <= x0 < x1 < cols and 0 <= y0 < y1 < rows):
            return False
        for x in range(x0, x1 + 1):
            if grid[y0][x] or grid[y1][x]:
                return False
        for y in range(y0, y1 + 1):
            if grid[y][x0] or grid[y][x1]:
                return False
        return True
    px, py = pos
    for s in range(span, 1, -1):
        for ox in range(-s, 1):
            for oy in range(-s, 1):
                x0, y0 = px + ox, py + oy
                if ok_rect(x0, y0, x0 + s, y0 + s):
                    return [[x0, y0], [x0 + s, y0], [x0 + s, y0 + s], [x0, y0 + s]]
    return None


def cmd_set_npc_behavior(data, ch, params):
    q = _norm(params.get('id') or params.get('npc') or '')
    npc = next((n for n in ch.get('npcs', []) if _norm(n.get('id')) == q or q in _norm(n.get('name')) or _norm(n.get('name')) in q), None)
    if not npc:
        return {'ok': False, 'error': f'本图里找不到角色「{params.get("npc") or params.get("id")}」。在场:' + '、'.join(n.get('name', '') for n in ch.get('npcs', []))}
    b = params.get('behavior')
    if b not in ('static', 'wander', 'patrol'):
        return {'ok': False, 'error': f'行为只支持 static/wander/patrol,收到「{b}」'}
    if b == 'static':
        for k in ('behavior', 'range', 'waypoints'):
            npc.pop(k, None)
        write_chapters(data)
        return {'ok': True, 'npcId': npc['id'], 'name': npc.get('name'), 'behavior': 'static'}
    if b == 'wander':
        npc['behavior'] = 'wander'
        npc['range'] = int(params.get('range') or 3)
        npc.pop('waypoints', None)
        write_chapters(data)
        return {'ok': True, 'npcId': npc['id'], 'name': npc.get('name'), 'behavior': 'wander', 'range': npc['range']}
    # patrol:显式 waypoints 验证可走;没给就围地标(或当前位置)自动生成环线
    wps = params.get('waypoints')
    if wps:
        grid = _grid_of(ch['room'])
        bad = [w for w in wps if not (0 <= w[1] < len(grid) and 0 <= w[0] < len(grid[0]) and grid[w[1]][w[0]] == 0)]
        if bad:
            return {'ok': False, 'error': f'路径点 {bad} 在墙里/出界'}
    else:
        center = npc['pos']
        if params.get('area'):
            xy, _lb = resolve_landmark(ch, params['area'])
            if xy:
                center = list(xy)
        wps = _auto_patrol_loop(ch, center)
        if not wps:
            return {'ok': False, 'error': '这附近太挤,围不出巡逻环线——把角色挪到开阔处再试'}
    npc['behavior'] = 'patrol'
    npc['waypoints'] = wps
    npc.pop('range', None)
    write_chapters(data)
    return {'ok': True, 'npcId': npc['id'], 'name': npc.get('name'), 'behavior': 'patrol', 'waypoints': wps}


# ===== M8 语义层:semantics={ground,roads} 是原始事实,walkable 是编译产物 =====
def derive_ground(ch, walkable):
    """从 walkable 反演 L0 地形层:把所有 isObstacle 物件的 footprint 格抠回可走(物件碰撞编译时再烧)"""
    w = [list(r) for r in walkable]
    for p in ch.get('props', []):
        if not p.get('isObstacle'):
            continue
        x0, y0 = p['pos']
        sw, sh = p['size']
        fp = int(p.get('footprint') or sh)
        for y in range(y0 + sh - fp, y0 + sh):
            for x in range(x0, x0 + sw):
                if 0 <= y < len(w) and 0 <= x < len(w[0]):
                    w[y][x] = '0'
    return [''.join(r) for r in w]


def cmd_bake_semantics(data, ch, params):
    room = ch['room']
    if not room.get('walkable'):
        return {'ok': False, 'error': '本图没有 walkable 层(tile 小房间不需要语义层)'}
    ground = derive_ground(ch, room['walkable'])
    # 街道识别:编辑器端 canvas 识别结果优先(server 的系统 python 没有 PIL——PEP668 锁,优雅降级)
    roads = []
    client_roads = params.get('roads')
    if isinstance(client_roads, list) and len(client_roads) == room['rows'] and all(len(r) == room['cols'] for r in client_roads):
        roads = client_roads
    else:
        mask = street_mask_of(room)
        roads = [''.join('1' if v else '0' for v in r) for r in mask] if mask else []
    room['semantics'] = {'ground': ground, 'roads': roads}
    write_chapters(data)
    return {'ok': True, 'action': 'bake', 'hasRoads': bool(roads),
            'groundOpen': sum(r.count('0') for r in ground),
            'roadCells': sum(r.count('1') for r in roads) if roads else 0}


def compile_walkable_room(ch):
    """语义层 → 通行层:walkable = ground + 全部 isObstacle 物件 footprint(编译,天然无鬼影/无残留)"""
    sem = ch['room'].get('semantics')
    if not sem or not sem.get('ground'):
        return None
    w = [list(r) for r in sem['ground']]
    for p in ch.get('props', []):
        if not p.get('isObstacle'):
            continue
        x0, y0 = p['pos']
        sw, sh = p['size']
        fp = int(p.get('footprint') or sh)
        for y in range(y0 + sh - fp, y0 + sh):
            for x in range(x0, x0 + sw):
                if 0 <= y < len(w) and 0 <= x < len(w[0]):
                    w[y][x] = '1'
    return [''.join(r) for r in w]


def cmd_compile_walkable(data, ch, params):
    new_w = compile_walkable_room(ch)
    if new_w is None:
        return {'ok': False, 'error': '本图还没有语义层——先点「烘焙语义层」'}
    old = ch['room']['walkable']
    ch['room']['walkable'] = new_w
    ok, why = _conn_ok(ch, _grid_of(ch['room']))
    if not ok:
        ch['room']['walkable'] = old
        return {'ok': False, 'error': f'编译后连通性破坏({why})——检查物件是否堵死通道。未写盘'}
    changed = sum(1 for a, b in zip(''.join(old), ''.join(new_w)) if a != b)
    write_chapters(data)
    return {'ok': True, 'action': 'compile', 'changedCells': changed}


@chapters_write_lock
def execute_command(body):
    intent = body.get('intent')
    ch_id = body.get('chapterId')
    params = body.get('params') or {k: v for k, v in body.items() if k not in ('intent', 'chapterId')}
    data = load_chapters()
    ch = next((c for c in data.get('chapters', []) if c.get('id') == ch_id), None)
    if not ch:
        return {'ok': False, 'error': f'chapter {ch_id} not found'}
    if intent == 'place_prop':
        return cmd_place_prop(data, ch, params)
    if intent == 'set_npc_behavior':
        return cmd_set_npc_behavior(data, ch, params)
    if intent == 'bake_semantics':
        return cmd_bake_semantics(data, ch, params)
    if intent == 'compile_walkable':
        return cmd_compile_walkable(data, ch, params)
    return {'ok': False, 'error': f'未知意图 {intent}(支持 place_prop / set_npc_behavior / bake_semantics / compile_walkable)'}


# ===== M7 自然语言 → 意图:DeepSeek 优先,规则解析兜底 =====
def _read_ai_key():
    k = os.environ.get('DEEPSEEK_API_KEY')
    if k:
        return k.strip()
    f = ROOT / '.ai_key'
    if f.exists():
        return f.read_text(encoding='utf-8').strip()
    return None


def _read_ai_model():
    # 默认 deepseek-v4-pro(用户指定);可在 .ai_model 文件写 deepseek-v4-flash 换更快更省的档
    # (翻译填表任务 flash 足够胜任;官方 V4 model 名:deepseek-v4-pro / deepseek-v4-flash,2026 已升级,非旧 deepseek-chat)
    f = ROOT / '.ai_model'
    if f.exists():
        m = f.read_text(encoding='utf-8').strip()
        if m:
            return m
    return os.environ.get('DEEPSEEK_MODEL', 'deepseek-v4-pro')


def deepseek_parse(text, ch):
    key = _read_ai_key()
    if not key:
        return None, 'no-key'
    import urllib.request
    ents = {
        'props': [{'id': p['id'], 'name': p.get('name', '')} for p in ch.get('props', [])],
        'npcs': [{'id': n['id'], 'name': n.get('name', '')} for n in ch.get('npcs', [])],
        'gates': [{'to': g['to'], 'label': g.get('label', '')} for g in ch.get('gates', [])],
    }
    sys_prompt = (
        '你是地图编辑器的命令翻译器。把用户的中文指令翻译成 JSON 意图,只输出 JSON,不解释。\n'
        '可用意图:\n'
        '1. {"intent":"place_prop","object":"<物件名>","near":"<地标名>","mode":"clone|move"} — 摆放(放/加/建=clone,挪/移=move)\n'
        '2. {"intent":"set_npc_behavior","npc":"<角色名>","behavior":"static|wander|patrol","range":<格数,可选>,"area":"<巡逻地标,可选>"}\n'
        '3. {"intent":"unknown"} — 听不懂或超出能力时\n'
        'object/near/npc 填用户提到的名称原文(系统会自己解析坐标,你不要编坐标)。\n'
        '场景实体:' + json.dumps(ents, ensure_ascii=False)
    )
    req_body = json.dumps({
        'model': _read_ai_model(),
        'messages': [
            {'role': 'system', 'content': sys_prompt},
            {'role': 'user', 'content': text},
        ],
        'temperature': 0,
        'response_format': {'type': 'json_object'},
        'max_tokens': 200,
    }).encode('utf-8')
    req = urllib.request.Request(
        'https://api.deepseek.com/chat/completions', data=req_body,
        headers={'Content-Type': 'application/json', 'Authorization': 'Bearer ' + key}, method='POST')
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:  # V4 Pro 推理慢,给足超时;Flash 一般 1-3s
            out = json.loads(resp.read())
        intent = json.loads(out['choices'][0]['message']['content'])
        if intent.get('intent') in ('place_prop', 'set_npc_behavior'):
            return intent, 'deepseek'
        return None, 'deepseek-unknown'
    except Exception as e:
        sys.stderr.write(f'[凤翎工坊] deepseek 调用失败,降级规则解析: {e}\n')
        return None, 'deepseek-error'


def rules_parse(text):
    """规则解析器(离线兜底):听得懂固定句式"""
    import re as _re
    t = text.strip().rstrip('。!！.')
    # NPC 行为
    m = _re.search(r'让(.+?)(?:在(.+?)(?:附近|周围|一带|那边))?巡逻', t)
    if m:
        return {'intent': 'set_npc_behavior', 'npc': m.group(1).strip(), 'behavior': 'patrol', 'area': (m.group(2) or '').strip() or None}
    m = _re.search(r'让(.+?)(?:随便走走|游走|走动|溜达|逛逛|逛一逛|转转)', t)
    if m:
        return {'intent': 'set_npc_behavior', 'npc': m.group(1).strip(), 'behavior': 'wander'}
    m = _re.search(r'让(.+?)(?:停下|站住|别动|静止|回到原位|站好)', t)
    if m:
        return {'intent': 'set_npc_behavior', 'npc': m.group(1).strip(), 'behavior': 'static'}
    # 摆放:挪/移=move,放/摆/加/建/复制=clone
    m = _re.search(r'把(.+?)(?:挪|移)(?:到|去)(.+?)(?:的)?(?:附近|旁边|旁|边上|那边)?$', t)
    if m:
        return {'intent': 'place_prop', 'object': m.group(1).strip(), 'near': m.group(2).strip(), 'mode': 'move'}
    m = _re.search(r'(?:把|复制)?(?:一个|一座|一栋|个|座|栋)?(.+?)(?:放到|放在|摆到|摆在|加到|复制到)(.+?)(?:的)?(?:附近|旁边|旁|边上|那边)?$', t)
    if m:
        return {'intent': 'place_prop', 'object': m.group(1).strip(), 'near': m.group(2).strip(), 'mode': 'clone'}
    m = _re.search(r'在(.+?)(?:的)?(?:附近|旁边|旁|边上)(?:放|摆|加|建|复制)(?:一个|一座|一栋|个|座|栋)?(.+)$', t)
    if m:
        return {'intent': 'place_prop', 'object': m.group(2).strip(), 'near': m.group(1).strip(), 'mode': 'clone'}
    return None


def parse_intent(text, ch):
    """返回 (intent, engine, error)"""
    intent, tag = deepseek_parse(text, ch)
    if intent:
        return intent, 'deepseek', None
    intent = rules_parse(text)
    if intent:
        return intent, 'rules' if tag == 'no-key' else 'rules(deepseek降级)', None
    return None, 'rules' if tag == 'no-key' else tag, None


if __name__ == '__main__':
    os.chdir(ROOT)
    socketserver.ThreadingTCPServer.allow_reuse_address = True
    socketserver.ThreadingTCPServer.daemon_threads = True
    # ⚠️ 必须 Threading 版:单线程 TCPServer 会被一个挂起的连接堵死整个服务("网页又进不去"的根因)
    with socketserver.ThreadingTCPServer(('127.0.0.1', PORT), Handler) as httpd:
        print(f'凤翎工坊 · 本地 server 启动 → http://127.0.0.1:{PORT}')
        print(f'  GET  /<file>                  - 静态文件')
        print(f'  POST /api/save-chapter        - 保存章节(编辑器调用)')
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print('\n[凤翎工坊] 已关闭')
