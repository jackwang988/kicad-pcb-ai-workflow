#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""fold_check.py — 全板折叠(打结)体检
对每个非 GND 网络: 焊盘两两之间用铜皮图求最短铜路径, 检测:
  1) V 形折返: 相邻段"前进方向反转"(夹角 > 90°) 次数 >= 2
  2) 折叠度  : 路径长度 / 路径包围盒对角线 > 1.6
任一命中即判"折叠(SKILL.md §6)"。
用法: python fold_check.py [折返阈值] [折叠度阈值]    默认 2 1.6
"""
import sys, math, heapq
import pcbnew

from _runtime import board_option
PATH = board_option()
MM = lambda v: v / 1e6
U_TURNS = int(sys.argv[1]) if len(sys.argv) > 1 else 2
FOLD_RATIO = float(sys.argv[2]) if len(sys.argv) > 2 else 1.6
MIN_LEN = 3.0

b = pcbnew.LoadBoard(PATH)


def seg_dist(px, py, x0, y0, x1, y1):
    dx, dy = x1 - x0, y1 - y0
    L2 = dx * dx + dy * dy
    t = 0.0 if L2 == 0 else max(0.0, min(1.0, ((px - x0) * dx + (py - y0) * dy) / L2))
    return math.hypot(px - (x0 + t * dx), py - (y0 + t * dy))


def rect_gap(px, py, r):
    return math.hypot(max(r[0] - px, 0.0, px - r[2]), max(r[1] - py, 0.0, py - r[3]))


def gap(k1, g1, k2, g2):
    if (k1, k2) == ('S', 'R') or (k1, k2) == ('C', 'R') or (k1, k2) == ('C', 'S'):
        return gap(k2, g2, k1, g1)
    if k1 == 'R' and k2 == 'R':
        dx = max(g1[0] - g2[2], g2[0] - g1[2], 0.0)
        dy = max(g1[1] - g2[3], g2[1] - g1[3], 0.0)
        return math.hypot(dx, dy)
    if k1 == 'R' and k2 == 'S':
        return min(rect_gap(g2[0], g2[1], g1), rect_gap(g2[2], g2[3], g1))
    if k1 == 'R' and k2 == 'C':
        return rect_gap(g2[0], g2[1], g1) - g2[2]
    if k1 == 'S' and k2 == 'S':
        return min(seg_dist(g2[0], g2[1], g1[0], g1[1], g1[2], g1[3]),
                   seg_dist(g2[2], g2[3], g1[0], g1[1], g1[2], g1[3]),
                   seg_dist(g1[0], g1[1], g2[0], g2[1], g2[2], g2[3]),
                   seg_dist(g1[2], g1[3], g2[0], g2[1], g2[2], g2[3]))
    if k1 == 'S' and k2 == 'C':
        return seg_dist(g2[0], g2[1], g1[0], g1[1], g1[2], g1[3]) - g2[2]
    if k1 == 'C' and k2 == 'C':
        return math.hypot(g1[0] - g2[0], g1[1] - g2[1]) - g1[2] - g2[2]
    return 9e9


# ---- 收集元素: (kind, geom, center) ; kind: R=pad矩形 S=走线段 C=过孔圆 ----
nets = {}
for fp in b.GetFootprints():
    for p in fp.Pads():
        nm = (p.GetNetname() or '').lstrip('/')
        if not nm or nm == 'GND':
            continue
        bb = p.GetBoundingBox()
        r = (MM(bb.GetLeft()), MM(bb.GetTop()), MM(bb.GetRight()), MM(bb.GetBottom()))
        cx, cy = (r[0] + r[2]) / 2, (r[1] + r[3]) / 2
        nets.setdefault(nm, {'R': [], 'S': [], 'C': []})
        nets[nm]['R'].append((r, (cx, cy), fp.GetReference() + '.' + p.GetPadName()))
for t in b.GetTracks():
    nm = (t.GetNetname() or '').lstrip('/')
    if not nm or nm == 'GND':
        continue
    if t.Type() == pcbnew.PCB_VIA_T:
        c = t.GetPosition()
        x, y = MM(c.x), MM(c.y)
        nets.setdefault(nm, {'R': [], 'S': [], 'C': []})
        nets[nm]['C'].append(((x, y, 0.125), (x, y), 'via'))
    else:
        s, e = t.GetStart(), t.GetEnd()
        g = (MM(s.x), MM(s.y), MM(e.x), MM(e.y))
        cx, cy = (g[0] + g[2]) / 2, (g[1] + g[3]) / 2
        nets.setdefault(nm, {'R': [], 'S': [], 'C': []})
        nets[nm]['S'].append((g, (cx, cy), 'seg'))


def build_graph(items):
    """items: [(kind, geom, center, tag)] -> 邻接表"""
    n = len(items)
    adj = [[] for _ in range(n)]
    for i in range(n):
        ki, gi, ci, _ = items[i]
        for j in range(i + 1, n):
            kj, gj, cj, _ = items[j]
            d = gap(ki, gi, kj, gj)
            if d < 0.05:
                w = math.hypot(ci[0] - cj[0], ci[1] - cj[1])
                adj[i].append((j, w))
                adj[j].append((i, w))
    return adj


def dijkstra(adj, s, t):
    n = len(adj)
    dist = [9e9] * n
    prev = [-1] * n
    dist[s] = 0.0
    pq = [(0.0, s)]
    while pq:
        d, u = heapq.heappop(pq)
        if d > dist[u] + 1e-12:
            continue
        if u == t:
            break
        for v, w in adj[u]:
            nd = d + w
            if nd < dist[v] - 1e-12:
                dist[v] = nd
                prev[v] = u
                heapq.heappush(pq, (nd, v))
    if dist[t] >= 9e8:
        return None, None
    path = []
    u = t
    while u != -1:
        path.append(u)
        u = prev[u]
    path.reverse()
    return dist[t], path


def analyze(pts):
    """pts: 中心点序列 -> (路径长, 折返次数, 折叠度)"""
    # 去掉连续重复点
    q = [pts[0]]
    for p in pts[1:]:
        if math.hypot(p[0] - q[-1][0], p[1] - q[-1][1]) > 1e-6:
            q.append(p)
    if len(q) < 2:
        return 0.0, 0, 0.0
    L = sum(math.hypot(q[k + 1][0] - q[k][0], q[k + 1][1] - q[k][1]) for k in range(len(q) - 1))
    # 折返: 相邻方向夹角 > 90°
    turns = 0
    for k in range(1, len(q) - 1):
        v1 = (q[k][0] - q[k - 1][0], q[k][1] - q[k - 1][1])
        v2 = (q[k + 1][0] - q[k][0], q[k + 1][1] - q[k][1])
        n1 = math.hypot(*v1)
        n2 = math.hypot(*v2)
        if n1 < 1e-6 or n2 < 1e-6:
            continue
        cos = (v1[0] * v2[0] + v1[1] * v2[1]) / (n1 * n2)
        cos = max(-1.0, min(1.0, cos))
        if math.degrees(math.acos(cos)) > 90.0:
            turns += 1
    xs = [p[0] for p in q]
    ys = [p[1] for p in q]
    diag = math.hypot(max(xs) - min(xs), max(ys) - min(ys))
    fold = L / diag if diag > 0.3 else 0.0
    return L, turns, fold


print('=== 折叠体检 (折返>=%d 或 折叠度>%.2f) ===' % (U_TURNS, FOLD_RATIO))
hits = []
for nm in sorted(nets):
    d = nets[nm]
    items = []
    for kind in ('R', 'S', 'C'):
        for (g, c, tag) in d[kind]:
            items.append((kind if kind != 'R' else 'R', g, c, tag))
    pads = [i for i, it in enumerate(items) if it[0] == 'R']
    if len(pads) < 2 or len(items) > 400:
        continue
    adj = build_graph(items)
    for a in range(len(pads)):
        for b2 in range(a + 1, len(pads)):
            ia, ib = pads[a], pads[b2]
            ca, cb = items[ia][2], items[ib][2]
            eu = math.hypot(ca[0] - cb[0], ca[1] - cb[1])
            if eu < MIN_LEN:
                continue
            L, path = dijkstra(adj, ia, ib)
            if path is None:
                continue
            pts = [items[i][2] for i in path]
            pl, turns, fold = analyze(pts)
            if turns >= U_TURNS or fold > FOLD_RATIO:
                hits.append((turns, fold, pl, eu, nm,
                             items[ia][3], items[ib][3]))
hits.sort(key=lambda h: (-h[0], -h[1]))
print('共 %d 条折叠/打结:' % len(hits))
print('  折返  折叠度   路径     直线   网络                  两端')
for turns, fold, pl, eu, nm, ta, tb in hits:
    print('  %3d   %5.2f  %6.1fmm %6.1fmm  %-20s %s <-> %s' %
          (turns, fold, pl, eu, nm[:20], ta, tb))
