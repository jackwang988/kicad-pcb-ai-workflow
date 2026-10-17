# -*- coding: utf-8 -*-
"""走线严格审计：端点连接性 / 栅格 / 压引脚 / 绕远 / 贴器件"""
import re, sys, math, collections
sys.stdout.reconfigure(encoding='utf-8')
from sch_parse import load, endpoints, inst_bboxes

GRID = 1.27
SRC = sys.argv[1] if len(sys.argv) > 1 else None   # 用法: python audit_route.py <原理图.kicad_sch>

t, libs, insts = load(SRC)
eps = endpoints(t, libs, insts)
bodies = inst_bboxes(t, libs, insts)


def span(t, s):
    d = 0; i = s
    while True:
        if t[i] == '(': d += 1
        elif t[i] == ')':
            d -= 1
            if d == 0: return i
        i += 1


# ---- wire ----
wires = []
for m in re.finditer(r'\n\t\(wire\n', t):
    s = m.start(); e = span(t, s); blk = t[s:e]
    pm = re.search(r'\(pts\n((?:\t\t\t\(xy [^\n]*\)\n?)+)', blk)
    if not pm: continue
    pts = [(float(a), float(b)) for a, b in re.findall(r'\(xy ([-\d.]+) ([-\d.]+)\)', pm.group(1))]
    wires.append((m.start(), pts))

segs = []
for wi, (pos, pts) in enumerate(wires):
    for k in range(len(pts) - 1):
        segs.append((pts[k][0], pts[k][1], pts[k + 1][0], pts[k + 1][1], wi))

# ---- 引脚端点表 ----
pins = []
for ref, lst in eps.items():
    for p in lst:
        pins.append((round(p['x'], 3), round(p['y'], 3), ref, p['num']))
# 引脚线段（从本体到端点，长度用 dir 反推 2.54 或库长度）——这里只查"走线是否压在引脚端点附近"
pinpt = {(round(p[0], 2), round(p[1], 2)): (p[2], p[3]) for p in pins}

# ---- label ----
labs = []
for m in re.finditer(r'\t\(label "([^"]+)"\n\t\t\(at ([-\d.]+) ([-\d.]+) ([-\d.]+)\)', t):
    labs.append((m.group(1), float(m.group(2)), float(m.group(3)), m.start()))

print("=" * 74)
print("走线严格审计  源:", SRC)
print("=" * 74)
print("wire 数 %d / 段数 %d / label %d / 实例 %d" % (len(wires), len(segs), len(labs), len(insts)))


def on_grid(v):
    return abs(v / GRID - round(v / GRID)) < 0.02


# [A] 端点连接性：wire 端点必须落在引脚端点 / 另一 wire 端点 / 另一 wire 线段内部
def pt_on_seg(px, py, s, tol=0.02):
    x0, y0, x1, y1, wi = s
    if abs(x0 - x1) < 1e-6:
        if abs(px - x0) < tol and min(y0, y1) - tol <= py <= max(y0, y1) + tol: return True
    if abs(y0 - y1) < 1e-6:
        if abs(py - y0) < tol and min(x0, x1) - tol <= px <= max(x0, x1) + tol: return True
    return False


allends = set()
for s in segs:
    allends.add((round(s[0], 2), round(s[1], 2)))
    allends.add((round(s[2], 2), round(s[3], 2)))

bad = []
for wi, (pos, pts) in enumerate(wires):
    for P in (pts[0], pts[-1]):
        k = (round(P[0], 2), round(P[1], 2))
        if k in pinpt: continue
        # 落在别的 wire 段上（T 接）
        if any(pt_on_seg(P[0], P[1], s) for s in segs if s[4] != wi): continue
        bad.append((wi, P))
print()
print("[A] 悬空 wire 端点（既不在引脚端点、也不搭在别的线上）: %d" % len(bad))
for wi, P in bad:
    print("    W%-3d 端点 (%.3f,%.3f)   整条: %s" %
          (wi, P[0], P[1], ' -> '.join('(%.2f,%.2f)' % q for q in wires[wi][1])))

# [B] 拐点栅格
print()
print("[B] 非栅格拐点（端点除外，端点可能继承 off-grid 引脚）: %d" % 0)
off = []
for wi, (pos, pts) in enumerate(wires):
    for q in pts[1:-1]:
        if not (on_grid(q[0]) and on_grid(q[1])):
            off.append((wi, q))
print("    实际: %d" % len(off))
for wi, q in off:
    print("    W%-3d 拐点 (%.3f,%.3f)  /1.27 = %.3f , %.3f" % (wi, q[0], q[1], q[0] / GRID, q[1] / GRID))

print()
print("[B2] 非栅格端点（继承自 off-grid 引脚，属基线固有）: %d" %
      len([1 for wi, (p, pts) in enumerate(wires)
           for q in (pts[0], pts[-1]) if not (on_grid(q[0]) and on_grid(q[1]))]))

# [C] 走线压在别的器件引脚端点上（不是本体，是引脚尖）
print()
hit = []
for s in segs:
    for k, (ref, num) in pinpt.items():
        if abs(k[0] - s[0]) < 0.01 and abs(k[1] - s[1]) < 0.01: continue
        if abs(k[0] - s[2]) < 0.01 and abs(k[1] - s[3]) < 0.01: continue
        if pt_on_seg(k[0], k[1], s, tol=0.01):
            hit.append((s, ref, num))
print("[C] 走线穿过其它器件引脚端点（会误连/视觉脏）: %d" % len(hit))
for s, ref, num in hit[:30]:
    print("    W%-3d (%.2f,%.2f)-(%.2f,%.2f)  压 %s.%s" % (s[4], s[0], s[1], s[2], s[3], ref, num))

# [D] 绕远比
print()
print("[D] 绕远比 (= 实际长度 / 曼哈顿距离)，>1.6 视为视觉绕")
rows = []
for wi, (pos, pts) in enumerate(wires):
    L = sum(math.hypot(pts[i + 1][0] - pts[i][0], pts[i + 1][1] - pts[i][1]) for i in range(len(pts) - 1))
    manh = abs(pts[-1][0] - pts[0][0]) + abs(pts[-1][1] - pts[0][1])
    rows.append((L / manh if manh else 9.9, wi, len(pts), L, manh, pts))
rows.sort(reverse=True)
for r in rows[:18]:
    flag = "  <== 绕" if r[0] > 1.6 else ""
    print("    %.2f  W%-3d %d点 L=%.1f manh=%.1f  %s%s" %
          (r[0], r[1], r[2], r[3], r[4], ' -> '.join('(%.1f,%.1f)' % q for q in r[5]), flag))

# [E] 贴器件（走线距器件本体 bbox < 0.8mm）
print()
near = []
for s in segs:
    a0, a1 = min(s[0], s[2]), max(s[0], s[2])
    b0, b1 = min(s[1], s[3]), max(s[1], s[3])
    for ref, (x0, y0, x1, y1) in bodies.items():
        dx = max(x0 - a1, a0 - x1, 0.0)
        dy = max(y0 - b1, b0 - y1, 0.0)
        d = math.hypot(dx, dy)
        if d < 0.8:
            near.append((s, ref, d))
print("[E] 走线贴器件本体 < 0.8mm: %d" % len(near))
for s, ref, d in near[:25]:
    print("    W%-3d (%.2f,%.2f)-(%.2f,%.2f)  距 %s %.2fmm" % (s[4], s[0], s[1], s[2], s[3], ref, d))

# [F] 走线总览
print()
print("[F] 全部走线一览（按 wire 序号）")
for wi, (pos, pts) in enumerate(wires):
    L = sum(math.hypot(pts[i + 1][0] - pts[i][0], pts[i + 1][1] - pts[i][1]) for i in range(len(pts) - 1))
    manh = abs(pts[-1][0] - pts[0][0]) + abs(pts[-1][1] - pts[0][1])
    a = pinpt.get((round(pts[0][0], 2), round(pts[0][1], 2)), ('?', '?'))
    b = pinpt.get((round(pts[-1][0], 2), round(pts[-1][1], 2)), ('?', '?'))
    print("  W%-3d %-6s.%-3s -> %-6s.%-3s  L=%5.1f detour=%.2f  %s" %
          (wi, a[0], a[1], b[0], b[1], L, L / manh if manh else 9.9,
           ' -> '.join('(%.2f,%.2f)' % q for q in pts)))
