"""Geographical labels for people, separate from physical stops and fares.

This module performs no network/geocoding calls and never infers a location
from the numerically closest stop, adjacent row, or a stop-code prefix.
Exact, operator-scoped references can be extended without editing the reader.
Unresolved stops remain queryable and are explicitly labelled as unresolved.
"""
from __future__ import annotations
import json, re, unicodedata
from functools import lru_cache
from pathlib import Path

REFERENCE = Path(__file__).parent/'config'/'places_reference.json'

def _clean(v): return re.sub(r'\s+', ' ', str(v or '')).strip()
def _norm(v): return re.sub(r'[^a-z0-9]+', ' ', unicodedata.normalize('NFKD', _clean(v)).encode('ascii', 'ignore').decode().lower()).strip()

@lru_cache(maxsize=1)
def reference():
    try:
        data=json.loads(REFERENCE.read_text('utf-8'))
        if data.get('schema')!=1 or not isinstance(data.get('places'),dict): return {'places':{},'rules':[]}
        return data
    except (OSError,ValueError): return {'places':{},'rules':[]}

@lru_cache(maxsize=1)
def _rules_by_name():
    by={}
    for rule in reference().get('rules',[]):
        if rule.get('place') not in reference()['places'] or not rule.get('source'): continue
        for name in rule.get('names',[]): by.setdefault((rule.get('operator'),_norm(name)),[]).append(rule)
    return by

LINE_DEFAULTS={('TORRES','L15'):'Maó',('TORRES','L60'):'Ciutadella'}
def _is_unknown(value): return not value or value.startswith('Parada:') or value in ('Otra','Otros')
def describe(key):
    item=reference().get('places',{}).get(key)
    if item:return {'key':key,'name':item['name'],'kind':item['kind'],'municipality':item.get('municipality',''),'resolved':True}
    return {'key':key,'name':key.removeprefix('Parada: '),'kind':'unknown' if _is_unknown(key) else 'zone','municipality':'','resolved':not _is_unknown(key)}

def enrich_row(row,operator,line_code,line_name='',line_url=''):
    original=row.setdefault('geo_area_original',row.get('area',''));name=_norm(row.get('stop'));code=str(line_code or '');candidates=[];default_place=LINE_DEFAULTS.get((operator,code))
    for rule in _rules_by_name().get((operator,name),[]):
        if rule.get('line_codes') and code not in rule['line_codes']:continue
        if rule.get('stop_ids') and str(row.get('stop_id','')) not in rule['stop_ids']:continue
        candidates.append(rule)
    targets={r['place'] for r in candidates};rule=candidates[0] if len(targets)==1 else None
    if rule is None and default_place and not row.get('source_locality'):
        rule={'place':default_place,'source':line_url,'basis':'whole_line_locality','detail':'Toda la línea publicada pertenece a la misma población.'}
    if rule and not row.get('source_locality'):
        row['area']=rule['place'];info=describe(row['area']);info.update(source=rule['source'],basis=rule['basis'],checked_on=reference().get('reviewed_on'),detail=rule.get('detail',''))
    else:
        row['area']=original or ('Parada: '+row.get('stop',''));info=describe(row['area']);info.update(source=line_url,basis='source_locality_or_existing_toponym' if info['resolved'] else 'unresolved',detail='')
    info['operator_code']=operator;info['line_code']=code;info['route_context']=_clean(line_name);row['place']=info;return row

def enrich_line(line):
    for block in line.get('blocks',[]):
        for row in block.get('rows',[]):enrich_row(row,line.get('operator_code','TMSA'),line.get('code'),line.get('name',''),line.get('url') or block.get('source',''))
    return line

def quote_row(row):
    if 'geo_area_original' in row:return {**row,'area':row['geo_area_original']}
    return row

def place_choices(areas,metadata=None):
    metadata=metadata or {};out=[]
    for key in areas:out.append(dict(metadata.get(key) or describe(key)))
    return sorted(out,key=lambda x:(x['kind']=='unknown',_norm(x['name']),x['key']))

def audit(snapshot):
    unique={}
    for line in snapshot.get('lines',[]):
        for b in line.get('blocks',[]):
            for r in b['rows']:
                key=(line.get('operator_code'),r['key']);x=unique.setdefault(key,{'operator':line.get('operator'),'stop':r['stop'],'key':r['key'],'area':r['area'],'original_area':r.get('geo_area_original',r['area']),'place':r.get('place',describe(r['area'])),'lines':[]})
                if line.get('code') not in x['lines']:x['lines'].append(line.get('code'))
    rows=sorted(unique.values(),key=lambda x:(x['operator'] or '',_norm(x['stop'])));unresolved=[r for r in rows if not r['place']['resolved']]
    return {'total_stops':len(rows),'labelled_stops':len(rows)-len(unresolved),'unresolved_stops':len(unresolved),'regrouped_stops':sum(r['area']!=r['original_area'] for r in rows),'scope':'Paradas de los horarios cargados, no inventario total de Menorca.','pending':unresolved,'stops':rows}
