"""Política de sincronización inteligente.

Objetivo: no volver a descargar y reinterpretar todos los horarios en cada arranque.
- Arranques repetidos dentro del intervalo corto: 0 peticiones de red.
- Después: sólo se consultan páginas/manifiestos ligeros de control.
- Si su firma semántica no cambia: se reutiliza el snapshot verificado.
- Si cambia un operador: sólo se resincroniza ese operador.
- Una vez al día se hace una comprobación profunda de seguridad para detectar
  cambios de horario publicados bajo la misma URL/estructura.
"""
from __future__ import annotations
from pathlib import Path
from datetime import datetime, timezone, timedelta
from urllib.parse import urlparse
import hashlib, json, re
from bs4 import BeautifulSoup
from net import Client, atomic_json
from domain import clean, norm

ALL_OPERATORS=('TMSA','TORRES','FORNELLS')
def now_utc(): return datetime.now(timezone.utc)
def parse_time(value):
    if not value:return None
    try:
        d=datetime.fromisoformat(str(value).replace('Z','+00:00'));return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except Exception:return None
def policy(config):
    p=config.get('SMART_SYNC',{}) if isinstance(config,dict) else {}
    return {'quick_check_minutes':int(p.get('quick_check_minutes',240)),'full_refresh_hours':int(p.get('full_refresh_hours',24)),'locations_refresh_hours':int(p.get('locations_refresh_hours',168))}
def state_path(data_dir):return Path(data_dir)/'sync_state.json'
def load_state(data_dir):
    try:
        raw=json.loads(state_path(data_dir).read_text('utf-8'));return raw if isinstance(raw,dict) else {}
    except Exception:return {}
def save_state(data_dir,state):atomic_json(state_path(data_dir),state)
def watch_urls(code,cfg):
    urls=[]
    def add(key):
        u=cfg.get(key)
        if u and u not in urls:urls.append(u)
    add('index')
    if code=='TORRES':add('catalog_page')
    add('fare_page');return urls
def _hash(value):return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode('utf-8')).hexdigest()
def _api_signature(raw):
    obj=json.loads(raw.decode('utf-8-sig'))
    if not isinstance(obj,dict):return _hash(obj)
    rows=[]
    for line in obj.get('data',[]) if isinstance(obj.get('data'),list) else []:
        schedules=[]
        for s in line.get('schedules',[]) if isinstance(line,dict) else []:schedules.append({k:s.get(k) for k in ('code','line','route_id','title','valid_from','valid_until','service_days','stop_count','departure_count','sha256')})
        rows.append({'code':line.get('code'),'schedules':schedules})
    if rows:return _hash({'source_updated_at':obj.get('source_updated_at'),'rows':rows})
    return _hash(obj)
def _html_signature(code,url,raw):
    soup=BeautifulSoup(raw,'html.parser')
    for x in soup(['script','style','noscript','template']):x.decompose()
    path=urlparse(url).path.lower();items=[]
    if code=='TMSA' and 'transporte-regular' in path:
        for h in soup.find_all(['h1','h2','h3','h4']):
            t=clean(h.get_text(' ',strip=True))
            if t:items.append(('h',norm(t)))
        for a in soup.find_all('a',href=True):
            if re.search(r'/linea/\d+',a['href']):items.append(('line',re.search(r'/linea/(\d+)',a['href']).group(1),norm(a.get_text(' ',strip=True))))
    elif code=='TORRES' and 'horarios' in path and 'informacion' not in path:
        for a in soup.find_all('a',href=True):
            t=clean(a.get_text(' ',strip=True))
            if re.match(r'^(L\d{2}|NATI)\b',t,re.I):items.append(('line',norm(t),a['href']))
    elif 'tarif' in path:
        for tr in soup.find_all('tr'):
            cells=[clean(c.get_text(' ',strip=True)) for c in tr.find_all(['th','td'])]
            if cells:items.append(tuple(norm(c) for c in cells))
        if not items:
            for t in soup.stripped_strings:
                s=clean(t)
                if '€' in s or re.match(r'^L\d+',s,re.I):items.append(norm(s))
    elif code=='FORNELLS':
        for h in soup.find_all(['h1','h2','h3','h4']):
            t=clean(h.get_text(' ',strip=True))
            if re.match(r'^L\d+',t,re.I):items.append(('h',norm(t)))
        for a in soup.find_all('a',href=True):
            t=norm(a.get_text(' ',strip=True));href=a['href']
            if '/horarios/' in href or 'horario general' in t or 'horari general' in t:items.append(('r',t,href))
    else:items=[norm(s) for s in soup.stripped_strings if clean(s)]
    return _hash(items)
def signature(code,url,raw,content_type=''):
    c=(content_type or '').lower()
    if 'json' in c or (urlparse(url).path.endswith('/api/horarios') and raw.lstrip().startswith(b'{')):
        try:return _api_signature(raw)
        except Exception:pass
    return _html_signature(code,url,raw)
def _cache_file(rawdir,code,url):
    k=hashlib.sha256(url.encode()).hexdigest();return Path(rawdir)/code/(k+'.bin'),Path(rawdir)/code/(k+'.json')
def cached_operator_signature(rawdir,code,cfg):
    parts=[]
    for url in watch_urls(code,cfg):
        body,meta=_cache_file(rawdir,code,url)
        if not body.exists():return None
        ctype=''
        try:ctype=json.loads(meta.read_text('utf-8')).get('content_type','')
        except Exception:pass
        parts.append((url,signature(code,url,body.read_bytes(),ctype)))
    return _hash(parts)
def probe_operator(rawdir,code,cfg,client_class=Client):
    client=client_class(Path(rawdir)/code,cfg['hosts']);parts=[]
    for url in watch_urls(code,cfg):
        r=client.get(url);parts.append((url,signature(code,url,r['bytes'],r.get('content_type',''))))
    return _hash(parts),client.log
def bootstrap_state(previous,rawdir,config):
    state={};stamp=previous.get('sync_attempted_at') or previous.get('synced_at')
    if stamp:state['last_full_sync']=stamp
    sigs={}
    for code in ALL_OPERATORS:
        if code in config:
            s=cached_operator_signature(rawdir,code,config[code])
            if s:sigs[code]=s
    if sigs:state['signatures']=sigs
    return state
def decide(previous,rawdir,config,force=False,client_class=Client,now=None):
    now=now or now_utc();pol=policy(config);state=load_state(Path(rawdir).parent)
    if not state:state=bootstrap_state(previous,rawdir,config)
    previous_ok=bool(previous.get('lines'))
    if force or not previous_ok:return {'operators':list(ALL_OPERATORS),'reason':'forced' if force else 'no_snapshot','state':state,'probes':{},'errors':{},'did_probe':False,'full_due':True}
    last_full=parse_time(state.get('last_full_sync'));per_operator=state.get('last_deep_sync') or {};due_ops=[]
    for code in ALL_OPERATORS:
        if code not in config:continue
        stamp=parse_time(per_operator.get(code)) or last_full
        if not stamp or now-stamp>=timedelta(hours=pol['full_refresh_hours']):due_ops.append(code)
    full_due=bool(due_ops);last_quick=parse_time(state.get('last_quick_check'))
    if not full_due and last_quick and now-last_quick<timedelta(minutes=pol['quick_check_minutes']):return {'operators':[],'reason':'recent_check','state':state,'probes':{},'errors':{},'did_probe':False,'full_due':False,'due_operators':[]}
    probes={};errors={};logs={}
    for code in ALL_OPERATORS:
        if code not in config:continue
        try:probes[code],logs[code]=probe_operator(rawdir,code,config[code],client_class)
        except Exception as e:errors[code]=type(e).__name__+': '+str(e)
    old=state.get('signatures',{});changed=[c for c in ALL_OPERATORS if c in probes and (c not in old or probes[c]!=old[c])]
    if full_due:
        selected=[c for c in ALL_OPERATORS if c in probes and (c in due_ops or c in changed)];reason='daily_full_check' if selected else 'offline_cached'
    else:selected=changed;reason='source_changed' if selected else ('probe_failed_cached' if errors else 'unchanged')
    return {'operators':selected,'reason':reason,'state':state,'probes':probes,'probe_logs':logs,'errors':errors,'did_probe':True,'full_due':full_due,'due_operators':due_ops}
def finish_state(data_dir,decision,config,rawdir,deep_success,now=None):
    now=now or now_utc();state=dict(decision.get('state') or {});state['version']=1;state['last_quick_check']=now.isoformat();sigs=dict(state.get('signatures') or {});sigs.update(decision.get('probes') or {})
    for code in deep_success:
        s=cached_operator_signature(rawdir,code,config[code])
        if s:sigs[code]=s
    state['signatures']=sigs;deep_times=dict(state.get('last_deep_sync') or {})
    for code in deep_success:deep_times[code]=now.isoformat()
    state['last_deep_sync']=deep_times
    if set(deep_success)>=set(c for c in ALL_OPERATORS if c in config):state['last_full_sync']=now.isoformat()
    elif not state.get('last_full_sync') and deep_success:state['last_full_sync']=now.isoformat()
    state['last_reason']=decision.get('reason');state['last_deep_operators']=list(deep_success);save_state(data_dir,state);return state
