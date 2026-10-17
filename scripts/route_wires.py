# -*- coding: utf-8 -*-
"""原理图 label -> wire 走线转换器（电气连接不变）
规则：同一网络的两个引脚端点若能无障碍曼哈顿连通，则用 wire 直连并删掉其中一个 label。
      每个网络必须保留 >=1 个 label，否则网表里的网络名会退化成 Net-(Ref-PadN)。
"""
import sys, re, math, uuid, fitz
from collections import Counter, defaultdict
from sch_parse import load, endpoints, inst_bboxes

GRID = 1.27
TPAD = 0.40      # 文字框收缩量：>0 允许贴边过，禁止从文字正中穿
MM = 72/25.4
POWER = {'GND', '3V3', 'VBUS5V', '5V_F', 'BAT+', '+5V', 'VCC', '5V', 'VBUS', 'VIN', '+3V3'}

def snap(v): return round(round(v / GRID) * GRID, 2)


class Router:
    """带 1mm 空间网格索引的曼哈顿走线器"""

    def __init__(self, t, libs, insts, eps, wire_obs=False, pin_clear=0.40):
        self.t = t; self.eps = eps
        self.grid = {}
        self.pins = []            # 精确避让用的引脚端点表
        self.wsegs = []           # 已有线段：折点落在线上会造成疑似连接，需禁
        self.wire_obs = wire_obs  # False=允许与已有走线交叉(KiCad 无连接点即不连)
        self.last_reason = ''
        self.pin_clear = pin_clear
        self.bodies = inst_bboxes(t, libs, insts)
        for ref, (x0, y0, x1, y1) in self.bodies.items():
            self._add((x0 - 0.25, y0 - 0.25, x1 + 0.25, y1 + 0.25), ('body', ref, None, None))
        for ref, lst in eps.items():
            for p in lst:
                self._add((p['x'] - 0.55, p['y'] - 0.55, p['x'] + 0.55, p['y'] + 0.55),
                          ('pin', '%s.%s' % (ref, p['num']), p['x'], p['y']))
                self.pins.append((p['x'], p['y'], '%s.%s' % (ref, p['num'])))
        for m in re.finditer(r'\n\t\(wire\n\t\t\(pts\n((?:\t\t\t\(xy [^\n]*\)\n?)+)', t):
            pts = re.findall(r'\(xy ([-\d.]+) ([-\d.]+)\)', m.group(1))
            for i in range(len(pts) - 1):
                self.add_wire_seg((float(pts[i][0]), float(pts[i][1]),
                                   float(pts[i + 1][0]), float(pts[i + 1][1])))
        self.text_obs = []

    def _add(self, box, tag):
        x0, y0, x1, y1 = box
        for gx in range(int(math.floor(x0)), int(math.ceil(x1)) + 1):
            for gy in range(int(math.floor(y0)), int(math.ceil(y1)) + 1):
                self.grid.setdefault((gx, gy), []).append([box, tag, True])

    def add_wire_seg(self, seg):
        x0, y0, x1, y1 = seg
        self.wsegs.append(seg)
        self._add((min(x0, x1) - 0.35, min(y0, y1) - 0.35,
                   max(x0, x1) + 0.35, max(y0, y1) + 0.35), ('wire', 'wire', None, None))

    def add_wire(self, pts):
        for i in range(len(pts) - 1):
            self.add_wire_seg((pts[i][0], pts[i][1], pts[i + 1][0], pts[i + 1][1]))

    def set_texts(self, boxes):
        self.text_obs = []
        for b in boxes:
            x0, y0, x1, y1, txt = b
            box = (x0 + TPAD, y0 + TPAD, x1 - TPAD, y1 - TPAD)
            if box[2] <= box[0] or box[3] <= box[1]:
                self.text_obs.append(None); continue
            o = [box, ('text', txt, None, None), True]
            self.text_obs.append(o)
            self._add(box, o[1])

    def _find_text(self, box):
        for o in self.text_obs:
            if o and o[1][1] == box[4] and abs(o[0][0] - (box[0] + TPAD)) < 0.02 \
               and abs(o[0][1] - (box[1] + TPAD)) < 0.02:
                return o
        return None

    def kill_text(self, box):
        o = self._find_text(box)
        if o: o[2] = False

    def restore_text(self, box):
        o = self._find_text(box)
        if o: o[2] = True

    def blocked(self, x, y, ends):
        """ends = 本次允许的两个引脚端点坐标 [(x,y),(x,y)]"""
        for box, tag, alive in self.grid.get((int(x), int(y)), ()):
            if not alive: continue
            if tag[0] == 'wire' and not self.wire_obs: continue
            x0, y0, x1, y1 = box
            if x0 <= x <= x1 and y0 <= y <= y1:
                if tag[0] == 'pin':
                    if any(abs(tag[2] - a) <= 0.05 and abs(tag[3] - b) <= 0.05 for a, b in ends):
                        continue
                return '%s:%s' % (tag[0], tag[1])
        return None

    @staticmethod
    def _p2seg(px, py, x0, y0, x1, y1):
        dx, dy = x1 - x0, y1 - y0
        L2 = dx * dx + dy * dy
        t = 0.0 if L2 == 0 else ((px - x0) * dx + (py - y0) * dy) / L2
        t = 0.0 if t < 0 else (1.0 if t > 1 else t)
        return math.hypot(px - (x0 + t * dx), py - (y0 + t * dy))

    def verts_clear(self, pts, A, B, need=0.35):
        """折点不能落在已有线段上（除首尾 = 目标引脚），否则会产生"疑似连接"的歧义"""
        for q in pts[1:-1]:
            for x0, y0, x1, y1 in self.wsegs:
                if self._p2seg(q[0], q[1], x0, y0, x1, y1) < need:
                    return 'onwire@(%.2f,%.2f)' % (q[0], q[1])
        return None

    def pins_clear(self, pts, A, B, need=0.60):
        """精确检测：任何非目标引脚端点到折线的距离必须 > need（抽样会漏折点，必须几何判）"""
        xs = [p[0] for p in pts]; ys = [p[1] for p in pts]
        x0, x1, y0, y1 = min(xs) - 1.0, max(xs) + 1.0, min(ys) - 1.0, max(ys) + 1.0
        for px, py, tag in self.pins:
            if abs(px - A[0]) < 0.05 and abs(py - A[1]) < 0.05: continue
            if abs(px - B[0]) < 0.05 and abs(py - B[1]) < 0.05: continue
            if not (x0 <= px <= x1 and y0 <= py <= y1): continue
            for i in range(len(pts) - 1):
                if self._p2seg(px, py, pts[i][0], pts[i][1], pts[i + 1][0], pts[i + 1][1]) < need:
                    return 'pin:%s' % tag
        return None

    def seg_ok(self, p0, p1, ends, step=0.8):
        x0, y0 = p0; x1, y1 = p1
        L = math.hypot(x1 - x0, y1 - y0)
        n = max(2, int(L / step))
        for i in range(n + 1):
            f = i / n
            b = self.blocked(x0 + (x1 - x0) * f, y0 + (y1 - y0) * f, ends)
            if b: return b
        return None

    def path_ok(self, pts, ends):
        A, B = ends
        b = self.pins_clear(pts, A, B, self.pin_clear)
        if b: self.last_reason = b; return b
        b = self.verts_clear(pts, A, B)
        if b: self.last_reason = b; return b
        # 其余障碍（本体/已有线/文字）用采样：只跳过"整条路径首尾"附近，折点必须检
        cum = [0.0]
        for i in range(len(pts) - 1):
            cum.append(cum[-1] + math.hypot(pts[i + 1][0] - pts[i][0], pts[i + 1][1] - pts[i][1]))
        total = cum[-1]
        SKIP = 1.2
        if total <= 2 * SKIP: return None
        for i in range(len(pts) - 1):
            L = cum[i + 1] - cum[i]
            n = max(1, int(L / 0.5))
            for k in range(n + 1):
                f = k / n
                s = cum[i] + f * L
                if s < SKIP or total - s < SKIP: continue
                b = self.blocked(pts[i][0] + (pts[i + 1][0] - pts[i][0]) * f,
                                 pts[i][1] + (pts[i + 1][1] - pts[i][1]) * f, ends)
                if b: return b
        return None

    # ---------------- A* 网格寻路（候选式规划失败时的兜底） ----------------
    G = 1.27
    DIRS = [(1, 0), (-1, 0), (0, 1), (0, -1)]

    def _bounds(self):
        if not hasattr(self, '_bb'):
            xs = [b[0] for b in self.bodies.values()] + [b[2] for b in self.bodies.values()]
            ys = [b[1] for b in self.bodies.values()] + [b[3] for b in self.bodies.values()]
            self._bb = (min(xs) - 12.0, max(xs) + 12.0, min(ys) - 12.0, max(ys) + 12.0)
        return self._bb

    def astar(self, A, B, dA, dB, esc=2.54, pad=16.0, turn=0.9):
        import heapq
        G = self.G
        bx0, bx1, by0, by1 = self._bounds()
        ends = (A, B)

        def esc_cell(P, d, e):
            return (int(round((P[0] + d[0] * e) / G)), int(round((P[1] + d[1] * e) / G)))

        si, sj = esc_cell(A, dA, esc); gi, gj = esc_cell(B, dB, esc)
        x0 = max(min(A[0], B[0]) - pad, bx0); x1 = min(max(A[0], B[0]) + pad, bx1)
        y0 = max(min(A[1], B[1]) - pad, by0); y1 = min(max(A[1], B[1]) + pad, by1)
        i0, i1 = int(math.floor(x0 / G)), int(math.ceil(x1 / G))
        j0, j1 = int(math.floor(y0 / G)), int(math.ceil(y1 / G))
        if not (i0 <= si <= i1 and j0 <= sj <= j1 and i0 <= gi <= i1 and j0 <= gj <= j1):
            return None
        W = i1 - i0 + 1; H = j1 - j0 + 1
        blk = bytearray(W * H)
        for j in range(H):
            for i in range(W):
                if self.blocked((i0 + i) * G, (j0 + j) * G, ends):
                    blk[j * W + i] = 1
        blk[(sj - j0) * W + (si - i0)] = 0
        blk[(gj - j0) * W + (gi - i0)] = 0
        dist = {}; prev = {}; h = []
        for d0 in range(4):
            dist[(si, sj, d0)] = 0.0
            heapq.heappush(h, (0.0, si, sj, d0))
        best = None
        while h:
            d, i, j, dd = heapq.heappop(h)
            if d > dist.get((i, j, dd), 1e18) + 1e-9: continue
            if i == gi and j == gj:
                best = (i, j, dd); break
            for nd in range(4):
                ni = i + self.DIRS[nd][0]; nj = j + self.DIRS[nd][1]
                if ni < i0 or ni > i1 or nj < j0 or nj > j1: continue
                if blk[(nj - j0) * W + (ni - i0)]: continue
                nd2 = d + 1.0 + (turn if nd != dd else 0.0)
                k = (ni, nj, nd)
                if nd2 < dist.get(k, 1e18) - 1e-9:
                    dist[k] = nd2; prev[k] = (i, j, dd)
                    heapq.heappush(h, (nd2, ni, nj, nd))
        if best is None: return None
        cells = []; cur = best
        while cur in prev:
            cells.append((cur[0] * G, cur[1] * G))
            cur = prev[cur]
        cells.append((si * G, sj * G))
        cells.reverse()
        # 只保留拐点
        pts = [cells[0]]
        for k in range(1, len(cells) - 1):
            a, b, c = pts[-1], cells[k], cells[k + 1]
            if (abs(a[0] - b[0]) < 0.01 and abs(b[0] - c[0]) < 0.01) or \
               (abs(a[1] - b[1]) < 0.01 and abs(b[1] - c[1]) < 0.01):
                continue
            pts.append(b)
        pts.append(cells[-1])
        return pts

    def plan(self, A, B, dA=None, dB=None):
        ax, ay = A; bx, by = B
        if dA is None: dA = (1, 0) if bx >= ax else (-1, 0)
        if dB is None: dB = (1, 0) if bx >= ax else (-1, 0)
        def out(P, d, e): return (round(P[0] + d[0] * e, 2), round(P[1] + d[1] * e, 2))
        cands = []
        if abs(ax - bx) < 0.01 or abs(ay - by) < 0.01:
            cands.append([A, B])
        for e in (2.54, 5.08):
            Ao = out(A, dA, e); Bo = out(B, dB, e)
            def mk(mid): return [A, Ao] + mid + [Bo, B]
            cands.append(mk([(Bo[0], Ao[1])]))
            cands.append(mk([(Ao[0], Bo[1])]))
            mx = snap((Ao[0] + Bo[0]) / 2); my = snap((Ao[1] + Bo[1]) / 2)
            if abs(mx - Ao[0]) > 1.0 and abs(mx - Bo[0]) > 1.0:
                cands.append(mk([(mx, Ao[1]), (mx, Bo[1])]))
            if abs(my - Ao[1]) > 1.0 and abs(my - Bo[1]) > 1.0:
                cands.append(mk([(Ao[0], my), (Bo[0], my)]))
            for off in (2.54, 5.08, -2.54, -5.08, 7.62, -7.62, 10.16, -10.16, 15.24, -15.24):
                m2 = snap((Ao[0] + Bo[0]) / 2 + off)
                if abs(m2 - Ao[0]) > 1.0 and abs(m2 - Bo[0]) > 1.0:
                    cands.append(mk([(m2, Ao[1]), (m2, Bo[1])]))
                m3 = snap((Ao[1] + Bo[1]) / 2 + off)
                if abs(m3 - Ao[1]) > 1.0 and abs(m3 - Bo[1]) > 1.0:
                    cands.append(mk([(Ao[0], m3), (Bo[0], m3)]))
        best = None
        for c in cands:
            cc = [c[0]]
            for q in c[1:]:
                if abs(q[0] - cc[-1][0]) > 0.01 or abs(q[1] - cc[-1][1]) > 0.01: cc.append(q)
            if len(cc) < 2: continue
            cc = cleanup(cc)
            cc[0] = A; cc[-1] = B          # 首尾强制为精确引脚端点
            if self.path_ok(cc, (A, B)): continue
            L = sum(math.hypot(cc[i + 1][0] - cc[i][0], cc[i + 1][1] - cc[i][1]) for i in range(len(cc) - 1))
            score = (len(cc), round(L, 1))
            if best is None or score < best[0]: best = (score, cc)
            if score[0] == 2: break
        if best is None:                       # 候选式失败 -> A* 兜底
            for esc in (2.54, 1.27, 3.81, 5.08):
                gp = self.astar(A, B, dA, dB, esc=esc)
                if not gp: continue
                Ao = (round(A[0] + dA[0] * esc, 3), round(A[1] + dA[1] * esc, 3))
                Bo = (round(B[0] + dB[0] * esc, 3), round(B[1] + dB[1] * esc, 3))
                for a1 in ([], [(Ao[0], gp[0][1])], [(gp[0][0], Ao[1])]):
                    for b1 in ([], [(gp[-1][0], Bo[1])], [(Bo[0], gp[-1][1])]):
                        cc = cleanup([A, Ao] + a1 + gp + b1 + [Bo, B])
                        cc[0] = A; cc[-1] = B
                        if self.path_ok(cc, (A, B)): continue
                        L = sum(math.hypot(cc[i + 1][0] - cc[i][0], cc[i + 1][1] - cc[i][1])
                                for i in range(len(cc) - 1))
                        score = (len(cc), round(L, 1))
                        if best is None or score < best[0]: best = (score, cc)
                if best: break
        return best[1] if best else None


def cleanup(pts):
    """合并共线点、去掉往复抖动（几何路径不变）。首尾点必须原样保留——
       早期版本用 0.01 容差去重会把精确引脚端点(60.706)当成与取整点(60.71)重复而删掉，
       导致 wire 端点偏离引脚 0.004mm 而连不上。"""
    if len(pts) <= 2:
        return [pts[0], pts[-1]]
    head, tail = pts[0], pts[-1]
    mid = []
    for q in pts[1:-1]:
        if mid and abs(q[0] - mid[-1][0]) < 1e-9 and abs(q[1] - mid[-1][1]) < 1e-9:
            continue
        mid.append(q)
    changed = True
    while changed:
        changed = False
        res = [head] + mid + [tail]
        out = [res[0]]; i = 1
        while i < len(res) - 1:
            a, b, c = out[-1], res[i], res[i + 1]
            if (abs(a[0] - b[0]) < 0.02 and abs(b[0] - c[0]) < 0.02) or \
               (abs(a[1] - b[1]) < 0.02 and abs(b[1] - c[1]) < 0.02):
                changed = True; i += 1; continue
            out.append(res[i]); i += 1
        out.append(res[-1])
        head, mid, tail = out[0], out[1:-1], out[-1]
    return [head] + mid + [tail]


# ---------------- 辅助 ----------------
def span_of(t, s):
    d = 0; i = s
    while True:
        if t[i] == '(': d += 1
        elif t[i] == ')':
            d -= 1
            if d == 0: return i
        i += 1


def collect_labels(t):
    out = []
    for m in re.finditer(r'\t\(label "([^"]+)"\n\t\t\(at ([-\d.]+) ([-\d.]+) ([-\d.]+)\)', t):
        out.append(dict(name=m.group(1), x=float(m.group(2)), y=float(m.group(3)),
                        ang=float(m.group(4)), pos=m.start()))
    return out


def pdf_text_boxes(pdf_path):
    doc = fitz.open(pdf_path); out = []
    def iou(a, b):
        ix0, iy0 = max(a[0], b[0]), max(a[1], b[1]); ix1, iy1 = min(a[2], b[2]), min(a[3], b[3])
        if ix1 <= ix0 or iy1 <= iy0: return 0.0
        it = (ix1 - ix0) * (iy1 - iy0)
        return it / ((a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - it)
    for pg in doc:
        for w in pg.get_text('words'):
            b = (w[0] / MM, w[1] / MM, w[2] / MM, w[3] / MM)
            if not any(d[4] == w[4] and iou(d[:4], b) > 0.7 for d in out):
                out.append((b[0], b[1], b[2], b[3], w[4]))
    return out


def dup_labels(t):
    """同网络 + 同坐标的冗余标签：返回应删除的 pos 列表（每组保留第一个）"""
    g = defaultdict(list)
    for L in collect_labels(t):
        g[(L['name'], round(L['x'], 2), round(L['y'], 2))].append(L)
    out = []
    for k, v in g.items():
        if len(v) > 1:
            out += [L['pos'] for L in v[1:]]
    return sorted(out, reverse=True)


def build_plan(t, libs, insts, eps, pdfs, maxd=60.0, use_text=True, pmaxd=22.0, pcap=10,
               wire_obs=False, pin_clear=0.40):
    R = Router(t, libs, insts, eps, wire_obs=wire_obs, pin_clear=pin_clear)
    if use_text: R.set_texts(pdfs)
    key = {}
    for ref, lst in eps.items():
        for p in lst: key[(round(p['x'], 2), round(p['y'], 2))] = p
    labs = collect_labels(t)
    for L in labs:
        L['pin'] = key.get((round(L['x'], 2), round(L['y'], 2)))
        L['box'] = None
        if use_text:
            best = None
            for b in pdfs:
                if b[4] != L['name']: continue
                d = math.hypot((b[0] + b[2]) / 2 - L['x'], (b[1] + b[3]) / 2 - L['y'])
                if best is None or d < best[0]: best = (d, b)
            if best and best[0] < 2.5: L['box'] = best[1]
    bynet = defaultdict(list)
    for L in labs: bynet[L['name']].append(L)

    pairs = []
    for nm, ls in bynet.items():
        lim = pmaxd if nm in POWER else maxd
        ps = [L for L in ls if L['pin']]
        for i in range(len(ps)):
            for j in range(i + 1, len(ps)):
                d = math.hypot(ps[i]['x'] - ps[j]['x'], ps[i]['y'] - ps[j]['y'])
                if 1.0 <= d <= lim: pairs.append((d, nm, ps[i], ps[j]))   # d<1mm 视为重合，跳过(防死循环)
    pairs.sort(key=lambda z: z[0])
    ok = []; fail = []; used = Counter(); tried = Counter(); dropped = set()
    for d, nm, A, B in pairs:
        cap = pcap if nm in POWER else len([L for L in bynet[nm] if L['pin']]) - 1
        if used[nm] >= cap: continue
        if tried[nm] >= cap + 6: continue          # 每网尝试上限，防止大网络拖垮规划
        if B['pos'] in dropped: continue           # 同一标签只能被替代一次，否则会重复删除
        tried[nm] += 1
        pA, pB = A['pin'], B['pin']
        saved = []
        for bx in (A.get('box'), B.get('box')):
            if bx: R.kill_text(bx); saved.append(bx)
        path = R.plan((A['x'], A['y']), (B['x'], B['y']), (pA['dirx'], pA['diry']), (pB['dirx'], pB['diry']))
        if path:
            R.add_wire(path); used[nm] += 1; dropped.add(B['pos'])
            ok.append(dict(d=d, net=nm, keep=A, drop=B, path=path))
        else:
            for bx in saved: R.restore_text(bx)
            fail.append((d, nm, A, B))
    return ok, fail, bynet
