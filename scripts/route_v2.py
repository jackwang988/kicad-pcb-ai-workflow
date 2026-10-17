# -*- coding: utf-8 -*-
"""走线器 v2：电气零改变 + 视觉优先

相比 v1 的修正：
 1. esc 出线方向用【几何实测】确定（比较 P±dir 谁离器件本体更远），不再信任 dir 字段
 2. 障碍模型加入【引脚线段】，走线不再压在别人的引脚上
 3. 拐点强制 snap 到 1.27 栅格；且只连接【两端引脚都在栅格上】的点对，
    避免像 v1 那样新增 11 条 endpoint_off_grid
 4. 每条 wire 首尾硬断言必须落在引脚端点上（杜绝悬空端点）
 5. 不删改基线任何原有 wire（基线的 5 条"引脚->悬空标签"短接线是连接结构的一部分）
"""
import sys, re, math, uuid, shutil, collections
sys.stdout.reconfigure(encoding='utf-8')
import route_wires as RW
from sch_parse import load, endpoints, inst_bboxes

GRID = 1.27
ESC = 2.54           # 出线长度
SKIP = 0.55          # 首尾豁免（端点必然贴着自己的引脚）
MIN_MANH = 5.0       # 太近不走线（用 label 更清楚）
MAX_MANH = 55.0
DETOUR = 1.35        # 绕远否决
MINSEG = 1.27        # 碎段否决
BODY_PAD = 0.55
PIN_PAD = 0.50
PINSEG_PAD = 0.25
TXT_PAD = 0.20
WIRE_PAD = 0.35
PCAP = 99            # 每个网络最多走几条
REASON = collections.Counter()


def fnum(v):
    s = '%.6f' % v
    s = s.rstrip('0').rstrip('.')
    return s if s else '0'


def on_grid(v, g=GRID):
    return abs(v / g - round(v / g)) < 0.02


class Obs:
    """轴对齐矩形障碍集合；曼哈顿线段求交"""

    def __init__(self):
        self.rects = []   # (x0,y0,x1,y1,tag,alive)

    def add(self, x0, y0, x1, y1, tag):
        if x1 <= x0 or y1 <= y0: return None
        o = [x0, y0, x1, y1, tag, True]
        self.rects.append(o)
        return o

    def kill(self, o):
        if o is not None: o[5] = False

    def revive(self, o):
        if o is not None: o[5] = True

    @staticmethod
    def _hit(x0, y0, x1, y1, r):
        rx0, ry0, rx1, ry1 = r
        if abs(y0 - y1) < 1e-9:                       # 水平段
            if not (ry0 < y0 < ry1): return False
            return max(x0, x1) > rx0 and min(x0, x1) < rx1
        if abs(x0 - x1) < 1e-9:                       # 垂直段
            if not (rx0 < x0 < rx1): return False
            return max(y0, y1) > ry0 and min(y0, y1) < ry1
        return False                                   # 斜线不参与（本器不产生）

    def hit(self, x0, y0, x1, y1):
        for r in self.rects:
            if not r[5]: continue
            if self._hit(x0, y0, x1, y1, r[0:4]): return r[4]
        return None

    def blocked_pt(self, x, y):
        for r in self.rects:
            if not r[5]: continue
            if r[0] <= x <= r[2] and r[1] <= y <= r[3]: return True
        return False

    def hit_path(self, pts, skip=SKIP):
        """沿折线检测，首尾各豁免 skip mm"""
        cum = [0.0]
        for i in range(len(pts) - 1):
            cum.append(cum[-1] + math.hypot(pts[i + 1][0] - pts[i][0],
                                            pts[i + 1][1] - pts[i][1]))
        total = cum[-1]
        for i in range(len(pts) - 1):
            x0, y0 = pts[i]; x1, y1 = pts[i + 1]
            L = cum[i + 1] - cum[i]
            if L < 1e-9: continue
            ux = (x1 - x0) / L; uy = (y1 - y0) / L
            a = 0.0 if cum[i] < skip else min(L, cum[i] - skip + (skip - cum[i]) if cum[i] < skip else 0.0)
            # 起端裁掉 skip
            sa = max(0.0, skip - cum[i])
            sb = max(0.0, skip - (total - cum[i + 1]))
            a = sa; b = L - sb
            if b - a < 0.05: continue
            h = self.hit(x0 + ux * a, y0 + uy * a, x0 + ux * b, y0 + uy * b)
            if h: return h
        return None


def build_obs(t, libs, insts, eps, bodies, texts):
    O = Obs()
    # 1. 器件本体
    for ref, (x0, y0, x1, y1) in bodies.items():
        O.add(x0 - BODY_PAD, y0 - BODY_PAD, x1 + BODY_PAD, y1 + BODY_PAD, 'body:%s' % ref)
    # 2. 引脚端点方框 + 引脚线段（从端点朝本体 2.54mm）
    for ref, lst in eps.items():
        bx0, by0, bx1, by1 = bodies.get(ref, (0, 0, 0, 0))
        cx, cy = (bx0 + bx1) / 2, (by0 + by1) / 2
        for p in lst:
            px, py = p['x'], p['y']
            O.add(px - PIN_PAD, py - PIN_PAD, px + PIN_PAD, py + PIN_PAD,
                  'pin:%s.%s' % (ref, p['num']))
            vx, vy = cx - px, cy - py
            n = math.hypot(vx, vy)
            if n > 0.3:
                vx, vy = vx / n, vy / n
                qx, qy = px + vx * 2.54, py + vy * 2.54
                O.add(min(px, qx) - PINSEG_PAD, min(py, qy) - PINSEG_PAD,
                      max(px, qx) + PINSEG_PAD, max(py, qy) + PINSEG_PAD,
                      'pinseg:%s.%s' % (ref, p['num']))
    # 3. 已有 wire
    for m in re.finditer(r'\n\t\(wire\n\t\t\(pts\n((?:\t\t\t\(xy [^\n]*\)\n?)+)', t):
        pts = [(float(a), float(b)) for a, b in re.findall(r'\(xy ([-\d.]+) ([-\d.]+)\)', m.group(1))]
        for i in range(len(pts) - 1):
            x0, y0 = pts[i]; x1, y1 = pts[i + 1]
            O.add(min(x0, x1) - WIRE_PAD, min(y0, y1) - WIRE_PAD,
                  max(x0, x1) + WIRE_PAD, max(y0, y1) + WIRE_PAD, 'wire')
    # 4. 文字（PDF 实测框）
    tbox = []
    for (x0, y0, x1, y1, s) in texts:
        o = O.add(x0 + TXT_PAD, y0 + TXT_PAD, x1 - TXT_PAD, y1 - TXT_PAD, 'txt:%s' % s[:16])
        tbox.append((o, x0, y0, x1, y1, s))
    return O, tbox


def esc_dir(P, dirv, body):
    """返回远离本体的单位轴向方向；dirv 是 endpoints() 给的 dir，仅作候选"""
    bx0, by0, bx1, by1 = body
    cx, cy = (bx0 + bx1) / 2, (by0 + by1) / 2
    cands = []
    if dirv is not None:
        cands.append((dirv[0], dirv[1]))
        cands.append((-dirv[0], -dirv[1]))
    dx = P[0] - cx; dy = P[1] - cy
    # 主轴：离本体中心更远的那个轴向
    if abs(dx) >= abs(dy):
        cands.append((1.0 if dx >= 0 else -1.0, 0.0))
    else:
        cands.append((0.0, 1.0 if dy >= 0 else -1.0))
    best = None
    for d in cands:
        q = (P[0] + d[0] * ESC, P[1] + d[1] * ESC)
        # 到本体矩形的距离（越大越好）
        ddx = max(bx0 - q[0], q[0] - bx1, 0.0)
        ddy = max(by0 - q[1], q[1] - by1, 0.0)
        dist = math.hypot(ddx, ddy)
        if best is None or dist > best[0]: best = (dist, d)
    return best[1]


def plan(A, B, dA, dB, O, skip_self, last_hit=None):
    """候选：直线 / L(1拐) / Z(2拐)；返回最优折线或 None"""
    if last_hit is None: last_hit = []
    ax, ay = A; bx, by = B
    manh = abs(ax - bx) + abs(ay - by)
    if manh < MIN_MANH or manh > MAX_MANH: return None
    Ao = (round(ax + dA[0] * ESC, 3), round(ay + dA[1] * ESC, 3))
    Bo = (round(bx + dB[0] * ESC, 3), round(by + dB[1] * ESC, 3))

    def mk(mid): return [A, Ao] + mid + [Bo, B]

    cands = []
    if abs(ax - bx) < 0.01 or abs(ay - by) < 0.01:
        cands.append([A, B])
    cands.append(mk([(Bo[0], Ao[1])]))
    cands.append(mk([(Ao[0], Bo[1])]))

    def sg(v): return round(round(v / GRID) * GRID, 2)

    mids = set()
    for base in ((Ao[0] + Bo[0]) / 2,):
        for off in (0, 2.54, -2.54, 5.08, -5.08, 7.62, -7.62, 10.16, -10.16, 12.7, -12.7):
            mids.add(('x', sg(base + off)))
    for base in ((Ao[1] + Bo[1]) / 2,):
        for off in (0, 2.54, -2.54, 5.08, -5.08, 7.62, -7.62, 10.16, -10.16, 12.7, -12.7):
            mids.add(('y', sg(base + off)))
    for ax_, v in mids:
        if ax_ == 'x':
            if abs(v - Ao[0]) < 1.0 or abs(v - Bo[0]) < 1.0: continue
            cands.append(mk([(v, Ao[1]), (v, Bo[1])]))
        else:
            if abs(v - Ao[1]) < 1.0 or abs(v - Bo[1]) < 1.0: continue
            cands.append(mk([(Ao[0], v), (Bo[0], v)]))

    best = None
    for c in cands:
        cc = [c[0]]
        for q in c[1:]:
            if abs(q[0] - cc[-1][0]) > 0.01 or abs(q[1] - cc[-1][1]) > 0.01: cc.append(q)
        if len(cc) < 2: continue
        cc = RW.cleanup(cc)
        cc[0] = A; cc[-1] = B
        if len(cc) > 4: continue
        # 拐点必须栅格对齐
        if any(not (on_grid(q[0]) and on_grid(q[1])) for q in cc[1:-1]): continue
        # 碎段否决
        if any(math.hypot(cc[i + 1][0] - cc[i][0], cc[i + 1][1] - cc[i][1]) < MINSEG
               for i in range(len(cc) - 1)): continue
        L = sum(math.hypot(cc[i + 1][0] - cc[i][0], cc[i + 1][1] - cc[i][1])
                for i in range(len(cc) - 1))
        if L > manh * DETOUR + 2.0: continue
        skip_self(O, True)
        h = O.hit_path(cc)
        skip_self(O, False)
        if h:
            last_hit.append(str(h))
            continue
        score = (len(cc), round(L, 1))
        if best is None or score < best[0]: best = (score, cc)
        if score[0] == 2: break
    if best: return best[1]

    # ---- A* 兜底 ----
    gp = astar(O, A, B, dA, dB, skip_self, turn_pen=TURN_PEN)
    if not gp: return None
    cc = RW.cleanup([A] + gp + [B])
    cc[0] = A; cc[-1] = B
    if len(cc) > 5: return None                       # 拐点太多（>3个），宁可不走
    if any(not (on_grid(q[0]) and on_grid(q[1])) for q in cc[1:-1]): return None
    if any(math.hypot(cc[i + 1][0] - cc[i][0], cc[i + 1][1] - cc[i][1]) < MINSEG
           for i in range(len(cc) - 1)): return None
    L = sum(math.hypot(cc[i + 1][0] - cc[i][0], cc[i + 1][1] - cc[i][1])
            for i in range(len(cc) - 1))
    if L > manh * 1.45 + 2.0: return None
    skip_self(O, True)
    h = O.hit_path(cc)
    skip_self(O, False)
    if h:
        last_hit.append(str(h)); return None
    return cc


TURN_PEN = 5.0       # A* 拐点惩罚（越大越"少拐弯"）


def astar(O, A, B, dA, dB, skip_self, pad=15.0, turn_pen=TURN_PEN):
    """栅格 A* 兜底：只在候选式失败时启用。代价 = 长度 + 拐点惩罚，天然少拐。
    返回 [Ao, ..., Bo]（不含 A/B 本身），失败返回 None"""
    import heapq
    G = GRID
    x0 = min(A[0], B[0]) - pad; x1 = max(A[0], B[0]) + pad
    y0 = min(A[1], B[1]) - pad; y1 = max(A[1], B[1]) + pad
    i0 = int(math.floor(x0 / G)); i1 = int(math.ceil(x1 / G))
    j0 = int(math.floor(y0 / G)); j1 = int(math.ceil(y1 / G))
    W = i1 - i0 + 1; H = j1 - j0 + 1
    if W * H > 90000: return None

    # esc 起点：选第一个不被挡的
    def pick(P, d):
        for e in (2.54, 1.27, 3.81, 5.08):
            q = (round(P[0] + d[0] * e, 3), round(P[1] + d[1] * e, 3))
            skip_self(O, True)
            b = O.blocked_pt(q[0], q[1])
            skip_self(O, False)
            if not b: return q
        return None

    Ao = pick(A, dA); Bo = pick(B, dB)
    if Ao is None or Bo is None: return None
    si = int(round(Ao[0] / G)); sj = int(round(Ao[1] / G))
    gi = int(round(Bo[0] / G)); gj = int(round(Bo[1] / G))
    if not (i0 <= si <= i1 and j0 <= sj <= j1 and i0 <= gi <= i1 and j0 <= gj <= j1): return None

    skip_self(O, True)
    blk = bytearray(W * H)
    for j in range(H):
        for i in range(W):
            if O.blocked_pt((i0 + i) * G, (j0 + j) * G): blk[j * W + i] = 1
    skip_self(O, False)
    blk[(sj - j0) * W + (si - i0)] = 0
    blk[(gj - j0) * W + (gi - i0)] = 0

    DIRS = [(1, 0), (-1, 0), (0, 1), (0, -1)]
    dist = {}; prev = {}; h = []
    for d0 in range(4):
        dist[(si, sj, d0)] = 0.0
        heapq.heappush(h, (abs(gi - si) + abs(gj - sj), si, sj, d0))
    best = None
    while h:
        f, i, j, dd = heapq.heappop(h)
        if f > dist.get((i, j, dd), 1e18) + abs(gi - i) + abs(gj - j) + 1e-9: continue
        if i == gi and j == gj: best = (i, j, dd); break
        for nd in range(4):
            ni = i + DIRS[nd][0]; nj = j + DIRS[nd][1]
            if ni < i0 or ni > i1 or nj < j0 or nj > j1: continue
            if blk[(nj - j0) * W + (ni - i0)]: continue
            ng = dist[(i, j, dd)] + 1.0 + (turn_pen / G if nd != dd else 0.0)
            k = (ni, nj, nd)
            if ng < dist.get(k, 1e18) - 1e-9:
                dist[k] = ng; prev[k] = (i, j, dd)
                heapq.heappush(h, (ng + abs(gi - ni) + abs(gj - nj), ni, nj, nd))
    if best is None: return None
    cells = []; cur = best
    while cur in prev:
        cells.append((cur[0] * G, cur[1] * G))
        cur = prev[cur]
    cells.append((si * G, sj * G))
    cells.reverse()
    return [Ao] + cells[1:] + [Bo] if len(cells) > 1 else [Ao, Bo]


def path_hits_box(pts, box, skip=SKIP):
    """box = build_obs 返回的矩形对象 [x0,y0,x1,y1,tag,alive]（已含 TXT_PAD 收缩）。
    首尾各豁免 skip —— 端点必然贴着自己的标签，那段重叠是正常的。"""
    if box is None: return False
    r = (box[0], box[1], box[2], box[3])
    if r[2] <= r[0] or r[3] <= r[1]: return False
    cum = [0.0]
    for i in range(len(pts) - 1):
        cum.append(cum[-1] + math.hypot(pts[i + 1][0] - pts[i][0], pts[i + 1][1] - pts[i][1]))
    total = cum[-1]
    for i in range(len(pts) - 1):
        x0, y0 = pts[i]; x1, y1 = pts[i + 1]
        L = cum[i + 1] - cum[i]
        if L < 1e-9: continue
        ux, uy = (x1 - x0) / L, (y1 - y0) / L
        a = max(0.0, skip - cum[i]); b = L - max(0.0, skip - (total - cum[i + 1]))
        if b - a < 0.05: continue
        if Obs._hit(x0 + ux * a, y0 + uy * a, x0 + ux * b, y0 + uy * b, r): return True
    return False


def pdf_texts(path):
    """从导出 PDF 实测文字包围盒（mm）。
    自适应页面尺寸（不再硬编码 A4 的 12/266），图框上下各留 6% 边距。
    找不到 PDF / 没装 PyMuPDF 时返回空列表并告警——此时走线仍可跑，只是不避让文字。"""
    if not path:
        print("  [warn] 未给 --pdf，不做文字避让（强烈建议先导出 PDF）")
        return []
    try:
        import fitz
    except ImportError:
        print("  [warn] 无 PyMuPDF(fitz)，跳过文字避让")
        return []
    import os
    if not os.path.exists(path):
        print("  [warn] PDF 不存在: %s，跳过文字避让" % path)
        return []
    MM = 72 / 25.4
    doc = fitz.open(path); out = []

    def iou(a, b):
        ix0, iy0 = max(a[0], b[0]), max(a[1], b[1]); ix1, iy1 = min(a[2], b[2]), min(a[3], b[3])
        if ix1 <= ix0 or iy1 <= iy0: return 0.0
        it = (ix1 - ix0) * (iy1 - iy0)
        return it / ((a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - it)

    for pg in doc:
        H = pg.rect.height / MM          # 页面高度(mm)，自适应 A4/A3/A2
        ytop, ybot = H * 0.06, H * 0.94  # 图框上下各留 6%，过滤标题栏/图框文字
        for w in pg.get_text('words'):
            b = (w[0] / MM, w[1] / MM, w[2] / MM, w[3] / MM)
            s = w[4]
            if b[1] < ytop or b[3] > ybot: continue
            if len(s) == 1 and s in 'ABCDEF0123456789': continue
            if any(d[4] == s and iou(d[:4], b) > 0.7 for d in out): continue
            out.append((b[0], b[1], b[2], b[3], s))
    return out


def run(SRC, DST, pdf_path="base2.pdf", only_ongrid=True, verbose=True):
    from _runtime import new_output
    new_output(SRC, DST)
    shutil.copyfile(SRC, DST)
    t, libs, insts = load(DST)
    eps = endpoints(t, libs, insts)
    bodies = inst_bboxes(t, libs, insts)
    texts = pdf_texts(pdf_path)

    pinkey = {}
    for ref, lst in eps.items():
        for p in lst:
            pinkey[(round(p['x'], 2), round(p['y'], 2))] = (ref, p['num'], p)
    O, tbox = build_obs(t, libs, insts, eps, bodies, texts)

    def txt_of(nm, x, y):
        """只匹配【本 label 自己】的文字框：要求 label 锚点落在框内（含容差）。
        旧版按 网络名+中心最近 匹配，会把路径上另一个同名 label 的框误当成自己的杀掉，
        结果走线从别人标签上压过去。"""
        best = None
        for o, x0, y0, x1, y1, s in tbox:
            if s != nm: continue
            if not (x0 - 1.2 <= x <= x1 + 1.2 and y0 - 1.2 <= y <= y1 + 1.2): continue
            d = math.hypot(max(x0 - x, 0.0, x - x1), max(y0 - y, 0.0, y - y1))
            if best is None or d < best[0]: best = (d, o)
        return best[1] if best else None

    labs = RW.collect_labels(t)
    for L in labs:
        k = (round(L['x'], 2), round(L['y'], 2))
        L['pin'] = pinkey.get(k)
        L['ongrid'] = L['pin'] is not None and on_grid(L['x']) and on_grid(L['y'])
        L['tbox'] = txt_of(L['name'], L['x'], L['y'])
    bynet = collections.defaultdict(list)
    for L in labs:
        if L['pin']: bynet[L['name']].append(L)

    pairs = []
    for nm, ls in bynet.items():
        ps = [L for L in ls if L['ongrid']] if only_ongrid else ls
        for i in range(len(ps)):
            for j in range(i + 1, len(ps)):
                mh = abs(ps[i]['x'] - ps[j]['x']) + abs(ps[i]['y'] - ps[j]['y'])
                if MIN_MANH <= mh <= MAX_MANH:
                    pairs.append((mh, nm, ps[i], ps[j]))
    pairs.sort(key=lambda z: z[0])
    if verbose:
        print("  候选点对 %d（来自 %d 个网络 / %d 个可走标签）"
              % (len(pairs), len(bynet), sum(len(v) for v in bynet.values())))

    ok = []; fail = collections.Counter(); used = collections.Counter(); busy = set()
    REASON.clear()
    for mh, nm, A, B in pairs:
        if used[nm] >= PCAP: continue
        if B['pos'] in busy: continue          # 同一个标签只能被替代一次
        pA, pB = A['pin'][2], B['pin'][2]
        dA = esc_dir((A['x'], A['y']), (pA['dirx'], pA['diry']), bodies[A['pin'][0]])
        dB = esc_dir((B['x'], B['y']), (pB['dirx'], pB['diry']), bodies[B['pin'][0]])

        def skip_self(O, on, _a=A, _b=B):
            # 端点自豁免：把 A、B 自己的引脚/引脚线框临时关掉
            for r in O.rects:
                if r[4].endswith('.%s' % _a['pin'][1]) or r[4].endswith('.%s' % _b['pin'][1]):
                    if r[4].split(':')[1].split('.')[0] == _a['pin'][0] or \
                       r[4].split(':')[1].split('.')[0] == _b['pin'][0]:
                        r[5] = not on

        saved = []
        for bx in (A['tbox'], B['tbox']):
            if bx is not None: O.kill(bx); saved.append(bx)
        lh = []
        path = plan((A['x'], A['y']), (B['x'], B['y']), dA, dB, O, skip_self, lh)
        for x in lh: REASON[x.split(':')[0]] += 1
        if path:
            O.revive(A['tbox']); O.revive(B['tbox'])
            # 保留的那个标签不能被自己的走线压住，否则视觉上很难看
            hA = path_hits_box(path, A['tbox'])
            hB = path_hits_box(path, B['tbox'])
            if hA and hB:
                for bx in saved: O.revive(bx)
                fail[nm] += 1; continue          # 两头都会压到 -> 放弃这条
            keep, drop = (B, A) if hA else (A, B)
            if drop['tbox'] is not None: O.kill(drop['tbox'])   # 被删标签的文字消失
            for i in range(len(path) - 1):
                x0, y0 = path[i]; x1, y1 = path[i + 1]
                O.add(min(x0, x1) - WIRE_PAD, min(y0, y1) - WIRE_PAD,
                      max(x0, x1) + WIRE_PAD, max(y0, y1) + WIRE_PAD, 'wire')
            used[nm] += 1; busy.add(drop['pos'])  # 只锁住被删的标签，keep 可继续成链
            ok.append(dict(net=nm, mh=mh, keep=keep, drop=drop, path=path))
        else:
            for bx in saved: O.revive(bx)
            fail[nm] += 1

    if verbose:
        print("  走成 %d 条；失败最多的网络: %s" % (len(ok), fail.most_common(6)))
        print("  障碍否决统计:", REASON.most_common(12))

    # ---- 写回：删 label（保留每个网络至少 1 个）----
    drop = [r['drop']['pos'] for r in ok]
    n0 = len(RW.collect_labels(t))
    for pos in sorted(drop, reverse=True):
        e0 = RW.span_of(t, pos + 1); end = e0 + 1
        if end < len(t) and t[end] == '\n': end += 1
        t = t[:pos] + t[end:]
    assert t.count('(') == t.count(')'), "删 label 后括号不平衡"
    n1 = len(RW.collect_labels(t))
    if verbose: print("  label %d -> %d（删 %d）" % (n0, n1, n0 - n1))

    # ---- 写回：插 wire ----
    anchor = t.find('\n\t(sheet_instances')
    assert anchor > 0
    blocks = []
    nseg = 0
    for r in ok:
        p = r['path']
        for i in range(len(p) - 1):
            a1, b1 = p[i], p[i + 1]
            if abs(a1[0] - b1[0]) < 1e-9 and abs(a1[1] - b1[1]) < 1e-9: continue
            xy = '(xy %s %s) (xy %s %s)' % (fnum(a1[0]), fnum(a1[1]), fnum(b1[0]), fnum(b1[1]))
            blocks.append('\t(wire\n\t\t(pts\n\t\t\t%s\n\t\t)\n\t\t(stroke\n\t\t\t(width 0)\n'
                          '\t\t\t(type default)\n\t\t)\n\t\t(uuid "%s")\n\t)\n'
                          % (xy, str(uuid.uuid4())))
            nseg += 1
    t = t[:anchor + 1] + ''.join(blocks) + t[anchor + 1:]
    assert t.count('(') == t.count(')'), "插 wire 后括号不平衡"
    open(DST, 'w', encoding='utf-8').write(t)
    if verbose: print("  插入 wire %d 段（%d 条折线）" % (nseg, len(ok)))
    return ok


def _cli():
    import argparse, os
    ap = argparse.ArgumentParser(
        description="原理图 label -> wire 走线器 v2（把网络标签两两换成真实走线，修改后须验证电气连接）")
    ap.add_argument('src', help='输入 .kicad_sch')
    ap.add_argument('dst', help='输出 .kicad_sch')
    ap.add_argument('--pdf', default=None,
                    help='由 src 导出的 PDF（实测文字包围盒做避让）。缺省自动取同名 .pdf')
    ap.add_argument('--loose', action='store_true',
                    help='允许连接非栅格引脚（会新增 ERC endpoint_off_grid，默认关闭）')
    ap.add_argument('--min-manh', type=float, default=MIN_MANH, help='太近不走线(mm)')
    ap.add_argument('--max-manh', type=float, default=MAX_MANH, help='太远不走线(mm)')
    ap.add_argument('--detour', type=float, default=DETOUR, help='绕远否决比')
    ap.add_argument('--body-pad', type=float, default=BODY_PAD, help='器件本体避让余量')
    ap.add_argument('--pin-pad', type=float, default=PIN_PAD, help='引脚端点避让余量')
    ap.add_argument('--txt-pad', type=float, default=TXT_PAD, help='文字避让余量')
    ap.add_argument('--wire-pad', type=float, default=WIRE_PAD, help='已有走线避让余量')
    ap.add_argument('--pcap', type=int, default=PCAP, help='每个网络最多走几条')
    ap.add_argument('--turn-pen', type=float, default=TURN_PEN, help='A* 拐点惩罚(越大越少拐)')
    a = ap.parse_args()
    globals()['MIN_MANH'] = a.min_manh
    globals()['MAX_MANH'] = a.max_manh
    globals()['DETOUR'] = a.detour
    globals()['BODY_PAD'] = a.body_pad
    globals()['PIN_PAD'] = a.pin_pad
    globals()['TXT_PAD'] = a.txt_pad
    globals()['WIRE_PAD'] = a.wire_pad
    globals()['PCAP'] = a.pcap
    globals()['TURN_PEN'] = a.turn_pen
    pdf = a.pdf or os.path.splitext(a.src)[0] + '.pdf'
    og = not a.loose
    print("only_ongrid(只连栅格对齐引脚) = %s ; pdf = %s" % (og, pdf))
    run(a.src, a.dst, pdf_path=pdf, only_ongrid=og)


if __name__ == '__main__':
    from _runtime import require_apply
    require_apply()
    _cli()
