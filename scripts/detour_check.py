#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""detour_check.py — 全板绕行体检
对每个非 GND 网络: 焊盘两两之间用铜皮图求最短铜路径长度, 与直线距离比 = 绕行比。
绕行比 > 1.8 且直线距离 > 4mm 判为绕行(与 SKILL.md「最短路径原则」配套)。
用法: python detour_check.py [阈值]     默认 1.8
"""
import sys, math, heapq
import pcbnew

from _runtime import board_option
PATH = board_option()
MM = lambda v: v / 1e6
THRESH = float(sys.argv[1]) if len(sys.argv) > 1 else 1.8
MIN_LEN = 4.0
TOUCH = 0.06

b = pcbnew.LoadBoard(PATH)
ALLL = [0, 2, 4, 6, 8, 10, 12, 14]

def seg_dist(px, py, x0, y0, x1, y1):
    dx, dy = x1 - x0, y1 - y0
    L2 = dx * dx + dy * dy
    t = 0.0 if L2 == 0 else max(0.0, min(1.0, ((px - x0) * dx + (py - y0) * dy) / L2))
    return math.hypot(px - (x0 + t * dx), py - (y0 + t * dy))

def rect_gap(px, py, r):
    return math.hypot(max(r[0] - px, 0.0, px - r[2]), max(r[1] - py, 0.0, py - r[3]))

def gap(k1, g1, k2, g2):
    if k1 == 'S' and k2 == 'R': k1, g1, k2, g2 = k2, g2, k1, g1
    if k1 == 'C' and k2 == 'R': k1, g1, k2, g2 = k2, g2, k1, g1
    if k1 == 'C' and k2 == 'S': k1, g1, k2, g2 = k2, g2, k1, g1
    if k1 == 'R' and k2 == 'R':
        dx = max(g1[0] - g2[2], g2[0] - g1[2], 0.0)
        dy = max(g1[1] - g2[3], g2[1] - g1[3], 0.0)
        return math.hypot(dx, dy)
    if k1 == 'R' and k2 == 'S':
        return seg_dist(g2[0], g2[1], *g1[:2]) if False else min(
            rect_gap(g2[0], g2[1], g1), rect_gap(g2[2], g2[3], g1))
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

# 收集每个网络的元素
nets = {}
for fp in b.GetFootprints():
    for p in fp.Pads():
        nm = (p.GetNetname() or '').lstrip('/')
        if not nm or nm == 'GND':
            continue
        bb = p.GetBoundingBox()
        r = (MM(bb.GetLeft()), MM(bb.GetTop()), MM(bb.GetRight()), MM(bb.GetBottom()))
        lays = frozenset(L for L in ALLL if p.IsOnLayer(L))
        cx, cy = (r[0] + r[2]) / 2, (r[1] + r[3]) / 2
        nets.setdefault(nm, []).append(('R', r, lays, (cx, cy), '%s.%s' % (fp.GetReference(), p.GetPadName())))
for t in b.GetTracks():
    nm = (t.GetNetname() or '').lstrip('/')
    if not nm or nm == 'GND':
        continue
    if t.Type() == pcbnew.PCB_VIA_T:
        c = t.GetPosition()
        nets.setdefault(nm, []).append(('C', (MM(c.x), MM(c.y), MM(t.GetWidth(pcbnew.F_Cu)) / 2),
                                        frozenset(ALLL), (MM(c.x), MM(c.y)), 'VIA'))
    else:
        s, e = t.GetStart(), t.GetEnd()
        nets.setdefault(nm, []).append(('S', (MM(s.x), MM(s.y), MM(e.x), MM(e.y)),
                                        frozenset([t.GetLayer()]), None, None))

report = []
for nm, els in nets.items():
    pads = [e for e in els if e[0] == 'R']
    if len(pads) < 2:
        continue
    # 节点: 每个元素取代表点(焊盘中心/段两端/过孔心)
    nodes = []
    for idx, e in enumerate(els):
        k, geo, lays = e[0], e[1], e[2]
        if k == 'R':
            nodes.append((e[3][0], e[3][1], lays, idx, 'P', e[4]))
        elif k == 'S':
            nodes.append((geo[0], geo[1], lays, idx, 'E', None))
            nodes.append((geo[2], geo[3], lays, idx, 'E', None))
        else:
            nodes.append((geo[0], geo[1], lays, idx, 'V', 'VIA'))
    n = len(nodes)
    adj = [[] for _ in range(n)]
    for i in range(n):
        for j in range(i + 1, n):
            ni, nj = nodes[i], nodes[j]
            if not (ni[2] & nj[2]):
                continue
            d = math.hypot(ni[0] - nj[0], ni[1] - nj[1])
            if d < TOUCH:
                adj[i].append((j, d))
                adj[j].append((i, d))
    # 同元素两端相连(段长)
    for i in range(n):
        for j in range(i + 1, n):
            if nodes[i][3] == nodes[j][3] and nodes[i][3] is not None:
                d = math.hypot(nodes[i][0] - nodes[j][0], nodes[i][1] - nodes[j][1])
                adj[i].append((j, d))
                adj[j].append((i, d))

    def dijkstra(src):
        dist = {src: 0.0}
        h = [(0.0, src)]
        while h:
            d, u = heapq.heappop(h)
            if d > dist.get(u, 9e9):
                continue
            for v, w in adj[u]:
                nd = d + w
                if nd < dist.get(v, 9e9):
                    dist[v] = nd
                    heapq.heappush(h, (nd, v))
        return dist

    pad_idx = [i for i, nd in enumerate(nodes) if nd[4] == 'P']
    dists = {}
    for a in range(len(pad_idx)):
        da = dijkstra(pad_idx[a])
        for c in range(a + 1, len(pad_idx)):
            bi = pad_idx[c]
            pa, pc = nodes[pad_idx[a]], nodes[bi]
            straight = math.hypot(pa[0] - pc[0], pa[1] - pc[1])
            if straight < MIN_LEN:
                continue
            copper = da.get(bi, 9e9)
            if copper >= 9e9:
                continue
            ratio = copper / straight
            if ratio > THRESH:
                report.append((ratio, copper, straight, nm, pa[5], pc[5]))

report.sort(reverse=True)
print('=== 绕行体检 (阈值 %.1f, 直线距离 >= %.0fmm) ===' % (THRESH, MIN_LEN))
print('%-6s %-9s %-8s %-24s %s' % ('比值', '铜路径', '直线', '网络', '两端'))
for ratio, copper, straight, nm, pa, pc in report:
    print('%5.2fx  %6.1fmm %6.1fmm  %-24s %s <-> %s' % (ratio, copper, straight, nm, pa, pc))
print('\n共 %d 处疑似绕行' % len(report))
