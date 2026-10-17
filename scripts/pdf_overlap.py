#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
pdf_overlap.py — 基于 PDF 实测文字 bbox 的重叠检测（版面终审用）。

原理：
  kicad-cli 导出的 PDF 里，每个文字都有真实 bbox（PyMuPDF get_text('words')，
  左上原点，pt → mm 直接除 72/25.4，无需翻转）。实测即真值，避开字宽模型误差。

  假阳性来源与处理：
  1. KiCad 双重渲染：同文本同位置出现两份 → 按「同文本 + IoU>0.7」去重。
  2. 图框"家具"：边框格位字母/数字、标题栏文字 → 按区域排除。

用法：
  python pdf_overlap.py <file.pdf> [--min 0.30] [-v]
"""
import sys, re
import fitz

PT = 72 / 25.4
A4 = (210.0, 297.0)


def furniture(w, page):
    x0, y0, x1, y1 = w[0] / PT, w[1] / PT, w[2] / PT, w[3] / PT
    # 边框格位（页面最外 12mm 环）
    if x0 < 14 or x1 > A4[0] - 14 or y0 < 14 or y1 > A4[1] - 14:
        return True
    # 标题栏区（x>=88, y>=262）
    if x0 >= 88 and y0 >= 262:
        return True
    return False


def main():
    a = sys.argv[1:]
    path = a[0]
    vmin = 0.30
    verbose = '-v' in a
    ascii_only = '--ascii' in a
    if '--min' in a:
        vmin = float(a[a.index('--min') + 1])
    d = fitz.open(path)
    total = 0
    for pi, p in enumerate(d):
        raw = [w for w in p.get_text('words') if not furniture(w, p)]
        if ascii_only:
            raw = [w for w in raw if all(ord(c) < 127 for c in w[4])]
        # 去重：同文本 + IoU>0.7 保留一个
        items = []
        for w in raw:
            bx = (w[0] / PT, w[1] / PT, w[2] / PT, w[3] / PT)
            dup = False
            for it in items:
                if it[1] != w[4]:
                    continue
                ix0 = max(bx[0], it[0][0]); iy0 = max(bx[1], it[0][1])
                ix1 = min(bx[2], it[0][2]); iy1 = min(bx[3], it[0][3])
                ia = max(0.0, ix1 - ix0) * max(0.0, iy1 - iy0)
                aa = (bx[2] - bx[0]) * (bx[3] - bx[1])
                ab = (it[0][2] - it[0][0]) * (it[0][3] - it[0][1])
                if aa > 0 and ab > 0 and ia / min(aa, ab) > 0.7:
                    dup = True
                    break
            if not dup:
                items.append((bx, w[4]))
        ov = []
        for i in range(len(items)):
            for j in range(i + 1, len(items)):
                x0 = max(items[i][0][0], items[j][0][0])
                y0 = max(items[i][0][1], items[j][0][1])
                x1 = min(items[i][0][2], items[j][0][2])
                y1 = min(items[i][0][3], items[j][0][3])
                if x1 <= x0 or y1 <= y0:
                    continue
                # 两轴重叠都要 >0.5mm 才算真碰撞（字框含 ascent/descent padding，
                # 0.2~0.4mm 的边缘接触实际字形不会相碰）
                if (x1 - x0) <= 0.5 or (y1 - y0) <= 0.5:
                    continue
                s = (x1 - x0) * (y1 - y0)
                if s > vmin:
                    ov.append((s, items[i], items[j]))
        ov.sort(key=lambda z: -z[0])
        print('第%d页: 文字%d, 重叠%d对' % (pi, len(items), len(ov)))
        for s, x, y in ov[:40]:
            print('   [%.2fmm2] "%s" (%.1f,%.1f)-(%.1f,%.1f)  ×  "%s" (%.1f,%.1f)-(%.1f,%.1f)'
                  % (s, x[1][:24], x[0][0], x[0][1], x[0][2], x[0][3],
                     y[1][:24], y[0][0], y[0][1], y[0][2], y[0][3]))
        if verbose:
            for bx, txt in items:
                print('     %-26s (%.1f,%.1f)-(%.1f,%.1f)' % (txt[:26], bx[0], bx[1], bx[2], bx[3]))
        total += len(ov)
    print('\n全 PDF 重叠合计: %d 对' % total)
    return total


if __name__ == '__main__':
    sys.exit(0 if main() == 0 else 1)
