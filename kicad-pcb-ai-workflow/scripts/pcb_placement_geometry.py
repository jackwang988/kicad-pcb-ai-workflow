"""Conservative native PCB Courtyard and mechanical keepout geometry for G3 planning.

Read-only: supported top-side KiCad courtyard polygons only. This is a pre-screen,
not the KiCad DRC engine. Unsupported native geometry blocks automatic placement.
No external geometry dependencies. Units are millimeters.
"""
import math
from npi_common import child, children, value, transform

EPS=1e-8


def bbox(poly):
    return (min(p[0] for p in poly),min(p[1] for p in poly),max(p[0] for p in poly),max(p[1] for p in poly))


def shift(poly, dx, dy):
    return [(p[0]+dx,p[1]+dy) for p in poly]


def _orient(a,b,p):
    return (b[0]-a[0])*(p[1]-a[1])-(b[1]-a[1])*(p[0]-a[0])


def _on_segment(p,a,b):
    return abs(_orient(a,b,p))<EPS and min(a[0],b[0])-EPS<=p[0]<=max(a[0],b[0])+EPS and min(a[1],b[1])-EPS<=p[1]<=max(a[1],b[1])+EPS


def _cross(a,b,c,d):
    o1,o2,o3,o4=_orient(a,b,c),_orient(a,b,d),_orient(c,d,a),_orient(c,d,b)
    return ((o1>EPS and o2 < -EPS or o1 < -EPS and o2>EPS) and (o3>EPS and o4 < -EPS or o3 < -EPS and o4>EPS)
            or _on_segment(c,a,b) or _on_segment(d,a,b) or _on_segment(a,c,d) or _on_segment(b,c,d))


def _contains(poly,p):
    inside=False
    for a,b in zip(poly,poly[1:]+poly[:1]):
        if _on_segment(p,a,b):return True
        if (a[1]>p[1])!=(b[1]>p[1]):
            x=(b[0]-a[0])*(p[1]-a[1])/(b[1]-a[1])+a[0]
            if x>p[0]:inside=not inside
    return inside


def _pseg(p,a,b):
    dx,dy=b[0]-a[0],b[1]-a[1]
    t=max(0.,min(1.,((p[0]-a[0])*dx+(p[1]-a[1])*dy)/(dx*dx+dy*dy))) if dx*dx+dy*dy>EPS else 0
    return math.hypot(p[0]-a[0]-t*dx,p[1]-a[1]-t*dy)


def intersects(a,b,clearance=0):
    """True when simple closed polygons overlap/touch or violate edge clearance.

    Supports convex or concave polygons; exact for straight segments.
    Caller verifies native polygon provenance and layer applicability.
    """
    if len(a)<3 or len(b)<3:raise ValueError('Verified closed Courtyard / keepout polygon required')
    A,B=bbox(a),bbox(b)
    if A[2]+clearance < B[0]-EPS or B[2]+clearance < A[0]-EPS or A[3]+clearance < B[1]-EPS or B[3]+clearance < A[1]-EPS:return False
    for u,v in zip(a,a[1:]+a[:1]):
        for s,t in zip(b,b[1:]+b[:1]):
            if _cross(u,v,s,t):return True
            if clearance>0 and min(_pseg(u,s,t),_pseg(v,s,t),_pseg(s,u,v),_pseg(t,u,v)) < clearance-EPS:return True
    return _contains(a,b[0]) or _contains(b,a[0])


def in_rectangle(poly,rect):
    return all(rect[0]-EPS<=x<=rect[2]+EPS and rect[1]-EPS<=y<=rect[3]+EPS for x,y in poly)


def _pts(node):
    points=[]
    for p in children(child(child(node,'polygon',[]),'pts',[]),'xy'):
        if len(p)<3:raise ValueError('Malformed native Keepout polygon point')
        x,y=float(p[1]),float(p[2])
        if not (math.isfinite(x) and math.isfinite(y)):raise ValueError('Non-finite native Keepout polygon')
        points.append((x,y))
    if points and points[0]==points[-1]:points.pop()
    return points


def footprint_keepouts(board):
    """Real KiCad footprint-disallow zone polygons. Unknown geometry blocks.

    All footprint-forbidding zones are kept as obstacles: a conservative default
    avoids silently ignoring non-copper, multi-layer or unusual keepout areas.
    """
    out=[]
    for zone in children(board,'zone'):
        ko=child(zone,'keepout',[])
        if str(value(ko,'footprints','allowed')).lower()!='not_allowed':continue
        points=_pts(zone)
        if len(points)<3:raise ValueError('Native footprint Keepout missing supported polygon')
        out.append({'kind':'footprint_keepout','polygon':points,'id':str(value(zone,'uuid','unidentified'))})
    return out


def locked(fp):
    """KiCad may serialize lock either as a bare token or an S-expression."""
    if any(x=='locked' for x in fp):return True
    state=child(fp,'locked',[])
    return bool(state and (len(state)==1 or str(state[1]).lower() not in ('no','false','0')))


def npth_holes(board, locked_refs):
    """Fixed NPTH mounting drills; movable NPTH holes cannot be planned safely.

    This only models circular, top-side, unrotated pads. Slotted or other
    mechanical holes require native geometry evidence before automated layout.
    """
    result=[]
    for fp in children(board,'footprint'):
        ref=next((p[2] for p in children(fp,'property') if len(p)>2 and p[1]=='Reference'),None)
        for pad in children(fp,'pad'):
            if len(pad)<3 or pad[2]!='np_thru_hole':continue
            if ref not in locked_refs:raise ValueError('Footprint with NPTH mounting hole must be fixed: '+str(ref))
            at=child(fp,'at',[]);local=child(pad,'at',[]);drill=child(pad,'drill',[])
            if (len(at)<3 or len(local)<3 or len(drill)<2 or 'oval' in drill or
                value(fp,'layer')!='F.Cu' or (float(at[3]) if len(at)>3 else 0)%360):
                raise ValueError('Unsupported NPTH orientation/slot; need native mechanical evidence: '+str(ref))
            radius=float(drill[1])/2
            if not math.isfinite(radius) or radius<=0:raise ValueError('Invalid NPTH drill size')
            result.append({'ref':ref,'center':(float(at[1])+float(local[1]),float(at[2])+float(local[2])),'radius':radius})
    return result


def hits_holes(poly,holes,clearance=0,own_ref=None):
    for h in holes:
        if h['ref']==own_ref:continue
        p=h['center'];radius=h['radius']+clearance
        if _contains(poly,p):return True
        if any(_pseg(p,a,b)<radius-EPS for a,b in zip(poly,poly[1:]+poly[:1])):return True
    return False


def pad_anchor(fp,position,pad_number,net,native_offsets=None):
    """Find source-bound pad anchor for fixed-orientation supported footprints.

    Rotated, mirrored or multi-layer pads need verified native pad coordinates;
    this helper must never invent a pin center for a hard electrical rule.
    """
    if native_offsets is not None:
        n=native_offsets.get(str(pad_number))
        if not n or n[1]!=net:
            raise ValueError('Native pad/net identity missing or inconsistent')
        return (position[0]+n[0][0],position[1]+n[0][1])
    at=child(fp,'at',[])
    angle=float(at[3]) if len(at)>3 else 0.
    if value(fp,'layer')!='F.Cu' or abs(angle%360)>EPS:
        raise ValueError('Native pad position required for rotated/bottom footprint with hard electrical rule')
    pads=[p for p in children(fp,'pad') if len(p)>1 and str(p[1])==str(pad_number)]
    if len(pads)!=1:raise ValueError('Ambiguous/missing native pad '+str(pad_number))
    p=pads[0];n=child(p,'net',[])
    if len(n)<3 or str(n[2])!=net:raise ValueError('Hard constraint pad/net mismatch')
    loc=child(p,'at',[])
    if len(loc)<3:raise ValueError('Native pad local position missing')
    return (position[0]+float(loc[1]),position[1]+float(loc[2]))
