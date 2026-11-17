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
def write(p,j):Path(p).write_text(json.dumps(j,ensure_ascii=False,indent=2)+'\n', encoding='utf-8')
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
    text=local(cache,r['text_file']).read_text(encoding='utf-8-sig');ids=[]
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
    return [mp.relative_to(root).as_posix()]+[local(base,n).relative_to(root).as_posix() for n in sorted(expected)]


def project_review_cache(root, binding, max_items_per_device=12):
    """Project-frozen, offline G1/PCB review index; never queries shared cache or web.

    Source text mapping is produced only for original byte-identical, verified
    documents. Brief entries are candidate evidence, not design approvals.
    """
    if max_items_per_device is not None and (isinstance(max_items_per_device,bool) or not isinstance(max_items_per_device,int) or not 1<=max_items_per_device<=30):
        raise ValueError('Review brief item limit must be 1..30')
    root=Path(root).resolve()
    validate_bundle(root,binding) # verify manifest, every included file, card, and version check
    mp=local(root,binding['manifest'])
    base=mp.parent
    manifest=read(mp)
    requirements=manifest['requirements']
    source_texts={}
    devices=[]
    for dev in requirements['devices']:
        entries=[];sources=[]
        for name in dev['cards']:
            card,record,_=validate_card(base,local(base,name),True)
            if any(record[k]!=dev[k] for k in ('manufacturer','mpn','package')):
                raise ValueError('Review card identity differs from device: '+dev['ref'])
            source_file=local(base,record['source_file'])
            text_file=local(base,record['text_file'])
            if sha256(source_file)!=record['source_sha256'] or sha256(text_file)!=record['text_sha256']:
                raise ValueError('Cached original/text changed for '+dev['ref'])
            previous=source_texts.get(record['source_sha256'])
            if previous is not None and previous!=text_file:
                # Identical original bytes must have one unambiguous extracted text.
                if previous.read_bytes()!=text_file.read_bytes():
                    raise ValueError('Conflicting cached text for identical source')
            source_texts[record['source_sha256']]=text_file
            sources.append({'kind':record['kind'],'document_id':record['document_id'],
                            'revision':record['revision'],'source_sha256':record['source_sha256'],
                            'original_file':(mp.parent/record['source_file']).relative_to(root).as_posix(),
                            'card_file':(mp.parent/name).relative_to(root).as_posix()})
            for item in card['items']:
                entries.append({'item_id':item['id'],'category':item['category'],
                    'kind':record['kind'],'document_id':record['document_id'],
                    'revision':record['revision'],'source_sha256':record['source_sha256'],
                    'requirement':item['requirement'],'conditions':item['conditions'],
                    'strength':item['strength'],'locator':item['locator'],
                    'quote':item['quote'],'verification_method':item['verification_method']})
        devices.append({'ref':dev['ref'],'manufacturer':dev['manufacturer'],
                        'mpn':dev['mpn'],'package':dev['package'],
                        'application':dev['application'],'required_kinds':dev['required_kinds'],
                        'sources':sources,'item_count':len(entries),
                        'shown_count':min(len(entries),max_items_per_device) if max_items_per_device is not None else len(entries),
                        'truncated':len(entries)>max_items_per_device if max_items_per_device is not None else False,
                        'items':entries[:max_items_per_device] if max_items_per_device is not None else entries,
                        'review_status':'CANDIDATES_REQUIRING_CURRENT_PROJECT_APPLICABILITY'})
    brief={'schema_version':1,'stage':'schematic','status':'VERIFIED_CACHED_CARDS_NOT_DESIGN_APPROVAL',
           'source':'project_frozen_device_bundle','bundle_manifest':binding['manifest'],
           'bundle_sha256':binding['sha256'],'devices':devices,'offline':True,
           'downloaded':False,'production_authorized':False,
           'instruction':'Use these verified card items first; selectively open cached original text/figures only for missing details, figures, conflicting or safety-critical conditions. Every G1 task still requires current project-specific assessment and original document citations.'}
    return brief,source_texts


# Each stage sees just the manufacturer evidence relevant to its engineering task.
# The categories are intentionally explicit: unknown categories never silently
# become mandatory pinout or PCB evidence. Gaps are reported, not invented.
STAGE_CARD_CATEGORIES = {
    'g2': frozenset(('footprint_pinmap_variants','pinout','pin_map','pin_mapping',
                     'land_pattern','footprint','package','thermal_pad','polarity',
                     'symbol','mechanical_manufacturing')),
    'g3': frozenset(('decoupling','clock','rf_antenna','power_return_loops',
                     'critical_signal_paths','source_layouts','placement','layout',
                     'power_domains','mechanical_manufacturing','thermal')),
    'g4': frozenset(('stackup_reference_planes','critical_signal_paths',
                     'power_return_loops','decoupling','clock','rf_antenna',
                     'pads_vias_fanout','mechanical_manufacturing','layout',
                     'placement','protection','interfaces','power_domains',
                     'footprint_pinmap_variants','thermal')),
}

def project_stage_brief(root, binding, stage, max_items_per_device=12):
    """Revalidate frozen source/cards and return compact *candidate* facts for G2/G3/G4.

    No search, download, extraction or design verdict. Stages are not allowed to
    interpret absent relevant card categories as approved design requirements.
    """
    if stage not in STAGE_CARD_CATEGORIES:
        raise ValueError('Stage must be g2/g3/g4')
    raw,texts = project_review_cache(root, binding, max_items_per_device=None)
    allowed=STAGE_CARD_CATEGORIES[stage]
    gaps=[];devices=[]
    for dev in raw['devices']:
        matching=[x for x in dev['items'] if str(x['category']).strip().lower() in allowed]
        if not matching:
            gaps.append({'ref':dev['ref'],'reason':'No verified stage-relevant card items',
                         'required_categories':sorted(allowed),
                         'action':'Return to node 3 to verify the relevant original sections; no automatic PASS'})
        devices.append({**{k:dev[k] for k in ('ref','manufacturer','mpn','package','application','sources')},
                        'total_stage_items':len(matching),
                        'shown_count':min(len(matching),max_items_per_device),
                        'truncated':len(matching)>max_items_per_device,
                        'items':matching[:max_items_per_device],
                        'stage_review_status':'PROJECT_SPECIFIC_VERIFICATION_REQUIRED'})
    result={'schema_version':1,'stage':stage,
            'status':'STAGE_CARD_COVERAGE_INCOMPLETE' if gaps else 'VERIFIED_FROZEN_STAGE_CARDS_NOT_DESIGN_APPROVAL',
            'source':'project_frozen_device_bundle','bundle_manifest':binding['manifest'],
            'bundle_sha256':binding['sha256'], 'offline':True, 'downloaded':False,
            'devices':devices,'coverage_gaps':gaps, 'production_authorized':False,
            'instruction':'Read relevant verified items first; check current symbol/pad or actual PCB against the project and native KiCad. Missing items require targeted source review at node 3, never automatic approval.'}
    return result,texts

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


# Cache-first device knowledge reuse. The immutable registry stores vetted links,
# never an unverified model-generated summary and never an online freshness claim.
def _validated_check(cache, check, record, days):
    need(check, ('date','revision','source_sha256','file','sha256','checked_by','result'))
    age=(today()-date(check['date'])).days
    if age<0 or age>days or check['result']!='current':
        raise ValueError('Latest-version evidence expired or is not current')
    if check['revision']!=record['revision'] or check['source_sha256']!=record['source_sha256']:
        raise ValueError('Latest-check revision/source differs from cached card')
    ep=local(cache,check['file'])
    if not ep.is_file() or not ep.stat().st_size or sha256(ep)!=check['sha256']:
        raise ValueError('Latest-check evidence missing or changed')
    return age


def register(cache, requirements, apply=False):
    """Promote an already audited project source selection to an immutable shared registry."""
    cache=Path(cache).resolve();q=read(requirements)
    verified=audit(cache,q)
    if verified['findings']:
        return {'status':'BLOCKED','findings':verified['findings'],'registered':0,'production_authorized':False}
    registrations=[]
    for dev in q['devices']:
        for kind in dev['required_kinds']:
            matched=[]
            for name in dev['cards']:
                c,r,_=validate_card(cache,local(cache,name),True)
                if r['kind']==kind and all(r[k]==dev[k] for k in ('manufacturer','mpn','package')):
                    matched.append((name,r))
            if len(matched)!=1:
                raise ValueError('Cannot register an ambiguous card for '+dev['ref']+'/'+kind)
            name,r=matched[0]
            check=dev['latest_checks'][kind]
            _validated_check(cache,check,r,q['max_check_age_days'])
            entry={'schema_version':1,'identity':{k:dev[k] for k in ('manufacturer','mpn','package')},
                   'kind':kind,'card':name,'card_sha256':sha256(local(cache,name)),
                   'latest_check':check}
            relative='registry/'+digest(entry)+'.json'
            registrations.append((relative,entry))
    unique={name:entry for name,entry in registrations}
    if apply:
        (cache/'registry').mkdir(parents=True,exist_ok=True)
        for name,entry in sorted(unique.items()):
            target=local(cache,name)
            if target.exists():
                if read(target)!=entry:
                    raise ValueError('Registry collision/corruption; no overwrite')
            else:
                with target.open('x',encoding='utf-8') as f:
                    json.dump(entry,f,ensure_ascii=False,indent=2)
    return {'status':'REGISTERED' if apply else 'PREVIEW','registered':len(unique),
            'registry_files':sorted(unique),'written':apply,'production_authorized':False,
            'note':'Only previously verified cards and actual current-version evidence are registered.'}


def _find_cached(cache, identity, kind, days):
    registry=Path(cache)/'registry';matches=[];invalid=[]
    for path in sorted(registry.glob('*.json')):
        # Never trust a registry entry merely because it exists on disk.
        try:
            raw=read(path)
        except (OSError,ValueError,TypeError) as e:
            invalid.append('Unreadable registry entry '+path.name+': '+str(e))
            continue
        if raw.get('identity')!=identity or raw.get('kind')!=kind:
            continue
        try:
            if raw.get('schema_version')!=1 or path.name!=digest({k:raw[k] for k in ('schema_version','identity','kind','card','card_sha256','latest_check')})+'.json':
                raise ValueError('Registry integrity/key mismatch')
            card_path=local(cache,raw['card'])
            if sha256(card_path)!=raw['card_sha256']:
                raise ValueError('Card content changed after registration')
            card,record,_=validate_card(cache,card_path,True)
            if record['kind']!=kind or {k:record[k] for k in identity}!=identity:
                raise ValueError('Registered record identity or kind changed')
            check=raw['latest_check']
            _validated_check(cache,check,record,10**9)
            matches.append((raw,card,record))
        except Exception as e:
            invalid.append(path.name+': '+str(e))
    if invalid:
        return {'status':'INVALID_CACHE_ENTRY','reason':'; '.join(invalid[:3])}
    if not matches:
        return {'status':'MISS','reason':'No registered, verified exact MPN/package card'}
    matches.sort(key=lambda row:row[0]['latest_check']['date'],reverse=True)
    newest=matches[0][0]['latest_check']['date']
    same=[m for m in matches if m[0]['latest_check']['date']==newest]
    # Distinct source/card on one most-recent check date requires manual arbitration.
    signatures={(m[2]['source_sha256'],m[0]['card_sha256']) for m in same}
    if len(signatures)>1:
        return {'status':'AMBIGUOUS','reason':'Multiple distinct latest cards/revisions for exact identity'}
    row=matches[0];check=row[0]['latest_check']
    age=(today()-date(check['date'])).days
    if age>days:
        return {'status':'STALE','reason':'Latest official-version check exceeds project freshness policy',
                'days_old':age,'revision':row[2]['revision'],
                'card':row[0]['card']}
    return {'status':'HIT','card':row[0]['card'],'latest_check':check,
            'revision':row[2]['revision'],'source_sha256':row[2]['source_sha256'],
            'item_count':len(row[1]['items']),'days_old':age,
            'record':row[1]['record']}


def resolve(cache, requirements, output=None, apply=False):
    """Resolve exact device inventory against vetted offline catalog before ANY web search.

    Does not update timestamps, download PDFs, or approve circuit applicability.
    """
    cache=Path(cache).resolve();q=read(requirements)
    if q.get('schema_version')!=1 or not isinstance(q.get('devices'),list) or not q['devices']:
        raise ValueError('Explicit device inventory required')
    days=q.get('max_check_age_days')
    if isinstance(days,bool) or not isinstance(days,int) or not 0<=days<=365:
        raise ValueError('Explicit freshness policy 0..365 days required')
    if apply and not output:
        raise ValueError('--apply requires explicit --output for NEW requirements file')
    report=[];result={**q,'devices':[]};used_refs=set();all_hit=True
    for dev in q['devices']:
        need(dev,('ref','manufacturer','mpn','package','application'))
        if dev['ref'] in used_refs:raise ValueError('Duplicate component reference')
        used_refs.add(dev['ref'])
        kinds=dev.get('required_kinds')
        if not isinstance(kinds,list) or not kinds or len(kinds)!=len(set(kinds)) or not set(kinds).issubset(KINDS) or 'datasheet' not in kinds:
            raise ValueError('Explicit unique required kinds including datasheet required')
        if dev.get('cards') or any(dev.get('latest_checks',{}).values()):
            raise ValueError('resolve expects NEW project inventory with empty cards/latest_checks; existing selections use audit')
        identity={k:dev[k] for k in ('manufacturer','mpn','package')}
        cards=[];checks={}
        for kind in kinds:
            hit=_find_cached(cache,identity,kind,days)
            report.append({'ref':dev['ref'],'identity':identity,'kind':kind,**hit})
            if hit['status']=='HIT':
                cards.append(hit['card']);checks[kind]=hit['latest_check']
            else:
                all_hit=False
        result['devices'].append({**dev,'cards':cards,'latest_checks':checks})
    status='CACHE_HIT_READY_FOR_AUDIT' if all_hit else 'CACHE_INCOMPLETE_SOURCE_REVIEW_REQUIRED'
    if all_hit:
        # Re-run all original gates, not a bypass around existing verification.
        review=audit(cache,result)
        if review['findings']:
            status='BLOCKED';all_hit=False
            report.append({'status':'AUDIT_BLOCKED','findings':review['findings']})
    if all_hit and apply:
        dest=Path(output).resolve()
        if dest.exists() or not dest.parent.is_dir():
            raise ValueError('Output must be NEW and parent directory must exist')
        with dest.open('x',encoding='utf-8') as f:
            json.dump(result,f,ensure_ascii=False,indent=2)
            f.write('\n')
    return {'status':status,'entries':report,
            'resolved_requirements':str(Path(output).resolve()) if all_hit and apply else None,
            'written':bool(all_hit and apply),'offline':True,'downloaded':False,
            'production_authorized':False,
            'next_step':('audit then bundle, review per-project application conditions' if all_hit
                         else 'Acquire/verify only MISS or STALE kinds, then register and resolve again')}


def brief(cache, requirements, ref, category=None, limit=12):
    """Small, cited card excerpts for an AI; original PDFs remain on disk."""
    cache=Path(cache).resolve();q=read(requirements)
    status=audit(cache,q)
    if status['findings']:
        return {'status':'BLOCKED','findings':status['findings']}
    selected=[s for s in status['selected'] if s['ref']==ref]
    if not selected:raise ValueError('Exact reference absent from resolved inventory')
    if limit<1 or limit>30:raise ValueError('Brief limit must be 1..30')
    items=[]
    for s in selected:
        card,record,_=validate_card(cache,local(cache,s['card']),True)
        for item in card['items']:
            if category and item['category']!=category:continue
            items.append({'kind':record['kind'],'document_id':record['document_id'],
                         'revision':record['revision'],'source_sha256':record['source_sha256'],
                         'locator':item['locator'],'item_id':item['id'],
                         'requirement':item['requirement'],'conditions':item['conditions'],
                         'strength':item['strength'],'quote':item['quote'],
                         'verification_method':item['verification_method']})
    return {'status':'VERIFIED_CACHED_BRIEF_REQUIRES_PROJECT_APPLICABILITY_REVIEW',
            'ref':ref,'application':next(d['application'] for d in q['devices'] if d['ref']==ref),
            'total_matching':len(items),'items':items[:limit],
            'truncated':len(items)>limit,'downloaded':False,'production_authorized':False}


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--cache',required=True);sub=p.add_subparsers(dest='cmd',required=True)
    a=sub.add_parser('ingest');a.add_argument('--metadata',required=True);a.add_argument('--official-host',action='append',required=True);a.add_argument('--source');a.add_argument('--apply',action='store_true')
    a=sub.add_parser('draft');a.add_argument('--record',required=True);a.add_argument('--output',required=True);a.add_argument('--apply',action='store_true')
    a=sub.add_parser('check-card');a.add_argument('--card',required=True)
    a=sub.add_parser('register');a.add_argument('--requirements',required=True);a.add_argument('--apply',action='store_true')
    a=sub.add_parser('resolve');a.add_argument('--requirements',required=True);a.add_argument('--output');a.add_argument('--apply',action='store_true')
    a=sub.add_parser('brief');a.add_argument('--requirements',required=True);a.add_argument('--ref',required=True);a.add_argument('--category');a.add_argument('--limit',type=int,default=12)
    for cmd in ('audit','bundle'):
        a=sub.add_parser(cmd);a.add_argument('--requirements',required=True)
        if cmd=='bundle':a.add_argument('--output',required=True);a.add_argument('--apply',action='store_true')
    a=p.parse_args()
    try:
        if a.cmd=='ingest':r=ingest(a.cache,read(a.metadata),a.official_host,a.source,a.apply)
        elif a.cmd=='draft':r=draft(a.cache,a.record,a.output,a.apply)
        elif a.cmd=='check-card':
            c,_,_=validate_card(a.cache,a.card,False);r={'status':'STRUCTURE_VALID','card_status':c['status'],'trusted':False}
        elif a.cmd=='register':r=register(a.cache,a.requirements,a.apply)
        elif a.cmd=='resolve':r=resolve(a.cache,a.requirements,a.output,a.apply)
        elif a.cmd=='brief':r=brief(a.cache,a.requirements,a.ref,a.category,a.limit)
        elif a.cmd=='audit':r=audit(a.cache,a.requirements)
        else:r=bundle(a.cache,a.requirements,a.output,a.apply)
        print(json.dumps(r,ensure_ascii=False,indent=2));return 2 if r.get('status') in ('BLOCKED','CACHE_INCOMPLETE_SOURCE_REVIEW_REQUIRED') else 0
    except Exception as e:print(json.dumps({'status':'BLOCKED','reason':str(e)},ensure_ascii=False));return 2
if __name__ == '__main__':
    # JSON/text CLI protocol is UTF-8 on every platform, including Windows.
    import sys as _stdio_sys
    for _stdio_stream in (_stdio_sys.stdout, _stdio_sys.stderr):
        if hasattr(_stdio_stream, 'reconfigure'):
            _stdio_stream.reconfigure(encoding='utf-8')


if __name__=='__main__':raise SystemExit(main())
