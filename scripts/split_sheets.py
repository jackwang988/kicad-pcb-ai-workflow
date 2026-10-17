# -*- coding: utf-8 -*-
"""split_sheets.py — 把单页原理图按模块拆成多页层次化工程（根页 + N 个子页）。

电气保证：跨页网络用 hierarchical_label（箭头形，【无矩形框】）+ 根页 sheet pin
同名配对；页内网络为纯文字 local label（KiCad 渲染无任何图形框）。
注意：hierarchical 方案下网名会带页路径前缀（/页名/网名），电气拓扑不变，
用 diff_net.py --topo 验证。--force-global 可回退旧行为（全部 global_label，带框）。

用法:
    python split_sheets.py <单页.kicad_sch> <输出目录> --map map.json [--project NAME]
                           [--attach 附加页.kicad_sch] [--title "工程名"]

map.json 格式:  {"01_Power": ["U5","U4","J5", ...], "02_MCU": [...], ...}
                键 = 子页文件名（不含扩展名），值 = 该页器件位号列表
                不在 map 里的器件 → 报错（防止漏拆）

产物:
    <输出目录>/00_Top.kicad_sch        根页（sheet 框 + 接口文本 + sheet pin，无器件）
    <输出目录>/01_Power.kicad_sch      ...
    <输出目录>/__split_report.txt      跨页网络清单 / 每页器件数 / 补标签记录
"""
import re, os, sys, json, math, uuid, shutil, collections
sys.stdout.reconfigure(encoding='utf-8')

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
from sch_parse import load, endpoints, inst_bboxes   # noqa

MARGIN = 25.4          # 页边距(mm)
FRAME_PAD = 5.0        # 模块框内缩
TITLE_H = 10.0         # 顶部标题留高
GRID = 1.27            # KiCad 默认栅格(50mil)；平移量必须取整到栅格，
                       # 否则整页元素全部 off-grid，KiCad 对"标签落在引脚线段上"
                       # 这类隐式连接会判定失败（实战丢过 U1.21）
# 纸张尺寸（宽x高，mm）。⚠️ KiCad eeschema 的 (paper "A4") 是【横放 297x210】！
# 想要竖版必须写 (paper "A4" portrait)（实测 KiCad 9 支持，"landscape" 这个词反而非法）。
# 本工具默认全部竖版排版（宽度 < 高度），所以这里登记的都是竖放尺寸。
PAPERS = [(210, 297, 'A4'), (297, 420, 'A3'), (420, 594, 'A2'), (594, 841, 'A1')]
PAPER_SIZE = {n: (w, h) for w, h, n in PAPERS}
# 紧凑化：把器件之间的大空隙压到这个宽度。太小会挤在一起，太大就压不进 A4
GAP_X = 12.7        # 列间目标间隙(mm)
GAP_Y = 10.16       # 行间目标间隙(mm)


# ---------- 基础工具 ----------
def span(t, s):
    d = 0; i = s
    while True:
        if t[i] == '(': d += 1
        elif t[i] == ')':
            d -= 1
            if d == 0: return i
        i += 1


def top_blocks(t):
    """顶层块 [(kind, start, end)]，start 指向 '('，end 指向匹配的 ')'"""
    out = []
    for m in re.finditer(r'\n\t\(([a-z_]+)', t):
        s = m.start() + 1
        try:
            e = span(t, s)
        except Exception:
            continue
        out.append((m.group(1), s, e))
    return out


def shift(blk, dx, dy):
    """把块内所有 (at/xy/start/end/center x y ...) 平移"""
    def rep(m):
        return "(%s %s %s%s)" % (m.group(1),
                                 round(float(m.group(2)) + dx, 4),
                                 round(float(m.group(3)) + dy, 4),
                                 m.group(4))
    return re.sub(r'\((at|xy|start|end|center) ([-\d.]+) ([-\d.]+)([^)]*)\)', rep, blk)


def blk_at(blk):
    """块的第一个 (at x y ...) → (x, y)"""
    m = re.search(r'\n?\s*\(at ([-\d.]+) ([-\d.]+)', blk)
    return (float(m.group(1)), float(m.group(2))) if m else None


def blk_pts(blk):
    """块内所有 (xy x y)"""
    return [(float(a), float(b)) for a, b in re.findall(r'\(xy ([-\d.]+) ([-\d.]+)\)', blk)]


def blk_center(blk):
    a = blk_at(blk)
    if a: return a
    p = blk_pts(blk)
    if p:
        return (sum(x for x, _ in p) / len(p), sum(y for _, y in p) / len(p))
    nums = [float(x) for x in re.findall(r'\((?:at|start) ([-\d.]+) ([-\d.]+)', blk)]
    return (0.0, 0.0)


def rnd_grid(v):
    """位移量取整到栅格：原本在栅格上的点仍在栅格上（否则 KiCad 判定"标签落在
    引脚线段上"的隐式连接会失败，实战丢过 U1.21）"""
    return round(v / GRID) * GRID


def axis_map(intervals, min_gap):
    """单轴紧凑化：把投影区间之间 > min_gap 的空隙压到 min_gap。

    返回 f(x) -> 位移量。要点：
      · 同一区间内的点位移【相同】—— 器件本体形状不变
      · 空隙内的点线性插值 —— 映射单调非减，线段不会被压成反向/斜线
    这是纯平移变换，不改任何拓扑，所以电气连接绝对安全。
    """
    iv = []
    for a, b in sorted((float(a), float(b)) for a, b in intervals):
        if iv and a <= iv[-1][1] + 1e-6:
            iv[-1][1] = max(iv[-1][1], b)
        else:
            iv.append([a, b])
    sh = [0.0] * len(iv)
    acc = 0.0
    for i in range(1, len(iv)):
        gap = iv[i][0] - iv[i - 1][1]
        if gap > min_gap:
            acc -= (gap - min_gap)
        sh[i] = acc

    def f(x):
        if not iv:
            return 0.0
        if x <= iv[0][0]:
            return sh[0]
        for i, (a, b) in enumerate(iv):
            if x <= b:
                if x >= a:
                    return sh[i]
                pa = iv[i - 1][1]
                t = 0.0 if a - pa < 1e-9 else (x - pa) / (a - pa)
                return sh[i - 1] + t * (sh[i] - sh[i - 1])
        return sh[-1]
    return f


def shift_by(blk, fn):
    """按 fn(x, y) -> (dx, dy) 逐点平移（用于 wire / label，两端可能不同位移）"""
    def rep(m):
        k, x, y, rest = m.group(1), float(m.group(2)), float(m.group(3)), m.group(4)
        dx, dy = fn(x, y)
        return "(%s %s %s%s)" % (k, round(x + dx, 4), round(y + dy, 4), rest)
    return re.sub(r'\((at|xy|start|end|center) ([-\d.]+) ([-\d.]+)([^)]*)\)', rep, blk)


class DSU:
    def __init__(self): self.p = {}

    def f(self, x):
        self.p.setdefault(x, x)
        while self.p[x] != x:
            self.p[x] = self.p[self.p[x]]; x = self.p[x]
        return x

    def u(self, a, b):
        ra, rb = self.f(a), self.f(b)
        if ra != rb: self.p[ra] = rb


def new_uuid():
    return str(uuid.uuid4())


# ---------- 文本宽度估算 / 自动换行（根页接口清单用） ----------
def _cw(ch):
    """单字符宽度系数（相对字号），按 KiCad 9 实测标定：CJK 最宽、大写/数字次之"""
    o = ord(ch)
    if o > 0x2E80:
        return 1.13      # CJK 及全角标点
    if ch == ' ':
        return 0.40
    if ch.isupper() or ch.isdigit():
        return 0.94
    if ch.islower():
        return 0.68
    return 0.55


def text_w(s, size):
    return sum(_cw(c) for c in s) * size


def wrap_lines(s, size, maxw, max_lines=2):
    """按估算宽度贪心折行；超过 max_lines 的尾部用 …(共N条) 收尾"""
    units = maxw / float(size)
    lines, cur, acc = [], '', 0.0
    for ch in s:
        w = _cw(ch)
        if acc + w > units and cur:
            lines.append(cur)
            cur, acc = '', 0.0
            if len(lines) == max_lines:
                break
        cur += ch
        acc += w
    if cur and len(lines) < max_lines:
        lines.append(cur)
    return lines


def _txt(x, y, s, size=1.0):
    return ('\t(text "%s"\n\t\t(at %s %s 0)\n'
            '\t\t(effects\n\t\t\t(font\n\t\t\t\t(size %s %s)\n\t\t\t\t(face "SimSun"))\n'
            '\t\t\t(justify left top)\n\t\t)\n\t\t(uuid "%s")\n\t)'
            % (s, round(x, 2), round(y, 2), size, size, new_uuid()))


# ---------- 主流程 ----------
def run(src, outdir, mapping, project='Project', attach=None, title='', force_global=False,
        paper_name='A4', gap_x=GAP_X, gap_y=GAP_Y, attach_first=True):
    from _runtime import new_output_directory
    new_output_directory(src, outdir)
    global GAP_X, GAP_Y
    GAP_X, GAP_Y = gap_x, gap_y
    t, libs, insts = load(src)
    os.makedirs(outdir, exist_ok=True)

    # --- 0. 分组校验 ---
    ref2inst = {i['ref']: i for i in insts}
    ref2page = {}
    for pg, refs in mapping.items():
        for r in refs:
            if r not in ref2inst:
                print("[警告] 位号 %s 不在原理图里（map 写错？）" % r)
                continue
            ref2page[r] = pg
    missing = [i['ref'] for i in insts if i['ref'] not in ref2page]
    if missing:
        raise SystemExit("以下器件未在 map 中分配页面，拒绝拆页（会丢器件）: %s" % missing)
    pages = list(mapping.keys())
    print("页面划分:", {p: len(mapping[p]) for p in pages})

    # --- 1. 收集顶层块 ---
    blocks = top_blocks(t)
    kind = collections.Counter(k for k, _, _ in blocks)
    print("顶层块:", dict(kind))

    sym_blks = [(s, e, t[s:e + 1]) for k, s, e in blocks if k == 'symbol' and '(lib_id' in t[s:e + 1]]
    wire_blks = [(s, e, t[s:e + 1]) for k, s, e in blocks if k == 'wire']
    lab_blks = [(s, e, t[s:e + 1]) for k, s, e in blocks if k == 'label']
    glob_blks = [(s, e, t[s:e + 1]) for k, s, e in blocks if k == 'global_label']
    nc_blks = [(s, e, t[s:e + 1]) for k, s, e in blocks if k == 'no_connect']
    sheet_blks = [(s, e, t[s:e + 1]) for k, s, e in blocks if k == 'sheet']
    # rectangle / text（旧的模块框与标题）— 拆页后重新生成，不搬运
    print("实例 %d / wire %d / label %d / global_label %d / no_connect %d" %
          (len(sym_blks), len(wire_blks), len(lab_blks), len(glob_blks), len(nc_blks)))

    # --- 2. 引脚端点索引 ---
    eps = endpoints(t, libs, insts)
    pin_at = {}
    for ref, lst in eps.items():
        for p in lst:
            pin_at[(round(p['x'], 2), round(p['y'], 2))] = (ref, p['num'])
    pin_list = list(pin_at.keys())

    def nearest_pin(x, y, tol=1.6):
        k = (round(x, 2), round(y, 2))
        if k in pin_at: return pin_at[k]
        best, bd = None, 1e9
        for px, py in pin_list:
            d = math.hypot(px - x, py - y)
            if d < bd: bd, best = d, (px, py)
        return pin_at[best] if best and bd <= tol else None

    # --- 2b. 引脚线段（端点 -> 本体端）——用于"标签落在引脚线段上"的隐式连接 ---
    def _lspan(s, i):
        d = 0
        while True:
            if s[i] == '(': d += 1
            elif s[i] == ')':
                d -= 1
                if d == 0: return i
            i += 1

    libid_len = {}                      # (lib_id, pin号) -> 引脚长度
    _ls = t.find('\n\t(lib_symbols'); _le = span(t, _ls)
    for m in re.finditer(r'\n\t\t\(symbol "([^"]+)"', t[_ls:_le]):
        s0 = _ls + m.start(); e0 = span(t, s0); lid = m.group(1)
        for pm in re.finditer(r'\n\t+\(pin ', t[s0:e0 + 1]):
            ps = s0 + pm.start(); pe = span(t, ps); pb = t[ps:pe + 1]
            nu = re.search(r'\(number "([^"]*)"', pb)
            ln = re.search(r'\(length ([-\d.]+)\)', pb)
            if nu and ln:
                libid_len[(lid, nu.group(1))] = float(ln.group(1))
    pin_seg = []        # (ref, num, 端点x, 端点y, 本体端x, 本体端y)
    for ins in insts:
        for q in eps.get(ins['ref'], []):
            L = libid_len.get((ins['lid'], q['num']), 2.54)
            pin_seg.append((ins['ref'], q['num'], q['x'], q['y'],
                            round(q['x'] - L * q['dirx'], 3),
                            round(q['y'] - L * q['diry'], 3)))

    # --- 3. 网络簇（并查集：wire 端点 + 坐标重合 + 同名 label）---
    def labs_of(blks):
        out = []
        for s, e, b in blks:
            nm = re.search(r'\(label "([^"]+)"', b)
            a = re.search(r'\(at ([-\d.]+) ([-\d.]+) ([-\d.]+)\)', b)
            if nm and a:
                out.append(dict(name=nm.group(1), x=float(a.group(1)), y=float(a.group(2)),
                                ang=float(a.group(3)), blk=b))
        return out

    labels = labs_of(lab_blks) + labs_of(glob_blks)
    dsu = DSU()
    for s, e, b in wire_blks:
        p = blk_pts(b)
        if len(p) >= 2:
            for q in p: dsu.f(q)
            dsu.u(p[0], p[-1])
    for L in labels:
        dsu.f((L['x'], L['y']))
    byname = collections.defaultdict(list)
    for L in labels: byname[L['name']].append((L['x'], L['y']))
    for nm, pts in byname.items():
        for q in pts[1:]: dsu.u(pts[0], q)

    clusters = collections.defaultdict(lambda: dict(pts=[], names=set(), refs=set()))
    allpts = []
    for s, e, b in wire_blks: allpts += blk_pts(b)
    for L in labels: allpts.append((L['x'], L['y']))
    for q in allpts:
        clusters[dsu.f(q)]['pts'].append(q)
    for L in labels:
        clusters[dsu.f((L['x'], L['y']))]['names'].add(L['name'])
    for c in clusters.values():
        for q in c['pts']:
            hit = pin_at.get((round(q[0], 2), round(q[1], 2))) or nearest_pin(*q)
            if hit: c['refs'].add(hit[0])

    # 簇 → 网名
    cl2net = {}
    for key, c in clusters.items():
        cl2net[key] = sorted(c['names'])[0] if c['names'] else None
    net_pages = collections.defaultdict(set)
    for key, c in clusters.items():
        n = cl2net[key]
        if n is None: continue
        for r in c['refs']:
            if r in ref2page: net_pages[n].add(ref2page[r])
    cross_nets = {n for n, ps in net_pages.items() if len(ps) > 1}
    print("网络总数 %d，跨页网络 %d" % (len(net_pages), len(cross_nets)))

    # --- 4/5. 归属：每个块分到哪一页 + 跨页 wire 拆分 ---
    page_refs = {p: set(mapping[p]) for p in pages}
    bb = inst_bboxes(t, libs, insts)

    def page_of_xy(x, y):
        """按坐标判定所属页：优先落在某页器件包围盒内，否则取最近器件"""
        best, bd = None, 1e9
        for p, refs in page_refs.items():
            for r in refs:
                x0, y0, x1, y1 = bb.get(r, (0, 0, 0, 0))
                if x0 - 3 <= x <= x1 + 3 and y0 - 3 <= y <= y1 + 3:
                    return p
                cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
                d = math.hypot(cx - x, cy - y)
                if d < bd: bd, best = d, p
        return best or pages[0]

    def pt_page(q):
        """点 → 页。三级判定：精确引脚 > 同簇最近引脚 > 最近器件
        ⚠️ 不能用 wire 中心点归页：一条从 MCU 引脚连到远处 GND 标签的线，
        中心可能落在别的模块区，归错页会让该引脚失去连接（实战丢过 16 个 GND 脚）"""
        k = (round(q[0], 2), round(q[1], 2))
        if k in pin_at:
            return ref2page.get(pin_at[k][0]) or page_of_xy(*q)
        c = clusters.get(dsu.f(q))
        if c:
            best, bd = None, 1e9
            for pp in c['pts']:
                kk = (round(pp[0], 2), round(pp[1], 2))
                if kk not in pin_at: continue
                d = math.hypot(pp[0] - q[0], pp[1] - q[1])
                if d < bd: bd, best = d, pin_at[kk][0]
            if best and bd <= 15.0:
                return ref2page.get(best) or page_of_xy(*q)
            # 三级：簇内器件若【全在同一页】，用那一页。
            # 悬空端点/标签离所有器件都远（>15mm），"最近器件中心"会判错页：
            # 实战把 BAT+ 的一条引出线判给了 MCU 页，导致 U4.3 整条链在电源页
            # 变成悬空、丢掉 BAT+ 连接。簇级归属对这种情况才是可靠的。
            pgs = set(ref2page.get(r) for r in c['refs'])
            pgs.discard(None)
            if len(pgs) == 1:
                return pgs.pop()
        return page_of_xy(*q)

    kill_wire = set()      # 要删除的 wire 块起始位置
    add_lab = []           # 跨页 wire 切断后需补的标签
    assign = collections.defaultdict(list)   # page -> [块文本]

    for s, e, b in sym_blks:
        ref = re.search(r'\(property "Reference" "([^"]+)"', b)
        assign[ref2page[ref.group(1)]].append(b)

    for s, e, b in wire_blks:
        p = blk_pts(b)
        if len(p) < 2:
            print("[警告] wire 点数<2，跳过: %s" % p); continue
        g1, g2 = pt_page(p[0]), pt_page(p[-1])
        if os.environ.get('SPLIT_DEBUG'):
            print("  wire %s -> %s : %s | %s" % (p[0], p[-1], g1, g2))
        if g1 and g2 and g1 != g2:
            kill_wire.add(s)
            net = cl2net.get(dsu.f(p[0]))
            if net is None:
                print("[警告] 跨页 wire 找不到网名，保留原样: %s" % p)
                kill_wire.discard(s); assign[g1].append(b); continue
            for q in (p[0], p[-1]):
                add_lab.append(dict(x=q[0], y=q[1], net=net))
        else:
            assign[g1 or g2].append(b)
    print("跨页 wire %d 条（拆成两端 hierarchical_label），补标签 %d 个" % (len(kill_wire), len(add_lab)))

    for s, e, b in lab_blks + glob_blks:
        m = re.search(r'\(at ([-\d.]+) ([-\d.]+)', b)
        assign[pt_page((float(m.group(1)), float(m.group(2))))].append(b)
    for s, e, b in nc_blks:
        m = re.search(r'\(at ([-\d.]+) ([-\d.]+)', b)
        assign[pt_page((float(m.group(1)), float(m.group(2))))].append(b)
    for L in add_lab:
        # 跨页 wire 切断端 → hierarchical_label（箭头形，无矩形框）；
        # 由根页 sheet pin 同名配对完成跨页连通
        assign[pt_page((L['x'], L['y']))].append(
            # 注意行首必须带 \t：KiCad 不在乎缩进，但按 '\n\t(' 扫描顶层块的
            # 脚本会静默漏掉列 0 的块（实测 relayout 漏平移 3 个 GND 标签 → 断链）
            '\t(hierarchical_label "%s"\n\t\t(shape passive)\n\t\t(at %s %s 0)\n'
            '\t\t(effects\n\t\t\t(font\n\t\t\t\t(size 1.27 1.27)\n\t\t\t)\n\t\t\t(justify left bottom)\n\t\t)\n'
            '\t\t(uuid "%s")\n\t)' % (L['net'], round(L['x'], 4), round(L['y'], 4), new_uuid()))

    # --- 5b. 引脚线段吸附补线 ---
    # 源图里大量连接靠"标签贴在引脚线段上"（标签不在引脚端点，而在引脚本体端，
    # KiCad 按线段 HitTest 判定为连通）。这种隐式连接很脆弱：拆页若坐标偏离栅格
    # 就会判定失败（实战丢过 U1.21 → LED_STAT）。这里显式补一条短 wire，
    # 电气完全等价，且工程师看图更清楚。
    def on_seg(px, py, x0, y0, x1, y1, tol=0.05):
        vx, vy = x1 - x0, y1 - y0
        L2 = vx * vx + vy * vy
        if L2 < 1e-9:
            return False
        tt = ((px - x0) * vx + (py - y0) * vy) / L2
        if tt < -1e-6 or tt > 1 + 1e-6:
            return False
        return math.hypot(px - (x0 + tt * vx), py - (y0 + tt * vy)) <= tol

    n_stub = 0
    for p in pages:
        extra = []
        for b in assign.get(p, []):
            if not re.match(r'\t\((?:global_|hierarchical_)?label "', b):
                continue
            a = re.search(r'\(at ([-\d.]+) ([-\d.]+)', b)
            if not a:
                continue
            lx, ly = float(a.group(1)), float(a.group(2))
            for (ref, num, x0, y0, x1, y1) in pin_seg:
                if ref2page.get(ref) != p:
                    continue
                if on_seg(lx, ly, x0, y0, x1, y1):
                    if math.hypot(lx - x0, ly - y0) < 0.01:
                        break          # 标签已在引脚端点，无需补
                    extra.append(
                        '\t(wire\n\t\t(pts\n\t\t\t(xy %s %s) (xy %s %s)\n\t\t)\n'
                        '\t\t(stroke\n\t\t\t(width 0)\n\t\t\t(type default)\n\t\t)\n'
                        '\t\t(uuid "%s")\n\t)'
                        % (round(x0, 3), round(y0, 3), round(lx, 3), round(ly, 3), new_uuid()))
                    n_stub += 1
                    break
        assign[p] += extra
    print("引脚线段吸附补线 %d 条（标签贴引脚 → 显式 wire）" % n_stub)

    # 完整性自检：分配的块数必须 = 源块数（否则有块被静默丢弃）
    n_in = len(sym_blks) + len(wire_blks) + len(lab_blks) + len(glob_blks) + len(nc_blks)
    n_out = sum(len(v) for v in assign.values())
    print("块守恒: 源 %d（含被拆 wire %d）→ 已分配 %d（含补标签 %d / 补线 %d）  %s"
          % (n_in, len(kill_wire), n_out, len(add_lab), n_stub,
             "OK" if n_out == n_in - len(kill_wire) + len(add_lab) + n_stub else "!! 有块丢失"))
    print("各页块数:", {p: len(assign.get(p, [])) for p in pages})

    # --- 6. 生成子页 ---
    # 每页搬运：新坐标 = 原坐标 - bbox.min + (MARGIN, MARGIN+TITLE_H)
    used_libs = collections.defaultdict(set)
    for i in insts:
        used_libs[ref2page[i['ref']]].add(i['lid'])

    ls = t.find('\n\t(lib_symbols')
    le = span(t, ls)
    lib_bodies = {}
    for m in re.finditer(r'\n\t\t\(symbol "([^"]+)"', t[ls:le]):
        s0 = ls + m.start(); e0 = span(t, s0)
        lib_bodies[m.group(1)] = t[s0:e0 + 1]

    report = []
    report.append("拆页报告  源: %s" % os.path.basename(src))
    report.append("=" * 60)
    sheets = []      # (filename, sheetname, uuid)

    def _to_global(nb):
        # 标签形态（历史版本 用户要求：网络标签一律不要矩形框，纯文字）：
        #   · 跨页网络 → hierarchical_label（箭头形，无框），根页 sheet pin 同名配对
        #   · 页内网络 → 保持纯文字 local label（KiCad 渲染无任何图形框）
        #   · --force-global 回退旧行为（全部转 global_label，带矩形框）
        nm = re.search(r'^\t\(label "([^"]+)"', nb)
        if not nm:
            return nb
        if force_global:
            return nb.replace('\t(label "%s"' % nm.group(1),
                              '\t(global_label "%s"\n\t\t(shape passive)' % nm.group(1), 1)
        if nm.group(1) in cross_nets:
            return nb.replace('\t(label "%s"' % nm.group(1),
                              '\t(hierarchical_label "%s"\n\t\t(shape passive)' % nm.group(1), 1)
        return nb

    for p in pages:
        # ===== 6a. 页内紧凑化 =====
        # 只做"整体平移"会保留器件在原单页里的散布：跨整个原理图的模块
        # （如 Audio_Out）会拉出 280mm 宽的版面，只能上 A3，评审时一片空白。
        # 这里按器件本体在 x/y 轴的投影，把 > GAP 的空隙压到 GAP。
        refs = sorted(page_refs[p])
        rset = set(refs)

        # 点 → 本页归属器件：精确引脚 > 同簇最近引脚(≤15mm)。
        # 这是"贴身 label 必须跟着器件走"的关键 —— 否则压缩会改变 label 与引脚的
        # 相对偏移，KiCad 的"标签落在引脚线段上"隐式连接就断了（实战丢 11 个脚）。
        def owner(x, y, _rs=rset):
            k = (round(x, 2), round(y, 2))
            if k in pin_at and pin_at[k][0] in _rs:
                return pin_at[k][0]
            c = clusters.get(dsu.f((x, y)))
            if c:
                best, bd = None, 1e9
                for pp in c['pts']:
                    kk = (round(pp[0], 2), round(pp[1], 2))
                    if kk not in pin_at or pin_at[kk][0] not in _rs:
                        continue
                    d = math.hypot(pp[0] - x, pp[1] - y)
                    if d < bd:
                        bd, best = d, pin_at[kk][0]
                if best and bd <= 15.0:
                    return best
            return None

        # 被 wire 直连的器件必须【同位移】，否则线会被拉成斜线/脱离引脚。
        # 用并查集把这些器件合并成一个压缩组（组长 wire 只有 0~3 条，不会过度合并）。
        par = {r: r for r in refs}

        def gf(x):
            while par[x] != x:
                par[x] = par[par[x]]; x = par[x]
            return x

        syms, wires, others = [], [], []
        for b in assign.get(p, []):
            m = re.search(r'\(property "Reference" "([^"]+)"', b)
            if m and m.group(1) in rset:
                syms.append((m.group(1), b))
            elif b.lstrip().startswith('(wire'):
                wires.append(b)
            else:
                others.append(b)
        # 按【wire 端点坐标】做连通分量：同一分量里的所有归属器件必须同位移。
        # ⚠️ 只看单条 wire 两端是不够的：C7┐
        #                                  ├(共享悬空点)├U4 这种 L 形链，
        #                                 U4┘
        # 两条 wire 各自只看到"一端有归属"，不会合并 C7/U4；压缩后两者位移不同，
        # 共享点被拉成两个坐标 → 链断（实战丢 U4.3 的 BAT+ 连接）。
        pt_par = {}

        def pf(x):
            pt_par.setdefault(x, x)
            while pt_par[x] != x:
                pt_par[x] = pt_par[pt_par[x]]; x = pt_par[x]
            return x

        for b in wires:
            pts = blk_pts(b)
            if len(pts) < 2:
                continue
            for q in pts[1:]:
                ra, rb = pf(pts[0]), pf(q)
                if ra != rb:
                    pt_par[ra] = rb
        comp_devs = collections.defaultdict(set)
        for b in wires:
            for q in blk_pts(b):
                o = owner(*q)
                if o:
                    comp_devs[pf(q)].add(o)
        for k, ds in comp_devs.items():
            ds = sorted(ds)
            for d in ds[1:]:
                if gf(ds[0]) != gf(d):
                    par[gf(ds[0])] = gf(d)
        grp = collections.defaultdict(list)
        for r in refs:
            grp[gf(r)].append(r)

        giv = []
        for k, rs in grp.items():
            giv.append((k,
                        min(bb[r][0] for r in rs if r in bb), min(bb[r][1] for r in rs if r in bb),
                        max(bb[r][2] for r in rs if r in bb), max(bb[r][3] for r in rs if r in bb)))
        fx = axis_map([(a[1], a[3]) for a in giv], GAP_X)
        fy = axis_map([(a[2], a[4]) for a in giv], GAP_Y)
        grp_sh = dict((k, (rnd_grid(fx(x0)), rnd_grid(fy(y0)))) for k, x0, y0, x1, y1 in giv)
        dev_sh = dict((r, grp_sh[gf(r)]) for r in refs)

        # 精确坐标 → 位移。引脚先注册；wire 端点后注册（供挂在悬空端的 label 跟随）
        psh = {}
        for r in refs:
            for q in eps.get(r, []):
                psh[(round(q['x'], 2), round(q['y'], 2))] = dev_sh[r]

        def base(x, y, _psh=psh, _fx=fx, _fy=fy, _dev=dev_sh):
            k = (round(x, 2), round(y, 2))
            if k in _psh:
                return _psh[k]
            o = owner(x, y)
            if o:
                return _dev[o]
            return (rnd_grid(_fx(x)), rnd_grid(_fy(y)))

        body = []
        for r, b in syms:
            body.append(shift(b, *dev_sh[r]))
        for b in wires:
            pts = blk_pts(b)
            if len(pts) >= 2:
                a, z = pts[0], pts[-1]
                sa, sz = base(*a), base(*z)
                oa, oz = owner(*a), owner(*z)
                if oz and not oa:
                    sa = sz                       # 整条跟随有归属的一端
                elif oa and not oz:
                    sz = sa
                elif not oa and not oz:           # 两端都悬空：按 map，但保正交
                    if abs(a[1] - z[1]) < 0.02:
                        sa, sz = (sa[0], sa[1]), (sz[0], sa[1])
                    elif abs(a[0] - z[0]) < 0.02:
                        sa, sz = (sa[0], sa[1]), (sa[0], sz[1])
                sh = {a: sa, z: sz}
                for q, s in sh.items():
                    psh[(round(q[0], 2), round(q[1], 2))] = s
                body.append(shift_by(b, lambda x, y, _sh=sh: _sh.get((x, y)) or base(x, y)))
            else:
                body.append(shift_by(b, base))
        for b in others:
            body.append(shift_by(b, base))

        # label → global_label
        # 默认【全部转】：KiCad 会给页内 local label 也加页路径前缀（/Power/5V_F），
        # 只有 global_label 的网名不带前缀，才能与单页版的网名对齐
        body = [_to_global(b) for b in body]

        # ===== 6b. 居中到纸张内容区 =====
        xs, ys = [], []
        for b in body:
            for a in re.findall(r'\(at ([-\d.]+) ([-\d.]+)', b): xs.append(float(a[0])); ys.append(float(a[1]))
            for a in re.findall(r'\(xy ([-\d.]+) ([-\d.]+)\)', b): xs.append(float(a[0])); ys.append(float(a[1]))
        if not xs:
            continue
        cw, ch = max(xs) - min(xs), max(ys) - min(ys)
        # 选纸：只按【竖放】尺寸选，装不下才换更大的纸。
        # ⚠️ 格式兼容性注意（历史版本 实测修订）：
        #   · eeschema 的 (paper "A4") 是【横放 297x210】——按竖版 210x297 排版的内容
        #     会整个溢出页底（PDF 上看不见），而且不报任何错！
        #   · 想要竖版必须写 (paper "A4" portrait) —— KiCad 9 实测支持，加载/导出正常；
        #     反例："A4 landscape" / "A4" landscape 两种写法都会导致【整页加载失败】，
        #     且父页导出网表时【静默跳过】该页。竖版一律加 portrait，别碰 landscape。
        paper = paper_name
        while True:
            pw, ph = PAPER_SIZE[paper]
            if cw + 2 * MARGIN <= pw and ch + 2 * MARGIN + TITLE_H <= ph:
                break
            i = [n for _, _, n in PAPERS].index(paper)
            if i >= len(PAPERS) - 1:
                break
            paper = PAPERS[i + 1][2]
        if paper != paper_name:
            print("  [警告] %s 紧凑后 %.0fx%.0fmm 装不进 %s，已升级为 %s"
                  % (p, cw + 2 * MARGIN, ch + 2 * MARGIN + TITLE_H, paper_name, paper))
        pw, ph = PAPER_SIZE[paper]
        tx = rnd_grid(MARGIN + (pw - 2 * MARGIN - cw) / 2 - min(xs))
        ty = rnd_grid(MARGIN + TITLE_H + (ph - 2 * MARGIN - TITLE_H - ch) / 2 - min(ys))
        body = [shift(b, tx, ty) for b in body]
        xs = [v + tx for v in xs]; ys = [v + ty for v in ys]
        W, H = cw + 2 * MARGIN, ch + 2 * MARGIN + TITLE_H

        # 模块框 + 标题
        fx0, fy0 = min(xs) - FRAME_PAD, min(ys) - FRAME_PAD
        fx1, fy1 = max(xs) + FRAME_PAD, max(ys) + FRAME_PAD
        name_cn = p.split('_', 1)[1] if '_' in p else p
        frame = ('\t(rectangle\n\t\t(start %s %s)\n\t\t(end %s %s)\n'
                 # 注意：color 第 4 分量是 alpha，必须写 255。
                 # 写 0 时 kicad-cli 导出 PDF 会把框线画成白色（不可见）且不报错。
                 '\t\t(stroke\n\t\t\t(width 0.1)\n\t\t\t(type dash_dot)\n\t\t\t(color 0 0 0 255)\n\t\t)\n'
                 '\t\t(fill\n\t\t\t(type none)\n\t\t)\n\t\t(uuid "%s")\n\t)'
                 % (round(fx0, 3), round(fy0, 3), round(fx1, 3), round(fy1, 3), new_uuid()))
        tit = ('\t(text "模块: %s   (%s)   位号: %s"\n\t\t(at %s %s 0)\n'
               '\t\t(effects\n\t\t\t(font\n\t\t\t\t(size 2.0 2.0)\n\t\t\t\t(face "SimSun"))\n'
               '\t\t\t(justify left bottom)\n\t\t)\n\t\t(uuid "%s")\n\t)'
               % (name_cn, p, ','.join(sorted(page_refs[p], key=lambda z: (len(z), z))),
                  round(fx0, 3), round(fy0 - 3.0, 3), new_uuid()))

        libs_txt = "\n".join(lib_bodies[l] for l in sorted(used_libs[p]) if l in lib_bodies)
        out = ['(kicad_sch', '\t(version 20250114)', '\t(generator "eeschema")',
               '\t(generator_version "9.0")', '\t(uuid "%s")' % new_uuid(),
               '\t(paper "%s" portrait)' % paper, '\t(lib_symbols', libs_txt, '\t)',
               frame, tit]
        out += body
        out += ['\t(sheet_instances', '\t\t(path "/"', '\t\t\t(page "1")', '\t\t)', '\t)',
                '\t(embedded_fonts no)', ')']
        fn = p + '.kicad_sch'
        open(os.path.join(outdir, fn), 'w', encoding='utf-8').write("\n".join(out) + "\n")
        sheets.append((fn, name_cn, new_uuid()))
        report.append("%-16s 器件 %2d  纸张 %s  版面 %.0fx%.0fmm" %
                      (fn, len(page_refs[p]), paper, W, H))

    # --- 7. 附加页（如系统架构页）---
    if attach and os.path.exists(attach):
        fn = os.path.basename(attach)
        at = open(attach, encoding='utf-8').read()
        # ⚠️ 格式兼容性注意：附加页若带顶层 (instances (project ...)) 块，无论单独打开还是被父页
        #    引用都会【加载失败】（kicad-cli 只报"加载原理图失败"不给细节）。
        #    该块是父页 sheet 框的字段，不属于子页文件本身 —— 拷贝时必须剥掉。
        n_ins = 0
        while True:
            m = re.search(r'\n\t\(instances', at)
            if not m:
                break
            s = m.start() + 1
            e = span(at, s)
            at = at[:s] + at[e + 1:]
            n_ins += 1
        if n_ins:
            print("附加页 %s: 已剥离 %d 个非法顶层 (instances) 块" % (fn, n_ins))
        open(os.path.join(outdir, fn), 'w', encoding='utf-8').write(at)
        if attach_first:
            # 排在所有模块页之前（根页 page 1 之后的第 2 页）：评审时先看到架构图
            sheets.insert(0, (fn, '系统架构图', new_uuid()))
            report.append("%-16s （附加页，已排到最前）" % fn)
        else:
            sheets.append((fn, '系统架构图', new_uuid()))
            report.append("%-16s （附加页，剥 instances 后拷贝）" % fn)

    # --- 8. 根页 ---
    # 每页的跨页网络（既用于接口文本标注，也用于生成 sheet pin 与子页
    # hierarchical_label 同名配对，实现跨页连通）
    pg_nets = collections.defaultdict(set)
    for n, ps in net_pages.items():
        if len(ps) > 1:
            for p in ps: pg_nets[p].add(n)

    # 根页版式：按纸张尺寸自适应列数/框尺寸，并整体居中。
    # 默认 A4（210x297）。若子页很多（>8）自动加列，装不下才升级纸张。
    # 跨页网络 >13 条的页跨 2 格（大框）——保证全部 pin 能以 2.54 间距排在
    # 左框边（pin 名渲染行高实测 2.43mm，压间距必叠字；右缘 pin 名会伸出
    # 框外/页边框，一律不用）。
    rp = paper_name
    n = len(sheets)
    spans = [2 if len(pg_nets.get(fn.replace('.kicad_sch', ''), [])) > 13 else 1
             for fn, _, _ in sheets]
    slots = sum(spans)
    for rp in [paper_name] + [q[2] for q in PAPERS]:
        pw, ph = PAPER_SIZE[rp]
        cols = 2 if slots <= 10 else 3
        for _ in range(3):
            rows = int(math.ceil(slots / float(cols)))
            m = 12.0                      # 根页页边距
            gap = 14.0                    # 框间距
            # 底部必须给 KiCad 自带标题栏留位：A4 portrait 下 Size/Title/File/Sheet/Id
            # 约占 x>=91mm、y>=263mm 区域，框压上去会和标题栏文字叠字。
            TB_H = 30.0
            TW = pw - 2 * m
            TH = ph - 2 * m - 20 - TB_H   # 顶部标题占 20mm，底部标题栏占 TB_H
            cellw = (TW - (cols - 1) * gap) / cols
            cellh = (TH - (rows - 1) * gap) / rows
            # 框内上部留 Sheetname 属性位（约 7mm）
            ch = cellh - 7.0
            # ⚠️ 页框实测（A4 portrait，从导出 PDF 量得）：x∈[10.6,199.4]、
            #    y∈[10.4,286.6]。左列 pin 名渲染在框外左侧（justify right），
            #    最长 ≈11.8mm（示例长网络名），若左列框按 x=m 起排，pin 名会
            #    戳出页框甚至页面（实测 x0=-0.2mm）；框右缘也要留可见边界。
            #    → 左缘 = m+mlab 预留 pin 名区，框宽收窄，右缘距页框 ≥10mm。
            mlab = 13.0                   # 左列 pin 名框外延伸预留区
            X0 = m + mlab
            cellw = min(cellw, (pw - X0 - m - 10.0 - (cols - 1) * gap) / cols)
            if ch >= 22.0 and cellw >= 40.0:
                break
            cols += 1
        if ch >= 22.0 and cellw >= 40.0:
            break
    cw = cellw
    tx0 = X0
    ty0 = 20 + m + (TH - (rows * cellh + (rows - 1) * gap)) / 2
    root_body = []
    tit0 = ('\t(text "%s  系统互连图（根页）"\n\t\t(at %s %s 0)\n'
            '\t\t(effects\n\t\t\t(font\n\t\t\t\t(size 2.6 2.6)\n\t\t\t\t(face "SimSun"))\n'
            '\t\t\t(justify left bottom)\n\t\t)\n\t\t(uuid "%s")\n\t)'
            % (title or project, round(tx0, 2), round(m + 8, 2), new_uuid()))
    root_body.append(tit0)
    slot = 0
    for idx, (fn, sname, suid) in enumerate(sheets):
        sp = spans[idx]
        # 列主序（先排满一列再下一列），跨格框沿【垂直方向】跨行
        c, r = slot // rows, slot % rows
        if r + sp > rows:                  # 本列底部放不下 → 挪到下一列列首
            slot = (slot // rows + 1) * rows
            c, r = slot // rows, slot % rows
        slot += sp
        X = tx0 + c * (cw + gap); Y = ty0 + r * (cellh + gap)
        ch_box = sp * cellh + (sp - 1) * gap - 7.0
        nets = sorted(pg_nets.get(fn.replace('.kicad_sch', ''), []))
        # 跨页网络 → sheet pin + 父页同名 local label。
        # ⚠️ 电气机制（实测）：sheet pin 与子页 hierarchical_label 同名配对【只到本页】，
        # 父页里不同 sheet 的同名 pin 之间【不会自动互连】！必须在父页 pin 落点上
        # 再放一个同名 local label（父页内同名 label 自动合并），跨页才能真正连通。
        # 电气连接只认名字，与坐标/角度无关；角度只影响渲染时的引脚朝向。
        # pin 全排左框边（此组合实测 pin 名与 label 文字重合、零叠字）
        n = len(nets)
        pitch = 2.54 if n <= int((ch_box - 6.0) / 2.54) else max(1.6, (ch_box - 6.0) / n)
        pin_blks = []
        for k, nn in enumerate(nets):
            py = round(Y + 3.0 + k * pitch, 2)
            pin_blks.append('\t\t(pin "%s" passive\n\t\t\t(at %s %s 180)\n\t\t\t(uuid "%s")\n\t\t)'
                            % (nn, round(X, 2), py, new_uuid()))
            root_body.append(
                '\t(label "%s"\n\t\t(at %s %s 0)\n'
                '\t\t(effects\n\t\t\t(font\n\t\t\t\t(size 1.27 1.27)\n\t\t\t)\n'
                '\t\t\t(justify right bottom)\n\t\t)\n\t\t(uuid "%s")\n\t)'
                % (nn, round(X, 2), py, new_uuid()))
        pin_txt = ('\n'.join(pin_blks) + '\n') if pin_blks else ''
        root_body.append(
            '\t(sheet\n\t\t(at %s %s)\n\t\t(size %s %s)\n\t\t(fields_autoplaced)\n'
            '\t\t(stroke\n\t\t\t(width 0)\n\t\t\t(type solid)\n\t\t\t(color 0 0 0 255)\n\t\t)\n'
            '\t\t(fill\n\t\t\t(type background)\n\t\t)\n\t\t(uuid "%s")\n'
            '\t\t(property "Sheetname" "%s"\n\t\t\t(at %s %s 0)\n'
            '\t\t\t(effects\n\t\t\t\t(font\n\t\t\t\t\t(size 1.27 1.27)\n\t\t\t\t)\n'
            '\t\t\t\t(justify left bottom)\n\t\t\t)\n\t\t)\n'
            '\t\t(property "Sheetfile" "%s"\n\t\t\t(at %s %s 0)\n'
            '\t\t\t(effects\n\t\t\t\t(font\n\t\t\t\t\t(size 1.27 1.27)\n\t\t\t\t)\n'
            '\t\t\t\t(justify left top)\n\t\t\t)\n\t\t)\n'
            '%s'
            '\t\t(instances\n\t\t\t(project "%s"\n\t\t\t\t(path "/%s"\n'
            '\t\t\t\t\t(page "%d")\n\t\t\t\t)\n\t\t\t)\n\t\t)\n\t)'
            % (round(X, 2), round(Y, 2), cw, round(ch_box, 2), suid, sname,
               round(X, 2), round(Y - 0.5, 2), fn, round(X, 2), round(Y + ch_box, 2),
               pin_txt, project, suid, idx + 2))
    root = ['(kicad_sch', '\t(version 20250114)', '\t(generator "eeschema")',
            '\t(generator_version "9.0")',             '\t(uuid "%s")' % new_uuid(),
            '\t(paper "%s" portrait)' % rp, '\t(lib_symbols', '\t)']
    root += root_body
    root += ['\t(sheet_instances', '\t\t(path "/"', '\t\t\t(page "1")', '\t\t)', '\t)',
             '\t(embedded_fonts no)', ')']
    open(os.path.join(outdir, '00_Top.kicad_sch'), 'w', encoding='utf-8').write("\n".join(root) + "\n")
    report.append("根页 00_Top.kicad_sch  纸张 %s  子页 %d 个（%d 列 x %d 行，框 %.0fx%.0fmm，"
                  "跨2格大框 %d 个）"
                  % (rp, len(sheets), cols, rows, cw, ch, sum(1 for s in spans if s > 1)))

    # --- 9. 跨页网络清单 ---
    report.append("")
    report.append("跨页网络 %d 条（hierarchical_label + 根页 sheet pin 同名配对；页内网络为纯文字 label）:" % len(cross_nets))
    for n in sorted(cross_nets):
        report.append("  %-14s 页: %s" % (n, ', '.join(sorted(net_pages[n]))))
    print("\n".join(report[:12]))
    print("实例守恒: 源 %d，已分配 %d" % (len(insts), len(ref2page)))

    # --- 10. 逐页加载校验（必做）---
    # 父页导出网表时，加载失败的子页会被【静默跳过】——不报错、不警告，
    # 表现为该页器件引脚全部丢失。只有逐页单独跑一次 kicad-cli 才能抓出来。
    # 典型触发：(paper "A4 landscape") 这类非法纸张名。
    ok = verify_pages(outdir, report)

    report.append("")
    report.append("跨页网络 %d 条，详见本报告上方清单" % len(cross_nets))
    open(os.path.join(outdir, '__split_report.txt'), 'w', encoding='utf-8').write("\n".join(report) + "\n")
    print("\n跨页网络 %d 条，详见 %s" % (len(cross_nets), os.path.join(outdir, '__split_report.txt')))
    if not ok:
        raise SystemExit("Generated pages failed KiCad load validation; do not accept output")


def verify_pages(outdir, report=None):
    """逐页用 kicad-cli 做真实加载校验。任一页失败 → 大声报错（不静默）。"""
    import subprocess
    kicad = os.environ.get('KICAD_CLI') or \
        'kicad-cli'
    kicad = shutil.which(kicad) or kicad
    if not os.path.exists(kicad):
        raise SystemExit('Incomplete validation: kicad-cli missing; generated files are NOT accepted')
    import tempfile
    temp_run = tempfile.TemporaryDirectory(prefix='kicad-split-check-')
    tmp = os.path.join(temp_run.name, 'probe.xml')
    bad = []
    for fn in sorted(os.listdir(outdir)):
        if not fn.endswith('.kicad_sch'):
            continue
        p = os.path.join(outdir, fn)
        if os.path.exists(tmp): os.remove(tmp)
        try:
            r = subprocess.run([kicad, 'sch', 'export', 'netlist', '--format', 'kicadxml',
                                '-o', tmp, p], capture_output=True, timeout=120)
            ok = (r.returncode == 0) and os.path.exists(tmp)
        except Exception as e:
            ok = False
            print('   %s 校验异常: %s' % (fn, e))
        if not ok:
            bad.append(fn)
    if os.path.exists(tmp):
        os.remove(tmp)
    print("\n== 逐页加载校验 ==")
    if bad:
        print("  !! %d 页加载失败（父页导出网表时会静默跳过 → 整页引脚丢失）:" % len(bad))
        for fn in bad:
            print("     - %s" % fn)
        print("  常见原因: (paper \"A4 landscape\") 非法纸张名 / 括号不平衡 / 非法 uuid")
        if report is not None:
            report.append("")
            report.append("!! 加载失败的页: %s" % ', '.join(bad))
        return False
    print("  OK 全部子页均可被 KiCad 正常加载")
    return True


def main():
    A = sys.argv[1:]
    a = [x for x in A if not x.startswith('--')]
    opt = {}
    for i, x in enumerate(A):
        if x.startswith('--') and i + 1 < len(A) and not A[i + 1].startswith('--'):
            opt[x] = A[i + 1]
        elif x.startswith('--'):
            opt[x] = True
    if len(a) < 2:
        raise SystemExit(__doc__)
    src, outdir = a[0], a[1]
    mp = opt.get('--map')
    if not mp:
        raise SystemExit("必须给 --map <map.json>")
    mapping = json.load(open(mp, encoding='utf-8'))
    run(src, outdir, mapping,
        project=opt.get('--project', 'Project'),
        attach=opt.get('--attach'),
        title=opt.get('--title', ''),
        force_global=('--force-global' in opt),
        paper_name=opt.get('--paper', 'A4').upper(),
        gap_x=float(opt.get('--gap-x', GAP_X)),
        gap_y=float(opt.get('--gap-y', GAP_Y)),
        attach_first=('--attach-last' not in opt))


if __name__ == '__main__':
    from _runtime import require_apply
    require_apply()
    main()
