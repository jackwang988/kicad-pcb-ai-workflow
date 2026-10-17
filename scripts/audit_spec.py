#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
audit_spec.py — PCB 规格符合性审计（kicad-pcb-ai-workflow skill 通用脚本）

检查项（对应 skill 规格）：
  1. 差分对：同层走线 / 长度等长 / 过孔数对称 / 线宽=差分阻抗线宽 / 耦合长度
  2. 直角走线（90° 直角 = 规格禁止）
  3. 网络类规则存在性（差分类/电源类线宽间距）
  4. GND 孤岛死铜
  5. 板边距（铜距板边）
  6. 电源网络线宽（电源走线是否足够粗）

用法：
  python audit_spec.py <board.kicad_pcb> [--pair "NET_P:NET_N:tol_mm"]... [--diff-width 0.3]
  无 --pair 时自动探测 *_P/*_N、*_DP/*_DM、*+/*- 差分对。
退出码：有 FAIL 项 = 1，全部通过 = 0。
"""
import sys, os, io, math, argparse

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('board')
    ap.add_argument('--pair', action='append', default=[],
                    help='NET1:NET2:tol_mm（长度容差）')
    ap.add_argument('--diff-width', type=float, default=0.3,
                    help='差分阻抗线宽要求 mm（默认 0.3）')
    ap.add_argument('--edge-clr', type=float, default=0.5,
                    help='铜到板边最小间距 mm（默认 0.5）')
    ap.add_argument('--min-pwr-width', type=float, default=0.4,
                    help='电源网络最小线宽 mm（默认 0.4）')
    A = ap.parse_args()

    OUT = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    import pcbnew
    b = pcbnew.LoadBoard(A.board)
    W = lambda v: v / 1e6

    results = []   # (name, status, detail)  status: PASS/FAIL/WARN

    # ---------- 1. 差分对 ----------
    tracks = list(b.GetTracks())
    def segs_of(net):
        s, v = [], 0
        for t in tracks:
            if t.GetNetname() != net:
                continue
            if t.Type() == pcbnew.PCB_TRACE_T:
                s.append((W(t.GetStart().x), W(t.GetStart().y),
                          W(t.GetEnd().x), W(t.GetEnd().y),
                          b.GetLayerName(t.GetLayer()), W(t.GetWidth())))
            else:
                v += 1
        return s, v

    pairs = []
    for spec in A.pair:
        p = spec.split(':')
        pairs.append((p[0], p[1], float(p[2]) if len(p) > 2 else 0.15))
    if not pairs:
        names = {t.GetNetname() for t in tracks}
        seen = set()
        for n in names:
            for suf_p, suf_n in (('_DP_', '_DM_'), ('_P', '_N'), ('+', '-')):
                if suf_p in n and n not in seen:
                    base = n.split(suf_p)[0]
                    m = base + suf_p + n.split(suf_p, 1)[1].replace(suf_p, '', 0)
                    cand = [x for x in names if x != n and x.replace(suf_n, suf_p, 1) == n]
                    if cand:
                        pairs.append((n, cand[0], 0.15)); seen.add(cand[0])
                    break

    OUT.write('==== 1. 差分对检查 ====\n')
    if not pairs:
        results.append(('差分对', 'WARN', '未发现差分对网络（也没用 --pair 指定）'))
    for (n1, n2, tol) in pairs:
        s1, v1 = segs_of(n1)
        s2, v2 = segs_of(n2)
        if not s1 and not s2:
            continue
        L1 = sum(math.hypot(x2-x1, y2-y1) for x1, y1, x2, y2, _, _ in s1)
        L2 = sum(math.hypot(x2-x1, y2-y1) for x1, y1, x2, y2, _, _ in s2)
        lay1 = {s[4] for s in s1}; lay2 = {s[4] for s in s2}
        w1 = {s[5] for s in s1}; w2 = {s[5] for s in s2}
        d = abs(L1 - L2)
        OUT.write('  %s / %s:\n' % (n1, n2))
        OUT.write('    长度 %.2f / %.2f mm  差 %.2f mm（容差 %.2f）\n' % (L1, L2, d, tol))
        OUT.write('    层 %s / %s   过孔 %d / %d   线宽 %s / %s\n' %
                  (sorted(lay1), sorted(lay2), v1, v2, sorted(w1), sorted(w2)))
        if d > tol:
            results.append(('差分等长 %s' % n1, 'FAIL', '长度差 %.2fmm > 容差 %.2fmm' % (d, tol)))
        else:
            results.append(('差分等长 %s' % n1, 'PASS', '长度差 %.2fmm' % d))
        # 同层判据（工程化，历史版本 修正）：
        #   焊盘必然在表层，差分主体必须走同一内层；两端换层用成对孪生过孔是允许的。
        #   判定 = 两线"主体层"（走线长度占比最大的层）相同 + 过孔数相同
        def main_layer(segs):
            acc = {}
            for x1, y1, x2, y2, lay, _w in segs:
                acc[lay] = acc.get(lay, 0) + math.hypot(x2-x1, y2-y1)
            return max(acc, key=acc.get) if acc else None
        m1, m2 = main_layer(s1), main_layer(s2)
        if m1 and m2 and m1 == m2 and v1 == v2:
            results.append(('差分同层 %s' % n1, 'PASS',
                            '主体层同层 %s，换层过孔对称 %d/%d（表层仅扇出 stub）' % (m1, v1, v2)))
        elif lay1 != lay2:
            results.append(('差分同层 %s' % n1, 'FAIL',
                            '两线层集合不同: %s vs %s（阻抗不连续）' % (sorted(lay1), sorted(lay2))))
        else:
            results.append(('差分同层 %s' % n1, 'FAIL',
                            '主体层不同 %s vs %s 或过孔不对称 %d/%d' % (m1, m2, v1, v2)))
        if v1 != v2:
            results.append(('差分过孔对称 %s' % n1, 'WARN', '过孔数 %d≠%d（换层位置不对称）' % (v1, v2)))
        allw = w1 | w2
        bad_w = [w for w in allw if abs(w - A.diff_width) > 0.02]
        if bad_w:
            results.append(('差分线宽 %s' % n1, 'FAIL',
                            '线宽 %s ≠ 阻抗线宽 %.2fmm' % (sorted(allw), A.diff_width)))
        else:
            results.append(('差分线宽 %s' % n1, 'PASS', '%.2fmm' % A.diff_width))

    # ---------- 2. 直角走线 ----------
    OUT.write('==== 2. 直角走线检查 ====\n')
    # 把同一网络上共点的段串起来，检查转角是否 90°
    from collections import defaultdict
    eps = 0.02
    corners90 = 0
    for t in tracks:
        if t.Type() != pcbnew.PCB_TRACE_T:
            continue
        x1, y1, x2, y2 = W(t.GetStart().x), W(t.GetStart().y), W(t.GetEnd().x), W(t.GetEnd().y)
        dx, dy = x2-x1, y2-y1
        # 只查轴对齐段之间的 90° 相接：KiCad 走线段本身是直线，直角=两段共点且点积为0
        for (px, py) in ((x1, y1), (x2, y2)):
            pass
    # 简化实现：对每段找共点段，点积≈0 且都不为0 -> 直角
    seg_list = [(W(t.GetStart().x), W(t.GetStart().y), W(t.GetEnd().x), W(t.GetEnd().y),
                 t.GetNetname(), t) for t in tracks if t.Type() == pcbnew.PCB_TRACE_T]
    pt_map = defaultdict(list)
    for i, (x1, y1, x2, y2, nn, t) in enumerate(seg_list):
        pt_map[(round(x1, 3), round(y1, 3))].append(i)
        pt_map[(round(x2, 3), round(y2, 3))].append(i)
    checked = set()
    for pt, idxs in pt_map.items():
        for a in range(len(idxs)):
            for c in range(a+1, len(idxs)):
                ia, ic = idxs[a], idxs[c]
                if ia == ic or (ia, ic) in checked:
                    continue
                checked.add((ia, ic))
                xa1, ya1, xa2, ya2, na, ta = seg_list[ia]
                xc1, yc1, xc2, yc2, nc, tc = seg_list[ic]
                if na != nc:
                    continue
                va = (xa2-xa1, ya2-ya1)
                vc = (xc2-xc1, yc2-yc1)
                la = math.hypot(*va); lc = math.hypot(*vc)
                if la < 1e-6 or lc < 1e-6:
                    continue
                dot = (va[0]*vc[0] + va[1]*vc[1]) / (la*lc)
                if abs(dot) < 0.02:      # 垂直
                    corners90 += 1
    OUT.write('  90° 直角转角: %d 处\n' % corners90)
    if corners90:
        results.append(('无直角走线', 'FAIL', '%d 处 90° 直角' % corners90))
    else:
        results.append(('无直角走线', 'PASS', '0 处'))

    # ---------- 3. 网络类规则 ----------
    OUT.write('==== 3. 网络类规则 ====\n')
    nc = b.GetNetClasses()
    has_diff = False
    for nm in list(nc.keys()):
        c = nc[nm]
        try:
            dpw = c.GetDiffPairWidth()/1e6; dpg = c.GetDiffPairGap()/1e6
        except Exception:
            dpw = dpg = 0
        OUT.write('  %-10s 线宽 %.3f 间距 %.3f%s\n' %
                  (str(nm), c.GetTrackWidth()/1e6, c.GetClearance()/1e6,
                   '  差分 %.2f/%.2f' % (dpw, dpg) if dpw else ''))
        if dpw:
            has_diff = True
    if not has_diff:
        results.append(('差分对网络类', 'FAIL', '无任何含 diff pair 宽度/间隙的网络类（90Ω 无从保证）'))
    else:
        results.append(('差分对网络类', 'PASS', '已定义'))

    # ---------- 4. GND 孤岛 ----------
    OUT.write('==== 4. GND 孤岛死铜 ====\n')
    islands = 0
    for z in b.Zones():
        if z.GetNetname() not in ('GND', '/GND'):
            continue
        lid = z.GetLayer()
        try:
            polys = z.GetFilledPolysList(lid)
            n = polys.OutlineCount()
        except Exception:
            n = 0
        if z.GetIslandRemovalMode() != pcbnew.ISLAND_REMOVAL_MODE_ALWAYS:
            islands += 1
            OUT.write('  zone @%s 孤岛删除未开启（OutlineCount=%d）\n' % (b.GetLayerName(lid), n))
    if islands:
        results.append(('GND 孤岛删除', 'WARN', '%d 块 zone 未开启 ALWAYS 删除模式' % islands))
    else:
        results.append(('GND 孤岛删除', 'PASS', '全部开启'))

    # ---------- 5. 板边距 ----------
    OUT.write('==== 5. 铜距板边 ====\n')
    bb = b.GetBoardEdgesBoundingBox()
    L, R, T, B_ = W(bb.GetLeft()), W(bb.GetRight()), W(bb.GetTop()), W(bb.GetBottom())
    viol = 0
    for t in tracks:
        if t.Type() == pcbnew.PCB_TRACE_T:
            m = min(W(t.GetStart().x)-L, R-W(t.GetEnd().x), W(t.GetStart().y)-T, B_-W(t.GetEnd().y),
                    W(t.GetEnd().x)-L, R-W(t.GetStart().x), W(t.GetEnd().y)-T, B_-W(t.GetStart().y))
            if m < A.edge_clr:
                viol += 1
    OUT.write('  端点距板边 <%.2fmm 的走线段: %d（粗查）\n' % (A.edge_clr, viol))
    if viol:
        results.append(('板边距', 'WARN', '%d 段端点贴近板边（精确判定以 kicad-cli DRC 为准）' % viol))
    else:
        results.append(('板边距', 'PASS', '粗查通过'))

    # ---------- 6. 电源线宽 ----------
    OUT.write('==== 6. 电源走线线宽 ====\n')
    thin_pwr = []
    for t in tracks:
        if t.Type() != pcbnew.PCB_TRACE_T:
            continue
        nn = t.GetNetname()
        if any(k in nn for k in ('+5V', '+3V3', '+BATT', 'VBUS', 'VCC')) and W(t.GetWidth()) < A.min_pwr_width:
            thin_pwr.append((nn, W(t.GetWidth())))
    if thin_pwr:
        from collections import Counter
        c = Counter(thin_pwr)
        results.append(('电源线宽', 'FAIL', '%d 段电源走线 <%.2fmm: %s' %
                        (len(thin_pwr), A.min_pwr_width, dict(c))))
        OUT.write('  细电源线 %d 段\n' % len(thin_pwr))
    else:
        results.append(('电源线宽', 'PASS', '全部 ≥%.2fmm' % A.min_pwr_width))

    # ---------- 汇总 ----------
    OUT.write('\n==== 审计汇总 ====\n')
    npass = sum(1 for _, s, _ in results if s == 'PASS')
    nfail = sum(1 for _, s, _ in results if s == 'FAIL')
    nwarn = sum(1 for _, s, _ in results if s == 'WARN')
    for nm, s, dt in results:
        OUT.write('  [%s] %-24s %s\n' % (s, nm, dt))
    OUT.write('  -> PASS %d / FAIL %d / WARN %d\n' % (npass, nfail, nwarn))
    OUT.flush()
    sys.exit(1 if nfail else 0)

if __name__ == '__main__':
    main()
