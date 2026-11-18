"""Read actual KiCad symbol geometry before placement (read-only).

Schematic symbol drawings contain primitives and pins, not a stored bounding
rectangle. This module computes the primitive bounding rectangle exactly for
supported primitives, calculates sheet pin anchors and conservatively estimates
font extents. No font estimate is ever represented as a measured KiCad render.
No editor, network or project mutation is performed.
"""
from __future__ import annotations
import math
import os
import re
import unicodedata
from functools import lru_cache
from pathlib import Path

from npi_common import child, children, value
from schematic_io import parse

EPS=1e-7


def _num(v):
    n=float(v)
    if not math.isfinite(n):raise ValueError('Non-finite KiCad coordinate')
    return n


def _xy(node,tag):
    v=child(node,tag)
    if not v or len(v)<3:raise ValueError('Missing KiCad '+tag+' coordinates')
    return (_num(v[1]),_num(v[2]))


def _box(points,pad=0):
    pts=list(points)
    if not pts:raise ValueError('Geometry has no points')
    return [min(x for x,y in pts)-pad,min(y for x,y in pts)-pad,
            max(x for x,y in pts)+pad,max(y for x,y in pts)+pad]


def _union(boxes):
    boxes=list(boxes)
    if not boxes:raise ValueError('Missing body graphics')
    return [min(b[0] for b in boxes),min(b[1] for b in boxes),
            max(b[2] for b in boxes),max(b[3] for b in boxes)]


def _expand(b,pad=0.01):
    # A zero-length wire/point still needs a strictly positive collision extent.
    return [b[0]-pad,b[1]-pad,b[2]+pad,b[3]+pad]


def _translate(b, x, y):
    return [b[0]+x,b[1]+y,b[2]+x,b[3]+y]


def _corners(b):
    return [(x,y) for x in (b[0],b[2]) for y in (b[1],b[3])]


def _round(b):return [round(float(x),5) for x in b]


def _rot(x,y,angle):
    """KiCad SCH angle: positive 90° rotates screen geometry CCW."""
    angle=int(angle)%360
    if angle==0:return (x,y)
    if angle==90:return (y,-x)
    if angle==180:return (-x,-y)
    if angle==270:return (-y,x)
    raise ValueError('Only orthogonal KiCad schematic rotations are supported')


def _world(x,y,at,angle=0,mirror=''):
    # KiCad symbol-library +Y points UP; sheet +Y points DOWN.
    dx,dy=_rot(x,-y,angle)
    if mirror=='x':dy=-dy
    elif mirror=='y':dx=-dx
    elif mirror:raise ValueError('Unknown KiCad mirror axis '+mirror)
    return (round(at[0]+dx,6),round(at[1]+dy,6))


def _transform_box(b,at,angle=0,mirror=''):
    return _box(_world(x,-y,at,angle,mirror) for x,y in _corners(b))


def _stroke(node):
    stroke=child(node,'stroke',[])
    width=value(stroke,'width',0) if stroke else 0
    return max(0.1,_num(width))/2


def _curve_extrema(p):
    # Cubic bezier x(t) or y(t): roots of first derivative.
    a,b,c,d=p
    A=-a+3*b-3*c+d;B=3*a-6*b+3*c;C=-3*a+3*b
    roots=[]
    if abs(A)<EPS:
        if abs(B)>EPS:roots=[-C/(2*B)]
    else:
        disc=B*B-3*A*C
        if disc>=0:
            roots=[(-B+math.sqrt(disc))/(3*A),(-B-math.sqrt(disc))/(3*A)]
    return [t for t in roots if EPS<t<1-EPS]


def _bezier_bbox(pts):
    if len(pts)!=4:raise ValueError('Only cubic KiCad Bezier curves supported')
    ts={0.,1.}
    for axis in (0,1):ts.update(_curve_extrema([p[axis] for p in pts]))
    def coord(t,axis):
        return sum(w*p[axis] for w,p in zip(((1-t)**3,3*(1-t)**2*t,3*(1-t)*t*t,t**3),pts))
    return _box((coord(t,0),coord(t,1)) for t in ts)


def _arc_bbox(a,b,c):
    # Circle through three points; calculate the arc containing the middle point.
    ax,ay=a;bx,by=b;cx,cy=c
    d=2*(ax*(by-cy)+bx*(cy-ay)+cx*(ay-by))
    if abs(d)<1e-9:return _box((a,b,c))
    u=((ax*ax+ay*ay)*(by-cy)+(bx*bx+by*by)*(cy-ay)+(cx*cx+cy*cy)*(ay-by))/d
    v=((ax*ax+ay*ay)*(cx-bx)+(bx*bx+by*by)*(ax-cx)+(cx*cx+cy*cy)*(bx-ax))/d
    r=math.hypot(ax-u,ay-v)
    theta=lambda q:math.atan2(q[1]-v,q[0]-u)%(2*math.pi)
    t0=theta(a);tm=theta(b);t1=theta(c)
    positive=(tm-t0)%(2*math.pi)<=(t1-t0)%(2*math.pi)+EPS
    sweep=((t1-t0) if positive else (t0-t1))%(2*math.pi)
    def contains(t):return ((t-t0) if positive else (t0-t))%(2*math.pi)<=sweep+EPS
    points=[a,b,c]+[(u+r*math.cos(t),v+r*math.sin(t)) for t in (0,math.pi/2,math.pi,3*math.pi/2) if contains(t)]
    return _box(points)


def _font_metrics(effects):
    font=child(effects,'font',[]) if effects else []
    sz=child(font,'size',[None,1.27,1.27]) if font else [None,1.27,1.27]
    return (_num(sz[1]),_num(sz[2]))


def _hidden(effects):
    if not effects:return False
    hide=child(effects,'hide')
    return bool(hide and (len(hide)==1 or str(hide[1]).lower() not in ('no','false','0')))


def _font_box(text,at,effects=None,angle=0):
    # Conservative font *estimate*, not a native font/renderer measurement.
    # Includes descenders, formatting variation and a 0.35mm guard on each side.
    sx,sy=_font_metrics(effects)
    def cw(ch):
        if unicodedata.east_asian_width(ch) in ('W','F'):return 1.4
        if ch in 'ijl.,:;|!\'':return 0.48
        if ch in 'MW@#%':return 1.15
        return 0.93
    text=str(text)
    width=max(0.5,sum(cw(c) for c in text)*sx*1.2)
    height=sy*1.6
    justify=child(effects,'justify',[]) if effects else []
    just=justify[1:] if justify else []
    if 'left' in just:xl,xr=0,width
    elif 'right' in just:xl,xr=-width,0
    else:xl,xr=-width/2,width/2
    if 'top' in just:yt,yb=0,height
    elif 'bottom' in just:yt,yb=-height,0
    else:yt,yb=-height/2,height/2
    pts=[_rot(x,y,angle) for x in (xl,xr) for y in (yt,yb)]
    return _round(_box(((x+at[0],y+at[1]) for x,y in pts),0.35))


def _graphic_box(g):
    kind=g[0]
    pad=_stroke(g)
    if kind=='rectangle':
        a=_xy(g,'start');b=_xy(g,'end');return _box((a,b),pad)
    if kind=='circle':
        center=_xy(g,'center');r=_num(value(g,'radius'))
        if r<0:raise ValueError('Invalid circle radius')
        return [center[0]-r-pad,center[1]-r-pad,center[0]+r+pad,center[1]+r+pad]
    if kind=='arc':
        a=_xy(g,'start');b=_xy(g,'mid');c=_xy(g,'end');return _expand(_arc_bbox(a,b,c),pad)
    if kind in ('polyline','bezier'):
        pts=child(g,'pts',[])
        xy=[(float(x[1]),float(x[2])) for x in children(pts,'xy')]
        if len(xy)<2:raise ValueError('Missing graphic points')
        b=_bezier_bbox(xy) if kind=='bezier' else _box(xy)
        return _expand(b,pad)
    if kind=='text':
        p=_xy(g,'at');at=child(g,'at',[])
        # font geometry is an estimate, transformed later with primitives
        effect=child(g,'effects',[])
        return _font_box(g[1],p,effect,float(at[3]) if len(at)>3 else 0)
    raise ValueError('Unsupported KiCad symbol graphic '+kind)


def _unit_tag(name,lib_id,unit,style):
    # Subsymbols have NAME_UNIT_STYLE, e.g. R_0_1 shared, R_1_1 unit 1.
    p=re.search(r'_(\d+)_(\d+)$',str(name))
    if not p:raise ValueError('Unrecognized KiCad subsymbol ID '+str(name))
    return int(p[1]) in (0,unit) and int(p[2]) in (0,style)


@lru_cache(maxsize=20)
def _parse_current(path,mtime_ns,size):
    return parse(Path(path).read_text(encoding='utf-8-sig'))


def _load_source(path):
    p=Path(path).resolve()
    st=p.stat()
    return _parse_current(str(p),st.st_mtime_ns,st.st_size)


def _resolve_library(root,schematic,lib_id):
    """Find the actual installed/project KiCad symbol library, not fabricated geometry."""
    libname=lib_id.split(':',1)[0]
    root=Path(root).resolve()
    search=[]
    for table in (root/'sym-lib-table',Path(schematic).parent/'sym-lib-table'):
        if not table.is_file():continue
        tree=_load_source(table)
        if tree[0]!='sym_lib_table':raise ValueError('Invalid project sym-lib-table')
        for lib in children(tree,'lib'):
            if value(lib,'name')!=libname:continue
            if value(lib,'type','KiCad')!='KiCad':raise ValueError('Non-native KiCad symbols are not supported')
            uri=value(lib,'uri')
            env={'KIPRJMOD':str(Path(schematic).parent.resolve())}
            env.update(os.environ)
            def replace(m):
                key=m.group(1)
                if key not in env:raise ValueError('KiCad symbol library variable missing: '+key)
                return env[key]
            name=re.sub(r'\$\{([^}]+)\}',replace,uri)
            search.append(Path(name))
    for key in ('KICAD10_SYMBOL_DIR','KICAD9_SYMBOL_DIR','KICAD_SYMBOL_DIR'):
        if os.environ.get(key):search.append(Path(os.environ[key])/f'{libname}.kicad_sym')
    search += [root/f'{libname}.kicad_sym',Path(schematic).parent/f'{libname}.kicad_sym']
    search += [Path(d)/f'{libname}.kicad_sym' for d in
               ('/usr/share/kicad/symbols','/usr/local/share/kicad/symbols',
                '/Applications/KiCad/KiCad.app/Contents/SharedSupport/symbols')]
    if os.name=='nt':
        for key in ('ProgramFiles','ProgramFiles(x86)'):
            base=os.environ.get(key)
            if base:
                for version in ('10.0','9.0','11.0'):
                    search.append(Path(base)/'KiCad'/version/'share'/'kicad'/'symbols'/f'{libname}.kicad_sym')
    for candidate in search:
        if candidate.is_file() and candidate.suffix=='.kicad_sym':return candidate.resolve()
    raise ValueError('Native symbol library '+libname+' not located; set KICAD10_SYMBOL_DIR or use explicit library_file')


def _library_symbol(root,schematic,lib_id,library_file=None):
    root=Path(root).resolve()
    schematic=Path(schematic).resolve()
    if not schematic.is_file():raise ValueError('Existing KiCad schematic required')
    sch=_load_source(schematic)
    defs=child(sch,'lib_symbols',[])
    if not library_file:
        for sym in children(defs,'symbol'):
            if len(sym)>1 and sym[1]==lib_id:
                return sym, {s[1]:s for s in children(defs,'symbol')},schematic
    if not library_file:
        library_file=_resolve_library(root,schematic,lib_id)
    if library_file:
        f=Path(library_file)
        if not f.is_absolute():f=root/f
        f=f.resolve()
        if not f.is_file() or f.suffix!='.kicad_sym' or f.is_symlink():
            raise ValueError('Explicit existing .kicad_sym library required')
        tree=_load_source(f)
        if tree[0]!='kicad_symbol_lib':raise ValueError('Not a KiCad symbol library')
        defs={s[1]:s for s in children(tree,'symbol') if len(s)>1}
        key=lib_id.split(':',1)[-1]
        if key not in defs:raise ValueError('Symbol not found in native library: '+lib_id)
        return defs[key],defs,f
    raise ValueError('Symbol '+lib_id+' absent from embedded KiCad lib_symbols; supply a .kicad_sym path before placement')


def _resolve_inheritance(symbol,defs):
    seen=set();stack=[]
    while True:
        name=symbol[1]
        if name in seen:raise ValueError('Cyclic symbol inheritance')
        seen.add(name);stack.append(symbol)
        parent=value(symbol,'extends')
        if not parent:break
        if parent not in defs:raise ValueError('Missing base symbol in inherited library: '+parent)
        symbol=defs[parent]
    return list(reversed(stack))


def symbol_geometry(root,schematic,lib_id,unit=1,style=1,library_file=None):
    """Extract native symbol primitives & pins; requires embedded or explicit lib."""
    sym,defs,source=_library_symbol(root,schematic,lib_id,library_file)
    ancestors=_resolve_inheritance(sym,defs)
    boxes=[];pins=[];fields={}
    pin_names_hidden=False;pin_numbers_hidden=False;pin_name_offset=.508
    for ancestor in ancestors:
        names_cfg=child(ancestor,'pin_names',[])
        numbers_cfg=child(ancestor,'pin_numbers',[])
        if names_cfg:
            pin_names_hidden=bool(child(names_cfg,'hide'))
            pin_name_offset=float(value(names_cfg,'offset',.508))
        if numbers_cfg:
            pin_numbers_hidden=bool(child(numbers_cfg,'hide'))
        for prop in children(ancestor,'property'):
            if len(prop)>2:fields[prop[1]]=prop
        for part in children(ancestor,'symbol'):
            if len(part)<2 or not _unit_tag(part[1],lib_id,unit,style):continue
            for g in part[2:]:
                if not isinstance(g,list) or not g:continue
                if g[0] in ('rectangle','circle','arc','polyline','bezier','text'):
                    boxes.append(_graphic_box(g))
                elif g[0]=='pin':
                    loc=_xy(g,'at');pin_angle=int(float(child(g,'at')[3]))%360
                    if pin_angle not in (0,90,180,270):raise ValueError('Non-orthogonal KiCad pin')
                    name=child(g,'name',[]);num=child(g,'number',[])
                    if not num or len(num)<2:raise ValueError('KiCad pin number missing')
                    length=_num(value(g,'length',0))
                    outward={0:(-1,0),90:(0,1),180:(1,0),270:(0,-1)}[pin_angle]
                    anchor=[loc[0],-loc[1]]
                    pins.append({'number':str(num[1]),'name':str(name[1]) if len(name)>1 else '',
                                 'xy_mm':anchor,'outward':list(outward),'electrical_type':g[1],
                                 'pin_angle_deg':pin_angle,'length_mm':length})
                    # Pin stem also occupies visible space; graphic connected end->body.
                    dr={0:(1,0),90:(0,1),180:(-1,0),270:(0,-1)}[pin_angle]
                    body_end=[loc[0]+dr[0]*length,loc[1]+dr[1]*length]
                    boxes.append(_expand(_box((loc,body_end)),0.15))
                    if len(name)>1 and str(name[1]) not in ('','~') and not pin_names_hidden:
                        effect=child(name,'effects',[])
                        if not _hidden(effect):
                            fs=_font_metrics(effect)
                            text_len=max(fs[0],len(str(name[1]))*fs[0]*1.25)+.65
                            center=(body_end[0]+dr[0]*(pin_name_offset+text_len/2),
                                    body_end[1]+dr[1]*(pin_name_offset+text_len/2))
                            boxes.append(_box(((center[0]+dx,center[1]+dy)
                               for dx,dy in ((-text_len/2,-fs[1]*.8),(text_len/2,fs[1]*.8))
                               ) if abs(dr[0]) else
                               ((center[0]+dx,center[1]+dy) for dx,dy in
                               ((-fs[1]*.8,-text_len/2),(fs[1]*.8,text_len/2))),.35))
                    if not pin_numbers_hidden and str(num[1]) not in ('','~'):
                        fs=_font_metrics(child(num,'effects',[]))
                        midpoint=((loc[0]+body_end[0])/2,(loc[1]+body_end[1])/2)
                        size=max(fs)*max(1,len(str(num[1])))*.85+.6
                        boxes.append(_expand(_box(((midpoint[0]-size,midpoint[1]-size),
                                                       (midpoint[0]+size,midpoint[1]+size))),.1))
                elif g[0] in ('unit_name','stroke','fill'):
                    continue
                else:
                    raise ValueError('Unsupported KiCad symbol graphic/pin primitive '+str(g[0]))
    if not boxes or not pins:raise ValueError('Symbol body or pins missing; cannot claim geometry available')
    # Library y-up -> local sheet y-down; bbox is axis-aligned after flip.
    b=_union(boxes);body=[b[0],-b[3],b[2],-b[1]]
    if body[0]>=body[2] or body[1]>=body[3]:raise ValueError('Invalid computed symbol dimensions')
    projected_fields=[]
    for name in ('Reference','Value'):
        prop=fields.get(name)
        if not prop:raise ValueError('Missing native symbol '+name+' field')
        at=_xy(prop,'at');eff=child(prop,'effects',[])
        angle=child(prop,'at',[])
        # Native library local field positions use Y-up; display uses Y-down.
        projected_fields.append({'name':name,'bbox_mm':_font_box(prop[2],(at[0],-at[1]),eff,-float(angle[3]) if len(angle)>3 else 0),
                                 'at_local_mm':[at[0],-at[1]], 'font_size_mm':list(_font_metrics(eff)),
                                 'angle_deg':(-float(angle[3]) if len(angle)>3 else 0),
                                 'hidden':_hidden(eff), 'text':prop[2],
                                 'confidence':'FONT_ESTIMATE_NOT_RENDER_MEASURED'})
    if not projected_fields:raise ValueError('Invisible reference/value fields need explicit layout policy')
    import hashlib
    f=Path(source);digest=hashlib.sha256(f.read_bytes()).hexdigest()
    root=Path(root).resolve()
    source_spec={'sha256':digest,'locator':'native KiCad lib symbol '+lib_id,'type':'native_kicad_symbol'}
    if f.is_relative_to(root):source_spec['file']=f.relative_to(root).as_posix()
    else:source_spec['external_file']=str(f)
    return {'lib_id':lib_id,'unit':unit,'style':style,'body_bbox_mm':_round(body),
            'pins':pins,'fields':projected_fields,'source':source_spec,
            'geometry_level':'NATIVE_PRIMITIVES_AND_PINS; CONSERVATIVE_FONT_ESTIMATE',
            'symbol_body_exact_for_supported_graphics':True,'text_render_exact':False}


def placed_instance_geometry(instance, native):
    """Read actual placed symbol origin/unit/mirror and instance field positions."""
    at=child(instance,'at')
    if not at or len(at)<3:raise ValueError('Placed symbol lacks actual (at)')
    origin=(_num(at[1]),_num(at[2]));angle=int(float(at[3]))%360 if len(at)>3 else 0
    mirror=value(instance,'mirror','')
    b=native['body_bbox_mm']
    # Native body is screen-Y-down local; convert to lib-Y-up for _world.
    body=_round(_box(_world(x,-y,origin,angle,mirror) for x,y in _corners(b)))
    props=[]
    for f in children(instance,'property'):
        if len(f)<3:continue
        eff=child(f,'effects',[])
        if _hidden(eff) or not f[2]:continue
        pt=_xy(f,'at');coord=child(f,'at',[])
        text_angle=float(coord[3]) if len(coord)>3 else 0
        props.append({'key':str(f[1]),'box':_font_box(str(f[2]),pt,eff,text_angle)})
    labels=[x['box'] for x in props]
    joined=_round(_union([body]+labels))
    pins=[]
    for p in native['pins']:
        pos=_world(p['xy_mm'][0],-p['xy_mm'][1],origin,angle,mirror)
        outward=_world(p['outward'][0],-p['outward'][1],(0.,0.),angle,mirror)
        pins.append({'number':p['number'],'at_mm':list(pos),'outward':list(outward)})
    return {'uuid':str(value(instance,'uuid')),'lib_id':native['lib_id'],'unit':native['unit'],
            'position_mm':list(origin),'rotation_deg':angle,'mirror':mirror,
            'body_bbox_mm':body,'bbox_mm':joined,'field_boxes':props,'pins':pins,
            'geometry_level':native['geometry_level']}


def _generic_box(obj):
    """Remaining native schematic entities: conservative drawing extents."""
    kind=obj[0]
    if kind in ('wire','bus','polyline'):
        pts=child(obj,'pts',[])
        coords=[(float(p[1]),float(p[2])) for p in children(pts,'xy') if len(p)>2]
        if len(coords)<2:raise ValueError('Invalid native '+kind+' coordinate points')
        return _round(_expand(_box(coords),0.15))
    if kind=='bus_entry':
        p=_xy(obj,'at');sz=_xy(obj,'size')
        return _round(_expand(_box((p,(p[0]+sz[0],p[1]+sz[1]))),0.2))
    if kind in ('label','global_label','hierarchical_label','text'):
        if len(obj)<2:raise ValueError('Missing native text')
        at=_xy(obj,'at');effects=child(obj,'effects',[])
        rot=child(obj,'at');angle=float(rot[3]) if len(rot)>3 else 0
        return _font_box(str(obj[1]),at,effects,angle)
    if kind in ('junction','no_connect'):
        p=_xy(obj,'at');return _round([p[0]-.45,p[1]-.45,p[0]+.45,p[1]+.45])
    if kind in ('sheet','text_box'):
        p=_xy(obj,'at');size=_xy(obj,'size')
        b=_expand(_box((p,(p[0]+size[0],p[1]+size[1]))),0.3)
        return _round(b)
    raise ValueError('Unsupported native schematic drawing '+kind)


def snapshot(root,top,protected_by_page):
    """Build an in-memory, hash-bound complete geometry manifest from KiCad.

    The worksheet keepout comes from the explicit project worksheet contract;
    native symbol/placement geometry is NEVER supplied manually. The caller
    must not claim font-exact visual acceptance from this conservative model.
    """
    from schematic_io import sheets
    from schematic_style import PAPER_MM, VISIBLE_KINDS
    import hashlib
    root=Path(root).resolve();trees=sheets(root,top);out={};sources={}
    for name,tree in trees.items():
        path=root/name
        paper=child(tree,'paper',[])
        dims=PAPER_MM.get(paper[1] if len(paper)>1 else None)
        if not dims:raise ValueError('Unsupported KiCad paper size for '+name)
        if 'portrait' in paper:dims=(dims[1],dims[0])
        cache=child(tree,'lib_symbols',[])
        lookup={s[1]:s for s in children(cache,'symbol') if len(s)>1}
        objects=[]
        for obj in tree:
            if not isinstance(obj,list) or not obj or obj[0] not in VISIBLE_KINDS:continue
            uid=value(obj,'uuid')
            if not uid:raise ValueError('Missing UUID for KiCad drawing '+obj[0])
            if obj[0]=='symbol':
                lib=value(obj,'lib_id')
                if not lib or lib not in lookup:raise ValueError('Missing embedded symbol geometry '+str(lib))
                unit=int(value(obj,'unit',1));style=int(value(obj,'convert',1))
                definition=symbol_geometry(root,path,lib,unit,style)
                actual=placed_instance_geometry(obj,definition)
                b=actual['bbox_mm'];sources[str(uid)]={'lib_id':lib,'pins':actual['pins']}
                collision=[actual['body_bbox_mm']]+[x['box'] for x in actual['field_boxes']]
            else:
                b=_generic_box(obj);collision=[b]
            objects.append({'uuid':str(uid),'kind':obj[0],'bbox_mm':b, 'collision_boxes_mm':collision})
        protected=protected_by_page.get(name,protected_by_page.get('*'))
        if not isinstance(protected,list) or not any(z.get('kind')=='title_block' for z in protected):
            raise ValueError('Worksheet title block protected region required for '+name)
        out[name]={'schematic_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
                   'sheet_mm':list(dims),'complete_object_inventory':True,'visible_fields_included':True,
                   'protected_regions':protected,'objects':objects,
                   'geometry_provenance':'KiCad native symbol primitives and current instance coordinates',
                   'text_precision':'CONSERVATIVE_FONT_ESTIMATE_REQUIRES_RENDER_VALIDATION'}
    return {'schema_version':1,'pages':out,'source':'kicad_native_geometry_auto','pin_inventory':sources,
            'text_render_exact':False}


def _label_bbox(text,anchor,outward):
    # A conservative upright label box extending AWAY from the symbol.
    width=max(2.,sum(1.5 if unicodedata.east_asian_width(ch) in ('W','F') else 1.1 for ch in str(text))+1.)
    height=2.75
    x,y=anchor;dx,dy=outward
    if dx<0:b=[x-width,y-height/2,x,y+height/2]
    elif dx>0:b=[x,y-height/2,x+width,y+height/2]
    elif dy<0:b=[x-width/2,y-height,x+width/2,y]
    elif dy>0:b=[x-width/2,y,x+width/2,y+height]
    else:raise ValueError('Invalid label direction')
    return _round(b)


def prospective_geometry(root,schematic,symbol,topology,pin_escape_mm):
    """For a symbol not yet on the sheet, derive geometry from native KiCad lib.

    Only ref/value and optional label KIND/net have to come from the electrical
    design. Body shape, pin positions, direction and field default origins
    originate in KiCad and are recalculated per legal candidate rotation.
    """
    lib=symbol.get('lib_id')
    if not isinstance(lib,str) or ':' not in lib:
        raise ValueError('Native pre-placement requires lib_id e.g. Device:R')
    ref=symbol['ref']; unit=int(symbol.get('unit',1));style=int(symbol.get('style',1))
    g=symbol_geometry(root,schematic,lib,unit,style,symbol.get('library_file'))
    pin_map={}
    for p in g['pins']:
        key=(ref,p['number'])
        if key not in topology:raise ValueError('Native symbol pin not in independent topology '+str(key))
        p['net']=topology[key]
        if p['number'] in pin_map:raise ValueError('Duplicate native pin number in selected symbol unit')
        pin_map[p['number']]=p
    if not pin_map:raise ValueError('Native symbol has no pin endpoints')
    fields=[]
    for f in g['fields']:
        value_text=(ref if f['name']=='Reference' else str(symbol.get('value',g['lib_id'].split(':')[-1])))
        size=f['font_size_mm']
        effects=['effects',['font',['size',*size]]]
        b=_font_box(value_text,tuple(f['at_local_mm']),effects,f['angle_deg'])
        fields.append({**f,'bbox_mm':b,'text':value_text})
    g['fields']=fields
    g['labels']=[]
    for lab in symbol.get('labels',[]):
        num=str(lab.get('pin'))
        if num not in pin_map:raise ValueError('Label references missing native pin '+num)
        p=pin_map[num]
        net=p['net'];kind=lab.get('kind')
        if kind not in ('local','hierarchical','global','power'):raise ValueError('Explicit label kind required')
        text=str(lab.get('text',net))
        if text!=net:raise ValueError('Label text must equal topology net')
        at=[round(p['xy_mm'][i]+p['outward'][i]*pin_escape_mm,5) for i in (0,1)]
        g['labels'].append({'pin':num,'kind':kind,'text':text,'net':net,
                            'anchor_local_mm':at,'bbox_mm':_label_bbox(text,at,p['outward']),
                            'geometry_level':'NATIVE_PIN_ANCHOR; CONSERVATIVE_LABEL_TEXT_ESTIMATE'})
    return g


def main():
    import argparse,json,hashlib
    from schematic_io import sheets
    p=argparse.ArgumentParser(description='Read native KiCad symbol geometry (never write a schematic)')
    p.add_argument('command',choices=('symbol','snapshot'))
    p.add_argument('project')
    p.add_argument('--schematic',required=True,help='Project-relative .kicad_sch path')
    p.add_argument('--lib-id',help='Native KiCad symbol ID for symbol command')
    p.add_argument('--unit',type=int,default=1)
    p.add_argument('--style',type=int,default=1)
    p.add_argument('--library-file',help='Existing native .kicad_sym (optional if embedded)')
    p.add_argument('--protected',help='Project-relative JSON region map required for snapshot')
    p.add_argument('--output',help='NEW report only; never overwrite project file')
    a=p.parse_args()
    root=Path(a.project).resolve()
    try:
        if not root.is_dir():raise ValueError('Project directory missing')
        sch=root/a.schematic
        if not sch.resolve().is_relative_to(root):raise ValueError('Unsafe schematic path')
        if a.command=='symbol':
            if not a.lib_id:raise ValueError('--lib-id required')
            res={'status':'NATIVE_SYMBOL_GEOMETRY_READ_ONLY',
                 'geometry':symbol_geometry(root,sch,a.lib_id,a.unit,a.style,a.library_file)}
        else:
            if not a.protected:raise ValueError('--protected required: worksheet clearance must be measured/configured once')
            f=(root/a.protected).resolve()
            if not f.is_file() or not f.is_relative_to(root):raise ValueError('Invalid region contract')
            protected=json.loads(f.read_text(encoding='utf-8-sig'))
            res={'status':'NATIVE_GEOMETRY_SNAPSHOT_READ_ONLY','manifest':snapshot(root,a.schematic,protected)}
        res['scope']='native primitives and pins, conservative font boxes; no actual KiCad edit or final visual PASS'
        res['production_authorized']=False
        if a.output:
            dest=Path(a.output).resolve()
            if dest.exists() or not dest.parent.is_dir() or (dest.is_relative_to(root) and not dest.is_relative_to(root/'03_REPORTS')):
                raise ValueError('Output must be new and inside 03_REPORTS or outside project')
            dest.write_text(json.dumps(res,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        print(json.dumps(res,ensure_ascii=False,indent=2))
        return 0
    except (ValueError,KeyError,TypeError,OSError) as exc:
        print(json.dumps({'status':'BLOCKED','reason':str(exc),'production_authorized':False}))
        return 2


if __name__=='__main__':raise SystemExit(main())
