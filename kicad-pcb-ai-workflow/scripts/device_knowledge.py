#!/usr/bin/env python3
"""Versioned device sources and grounded cards. Preview by default; no project overwrite."""
import argparse
import datetime as dt
import hashlib
import ipaddress
import json
import re
import shutil
import socket
import subprocess
import tempfile
import urllib.parse
import urllib.request
from pathlib import Path
from npi_common import sha256, finite_tree
from design_intent import local, digest

KINDS={'datasheet','errata','hardware_guide','application_note'}

def read(p):return finite_tree(json.loads(Path(p).read_text(encoding='utf-8-sig')))
def write(p,j):Path(p).write_text(json.dumps(j,ensure_ascii=False,indent=2)+'\n')
def today():return dt.date.today()
def date(s):return dt.date.fromisoformat(s)
def need(j,keys):
    if any(not isinstance(j.get(k),str) or not j[k].strip() for k in keys):raise ValueError('Required nonempty fields: '+','.join(keys))
def public_url(url,hosts):
    u=urllib.parse.urlsplit(url)
    if u.scheme!='https' or u.username or u.password or u.port not in (None,443) or u.hostname not in hosts:raise ValueError('HTTPS URL must match explicit manufacturer host allowlist')
    if not hosts or any('/' in h or '*' in h for h in hosts):raise ValueError('Use exact approved manufacturer hosts')
    for result in socket.getaddrinfo(u.hostname,443,type=socket.SOCK_STREAM):
        if not ipaddress.ip_address(result[4][0]).is_global:raise ValueError('Private/local network URLs forbidden')
    return url
class Redirect(urllib.request.HTTPRedirectHandler):
    def __init__(self,hosts):self.hosts=hosts
    def redirect_request(self,req,fp,code,msg,headers,newurl):
        public_url(newurl,self.hosts)
        return super().redirect_request(req,fp,code,msg,headers,newurl)

def acquire(meta,hosts,source=None):
    need(meta,('manufacturer','mpn','package','document_id','revision','title','source_url','kind'))
    if meta['kind'] not in KINDS:raise ValueError('Unknown document kind')
    u=urllib.parse.urlsplit(meta['source_url'])
    if u.scheme!='https' or u.hostname not in hosts or u.username or u.password:raise ValueError('Source must identify exact approved official HTTPS host')
    if source:
        p=Path(source)
        if p.suffix.lower() not in ('.pdf','.md','.txt'):raise ValueError('Supported source: PDF/md/txt')
        data=p.read_bytes();ext=p.suffix.lower();origin='local_import_not_independently_verified'
    else:
        public_url(meta['source_url'],hosts)
        opener=urllib.request.build_opener(Redirect(hosts),urllib.request.ProxyHandler({}))
        with opener.open(urllib.request.Request(meta['source_url'],headers={'User-Agent':'KiCad-device-knowledge/1'}),timeout=30) as r:
            public_url(r.url,hosts);data=r.read(32*1024*1024+1)
        ext='.pdf';origin='https_download'
    if not data or len(data)>32*1024*1024:raise ValueError('Empty or >32MiB source; use explicit offline handling')
    if ext=='.pdf' and not data.startswith(b'%PDF-'):raise ValueError('Not a PDF (possibly login/error HTML)')
    if ext!='.pdf':data.decode('utf-8-sig')
    return data,ext,origin

def extract(data,ext):
    if ext!='.pdf':return data.decode('utf-8-sig')
    tool=shutil.which('pdftotext')
    if not tool:return ''
    with tempfile.TemporaryDirectory() as d:
        src=Path(d)/'source.pdf';src.write_bytes(data)
        p=subprocess.run([tool,'-layout',str(src),'-'],capture_output=True,timeout=45)
        if p.returncode:return ''
        return p.stdout.decode('utf-8',errors='strict')

def ingest(cache,meta,hosts,source=None,apply=False):
    cache=Path(cache).resolve();data,ext,origin=acquire(meta,hosts,source)
    h=hashlib.sha256(data).hexdigest();text=extract(data,ext)
    record={**meta,'schema_version':1,'source_sha256':h,'source_file':'objects/'+h+ext,
            'text_file':'texts/'+h+'.txt','text_sha256':hashlib.sha256(text.encode()).hexdigest(),
            'acquired_on':today().isoformat(),'acquisition':origin,'approved_hosts':hosts,
            'visual_review_required':ext=='.pdf','status':'unverified_source'}
    rid=digest(record);target=cache/'records'/(rid+'.json')
    # Identity excludes timestamps: reuse same source/version/part without a duplicate record.
    identity={k:record[k] for k in ('manufacturer','mpn','package','document_id','revision','source_sha256')}
    for p in (cache/'records').glob('*.json'):
        old=read(p)
        if all(old.get(k)==v for k,v in identity.items()):
            validate_record(cache,p);return {'status':'REUSED','record':str(p),'source_sha256':h,'written':False}
    if apply:
        for name,content in ((record['source_file'],data),(record['text_file'],text.encode())):
            p=local(cache,name);p.parent.mkdir(parents=True,exist_ok=True)
            if p.exists():
                if p.read_bytes()!=content:raise ValueError('Cache object collision/corruption; do not overwrite')
            else:
                with p.open('xb') as f:f.write(content)
        target.parent.mkdir(parents=True,exist_ok=True)
        with target.open('x') as f:json.dump(record,f,ensure_ascii=False,indent=2)
    return {'status':'IMPORTED_UNVERIFIED' if apply else 'PREVIEW','record':str(target),'source_sha256':h,'written':apply,'text_available':bool(text.strip())}

def validate_record(cache,path):
    cache=Path(cache).resolve();path=Path(path).resolve()
    if not path.is_relative_to(cache):raise ValueError('Record outside cache')
    r=read(path);need(r,('manufacturer','mpn','package','revision','document_id','source_url','kind'))
    for file,h in ((r['source_file'],r['source_sha256']),(r['text_file'],r['text_sha256'])):
        p=local(cache,file)
        if not p.is_file() or sha256(p)!=h:raise ValueError('Missing/changed source cache: '+file)
    return r

def draft(cache,record,output,apply=False):
    r=validate_record(cache,record)
    card={'schema_version':1,'record':str(Path(record).resolve().relative_to(Path(cache).resolve())),
          'record_sha256':sha256(record),'identity':{k:r[k] for k in ('manufacturer','mpn','package')},
          'status':'draft','items':[],'gaps':['Agent must read full relevant text, tables, figures and errata; no automatic semantic extraction/approval'],
          'verification':None}
    if apply:
        p=Path(output)
        with p.open('x') as f:json.dump(card,f,ensure_ascii=False,indent=2)
    return {'status':'DRAFT_ONLY','written':apply,'card':card,'output':str(output)}

def validate_card(cache,path,verified=False):
    cache=Path(cache).resolve();path=Path(path).resolve();c=read(path)
    if c.get('schema_version')!=1:raise ValueError('Unknown card schema')
    rp=local(cache,c['record']);r=validate_record(cache,rp)
    if sha256(rp)!=c['record_sha256']:raise ValueError('Card bound to changed record')
    if c.get('identity')!={k:r[k] for k in ('manufacturer','mpn','package')}:raise ValueError('Card device identity mismatch')
    text=local(cache,r['text_file']).read_text();ids=[]
    for item in c.get('items',[]):
        need(item,('id','category','requirement','conditions','locator','quote','strength','verification_method'))
        if item['strength'] not in ('mandatory','recommended','typical_example'):raise ValueError('Invalid requirement strength')
        if len(item['quote'])<8 or len(item['quote'])>500 or ' '.join(item['quote'].split()) not in ' '.join(text.split()):raise ValueError('Card quote absent/too long')
        ids.append(item['id'])
    if len(ids)!=len(set(ids)):raise ValueError('Duplicate card items')
    files=[str(path.relative_to(cache)),c['record'],r['source_file'],r['text_file']]
    if verified:
        v=c.get('verification') or {}
        need(v,('reviewer','date','reason','source_identity_reason','file','sha256'))
        if c.get('status')!='verified' or not ids or c.get('gaps'):raise ValueError('Incomplete/draft card cannot supply trusted rules')
        if v.get('content_sha256')!=digest({k:c[k] for k in ('identity','record_sha256','items','gaps')}):raise ValueError('Verification predates card content')
        if date(v['date'])>today():raise ValueError('Future verification')
        ep=local(cache,v['file'])
        if not ep.is_file() or not ep.stat().st_size or sha256(ep)!=v['sha256']:raise ValueError('Missing actual card verification evidence')
        if r['visual_review_required'] and v.get('figures_checked') is not True:raise ValueError('PDF figures need actual visual review')
        files.append(v['file'])
    return c,r,files

def audit(cache,requirements):
    cache=Path(cache).resolve();q=read(requirements) if not isinstance(requirements,dict) else requirements
    if q.get('schema_version')!=1 or not q.get('devices'):raise ValueError('Explicit exact device inventory required')
    days=q.get('max_check_age_days')
    if isinstance(days,bool) or not isinstance(days,int) or not 0<=days<=365:raise ValueError('Explicit freshness policy 0..365 days required')
    findings=[];selected=[];refs=set()
    for dev in q['devices']:
        need(dev,('ref','manufacturer','mpn','package','application'))
        if dev['ref'] in refs:raise ValueError('Duplicate device ref')
        refs.add(dev['ref']);kinds=dev.get('required_kinds');badcards=set()
        if not kinds or not set(kinds).issubset(KINDS) or 'datasheet' not in kinds:raise ValueError('Explicit required document kinds including datasheet required')
        for kind in kinds:
            matches=[]
            for name in dev.get('cards',[]):
                try:
                    raw=read(local(cache,name));candidate=validate_record(cache,local(cache,raw['record']))
                    if candidate['kind']!=kind:continue
                    c,r,files=validate_card(cache,local(cache,name),True)
                    if any(r[k]!=dev[k] for k in ('manufacturer','mpn','package')) or r['kind']!=kind:continue
                    matches.append((name,c,r,files))
                except Exception as e:
                    if name not in badcards:
                        findings.append({'level':'阻断级','ref':dev['ref'],'kind':kind,'description':str(e),'suggestion':'修复资料卡或补充真实核对证据'})
                        badcards.add(name)
            if len(matches)!=1:
                findings.append({'level':'阻断级','ref':dev['ref'],'kind':kind,'description':'Missing/ambiguous verified card','suggestion':'从原厂获取匹配资料，实际阅读后核对资料卡'})
                if not dev.get('latest_checks',{}).get(kind):findings.append({'level':'阻断级','ref':dev['ref'],'kind':kind,'description':'Missing latest-version check evidence','suggestion':'核对原厂当前版本并保存真实查询依据'})
                continue
            name,c,r,files=matches[0];check=dev.get('latest_checks',{}).get(kind,{})
            try:
                need(check,('date','revision','source_sha256','file','sha256','checked_by','result'))
                age=(today()-date(check['date'])).days
                if age<0 or age>days or check['result']!='current' or check['revision']!=r['revision'] or check['source_sha256']!=r['source_sha256']:raise ValueError('Stale/new revision/unconfirmed latest check')
                ep=local(cache,check['file'])
                if not ep.is_file() or not ep.stat().st_size or sha256(ep)!=check['sha256']:raise ValueError('Latest-check evidence missing/changed')
                files.append(check['file'])
            except Exception as e:findings.append({'level':'阻断级','ref':dev['ref'],'kind':kind,'description':str(e),'suggestion':'核对原厂当前版本/勘误，保留证据；新版需差异评估，不能静默替换'})
            selected.append({'ref':dev['ref'],'application':dev['application'],'card':name,'files':files})
    for f in findings:
        f.update(location=f['ref'],reference='匹配器件原厂资料、文档版本与资料卡证据契约')
    return {'schema_version':1,'status':'BLOCKED' if findings else 'SOURCES_READY_FOR_PROJECT_REVIEW','findings':findings,'selected':selected,'production_authorized':False}

def bundle(cache,requirements,output,apply=False):
    cache=Path(cache).resolve();result=audit(cache,requirements)
    if result['findings']:return result
    out=Path(output).resolve()
    if out.exists():raise ValueError('Bundle directory must be new')
    if out==cache or cache.is_relative_to(out) or out.is_relative_to(cache):raise ValueError('Bundle must be separate from cache')
    files=sorted({n for s in result['selected'] for n in s['files']});q=read(requirements)
    candidates=[]
    for s in result['selected']:
        c=read(local(cache,s['card']))
        for item in c['items']:candidates.append({'ref':s['ref'],'application':s['application'],'card':s['card'],'item':item,'status':'CANDIDATE_REQUIRES_PROJECT_APPLICABILITY_REVIEW'})
    manifest={'schema_version':1,'requirements':q,'files_sha256':{n:sha256(local(cache,n)) for n in files},'candidates':candidates,'production_authorized':False}
    if apply:
        out.mkdir(parents=True,exist_ok=False)
        try:
            for n in files:
                p=local(out,n);p.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(local(cache,n),p)
            write(out/'device-bundle.json',manifest)
        except Exception:
            shutil.rmtree(out);raise
    return {'status':'BUNDLED' if apply else 'PREVIEW','written':apply,'manifest':manifest}

def validate_bundle(root,record):
    root=Path(root).resolve();mp=local(root,record['manifest'])
    if sha256(mp)!=record['sha256']:raise ValueError('Device bundle manifest changed')
    m=read(mp);base=mp.parent
    if m.get('schema_version')!=1 or not m.get('files_sha256'):raise ValueError('Empty/invalid device bundle')
    for n,h in m['files_sha256'].items():
        if sha256(local(base,n))!=h:raise ValueError('Changed bundled device evidence')
    result=audit(base,m['requirements'])
    if result['findings']:raise ValueError('Device source readiness blocked: '+json.dumps(result['findings'],ensure_ascii=False))
    expected={n for s in result['selected'] for n in s['files']}
    if not expected.issubset(m['files_sha256']):raise ValueError('Bundle misses required evidence')
    return [str(mp.relative_to(root))]+[str(local(base,n).relative_to(root)) for n in sorted(expected)]

def validate_project_binding(root,config,stage,graph):
    record=config['device_knowledge'];root=Path(root).resolve();mp=local(root,record['manifest']);m=read(mp)
    devices=m['requirements']['devices'];required=record.get('required_refs')
    if not required or len(required)!=len(set(required)) or set(required)!={d['ref'] for d in devices}:raise ValueError('Explicit core-device inventory differs from bundled sources')
    fields=record.get('identity_fields',{'manufacturer':'Manufacturer','mpn':'MPN','package':'Package'})
    docmap={d['sha256']:d['id'] for d in config['documents']}
    for dev in devices:
        part=graph['components'].get(dev['ref'])
        if not part or any(part.get('fields',{}).get(fields[k])!=dev[k] for k in ('manufacturer','mpn','package')):raise ValueError('Core device exact MPN/manufacturer/package differs from source: '+dev['ref'])
        linked=config['stages'][stage]['component_sources'].get(dev['ref'],[])
        for name in dev['cards']:
            c,r,_=validate_card(mp.parent,local(mp.parent,name),True)
            docid=docmap.get(r['source_sha256'])
            if not docid or docid not in linked:raise ValueError('Original device source must be linked as review document, not only its summary')
    return True

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--cache',required=True);sub=p.add_subparsers(dest='cmd',required=True)
    a=sub.add_parser('ingest');a.add_argument('--metadata',required=True);a.add_argument('--official-host',action='append',required=True);a.add_argument('--source');a.add_argument('--apply',action='store_true')
    a=sub.add_parser('draft');a.add_argument('--record',required=True);a.add_argument('--output',required=True);a.add_argument('--apply',action='store_true')
    a=sub.add_parser('check-card');a.add_argument('--card',required=True)
    for cmd in ('audit','bundle'):
        a=sub.add_parser(cmd);a.add_argument('--requirements',required=True)
        if cmd=='bundle':a.add_argument('--output',required=True);a.add_argument('--apply',action='store_true')
    a=p.parse_args()
    try:
        if a.cmd=='ingest':r=ingest(a.cache,read(a.metadata),a.official_host,a.source,a.apply)
        elif a.cmd=='draft':r=draft(a.cache,a.record,a.output,a.apply)
        elif a.cmd=='check-card':
            c,_,_=validate_card(a.cache,a.card,False);r={'status':'STRUCTURE_VALID','card_status':c['status'],'trusted':False}
        elif a.cmd=='audit':r=audit(a.cache,a.requirements)
        else:r=bundle(a.cache,a.requirements,a.output,a.apply)
        print(json.dumps(r,ensure_ascii=False,indent=2));return 2 if r.get('status')=='BLOCKED' else 0
    except Exception as e:print(json.dumps({'status':'BLOCKED','reason':str(e)},ensure_ascii=False));return 2
if __name__=='__main__':raise SystemExit(main())
