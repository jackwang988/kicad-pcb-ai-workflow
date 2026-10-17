#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
zcheck.py — 布局间距约束闸门 v4（阈值须按项目核实）

默认筛查策略（可按工程要求调整）:
  CHECK1  同面 逐焊盘矩形 两两不得重叠      → FAIL（硬性）
  CHECK2  同面 courtyard（封装自带）不得重叠  → FAIL（硬性，主判据，
           用封装自带 courtyard 作为器件占位区域，覆盖贴片机吸嘴/返修/目检空间）
  CHECK3  位号文字压焊盘/丝印/其他位号        → INFO（默认统计策略：不算问题，仅统计不门控）

退出码：0 = 通过；1 = CHECK1/CHECK2 有违例

用法（KiCad 9 自带 python 运行）:
  python zcheck.py <board>.kicad_pcb [--top 15] [--asm-gap 0.2]
"""
import sys, io, math

from _runtime import positional_board
PCB = positional_board()
TOP = 15
ASM_GAP = 0.2
if '--top' in sys.argv:
    TOP = int(sys.argv[sys.argv.index('--top') + 1])
if '--asm-gap' in sys.argv:
    ASM_GAP = float(sys.argv[sys.argv.index('--asm-gap') + 1])

OUT = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
import pcbnew

b = pcbnew.LoadBoard(PCB)
MM = lambda v: v / 1e6

def rect_of(x):
    r = x.GetBoundingBox() if hasattr(x, 'GetBoundingBox') else x
    return (MM(r.GetLeft()), MM(r.GetTop()), MM(r.GetRight()), MM(r.GetBottom()))

def inter(a, c):
    w = min(a[2], c[2]) - max(a[0], c[0])
    h = min(a[3], c[3]) - max(a[1], c[1])
    return w * h if (w > 0 and h > 0) else 0.0

def gap(a, c):
    dx = max(0.0, max(a[0] - c[2], c[0] - a[2]))
    dy = max(0.0, max(a[1] - c[3], c[1] - a[3]))
    return math.hypot(dx, dy)

F_SILK, B_SILK = pcbnew.F_SilkS, pcbnew.B_SilkS

devs = {}
for fp in b.GetFootprints():
    ref = fp.GetReference()
    if ref.startswith('H'):          # 安装孔无装配体，跳过
        continue
    side = 'B' if fp.IsFlipped() else 'F'
    sl = B_SILK if side == 'B' else F_SILK
    cu = pcbnew.B_Cu if side == 'B' else pcbnew.F_Cu
    pads = [rect_of(p.GetBoundingBox()) for p in fp.Pads() if p.IsOnLayer(cu)]
    ext = None
    if pads:
        ext = (min(r[0] for r in pads), min(r[1] for r in pads),
               max(r[2] for r in pads), max(r[3] for r in pads))
    crt = fp.GetCourtyard(pcbnew.B_CrtYd if side == 'B' else pcbnew.F_CrtYd)
    crt_bb = rect_of(crt.BBox()) if crt.OutlineCount() else ext
    gfx = [rect_of(g) for g in fp.GraphicalItems() if g.GetLayer() == sl]
    texts = []
    for ti in fp.GetFields():
        try:
            if ti.IsVisible() and ti.GetLayer() == sl:
                texts.append((ti.GetShownText(True, False), rect_of(ti)))
        except Exception:
            pass
    devs[ref] = dict(side=side, pads=pads, ext=ext, crt=crt,
                     crt_bb=crt_bb, gfx=gfx, texts=texts)

refs = sorted(devs)
OUT.write('==== 布局间距约束闸门 v4  (%s) ====\n' % PCB)
OUT.write('参与检查器件: %d 个（安装孔跳过）\n' % len(refs))

# ---- CHECK1: 同面逐焊盘矩形不得重叠 ----
f1 = []
for i in range(len(refs)):
    for j in range(i + 1, len(refs)):
        a, c = refs[i], refs[j]
        da, dc = devs[a], devs[c]
        if da['side'] != dc['side'] or not da['pads'] or not dc['pads']:
            continue
        if da['ext'] and dc['ext'] and inter(da['ext'], dc['ext']) <= 0:
            continue          # 器件级外扩不相交 → 焊盘必不相交
        worst = 0.0
        for pa in da['pads']:
            for pc in dc['pads']:
                x = inter(pa, pc)
                if x > worst:
                    worst = x
        if worst > 1e-6:
            f1.append((a, c, da['side'], worst))
OUT.write('\nCHECK1 同面逐焊盘矩形重叠: %d 对  → %s\n' % (len(f1), 'FAIL' if f1 else 'PASS'))
for a, c, s, w in sorted(f1, key=lambda x: -x[3])[:TOP]:
    OUT.write('   [%s] %s x %s  焊盘重叠 %.3f mm²\n' % (s, a, c, w))

# ---- CHECK2: 同面 courtyard（封装自带）不得重叠 ----
f2 = []
gaps = []
for i in range(len(refs)):
    for j in range(i + 1, len(refs)):
        a, c = refs[i], refs[j]
        da, dc = devs[a], devs[c]
        if da['side'] != dc['side']:
            continue
        g = gap(da['crt_bb'], dc['crt_bb'])
        if g > 0:
            if g < 3.0:
                gaps.append((a, c, da['side'], g))
            continue
        try:
            if da['crt'].OutlineCount() == 0 or dc['crt'].OutlineCount() == 0:
                continue
            clip = pcbnew.SHAPE_POLY_SET(da['crt'])
            clip.BooleanIntersection(dc['crt'], pcbnew.PM_FAST)
            area = sum(abs(clip.Outline(k).Area()) for k in range(clip.OutlineCount())) / 1e12
            if area > 1e-6:
                f2.append((a, c, da['side'], area))
        except Exception:
            pass
OUT.write('\nCHECK2 同面 courtyard（封装自带）重叠: %d 对  → %s\n' % (len(f2), 'FAIL' if f2 else 'PASS'))
for a, c, s, w in sorted(f2, key=lambda x: -x[3])[:TOP]:
    OUT.write('   [%s] %s x %s  courtyard 重叠 %.3f mm²\n' % (s, a, c, w))

gaps.sort(key=lambda x: x[3])
if gaps:
    OUT.write('   装配间距参考（courtyard 间隙最紧 %d 对, 建议 >= %.2fmm）:\n' % (min(len(gaps), 8), ASM_GAP))
    for a, c, s, g in gaps[:8]:
        OUT.write('      [%s] %s x %s  gap %.3f mm%s\n' % (s, a, c, g, '  < 建议值' if g < ASM_GAP else ''))

# ---- CHECK3: 位号文字（按 默认统计策略：仅统计，不门控）----
f3 = []
for i in range(len(refs)):
    for j in range(len(refs)):
        if i == j:
            continue
        a, c = refs[i], refs[j]
        da, dc = devs[a], devs[c]
        if da['side'] != dc['side']:
            continue
        for (ta, tba) in da['texts']:
            for bp in dc['pads']:
                if inter(tba, bp) > 0.01:
                    f3.append((ta, a, c, '压焊盘'))
                    break
            else:
                for bg in dc['gfx']:
                    if inter(tba, bg) > 0.01:
                        f3.append((ta, a, c, '压丝印'))
                        break
                else:
                    for (tc, tbc) in dc['texts']:
                        if inter(tba, tbc) > 0.01:
                            f3.append((ta, a, c, '压位号'))
                            break
OUT.write('\nCHECK3 位号文字压线: %d 处  → INFO（默认统计策略不门控，需人工复核后处理）\n' % len(f3))

ok = not (f1 or f2)
OUT.write('\nRESULT: %s\n' % ('PASS' if ok else 'FAIL'))
OUT.flush()
sys.exit(0 if ok else 1)
