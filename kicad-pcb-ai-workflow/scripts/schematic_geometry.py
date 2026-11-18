"""Source-bound KiCad schematic geometry evidence for pre-placement.

Two modes: historic externally measured manifest, and native-auto where symbol
primitives, pin geometry and placed objects are decoded directly from KiCad
S-expressions. Native font outlines/worksheet keepouts require separate review.
"""
import hashlib
import json
import math
from pathlib import Path
from npi_common import children, value
from schematic_io import sheets
from schematic_style import PAPER_MM, VISIBLE_KINDS


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def bounded(root, path):
    if not isinstance(path, str) or not path or '\\' in path or Path(path).is_absolute() or '..' in Path(path).parts:
        raise ValueError('Use a project-relative POSIX path')
    root = Path(root).resolve()
    p = root / path
    if p.is_symlink() or not p.resolve().is_relative_to(root) or not p.is_file():
        raise ValueError('Missing or unsafe project file: ' + path)
    return p.resolve()


def rect(v):
    if (not isinstance(v, list) or len(v) != 4 or
            any(isinstance(x, bool) or not isinstance(x, (float, int)) or not math.isfinite(x) for x in v) or
            v[0] >= v[2] or v[1] >= v[3]):
        raise ValueError('Expected finite bounding rectangle [left,top,right,bottom]')
    return tuple(float(x) for x in v)


def intersects(a, b, gap=0):
    return min(a[2], b[2]) - max(a[0], b[0]) > -gap + 1e-7 and min(a[3], b[3]) - max(a[1], b[1]) > -gap + 1e-7


def inside(r, page):
    return 0 <= r[0] < r[2] <= page[0] and 0 <= r[1] < r[3] <= page[1]


def evidence(root, request):
    """Verify all page UUIDs, file/view SHA bindings, and full declared bounds."""
    root = Path(root).resolve()
    top = request.get('schematic')
    sch = bounded(root, top)
    if sha(sch) != request.get('schematic_sha256'):
        raise ValueError('Schematic changed: recapture geometry before pre-placement')
    native_mode=request.get('geometry_mode')=='native_auto'
    if native_mode:
        from schematic_native_geometry import snapshot
        regions=request.get('protected_regions_by_page')
        if not isinstance(regions,dict):
            raise ValueError('Native extraction needs one project worksheet title-block region contract')
        data=snapshot(root,top,regions)
        g=view=None
    else:
        g = bounded(root, request.get('geometry_manifest'))
        if sha(g) != request.get('geometry_sha256'):
            raise ValueError('Geometry manifest changed')
        view = bounded(root, request.get('render_file'))
        if not view.stat().st_size or sha(view) != request.get('render_sha256'):
            raise ValueError('Rendered view evidence changed')
        data = json.loads(g.read_text(encoding='utf-8-sig'))
    trees = sheets(root, top)
    pages = data.get('pages')
    if data.get('schema_version') != 1 or not isinstance(pages, dict) or set(pages) != set(trees):
        raise ValueError('Geometry must cover all reachable KiCad schematic sheets')
    normalized = {}
    for name, tree in trees.items():
        src = bounded(root, name)
        p = pages[name]
        if p.get('schematic_sha256') != sha(src):
            raise ValueError('Stale geometry for sheet ' + name)
        paper = next((c for c in tree if isinstance(c, list) and c and c[0] == 'paper'), [])
        dims = PAPER_MM.get(paper[1] if len(paper) > 1 else None)
        if dims is None:
            raise ValueError('Unknown paper dimensions; no automatic geometry pass')
        if 'portrait' in paper:
            dims = (dims[1], dims[0])
        if len(p.get('sheet_mm', [])) != 2 or any(abs(float(x)-y) > 0.05 for x,y in zip(p['sheet_mm'], dims)):
            raise ValueError('Sheet dimension mismatch: ' + name)
        if p.get('complete_object_inventory') is not True or p.get('visible_fields_included') is not True:
            raise ValueError('Cannot place without complete measured symbol and visible-field bounds')
        expected = {str(value(obj,'uuid')) for k in VISIBLE_KINDS for obj in children(tree, k) if value(obj,'uuid')}
        objects = p.get('objects')
        if not isinstance(objects, list) or len({o.get('uuid') for o in objects}) != len(objects) or {o.get('uuid') for o in objects} != expected:
            raise ValueError('Geometry object UUID inventory is incomplete or duplicated')
        protected = p.get('protected_regions', [])
        if not any(isinstance(o, dict) and o.get('kind') == 'title_block' for o in protected):
            raise ValueError('Verified title-block keep-out is mandatory')
        obstacles = []
        for o in protected:
            box = rect(o['bbox_mm'])
            if not inside(box,dims):
                raise ValueError('Invalid protected region dimensions')
            obstacles.append(('protected:'+str(o['id']),box))
        for o in objects:
            box = rect(o['bbox_mm'])
            if not inside(box,dims):
                raise ValueError('Existing object extends outside sheet: '+str(o['uuid']))
            # The bounding rectangle of a functional frame encloses its content.
            # Treat frame edges separately rather than forbidding its interior.
            if o.get('kind') != 'polyline':
                for index,part in enumerate(o.get('collision_boxes_mm',[list(box)])):
                    obstacles.append((str(o['uuid'])+':'+str(index),rect(part)))
        normalized[name] = {'dims': dims, 'obstacles': obstacles, 'existing_uuids': expected}
    page = request.get('page')
    if page not in normalized:
        raise ValueError('Target page is not in the verified schematic hierarchy')
    used=[sch] if native_mode else [sch,g,view]
    import hashlib
    native_hash=hashlib.sha256(json.dumps(data,sort_keys=True,ensure_ascii=True).encode()).hexdigest() if native_mode else sha(g)
    return {'page': normalized[page], 'geometry_sha256':native_hash, 'files_sha256': {str(p.relative_to(root)): sha(p) for p in used},
            'all_sheet_sha256': {name: sha(bounded(root,name)) for name in trees},
            'evidence_level': ('NATIVE_PRIMITIVES_AUTO; CONSERVATIVE_TEXT_REQUIRES_RENDER_VERIFICATION'
                               if native_mode else 'DECLARED_SOURCE_BOUND_GEOMETRY_REQUIRES_RENDER_VERIFICATION')}
