# -*- coding: utf-8 -*-
"""通用解析器：实例 / 引脚端点 / label / wire"""
import re, json, sys
sys.stdout.reconfigure(encoding='utf-8')

def load(path=None):
    """读 .kicad_sch。省略 path 时取 sys.argv[1]（便于本目录下所有脚本统一 CLI 化）"""
    if path is None:
        path = sys.argv[1] if len(sys.argv) > 1 else None
        if path is None:
            raise SystemExit("用法: python <script>.py <原理图.kicad_sch> [其他参数]")
    t=open(path,encoding='utf-8').read()
    def span(s):
        d=0;i=s
        while True:
            if t[i]=='(':d+=1
            elif t[i]==')':
                d-=1
                if d==0:return i
            i+=1
    # lib_symbols 段
    ls=t.find('\n\t(lib_symbols')
    le=span(ls)
    libs={}
    for m in re.finditer(r'\n\t\t\(symbol "([^"]+)"', t[ls:le]):
        s=ls+m.start(); e=span(s); nm=m.group(1); body=t[s:e]
        pins=[]
        for pm in re.finditer(r'\n\t+\(pin ', body):
            ps=pm.start(); pe=span(s+ps); pb=body[ps:pe]
            a=re.search(r'\(at ([-\d.]+) ([-\d.]+) ([-\d.]+)\)',pb)
            nu=re.search(r'\(number "([^"]*)"',pb)
            na=re.search(r'\(name "([^"]*)"',pb)
            hid = '(hide yes)' in pb
            if not a: continue
            lx,ly=float(a.group(1)),float(a.group(2))
            lang=float(a.group(3))
            ex=lx; ey=ly   # KiCad 引脚 (at) 即连接端点
            pins.append(dict(num=nu.group(1) if nu else '?',name=na.group(1) if na else '?',
                             lx=lx,ly=ly,ex=ex,ey=ey,hide=hid,ang=lang))
        libs[nm]=pins
    # 顶层实例
    insts=[]
    for m in re.finditer(r'\n\t\(symbol\n', t):
        s=m.start(); e=span(s); blk=t[s:e]
        if '(lib_id' not in blk: continue
        lid=re.search(r'\(lib_id "([^"]+)"\)',blk).group(1)
        ia=re.search(r'\n\t\t\(at ([-\d.]+) ([-\d.]+) ([-\d.]+)\)',blk)
        if not ia: continue
        ax,ay,aa=float(ia.group(1)),float(ia.group(2)),float(ia.group(3))
        props={}
        for pm in re.finditer(r'\(property "([^"]+)" "([^"]*)"\n?\s*\(at ([-\d.]+) ([-\d.]+) ([-\d.]+)\)',blk):
            props[pm.group(1)]=dict(val=pm.group(2),x=float(pm.group(3)),y=float(pm.group(4)),a=float(pm.group(5)))
        ref=props.get('Reference',{}).get('val','?')
        val=props.get('Value',{}).get('val','?')
        insts.append(dict(ref=ref,val=val,lid=lid,ax=ax,ay=ay,aa=aa,s=s,e=e,props=props))
    return t,libs,insts

def endpoints(t,libs,insts):
    """每个实例的引脚端点绝对坐标"""
    import math
    eps={}
    for ins in insts:
        pins=libs.get(ins['lid'],[])
        lst=[]
        a=math.radians(ins['aa'])
        for p in pins:
            # 实例旋转 (KiCad 逆时针, y 轴向下翻转)
            rx=p['ex']*math.cos(a)-p['ey']*math.sin(a)
            ry=p['ex']*math.sin(a)+p['ey']*math.cos(a)
            sx=ins['ax']+rx; sy=ins['ay']-ry   # Y 翻转
            # 引脚外指方向（从本体指向连接端点），库坐标 -> 绝对坐标
            import math as _m
            la=_m.radians(p.get('ang',0))
            vx=_m.cos(la); vy=_m.sin(la)          # 库坐标 y 向上
            rx=vx*_m.cos(a)-vy*_m.sin(a); ry=vx*_m.sin(a)+vy*_m.cos(a)
            lst.append(dict(num=p['num'],name=p['name'],x=round(sx,3),y=round(sy,3),
                            dirx=round(rx,3),diry=round(-ry,3)))
        eps[ins['ref']]=lst
    return eps

if __name__=='__main__':
    t,libs,insts=load()
    eps=endpoints(t,libs,insts)
    print("实例数:",len(insts)," 库符号数:",len(libs))
    # label 列表
    labs=[]
    for m in re.finditer(r'\t\(label "([^"]+)"\n\t\t\(at ([-\d.]+) ([-\d.]+) ([-\d.]+)\)', t):
        labs.append((m.group(1),float(m.group(2)),float(m.group(3)),float(m.group(4)),m.start()))
    print("label 数:",len(labs))
    # 把 label 匹配到引脚端点
    key={}
    for ref,lst in eps.items():
        for p in lst:
            key[(round(p['x'],2),round(p['y'],2))]=(ref,p['num'],p['name'])
    unmatched=[]
    bynet={}
    for nm,x,y,a,pos in labs:
        k=(round(x,2),round(y,2))
        own=key.get(k)
        if own is None: unmatched.append((nm,x,y))
        bynet.setdefault(nm,[]).append(dict(x=x,y=y,angle=a,pos=pos,own=own))
    print("未匹配到引脚端点的 label 数:",len(unmatched))
    for u in unmatched[:10]: print("   ",u)
    # 双端点网络距离
    from collections import Counter
    c=Counter(x[0] for x in labs)
    print("\n== 双端点网络(36) 的两端归属与距离 ==")
    rows=[]
    for nm,v in c.items():
        if v!=2: continue
        a,b=bynet[nm]
        d=((a['x']-b['x'])**2+(a['y']-b['y'])**2)**0.5
        rows.append((d,nm,a,b))
    rows.sort()
    for d,nm,a,b in rows:
        oa=a['own'] or ('?','?','?'); ob=b['own'] or ('?','?','?')
        print(f"  {d:6.2f}mm  {nm:14s}  {oa[0]}.{oa[1]}({oa[2]}) @({a['x']:.2f},{a['y']:.2f})  <->  {ob[0]}.{ob[1]}({ob[2]}) @({b['x']:.2f},{b['y']:.2f})")


def lib_bbox(t, libs):
    """每个库符号的图形本体 bbox（相对坐标）"""
    def span(s):
        d=0;i=s
        while True:
            if t[i]=='(':d+=1
            elif t[i]==')':
                d-=1
                if d==0:return i
            i+=1
    ls=t.find('\n\t(lib_symbols'); le=span(ls)
    bb={}
    for m in re.finditer(r'\n\t\t\(symbol "([^"]+)"', t[ls:le]):
        s0=ls+m.start(); e0=span(s0); body=t[s0:e0]; nm=m.group(1)
        xs=[];ys=[]
        for r in re.finditer(r'\(rectangle\s*\n?\s*\(start ([-\d.]+) ([-\d.]+)\)\s*\n?\s*\(end ([-\d.]+) ([-\d.]+)\)', body):
            xs += [float(r.group(1)),float(r.group(3))]; ys += [float(r.group(2)),float(r.group(4))]
        for r in re.finditer(r'\(polyline', body):
            ps=r.start(); pe=span(s0+ps)
            for q in re.finditer(r'\(xy ([-\d.]+) ([-\d.]+)\)', body[ps:pe]):
                xs.append(float(q.group(1))); ys.append(float(q.group(2)))
        for r in re.finditer(r'\(circle\s*\n?\s*\(center ([-\d.]+) ([-\d.]+)\)\s*\n?\s*\(radius ([-\d.]+)\)', body):
            cx,cy,rr=float(r.group(1)),float(r.group(2)),float(r.group(3))
            xs+=[cx-rr,cx+rr]; ys+=[cy-rr,cy+rr]
        # 注意：不含引脚坐标，否则走线起点会被自身本体框判为阻挡
        bb[nm]=(min(xs),min(ys),max(xs),max(ys)) if xs else (0,0,0,0)
    return bb

def inst_bboxes(t, libs, insts):
    """实例本体绝对 bbox"""
    import math
    bb=lib_bbox(t,libs); out={}
    for ins in insts:
        x0,y0,x1,y1=bb.get(ins['lid'],(0,0,0,0))
        a=math.radians(ins['aa'])
        pts=[]
        for (lx,ly) in ((x0,y0),(x1,y0),(x1,y1),(x0,y1)):
            rx=lx*math.cos(a)-ly*math.sin(a); ry=lx*math.sin(a)+ly*math.cos(a)
            pts.append((ins['ax']+rx, ins['ay']-ry))
        xs=[q[0] for q in pts]; ys=[q[1] for q in pts]
        out[ins['ref']]=(min(xs),min(ys),max(xs),max(ys))
    return out
