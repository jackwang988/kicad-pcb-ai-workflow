"""Strict whitespace-independent schematic reading. No native validity claim."""
import json
import re
from pathlib import Path
from engineering_gate import local
from npi_common import children, value, child, sha256

def parse(text):
    tokens=[];i=0
    while i<len(text):
        if text[i].isspace():i+=1;continue
        if text[i] in '()':tokens.append(text[i]);i+=1;continue
        if text[i]=='"':
            start=i;i+=1
            while i<len(text):
                if text[i]=='\\':i+=2;continue
                if text[i]=='"':break
                i+=1
            if i>=len(text):raise ValueError('Unterminated quoted string')
            tokens.append(('string',json.loads(text[start:i+1])));i+=1;continue
        m=re.match(r'[^\s()"]+',text[i:])
        if not m:raise ValueError('Invalid schematic token')
        tokens.append(('atom',m.group()));i+=len(m.group())
    stack=[];root=[];current=root
    for t in tokens:
        if t=='(':
            new=[];current.append(new);stack.append(current);current=new
        elif t==')':
            if not stack:raise ValueError('Unbalanced schematic')
            current=stack.pop()
        else:current.append(t[1])
    if stack or len(root)!=1 or not isinstance(root[0],list):raise ValueError('Invalid schematic root')
    return root[0]

def sheets(root,top):
    """Return all reachable files; reject cycles, missing files and path escapes."""
    root=Path(root).resolve();result={};active=set()
    def walk(name):
        p=local(root,name);rel=p.relative_to(root).as_posix()
        if rel in active:raise ValueError('Cyclic sheet hierarchy: '+rel)
        if rel in result:return
        if p.suffix!='.kicad_sch':raise ValueError('Wrong sheet suffix')
        tree=parse(p.read_text(encoding='utf-8-sig'))
        if not tree or tree[0]!='kicad_sch':raise ValueError('Not a schematic: '+rel)
        result[rel]=tree;active.add(rel)
        for sheet in children(tree,'sheet'):
            props={p[1]:p[2] for p in children(sheet,'property') if len(p)>2}
            filename=props.get('Sheetfile') or props.get('Sheet file')
            if not filename or '${' in filename:raise ValueError('Unresolved sheet filename: '+rel)
            walk(str((p.parent/filename).relative_to(root)))
        active.remove(rel)
    walk(top)
    return result

def hashes(root,names):
    return {n:sha256(local(Path(root).resolve(),n)) for n in names}


def blocking(code,description,location='工程级'):
    return {'rule':code,'level':'阻断级','location':location,'description':str(description),'reference':'KiCad10.0.7 actual file/CLI semantics and explicit project contract','suggestion':'补齐真实输入/执行能力或修复该问题后重跑；不得补写批准或降低规则绕过。'}
