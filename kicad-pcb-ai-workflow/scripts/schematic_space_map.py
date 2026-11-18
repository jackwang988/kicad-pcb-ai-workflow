"""Pure collision/clearance and candidate occupancy model (no EDA writes)."""
import math
from schematic_geometry import rect, inside, intersects


def transform(xy, angle):
    # KiCad screen coordinates: +Y down; +90 means counterclockwise.
    x, y = xy
    if angle == 0: return (x,y)
    if angle == 90: return (y,-x)
    if angle == 180: return (-x,-y)
    if angle == 270: return (-y,x)
    raise ValueError('Rotations must be 0,90,180,270 (verified coordinates)')


def box_at(raw, at, angle):
    l,t,r,b = rect(raw)
    pts=[transform((x,y),angle) for x in (l,r) for y in (t,b)]
    return (min(p[0] for p in pts)+at[0], min(p[1] for p in pts)+at[1],
            max(p[0] for p in pts)+at[0], max(p[1] for p in pts)+at[1])


def point(raw):
    if (not isinstance(raw, list) or len(raw)!=2 or
        any(isinstance(x,bool) or not isinstance(x,(int,float)) or not math.isfinite(x) for x in raw)):
        raise ValueError('Expected finite [x,y] coordinates')
    return tuple(float(x) for x in raw)


def corridor(a, b, half_width):
    if abs(a[0]-b[0])>1e-6 and abs(a[1]-b[1])>1e-6:
        raise ValueError('Pin escape must be orthogonal')
    return (min(a[0],b[0])-half_width,min(a[1],b[1])-half_width,
            max(a[0],b[0])+half_width,max(a[1],b[1])+half_width)


def reject_collision(box, obstacles, clearance, dimensions, exempt=None):
    if not inside(box, dimensions):
        return 'PAGE_BORDER'
    for name, other in obstacles:
        if name == exempt:
            continue
        if intersects(box, other, clearance):
            return 'COLLISION:'+name
    return None


def placements(symbol, at, angle, pin_escape, width):
    geom=symbol['geometry']; body=box_at(geom['body_bbox_mm'],at,angle)
    obbs=[('body',body)]
    fields=geom.get('fields', [])
    if not fields or not {'Reference','Value'}.issubset({f.get('name') for f in fields}):
        raise ValueError('Visible Reference and Value field geometry required for '+symbol['ref'])
    for f in fields:
        if not f.get('hidden',False):
            obbs.append(('field:'+f['name'],box_at(f['bbox_mm'],at,angle)))
    pins={};escapes={};labels=[]
    for pin in geom['pins']:
        num=str(pin['number'])
        if num in pins:raise ValueError('Duplicate symbol pin '+symbol['ref']+'.'+num)
        local=point(pin['xy_mm']);direct=transform(point(pin['outward']),angle)
        if direct not in ((1,0),(-1,0),(0,1),(0,-1)):
            raise ValueError('Only exact orthogonal transformed pin vectors supported')
        pos=transform(local,angle);anchor=(pos[0]+at[0],pos[1]+at[1]);outer=(anchor[0]+direct[0]*pin_escape,anchor[1]+direct[1]*pin_escape)
        pins[num]={'net':pin.get('net'),'at':anchor,'end':outer,'direction':direct}
        if pin.get('net') not in (None,'NC'):
            escapes[num]=corridor(anchor,outer,width/2)
    for label in geom.get('labels',[]):
        num=str(label['pin']);pin=pins.get(num)
        if not pin or pin['net']!=label.get('net') or label.get('kind') not in ('local','hierarchical','global','power'):
            raise ValueError('Label pin/net/kind mismatch')
        if label.get('text') != label['net']:
            raise ValueError('Label/power symbol displayed net must match expected net')
        native_anchor=point(label.get('anchor_local_mm'))
        transformed=transform(native_anchor,angle)
        actual_anchor=(transformed[0]+at[0],transformed[1]+at[1])
        if any(abs(a-b)>1e-5 for a,b in zip(actual_anchor,pin['end'])):
            raise ValueError('Label/power anchor must coincide with reserved pin-escape endpoint')
        b=box_at(label['bbox_mm'],at,angle)
        if not(b[0]-1e-5<=actual_anchor[0]<=b[2]+1e-5 and b[1]-1e-5<=actual_anchor[1]<=b[3]+1e-5):
            raise ValueError('Label/power rendered box must include its connection anchor')
        labels.append((num,b,label))
    return {'objects':obbs,'pins':pins,'escapes':escapes,'labels':labels,'origin':at,'rotation':angle}
