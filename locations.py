"""Public stop coordinates, never user positions.

Timetables stay in the existing snapshot. Cartography is downloaded once per day
for the whole island (not around a user's GPS position) and cached separately.
An unlinked physical stop is NOT asserted to be served by a particular operator.
"""
from __future__ import annotations
import math, re
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.parse import urlencode
from domain import clean, norm, DataError
from net import Client, atomic_json
from storage import read_json

BOUNDS = (39.78, 3.76, 40.13, 4.35)
ATTRIBUTION = '© OpenStreetMap contributors'
LICENSE_URL = 'https://www.openstreetmap.org/copyright'
ENDPOINTS = ('https://overpass-api.de/api/interpreter','https://overpass.private.coffee/api/interpreter')
QUERY = ('[out:json][timeout:12];(' 'node["highway"="bus_stop"](39.78,3.76,40.13,4.35);' 'node["public_transport"="platform"]["bus"="yes"](39.78,3.76,40.13,4.35);' ');out body;')

def coordinate_pair(lat, lon):
    if isinstance(lat, bool) or isinstance(lon, bool): raise DataError('Coordenadas no numéricas')
    try: lat, lon = float(lat), float(lon)
    except (TypeError, ValueError): raise DataError('Coordenadas no numéricas')
    a,b,c,d=BOUNDS
    if not (math.isfinite(lat) and math.isfinite(lon) and a<=lat<=c and b<=lon<=d): raise DataError('Punto fuera de Menorca')
    return lat,lon

def valid_id(value): return isinstance(value,int) and not isinstance(value,bool) and value>0

def parse_osm(payload):
    if not isinstance(payload,dict) or not isinstance(payload.get('elements'),list): raise DataError('Respuesta cartográfica sin lista de elementos')
    if payload.get('remark'): raise DataError('Respuesta Overpass incompleta: '+clean(payload['remark'])[:300])
    if len(payload['elements'])>10000: raise DataError('Respuesta cartográfica excede el límite de la isla')
    found={}
    for e in payload['elements']:
        if not isinstance(e,dict) or e.get('type')!='node' or not valid_id(e.get('id')): continue
        t=e.get('tags') or {}
        if not isinstance(t,dict): continue
        if not (t.get('highway')=='bus_stop' or (t.get('public_transport')=='platform' and t.get('bus')=='yes')): continue
        if t.get('bus')=='no' or t.get('access') in ('private','no'): continue
        if any(t.get(x)=='yes' for x in ('disused','abandoned','demolished','construction')): continue
        try: lat,lon=coordinate_pair(e.get('lat'),e.get('lon'))
        except DataError: continue
        names=list(dict.fromkeys(clean(t[x])[:180] for x in ('name','name:ca','name:es','official_name','local_ref_name') if isinstance(t.get(x),str) and clean(t[x])))
        refs=list(dict.fromkeys(clean(t[x])[:60] for x in ('ref','ref:tib','ref:TIB','gtfs:stop_id') if isinstance(t.get(x),str) and clean(t[x])))
        item={'id':'osm-node-'+str(e['id']),'name':names[0] if names else '','names':names,'refs':refs,'lat':lat,'lon':lon,'source':'OpenStreetMap','source_url':'https://www.openstreetmap.org/node/'+str(e['id']),'direction':clean(t.get('direction',''))[:100]}
        if item['id'] in found and found[item['id']]!=item: raise DataError('Un identificador cartográfico tiene posiciones contradictorias')
        found[item['id']]=item
    if not found: raise DataError('La fuente no ha devuelto paradas georreferenciadas utilizables')
    return sorted(found.values(),key=lambda x:x['id'])

def checked_catalog(raw):
    if not isinstance(raw,dict) or raw.get('schema')!=1 or not isinstance(raw.get('stops'),list): return []
    found=[]
    for item in raw['stops']:
        if not isinstance(item,dict): continue
        if not re.fullmatch(r'osm-node-\d+',str(item.get('id',''))): continue
        try: lat,lon=coordinate_pair(item.get('lat'),item.get('lon'))
        except DataError: continue
        sid=item['id'].split('-')[-1];found.append({**item,'lat':lat,'lon':lon,'source_url':'https://www.openstreetmap.org/node/'+sid})
    return found

def recent(stamp,now,delta):
    try:
        when=datetime.fromisoformat(stamp.replace('Z','+00:00'));return timedelta(0)<=now-when<=delta
    except (AttributeError,TypeError,ValueError): return False

def sync_locations(directory,config,client_class=Client,now=None):
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=True);now=now or datetime.now(timezone.utc);path=directory/'stop_locations.json';last_path=directory/'GPS_DIAGNOSTICO.json';old=read_json(path);previous=checked_catalog(old);last=read_json(last_path);report={'attempted_at':now.isoformat(),'source':'OpenStreetMap','attribution':ATTRIBUTION,'privacy':'Consulta fija para Menorca. No contiene posiciones de usuarios.','requests':[],'errors':[]}
    if not config.get('enabled',False): report.update(status='disabled',stops=len(previous),checked_at=old.get('checked_at'));return report
    if previous and recent(old.get('checked_at'),now,timedelta(hours=24)): report.update(status='cached_recent',stops=len(previous),checked_at=old.get('checked_at'))
    elif recent(last.get('attempted_at'),now,timedelta(minutes=15)) and last.get('status') in ('unavailable','cached_after_error'): return {**last,'cooldown':True}
    else:
        candidate=None
        for endpoint in ENDPOINTS:
            from urllib.parse import urlsplit
            c=client_class(directory/'sources'/'GEO',[urlsplit(endpoint).hostname],timeout=15)
            try:
                data=c.json(endpoint+'?'+urlencode({'data':QUERY}));stops=parse_osm(data)
                if len(previous)>=30 and len(stops)<len(previous)//2: raise DataError('El recuento de paradas ha caído más de la mitad; se conserva la copia anterior')
                candidate={'schema':1,'source':'OpenStreetMap','attribution':ATTRIBUTION,'license_url':LICENSE_URL,'checked_at':now.isoformat(),'source_timestamp':(data.get('osm3s') or {}).get('timestamp_osm_base'),'stops':stops};atomic_json(path,candidate);report.update(status='fresh',stops=len(stops),checked_at=candidate['checked_at'])
            except Exception as e: report['errors'].append({'source':endpoint,'error':type(e).__name__+': '+str(e)[:400]})
            finally: report['requests'].extend(c.log)
            if candidate: break
        if candidate is None: report.update(status='cached_after_error' if previous else 'unavailable',stops=len(previous),checked_at=old.get('checked_at'))
    atomic_json(last_path,report);return report

def name_key(s):
    n=norm(s);n=re.sub(r'\bautobuses\b','autobusos',n);n=re.sub(r'\bestacion\b','estacio',n);return n

def _timetable_rows(snapshot):
    rows={}
    for l in snapshot.get('line_catalog',snapshot.get('lines',[])):
        for b in l.get('blocks',[]):
            for r in b['rows']:
                if r.get('key'): rows.setdefault(r['key'],{**r,'operator':l.get('operator',''),'operator_code':l.get('operator_code','')})
    return rows

def location_payload(planner,raw,report=None,destination=''):
    stops=checked_catalog(raw);rows=_timetable_rows(planner.snap);by_name,by_ref={},{}
    for s in stops:
        for n in set(name_key(x) for x in s.get('names',[]) if clean(x)): by_name.setdefault(n,set()).add(s['id'])
        for ref in set(s.get('refs',[])): by_ref.setdefault(ref,set()).add(s['id'])
    assigned={};collisions=0
    for key,r in rows.items():
        name_candidates=by_name.get(name_key(r['stop']),set());ref=str(r.get('stop_id') or '').strip();by_both=name_candidates&by_ref.get(ref,set()) if ref else set();candidates=by_both or name_candidates
        if len(candidates)==1: assigned[key]=next(iter(candidates))
        elif len(candidates)>1: collisions+=1
    available={}
    for service in planner.services.values():
        r,line=service['origin_stop'],service['line']
        if destination and not any(a['row']['area']==destination for a in service['arrivals']): continue
        k=r['key'];s=available.setdefault(k,{'key':k,'name':r['stop'],'area':r['area'],'lines':set(),'operators':set(),'directions':set()});s['lines'].add(line.get('code',''));s['operators'].add(line.get('operator',''));s['directions'].add(service['block'].get('direction',''))
    physical_links={}
    for k,sid in assigned.items(): physical_links.setdefault(sid,[]).append(k)
    result=[]
    for s in stops:
        keys=physical_links.get(s['id'],[]);matches=[{**available[k],'lines':sorted(available[k]['lines']),'operators':sorted(available[k]['operators']),'directions':sorted(available[k]['directions'])} for k in keys if k in available];result.append({**s,'matches':sorted(matches,key=lambda m:(m['name'],m['key'])),'service_state':'available' if matches else ('no_service_for_selection' if keys else 'unlinked')})
    return {'ok':True,'date':planner.date.isoformat(),'destination':destination,'stops':result,'checked_at':raw.get('checked_at'),'source_timestamp':raw.get('source_timestamp'),'status':(report or {}).get('status','available' if stops else 'unavailable'),'attribution':ATTRIBUTION,'license_url':LICENSE_URL,'coverage':{'mapped_stops':len(stops),'timetable_stops':len(rows),'linked_timetable_stops':len(assigned),'ambiguous_names':collisions},'privacy':'Las coordenadas del dispositivo no se envían a esta API.'}
