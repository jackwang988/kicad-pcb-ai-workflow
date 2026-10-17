#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""net_verify.py — 单网络连通性验证（走线/过孔/焊盘是否连成一体，有无断点）
用法: python net_verify.py <net1> [net2 ...]
"""
import sys, io, math
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
import pcbnew

from _runtime import board_option
PCB = board_option()
b = pcbnew.LoadBoard(PCB)
MM = lambda v: v / 1e6
R = lambda t: (round(t[0], 2), round(t[1], 2))

nets = sys.argv[1:]
if not nets:
    sys.exit('需指定网络名')

for net in nets:
    # 节点：走线端点 + 过孔 + 焊盘（按坐标+层归组）
    parent = {}

    def find(k):
        parent.setdefault(k, k)
        while parent[k] != k:
            parent[k] = parent[parent[k]]
            k = parent[k]
        return k

    def union(a, c):
        ra, rc = find(a), find(c)
        if ra != rc:
            parent[ra] = rc

    pads = []
    for fp in b.GetFootprints():
        for pd in fp.Pads():
            if str(pd.GetNetname()) != net:
                continue
            p = pd.GetPosition()
            bb = pd.GetBoundingBox()
            pads.append((fp.GetReference(), pd.GetNumber(),
                         (MM(p.x), MM(p.y)),
                         (MM(bb.GetLeft()), MM(bb.GetTop()), MM(bb.GetRight()), MM(bb.GetBottom())),
                         pd.GetLayerSet()))

    def near(pt, tol=0.12):
        """找与该点重合的节点（含落在焊盘矩形内的）"""
        for (ref, pn, c, bb, ls) in pads:
            if bb[0] - tol <= pt[0] <= bb[2] + tol and bb[1] - tol <= pt[1] <= bb[3] + tol:
                return ('PAD', ref, pn)
        return ('PT',) + R(pt)

    ntrk = nvia = 0
    for t in b.GetTracks():
        if str(t.GetNetname()) != net:
            continue
        if t.GetClass() == 'PCB_TRACK':
            a = (MM(t.GetStart().x), MM(t.GetStart().y))
            c = (MM(t.GetEnd().x), MM(t.GetEnd().y))
            union(near(a), near(c))
            ntrk += 1
        elif t.GetClass() == 'PCB_VIA':
            p = (MM(t.GetPosition().x), MM(t.GetPosition().y))
            union(near(p), ('V',) + R(p))
            nvia += 1

    comps = {}
    for k in list(parent):
        comps.setdefault(find(k), []).append(k)
    pad_nodes = [('PAD', r, n) for (r, n, c, bb, ls) in pads]
    groups = {}
    for pn in pad_nodes:
        if pn in parent:
            groups.setdefault(find(pn), []).append('%s.%s' % (pn[1], pn[2]))
    ncomp = len([g for g in groups.values()])
    ok = (ncomp <= 1 and len(groups) > 0)
    print('%-24s 走线%3d 过孔%2d 焊盘%2d -> 连通组 %d  %s'
          % (net, ntrk, nvia, len(pads), ncomp, 'OK' if ok else 'FAIL(断线!)'))
    if not ok:
        for root, members in groups.items():
            print('     组:', members)
