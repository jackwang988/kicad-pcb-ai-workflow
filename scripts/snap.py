#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
snap.py — PCB 自截图工具（KiCad 9 / pcbnew + PIL）

用途：任何一次 PCB 改动之后，自己把板子画成 PNG 目视核对，
     避免"脚本说 PASS 但实际不合规格"的假闭环。

用法（必须用 KiCad 自带 python 运行）:
  python snap.py <board>.kicad_pcb --layer F.Cu --out x.png
  python snap.py <board>.kicad_pcb --layers F.Cu,In2.Cu --bbox 130,85,175,110 --scale 30 --out usb.png
  python snap.py <board>.kicad_pcb --layer In2.Cu --hl USB_DP,USB_DM --bbox 138,88,170,106 --scale 60 --out usb_l3.png

参数:
  --layer / --layers   要画的层（逗号分隔），可用 F.Cu In1.Cu..In6.Cu B.Cu F.SilkS B.SilkS
                       Edge.Cuts 永远画（板框）
  --bbox x0,y0,x1,y1   只看这块区域（板坐标 mm）；缺省=整板
  --scale N            像素/毫米，缺省自动（整板按 1400px 宽，局部按 30）
  --hl NET1,NET2       高亮网络（其余线淡化），高亮网用醒目色 + 图例
  --no-zone            不画铺铜
  --no-pad             不画焊盘
  --no-ref             不画位号
  --no-track           不画走线
  --grid N             画 N mm 网格（默认 5mm）
  --mark "x,y,文字"    在图右上角标注（可多次）
  --out FILE           输出 PNG（默认 snap.png）

颜色：底层 F.Cu 红、中间层按调色板、B.Cu 绿；高亮网用各自颜色。
"""
import sys, os, math, io, argparse

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
import pcbnew
from PIL import Image, ImageDraw, ImageFont

MM = lambda v: v / 1e6

# ---- 层调色板（浅底深线，保证 Read 看图清晰）----
PAL = {
    'F.Cu':  (200,  30,  40),
    'B.Cu':  ( 20, 130,  70),
    'In1.Cu':( 60, 110, 200),
    'In2.Cu':(220, 130,  20),
    'In3.Cu':(120,  70, 190),
    'In4.Cu':(  0, 150, 160),
    'In5.Cu':(180,  90,  60),
    'In6.Cu':(210,  60, 150),
}
PAL_HL = [(230, 20, 20), (20, 60, 220), (0, 150, 90), (230, 140, 0), (150, 0, 180)]
BG = (250, 250, 248)
ZONE_FILL = {
    'F.Cu': (250, 214, 214), 'B.Cu': (214, 240, 226),
    'In1.Cu': (214, 228, 248), 'In2.Cu': (250, 232, 208),
    'In3.Cu': (230, 220, 246), 'In4.Cu': (210, 242, 242),
    'In5.Cu': (240, 226, 214), 'In6.Cu': (248, 216, 234),
}
GND_TINT = (232, 244, 232)


def layer_id(b, name):
    key = name.replace('.', '_')
    if hasattr(pcbnew, key):
        return int(getattr(pcbnew, key))
    for i in range(0, 64):
        try:
            if b.GetLayerName(i).replace('.', '_') == key:
                return i
        except Exception:
            pass
    raise SystemExit('未知层: %s' % name)


def poly_pts(poly_set, maxpts=4000):
    """SHAPE_POLY_SET -> [[(x,y)...], ...] 单位 mm（点数过多时抽稀，防止渲染卡死）"""
    out = []
    if poly_set is None:
        return out
    try:
        n = poly_set.OutlineCount()
    except Exception:
        return out
    for i in range(n):
        try:
            ch = poly_set.Outline(i)
        except Exception:
            ch = poly_set.COutline(i)
        pts = []
        n0 = ch.PointCount()
        step = 1 if n0 <= maxpts else int(math.ceil(n0 / float(maxpts)))
        for j in range(0, n0, step):
            p = ch.GetPoint(j)
            pts.append((MM(p.x), MM(p.y)))
        if len(pts) >= 3:
            out.append(pts)
    return out


def rot(p, c, deg):
    a = math.radians(deg)
    dx, dy = p[0] - c[0], p[1] - c[1]
    return (c[0] + dx * math.cos(a) - dy * math.sin(a),
            c[1] + dx * math.sin(a) + dy * math.cos(a))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('board')
    ap.add_argument('--layer', default='F.Cu')
    ap.add_argument('--layers', default=None)
    ap.add_argument('--bbox', default=None)
    ap.add_argument('--scale', type=float, default=0)
    ap.add_argument('--hl', default=None)
    ap.add_argument('--no-zone', action='store_true')
    ap.add_argument('--no-pad', action='store_true')
    ap.add_argument('--no-ref', action='store_true')
    ap.add_argument('--no-track', action='store_true')
    ap.add_argument('--no-via', action='store_true')
    ap.add_argument('--grid', type=float, default=5.0)
    ap.add_argument('--mark', action='append', default=[])
    ap.add_argument('--out', default='snap.png')
    ap.add_argument('--maxpx', type=int, default=1400)
    a = ap.parse_args()

    b = pcbnew.LoadBoard(a.board)
    names = [s.strip() for s in (a.layers or a.layer).split(',') if s.strip()]
    lids = [layer_id(b, n) for n in names]
    lname = {lid: n for lid, n in zip(lids, names)}

    hl = [s.strip() for s in a.hl.split(',')] if a.hl else []
    hlcol = {}
    for i, n in enumerate(hl):
        hlcol[n] = PAL_HL[i % len(PAL_HL)]

    # ---- 视图范围 ----
    bb = b.GetBoardEdgesBoundingBox()
    full = (MM(bb.GetLeft()), MM(bb.GetTop()), MM(bb.GetRight()), MM(bb.GetBottom()))
    if a.bbox:
        x0, y0, x1, y1 = [float(v) for v in a.bbox.split(',')]
    else:
        x0, y0, x1, y1 = full
    w_mm, h_mm = x1 - x0, y1 - y0
    if a.scale:
        sc = a.scale
    else:
        sc = min(a.maxpx / max(w_mm, 0.001), 30.0)
    sc = max(sc, 1.0)

    W = int(w_mm * sc) + 60
    H = int(h_mm * sc) + 60
    OFFX, OFFY = 30, 30
    tx = lambda x: OFFX + (x - x0) * sc
    ty = lambda y: OFFY + (y - y0) * sc

    img = Image.new('RGB', (W, H), BG)
    d = ImageDraw.Draw(img)
    try:
        font = ImageFont.load_default(size=18)
        fsm = ImageFont.load_default(size=13)
    except Exception:
        font = fsm = ImageFont.load_default()

    # ---- 网格 ----
    if a.grid > 0:
        g = a.grid
        gx = math.ceil(x0 / g) * g
        while gx <= x1:
            d.line([(tx(gx), ty(y0)), (tx(gx), ty(y1))], fill=(226, 226, 224), width=1)
            gx += g
        gy = math.ceil(y0 / g) * g
        while gy <= y1:
            d.line([(tx(x0), ty(gy)), (tx(x1), ty(gy))], fill=(226, 226, 224), width=1)
            gy += g

    # ---- 铺铜 ----
    if not a.no_zone:
        for z in b.Zones():
            zl = z.GetLayer()
            if zl not in lids:
                continue
            zn = (z.GetNetname() or '')
            col = GND_TINT if zn.upper().startswith('GND') else ZONE_FILL.get(lname.get(zl, ''), (238, 238, 238))
            try:
                polys = z.FilledPolysList(zl)
            except Exception:
                polys = None
            got = poly_pts(polys)
            if not got:
                got = poly_pts(z.Outline())
            for pts in got:
                p2 = [(tx(p[0]), ty(p[1])) for p in pts]
                if len(p2) >= 3:
                    d.polygon(p2, fill=col)

    # ---- 走线 ----
    if not a.no_track:
        for t in b.GetTracks():
            if t.Type() == pcbnew.PCB_VIA_T:
                continue
            tl = t.GetLayer()
            if tl not in lids:
                continue
            nm = t.GetNetname() or ''
            wpx = max(1, int(round(MM(t.GetWidth()) * sc)))
            col = hlcol.get(nm) if nm in hlcol else PAL.get(lname.get(tl, ''), (120, 120, 120))
            if hl and nm not in hlcol:
                col = (198, 198, 194)
                wpx = max(1, min(wpx, 2))
            try:
                if t.Type() == pcbnew.PCB_ARC_T:
                    # PCB_ARC 无 GetPointAt, 用 中心+半径+起止角 采样(否则退化成弦, 看不出圆角)
                    c = t.GetCenter(); r = t.GetRadius()
                    a0 = t.GetArcAngleStart().AsDegrees()
                    a1 = t.GetArcAngleEnd().AsDegrees()
                    while a1 < a0: a1 += 360.0
                    n = 40
                    xy = []
                    for k in range(n + 1):
                        th = math.radians(a0 + (a1 - a0) * k / n)
                        px = MM(c.x) + MM(r) * math.cos(th)
                        py = MM(c.y) + MM(r) * math.sin(th)
                        xy.append((tx(px), ty(py)))
                    d.line(xy, fill=col, width=wpx, joint='curve')
                else:
                    s, e = t.GetStart(), t.GetEnd()
                    d.line([(tx(MM(s.x)), ty(MM(s.y))), (tx(MM(e.x)), ty(MM(e.y)))], fill=col, width=wpx)
            except Exception:
                try:
                    s, e = t.GetStart(), t.GetEnd()
                    d.line([(tx(MM(s.x)), ty(MM(s.y))), (tx(MM(e.x)), ty(MM(e.y)))], fill=col, width=wpx)
                except Exception:
                    pass

    # ---- 焊盘 ----
    if not a.no_pad:
        for fp in b.GetFootprints():
            fora = fp.GetOrientation()
            for p in fp.Pads():
                if not any(p.IsOnLayer(l) for l in lids):
                    continue
                px, py = MM(p.GetPosition().x), MM(p.GetPosition().y)
                sz = p.GetSize()
                wm, hm = MM(sz.x), MM(sz.y)
                try:
                    ang = fora.AsDegrees() + p.GetOrientation().AsDegrees()
                except Exception:
                    ang = fora.AsDegrees()
                nm = p.GetNetname() or ''
                sh = p.GetShape()
                if sh == pcbnew.PAD_SHAPE_CIRCLE:
                    r = wm / 2 * sc
                    d.ellipse([tx(px) - r, ty(py) - r, tx(px) + r, ty(py) + r], fill=(186, 190, 196), outline=(90, 94, 100))
                    continue
                hw, hh = wm / 2, hm / 2
                corners = [(px - hw, py - hh), (px + hw, py - hh), (px + hw, py + hh), (px - hw, py + hh)]
                c2 = [(tx(rot(c, (px, py), ang)[0]), ty(rot(c, (px, py), ang)[1])) for c in corners]
                fill = (186, 190, 196)
                if nm in hlcol:
                    fill = (150, 155, 162)
                d.polygon(c2, fill=fill, outline=(88, 92, 98))

    # ---- 过孔 ----
    if not a.no_via:
        for t in b.GetTracks():
            if t.Type() != pcbnew.PCB_VIA_T:
                continue
            if not any(t.IsOnLayer(l) for l in lids):
                continue
            p = t.GetPosition()
            px, py = tx(MM(p.x)), ty(MM(p.y))
            try:
                vw = t.GetWidth(lids[0])
            except Exception:
                try:
                    vw = t.GetWidth(pcbnew.F_Cu)
                except Exception:
                    vw = 700000
            r = MM(vw) / 2 * sc
            dr = MM(t.GetDrillValue()) / 2 * sc
            nm = t.GetNetname() or ''
            col = hlcol.get(nm, (150, 150, 150)) if nm in hlcol else (150, 150, 150)
            d.ellipse([px - r, py - r, px + r, py + r], fill=col, outline=(60, 60, 60))
            d.ellipse([px - dr, py - dr, px + dr, py + dr], fill=(250, 250, 248))

    # ---- 板框 ----
    for dr_ in b.GetDrawings():
        try:
            if dr_.GetLayer() != pcbnew.Edge_Cuts:
                continue
            sh = dr_.GetShape()
            if sh in (pcbnew.SHAPE_T_SEGMENT, pcbnew.SHAPE_T_ARC):
                s, e = dr_.GetStart(), dr_.GetEnd()
                d.line([(tx(MM(s.x)), ty(MM(s.y))), (tx(MM(e.x)), ty(MM(e.y)))], fill=(20, 20, 20), width=2)
            else:
                for pts in poly_pts(dr_.GetPolyShape()):
                    p2 = [(tx(p[0]), ty(p[1])) for p in pts]
                    if len(p2) >= 2:
                        d.line(p2 + [p2[0]], fill=(20, 20, 20), width=2)
        except Exception:
            pass

    # ---- 位号 ----
    if not a.no_ref:
        for fp in b.GetFootprints():
            try:
                p = fp.GetPosition()
                d.text((tx(MM(p.x)), ty(MM(p.y))), fp.GetReference(), fill=(70, 70, 70), font=fsm)
            except Exception:
                pass

    # ---- 标注 ----
    ly = 8
    d.text((8, ly), '%s | %s | %.0f px/mm | view %.1fx%.1fmm' %
           (os.path.basename(a.board), '+'.join(names), sc, w_mm, h_mm), fill=(30, 30, 30), font=font)
    ly += 22
    if hl:
        for n in hl:
            d.rectangle([8, ly + 2, 22, ly + 14], fill=hlcol[n])
            d.text((28, ly), n, fill=(30, 30, 30), font=fsm)
            ly += 18
    for m in a.mark:
        try:
            _x, _y, _t = m.split(',', 2)
            d.text((8, ly), _t, fill=(200, 30, 40), font=fsm)
            ly += 18
        except Exception:
            pass

    img.save(a.out)
    print('saved %s  %dx%d  layers=%s  bbox=%.2f,%.2f,%.2f,%.2f  scale=%.0f'
          % (a.out, W, H, '+'.join(names), x0, y0, x1, y1, sc))


if __name__ == '__main__':
    main()
