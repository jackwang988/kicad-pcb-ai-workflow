# -*- coding: utf-8 -*-
"""page_check.py — 多页原理图的【结构 + 布局】机检（SKILL 阶段 1 机检第 [6] 项）。

检查项:
  [A] 结构   : 根页引用的子页文件都存在；目录下没有孤儿页（未被根页引用）
  [B] 分页   : 每页器件数 ≤ --max-dev（默认 30）
  [C] 守恒   : 各页实例数之和 == 期望值（--expect，不给则只打印）
  [D] 孤立标签: global_label 既不落在引脚线段上、也不在 wire 端点上 →
                这类标签是"纯接口标记"。若某页某跨页网络的标签【全是】孤立的，
                说明该网络在本页【没有任何实际电气连接】—— 这正是拆页时
                "引脚丢失"的典型症状（实战：U1.21 从 LED_STAT 掉线），必须报出来。
  [E] 布局   : 纸张 / 内容 bbox / 利用率 / 器件间最小间距（重叠告警）

用法:
    python page_check.py <根页.kicad_sch> [--expect 73] [--max-dev 30]

退出码: 0 = 全部通过；1 = 有 FAIL
"""
import re, os, sys, math, glob, collections
sys.stdout.reconfigure(encoding='utf-8')

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
from sch_parse import load, endpoints, inst_bboxes   # noqa

FAIL = []

KICAD_CLI = (os.environ.get('KICAD_CLI')
             or 'kicad-cli')
import shutil
KICAD_CLI = shutil.which(KICAD_CLI) or KICAD_CLI


def check_load(root_d, pages):
    """[F] 逐页用 kicad-cli 做真实加载校验（抓"静默跳过"的页）。"""
    import subprocess, tempfile
    print("\n== [F] 逐页加载校验（抓静默跳过的页）==")
    if not os.path.exists(KICAD_CLI):
        raise SystemExit("Incomplete validation: kicad-cli missing; set KICAD_CLI or PATH")
    temp_run = tempfile.TemporaryDirectory(prefix='kicad-page-check-')
    tmp = os.path.join(temp_run.name, 'probe.xml')
    bad = []
    for fn in sorted(pages):
        p = os.path.join(root_d, fn)
        if not os.path.exists(p):
            continue
        if os.path.exists(tmp):
            os.remove(tmp)
        try:
            r = subprocess.run([KICAD_CLI, 'sch', 'export', 'netlist', '--format', 'kicadxml',
                                '-o', tmp, p], capture_output=True, timeout=120)
            ok = (r.returncode == 0) and os.path.exists(tmp)
        except Exception as e:
            ok = False
            print("   %s 校验异常: %s" % (fn, e))
        if not ok:
            bad.append(fn)
    if os.path.exists(tmp):
        os.remove(tmp)
    if bad:
        say('F', False, "%d 页加载失败（父页导出网表时会静默跳过 → 整页引脚丢失）: %s"
            % (len(bad), ', '.join(bad)))
        print("     常见原因: (paper \"A4 landscape\") 非法纸张名 / 子页有顶层 (instances ...) 块")
    else:
        say('F', True, "全部 %d 页均可被 KiCad 正常加载" % len(pages))


def say(tag, ok, msg):
    print("  [%s] %-4s %s" % (tag, "OK" if ok else "FAIL", msg))
    if not ok:
        FAIL.append(msg)


def span(t, s):
    d = 0; i = s
    while True:
        if t[i] == '(': d += 1
        elif t[i] == ')':
            d -= 1
            if d == 0: return i
        i += 1


def blocks(t, kind):
    out = []
    for m in re.finditer(r'\n\t\(%s\n' % kind, t):
        s = m.start() + 1; e = span(t, s)
        out.append(t[s:e + 1])
    return out


def lib_pin_len(t):
    """(lib_id, pin号) -> 引脚长度"""
    out = {}
    ls = t.find('\n\t(lib_symbols')
    if ls < 0: return out
    le = span(t, ls)
    for m in re.finditer(r'\n\t\t\(symbol "([^"]+)"', t[ls:le]):
        s0 = ls + m.start(); e0 = span(t, s0); lid = m.group(1)
        for pm in re.finditer(r'\n\t+\(pin ', t[s0:e0 + 1]):
            ps = s0 + pm.start(); pe = span(t, ps); pb = t[ps:pe + 1]
            nu = re.search(r'\(number "([^"]*)"', pb)
            ln = re.search(r'\(length ([-\d.]+)\)', pb)
            if nu and ln:
                out[(lid, nu.group(1))] = float(ln.group(1))
    return out


def on_seg(px, py, x0, y0, x1, y1, tol=0.05):
    vx, vy = x1 - x0, y1 - y0
    L2 = vx * vx + vy * vy
    if L2 < 1e-9: return False
    tt = ((px - x0) * vx + (py - y0) * vy) / L2
    if tt < -1e-6 or tt > 1 + 1e-6: return False
    return math.hypot(px - (x0 + tt * vx), py - (y0 + tt * vy)) <= tol


def main():
    A = sys.argv[1:]
    a = [x for x in A if not x.startswith('--')]
    opt = {}
    for i, x in enumerate(A):
        if x.startswith('--') and i + 1 < len(A) and not A[i + 1].startswith('--'):
            opt[x] = A[i + 1]
        elif x.startswith('--'):
            opt[x] = True
    if not a:
        raise SystemExit(__doc__)
    root_p = a[0]
    root_d = os.path.dirname(os.path.abspath(root_p))
    expect = int(opt['--expect']) if '--expect' in opt else None
    maxdev = int(opt.get('--max-dev', 30))

    rt = open(root_p, encoding='utf-8').read()

    # ---------- [A] 结构 ----------
    print("== [A] 多页结构 ==")
    subs = []          # (Sheetfile, Sheetname)
    for b in blocks(rt, 'sheet'):
        f = re.search(r'\(property "Sheetfile" "([^"]+)"', b)
        n = re.search(r'\(property "Sheetname" "([^"]+)"', b)
        if f: subs.append((f.group(1), n.group(1) if n else ''))
        else: say('A', False, "根页有 sheet 框但缺 Sheetfile 属性")
    if '(instances' not in '\n'.join(blocks(rt, 'sheet')):
        say('A', False, "sheet 框缺 (instances ...) —— 子页不会被网表遍历（只导出根页）")
    miss = [f for f, _ in subs if not os.path.exists(os.path.join(root_d, f))]
    say('A', not miss, "根页引用 %d 个子页，缺失 %s" % (len(subs), miss or '无'))
    have = {os.path.basename(p) for p in glob.glob(os.path.join(root_d, '*.kicad_sch'))}
    have.discard(os.path.basename(root_p))
    orphan = sorted(have - {f for f, _ in subs})
    say('A', not orphan, "孤儿页（存在但未被根页引用）: %s" % (orphan or '无'))

    # ---------- 逐页 ----------
    total_inst = 0
    cross = collections.defaultdict(set)      # 网名 -> {页}
    page_iso = {}                             # 页 -> {网名: 孤立标签数}
    print("\n== [B][C][E] 逐页 ==")
    print("  %-26s %5s %5s %5s  %-4s %-16s %5s" %
          ("页", "器件", "标签", "线", "纸张", "内容bbox(mm)", "利用率"))
    for fn, sname in subs:
        p = os.path.join(root_d, fn)
        if not os.path.exists(p): continue
        t, libs, insts = load(p)
        eps = endpoints(t, libs, insts)
        bb = inst_bboxes(t, libs, insts)
        total_inst += len(insts)
        labs = re.findall(r'\t\((?:global_|hierarchical_)?label "([^"]+)"\n\t\t(?:\(shape \w+\)\n\t\t)?'
                          r'\(at ([-\d.]+) ([-\d.]+)', t)
        wl = blocks(t, 'wire')
        wpts = []
        for b in wl:
            wpts += [(float(x), float(y)) for x, y in re.findall(r'\(xy ([-\d.]+) ([-\d.]+)\)', b)]

        xs, ys = [], []
        for r in bb:
            x0, y0, x1, y1 = bb[r]
            xs += [x0, x1]; ys += [y0, y1]
        for b in wl:
            for x, y in re.findall(r'\(xy ([-\d.]+) ([-\d.]+)\)', b):
                xs.append(float(x)); ys.append(float(y))
        for nm, x, y in labs:
            xs.append(float(x)); ys.append(float(y))
        if not xs:
            # 纯图形页（架构图等）：用 rectangle/polyline/text 的坐标算版面
            for kind in ('rectangle', 'polyline', 'text'):
                for b in blocks(t, kind):
                    for x, y in re.findall(r'\((?:at|xy|start|end) ([-\d.]+) ([-\d.]+)', b):
                        xs.append(float(x)); ys.append(float(y))
        bw = (max(xs) - min(xs)) if xs else 0
        bh = (max(ys) - min(ys)) if ys else 0
        pm = re.search(r'\(paper "([^"]+)"( portrait)?\)', t)
        pap = pm.group(1) if pm else '?'
        portrait = bool(pm and pm.group(2))
        # ⚠️ eeschema 的 (paper "A4") 是横放 297x210；竖版是 (paper "A4" portrait) 210x297
        PW = {'A4': ((210, 297) if portrait else (297, 210)),
              'A3': ((297, 420) if portrait else (420, 297)),
              'A2': ((420, 594) if portrait else (594, 420)),
              'A1': ((594, 841) if portrait else (841, 594)),
              'A0': ((841, 1189) if portrait else (1189, 841))}.get(pap, (210, 297))
        util = (bw * bh) / (PW[0] * PW[1]) * 100
        print("  %-26s %5d %5d %5d  %-4s %-16s %5.1f%%" %
              (fn, len(insts), len(labs), len(wl), pap,
               "%.0fx%.0f" % (bw, bh), util))
        say('B', len(insts) <= maxdev,
            "%s 器件 %d ≤ %d" % (fn, len(insts), maxdev))
        say('E', bw <= PW[0] and bh <= PW[1],
            "%s 内容 %.0fx%.0f 未超出纸张 %s %.0fx%.0f" % (fn, bw, bh, pap, PW[0], PW[1]))
        if len(insts) == 0:
            # 纯图形页（如系统架构图）：没有 symbol 实例，利用率不适用
            print("       （纯图形页，跳过利用率检查）")
        elif util < 12:
            # 低利用率【不是】缺陷：器件少的页（麦克风 5 个件）本来就填不满 A4。
            # 真正的缺陷是"散" —— 用【居中度】和【长宽比】判定，利用率只作提示。
            print("       （提示）利用率 %.1f%% 偏低：器件少属正常；若器件多则需重排" % util)
        if xs:
            # 居中度：内容 bbox 中心 vs 纸张中心
            cx, cy = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
            dx, dy = abs(cx - PW[0] / 2), abs(cy - PW[1] / 2)
            say('E', dx <= 15 and dy <= 15,
                "%s 居中: 内容中心 (%.0f,%.0f) vs 纸心 (%.0f,%.0f) 偏移 (%.0f,%.0f) ≤ 15mm"
                % (fn, cx, cy, PW[0] / 2, PW[1] / 2, dx, dy))
            # 长宽比：内容被拉成一条线说明没换行/没紧凑化
            ar = (bw / bh) if bh > 0 else 99
            say('E', 0.25 <= ar <= 4.0,
                "%s 版面长宽比 %.2f 在 [0.25, 4.0] 内（过大=拉成一条，需换行重排）" % (fn, ar))

        # 器件重叠
        refs = sorted(bb)
        ov = []
        for i in range(len(refs)):
            for j in range(i + 1, len(refs)):
                a0 = bb[refs[i]]; b0 = bb[refs[j]]
                if a0[0] < b0[2] and b0[0] < a0[2] and a0[1] < b0[3] and b0[1] < a0[3]:
                    ov.append((refs[i], refs[j]))
        say('E', not ov, "%s 器件本体重叠 %s" % (fn, ov or '无'))

        # [D] 孤立标签
        plen = lib_pin_len(t)
        segs = []
        for ins in insts:
            for q in eps.get(ins['ref'], []):
                L = plen.get((ins['lid'], q['num']), 2.54)
                segs.append((q['x'], q['y'],
                             round(q['x'] - L * q['dirx'], 3),
                             round(q['y'] - L * q['diry'], 3)))
        iso = collections.Counter()
        for nm, sx, sy in labs:
            x, y = float(sx), float(sy)
            hit = False
            for (x0, y0, x1, y1) in segs:
                if on_seg(x, y, x0, y0, x1, y1): hit = True; break
            if not hit:
                for (wx, wy) in wpts:
                    if math.hypot(wx - x, wy - y) <= 0.05: hit = True; break
            if not hit: iso[nm] += 1
            cross[nm].add(fn)
        page_iso[fn] = iso

    # ---------- [C] 守恒 ----------
    print("\n== [C] 实例守恒 ==")
    if expect is None:
        print("  各页实例合计: %d（未给 --expect，跳过判定）" % total_inst)
    else:
        say('C', total_inst == expect,
            "实例合计 %d == 期望 %d" % (total_inst, expect))

    # ---------- [D] 孤立标签 / 跨页网络未真正落地 ----------
    print("\n== [D] 孤立标签（既不碰引脚也不碰 wire 端点）==")
    bad = []
    for fn, iso in page_iso.items():
        if not iso: continue
        for nm, c in sorted(iso.items()):
            tot = sum(1 for _ in re.finditer(r'\t\((?:global_|hierarchical_)?label "%s"' % re.escape(nm),
                                              open(os.path.join(root_d, fn), encoding='utf-8').read()))
            only = (c == tot)
            msg = "  %-24s %-14s 孤立 %d / 共 %d%s" % (
                fn, nm, c, tot, "   ← 该页此网络【无任何实际连接】" if only else "")
            print(msg)
            if only and len(cross.get(nm, ())) > 1:
                bad.append("%s:%s" % (fn, nm))
    if bad:
        say('D', False, "跨页网络在以下页完全没有实际连接（引脚丢失的典型症状）: %s" % bad)
    else:
        say('D', True, "所有跨页网络在其出现的页上都有实际电气连接")

    # ---------- 跨页网络清单 ----------
    print("\n跨页网络 %d 条:" % sum(1 for n, p in cross.items() if len(p) > 1))
    for n in sorted(cross):
        if len(cross[n]) > 1:
            print("   %-14s %s" % (n, ', '.join(sorted(cross[n]))))

    # ---------- [F] 逐页加载校验 ----------
    # 父页导出网表时，加载失败的子页会被【静默跳过】：不报错、不警告，
    # 表现为该页器件引脚全部丢失。只有逐页单独跑一次 kicad-cli 才抓得到。
    # 典型触发：(paper "A4 landscape") 非法纸张名 / 子页里有顶层 (instances ...) 块。
    page_files = sorted({f for f, _ in subs} | set(have))
    check_load(root_d, page_files)

    print("\n" + ("=" * 60))
    if FAIL:
        print("机检未通过，共 %d 项:" % len(FAIL))
        for f in FAIL: print("   ✗ " + f)
        sys.exit(1)
    print("机检全部通过 ✓")
    sys.exit(0)


if __name__ == '__main__':
    main()
