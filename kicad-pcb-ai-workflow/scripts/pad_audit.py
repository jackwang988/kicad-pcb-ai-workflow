"""Supported pad-shape overlap screening. Never resize original pads.

Circle and oriented-rectangle copper are supported. Other shapes require
native DRC/manufacturer land-pattern evidence, and are explicitly unverified.
"""
import math
from npi_common import parse_sexpr,children,child,value,xy,transform,distance
from pathlib import Path

def projection(p,axis):
    if p['shape']=='circle':return max(p['size'])/2
    a=math.radians(p['angle']);u=(math.cos(a),math.sin(a));v=(-math.sin(a),math.cos(a))
    return abs(axis[0]*u[0]+axis[1]*u[1])*p['size'][0]/2+abs(axis[0]*v[0]+axis[1]*v[1])*p['size'][1]/2

def signed_gap(a,b):
    """Positive = separated. Rect/rect SAT gap is a conservative clearance bound."""
    if a['shape'] not in ('rect','circle') or b['shape'] not in ('rect','circle'):raise ValueError('Unsupported copper pad shape')
    delta=(b['pos'][0]-a['pos'][0],b['pos'][1]-a['pos'][1])
    if a['shape']==b['shape']=='circle':return math.hypot(*delta)-(a['size'][0]+b['size'][0])/2
    if a['shape']=='circle' or b['shape']=='circle':
        circle,rect=(a,b) if a['shape']=='circle' else (b,a)
        d=(circle['pos'][0]-rect['pos'][0],circle['pos'][1]-rect['pos'][1]);ang=math.radians(-rect['angle'])
        x=d[0]*math.cos(ang)-d[1]*math.sin(ang);y=d[0]*math.sin(ang)+d[1]*math.cos(ang)
        qx=abs(x)-rect['size'][0]/2;qy=abs(y)-rect['size'][1]/2
        return math.hypot(max(qx,0),max(qy,0))+min(max(qx,qy),0)-circle['size'][0]/2
    axes=[]
    for p in (a,b):
        ang=math.radians(p['angle']);axes += [(math.cos(ang),math.sin(ang)),(-math.sin(ang),math.cos(ang))]
    return max(abs(delta[0]*v[0]+delta[1]*v[1])-projection(a,v)-projection(b,v) for v in axes)

def inspect(r,path):
    tree=parse_sexpr(Path(path).read_text(encoding='utf-8-sig'));pads=[]
    for fp in children(tree,'footprint'):
        props={x[1]:x[2] for x in children(fp,'property') if len(x)>2};origin=xy(fp)
        at=child(fp,'at',[]);angle=float(at[3]) if len(at)>3 else 0
        for p in children(fp,'pad'):
            if p[2]=='np_thru_hole':continue
            at=child(p,'at',[]);pa=float(at[3]) if len(at)>3 else 0
            net=child(p,'net',[]);layers=set(child(p,'layers',[])[1:])
            pads.append({'ref':props.get('Reference','?')+'.'+str(p[1]),'pos':transform(xy(p),origin,angle),
                         'size':xy(p,'size'),'shape':p[3],'angle':angle+pa,'net':net[2] if len(net)>2 else '',
                         'layers':layers,'side':value(fp,'layer')})
    unsupported=[]
    for i,a in enumerate(pads):
        if a['shape'] not in ('rect','circle') or a['side']=='B.Cu':
            unsupported.append(a['ref']);continue
        for b in pads[i+1:]:
            if b['shape'] not in ('rect','circle') or b['side']=='B.Cu' or a['net']==b['net'] and a['net']:continue
            if not (a['layers'] & b['layers']) and '*.Cu' not in a['layers']|b['layers']:continue
            gap=signed_gap(a,b)
            if gap < -1e-8:r.risk('PAD.OVERLAP','layout','阻断级','支持的真实旋转焊盘铜形状相交；扇出走线不能解除既有铜短路',a['ref']+'/'+b['ref'],'器件原厂land pattern、PCB厂间距要求','按原厂坐标/旋转/pad number核对封装；不得擅自缩焊盘或改线绕过。')
    if unsupported:r.check('PAD.SHAPE','pending',{'unverified_shapes_or_bottom_transform':unsupported},'必须原生DRC和封装原厂证据；不视为PASS')
    r.check('PAD.SUPPORTED','completed',f'{len(pads)} pads inventoried; supported top rect/circle overlap only','旋转几何；最小间距仍以DRC为准')
