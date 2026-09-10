"""Published single-ticket fares, independent of timetables and reachability.

No fare is extrapolated from a whole line, nearby place, transfer or distance.
Reference tables are explicitly dated transcriptions, not a successful live fetch.
"""
from __future__ import annotations
import copy,json,re
from functools import lru_cache
from datetime import date,datetime,timezone
from decimal import Decimal,InvalidOperation
from pathlib import Path
from bs4 import BeautifulSoup
from domain import clean,norm,DataError

DEFAULT_SOURCES={'TORRES':'https://www.bustorresmenorca.com/informacion/tarifas/','FORNELLS':'https://www.autosfornells.com/es/pasajeros/tarifas/'}
ALIASES={'mahon':'mao','mao centre':'mao','mao centre ciutat':'mao','ciutadella centre':'ciutadella','ciudadela':'ciutadella','aeropuerto':'aeroport','airport':'aeroport','cala en blanes':'cala blanes','calan blanes':'cala blanes','cala n blanes':'cala blanes','cala en forcat':'cala forcat','forcat':'cala forcat','cala n bosch':'cala bosch','calan bosch':'cala bosch','cala en bosch':'cala bosch','cala en bosc':'cala bosch','cala n bosc':'cala bosch','cala bosc':'cala bosch','santandria':'santandria','caleta':'sa caleta','estacio cos nou':'cos nou','estacio maritima cos nou':'cos nou','arenal castell':'arenal d en castell','a castell':'arenal d en castell','arenal den castell':'arenal d en castell','p addaia':'port d addaia','favaritx':'favaritx','favartix':'favaritx','far favaritx':'favaritx','far de favaritx':'favaritx','parking favaritx':'parking favaritx','parking favartix':'parking favaritx','entrada cami de cavalls':'cami de cavalls','parquing favaritx':'parking favaritx','poligon mao':'poima','poligono mao':'poima','poligono industrial de mao':'poima'}
KNOWN={'mao','ciutadella','aeroport','poima','cos nou','llucmacanes','cala blanes','cala forcat','cala bosch','son xoriguer','cala blanca','santandria','sa caleta','cala morell','la vall','port son blanc','son saura','cala turqueta','macarella','punta nati','fornells','cala tirant','es mercadal','son parc','arenal d en castell','port d addaia','es grau','favaritx','parking favaritx','cami de cavalls','alaior','na macaret','punta grossa'}

def canonical(text):
    n=norm(str(text or '').translate(str.maketrans({'’':"'",'‘':"'",'ʼ':"'"})));return ALIASES.get(n,n)
def money_minor(text):
    text=clean(text);m=re.fullmatch(r'([0-9]+(?:[,.][0-9]{1,2})?)\s*(?:€|EUR)',text,re.I)
    if not m:raise DataError('Precio no reconocido como importe EUR: '+text)
    try:value=Decimal(m[1].replace(',','.'))*100
    except InvalidOperation as e:raise DataError('Importe inválido') from e
    if value<0 or value>100000 or value!=value.to_integral_value():raise DataError('Importe fuera de límites')
    return int(value)
def format_price(minor):return f'{minor//100},{minor%100:02d} €'
def _group(text):
    out=[]
    for value in re.split(r'\s*/\s*',text):
        place=canonical(value)
        if not place or place not in KNOWN:raise DataError('Zona tarifaria no reconocida: '+value)
        if place not in out:out.append(place)
    return out

def rules_from_records(records,operator,source,observed_on):
    rules=[];issues=[]
    for rec in records:
        code=clean(rec.get('line')).upper();route=clean(rec.get('route'))
        try:
            amount=money_minor(rec['price']);parts=re.split(r'\s*(?:→|↔|–|—|-)\s*',route);scope='journey'
            if len(parts)==2 and not parts[0] and code in ('L15','L60'):
                if canonical(parts[1])!=('mao' if code=='L15' else 'ciutadella'):raise DataError('Cabecera urbana no reconocida')
                origins=[];destinations=[];scope='urban_line'
            elif len(parts)==2 and all(parts):origins=_group(parts[0]);destinations=_group(parts[1])
            else:raise DataError('Trayecto tarifario sin dos extremos explícitos')
            rules.append({'line':code,'origins':origins,'destinations':destinations,'amount_minor':amount,'currency':'EUR','ticket':'single','scope':scope,'bidirectional':True,'published_route':route,'source':source,'observed_on':observed_on,'valid_from':rec.get('valid_from'),'valid_to':rec.get('valid_to')})
        except (DataError,KeyError,TypeError) as e:issues.append({'route':route,'error':str(e)})
    unique={json.dumps(r,sort_keys=True,ensure_ascii=False):r for r in rules};return list(unique.values()),issues

def parse_tables(html,operator,source,observed_on):
    soup=BeautifulSoup(html,'html.parser');records=[];announced_codes=set();price_cells=0
    for table in soup.find_all('table'):
        current=None
        for row in table.find_all('tr'):
            cells=row.find_all(['td','th'],recursive=False)
            if not cells:continue
            texts=[clean(c.get_text(' ',strip=True)) for c in cells]
            for text in texts:
                for code in re.findall(r'\b(L\d{1,2}|NATI)\b',text,re.I):announced_codes.add(code.upper())
            for text in texts[:-1] if len(texts)>1 else texts:
                match=re.match(r'^(L\d{1,2}|NATI)\b',text,re.I)
                if match:current=match[1].upper();break
            if not current:continue
            price_at=None
            for i in range(len(texts)-1,-1,-1):
                try:money_minor(texts[i]);price_at=i;break
                except DataError:pass
            if price_at is None or price_at==0:continue
            price_cells+=1;routecell=cells[price_at-1];parts=[clean(t) for t in routecell.get_text('\n',strip=True).splitlines() if clean(t)];complete=[t for t in parts if re.search(r'→|↔|–|—|-',t)];route_labels=complete if complete and len(complete)==len(parts) else [clean(routecell.get_text(' ',strip=True))]
            for label in route_labels:records.append({'line':current,'route':label,'price':texts[price_at]})
    rules,issues=rules_from_records(records,operator,source,observed_on)
    if not rules:raise DataError('Página de tarifas sin filas verificables')
    if issues:raise DataError('Una o varias filas de tarifas no son inequívocas: '+str(issues[:3]))
    parsed_codes={r['line'] for r in rules};missing=sorted(announced_codes-parsed_codes)
    if missing:raise DataError('Tabla de tarifas parcialmente interpretada; faltan líneas: '+', '.join(missing))
    if len(records)<price_cells:raise DataError('Tabla de tarifas parcialmente interpretada; faltan trayectos con precio')
    return rules

def enrich_lines(lines,operator,client,config,previous,attempted,reference_path=None):
    if operator not in DEFAULT_SOURCES:return {'state':'unchanged','rules':sum(len(l.get('fares',[])) for l in lines)}
    source=config.get('fare_page') or DEFAULT_SOURCES[operator];rules=[];error=None;state='live'
    try:rules=parse_tables(client.text(source),operator,source,attempted[:10])
    except Exception as exc:error=type(exc).__name__+': '+str(exc);state='unavailable'
    old={str(l.get('id')):l for l in previous.get('line_catalog',previous.get('lines',[])) if l.get('operator_code')==operator};reference={}
    if not rules:
        p=Path(reference_path) if reference_path else Path(__file__).parent/'config/fares_reference.json'
        try:reference=json.loads(p.read_text('utf-8'))['operators'].get(operator,{})
        except (OSError,ValueError,KeyError):pass
    used_states=set();count=0
    for l in lines:
        code=l.get('code','');selected=[r for r in rules if r['line']==code];lstate=state;checked=attempted[:10] if rules else None
        if not rules:
            prev=old.get(str(l.get('id')),{ });saved=prev.get('fare_rules',[])
            if saved:selected=copy.deepcopy(saved);lstate='cached';checked=prev.get('fare_observed_on')
            elif reference:
                parsed,issues=rules_from_records(reference.get('rows',[]),operator,reference['source'],reference.get('observed_on'));selected=[r for r in parsed if r['line']==code];lstate='reference' if selected else 'unavailable';checked=reference.get('observed_on') if selected else None
        l['fare_rules']=selected;l['fare_state']=lstate if selected else ('not_published' if rules else 'unavailable');l['fare_source']=source;l['fare_observed_on']=checked;l['fare_last_attempt_at']=attempted;l['fare_error']=error;count+=len(selected);used_states.add(l['fare_state'])
    return {'source':source,'states':sorted(used_states),'rules':count,'error':error,'note':'Las tarifas publicadas no crean conexiones ni horarios. Las referencias conservan su fecha de consulta.'}

_SPECIFIC=[('parking favaritx','parking favaritx'),('parking favartix','parking favaritx'),('parquing favaritx','parking favaritx'),('cami de cavalls','cami de cavalls'),('poligon mao','poima'),('poligono de mao','poima'),('poima','poima')]
def row_zone(value):
    if isinstance(value,str):return canonical(value.removeprefix('Parada: '))
    stop=clean(value.get('stop',value.get('name','')));n=' '+norm(stop)+' '
    for token,place in _SPECIFIC:
        if ' '+token+' ' in n:return place
    key=canonical(stop)
    if key in KNOWN:return key
    area=value.get('area','')
    if area and not area.startswith('Parada:'):
        key=canonical(area)
        if key in KNOWN:return key
    candidates=[]
    for alias in KNOWN|set(ALIASES):
        if ' '+alias+' ' in n:candidates.append((len(alias),canonical(alias)))
    return max(candidates)[1] if candidates else None

def _legacy_quote(line,a,z):
    left=canonical(a['area'] if isinstance(a,dict) else a);right=canonical(z['area'] if isinstance(z,dict) else z);matches=[]
    for f in line.get('fares',[]):
        p=re.split(r'\s+(?:-|–|—|→)\s+',f.get('route',''))
        if len(p)==2 and ((canonical(p[0])==left and canonical(p[1])==right) or (canonical(p[0])==right and canonical(p[1])==left)):
            try:amount=money_minor(f.get('price','').replace("'",',').replace('’',','))
            except DataError:continue
            matches.append((amount,f))
    if not matches or len({m[0] for m in matches})!=1:return None
    amount,f=matches[0];return {'status':'published','price':f['price'],'amount_minor':amount,'currency':'EUR','ticket':'single','source':f.get('source') or line.get('url',''),'observed_on':line.get('checked_at'),'valid_from':None,'valid_to':None,'published_route':f['route'],'validity_specified':False}

@lru_cache(maxsize=8)
def _reference_rules(operator):
    try:
        payload=json.loads((Path(__file__).parent/'config/fares_reference.json').read_text('utf-8'));ref=payload['operators'][operator];rules,issues=rules_from_records(ref.get('rows',[]),operator,ref['source'],ref.get('observed_on'))
        if issues:return [],{}
        return rules,ref
    except (OSError,ValueError,KeyError,TypeError):return [],{}
def _effective_rules(line):
    rules=line.get('fare_rules',[])
    if rules:return rules,line.get('fare_state','live'),line.get('fare_observed_on'),line.get('fare_source')
    op=line.get('operator_code')
    if op not in DEFAULT_SOURCES or line.get('fare_state')=='not_published':return [],line.get('fare_state'),line.get('fare_observed_on'),line.get('fare_source')
    ref_rules,ref=_reference_rules(op);selected=[r for r in ref_rules if r.get('line')==line.get('code')]
    if not selected:return [],line.get('fare_state'),line.get('fare_observed_on'),line.get('fare_source')
    return selected,'reference',ref.get('observed_on'),ref.get('source')

def quote(line,origin,destination,travel_date=None):
    if line.get('operator_code') not in DEFAULT_SOURCES and 'fare_rules' not in line:
        source=line.get('fare_source') or '';empty={'status':'not_verified','price':'','amount_minor':None,'currency':'EUR','ticket':'single','source':source,'observed_on':line.get('fare_observed_on'),'validity_specified':False};return _legacy_quote(line,origin,destination) or empty
    rules,state,observed_hint,source_hint=_effective_rules(line);source=source_hint or line.get('fare_source') or DEFAULT_SOURCES.get(line.get('operator_code'),'');empty={'status':'not_verified','price':'','amount_minor':None,'currency':'EUR','ticket':'single','source':source,'observed_on':observed_hint or line.get('fare_observed_on'),'validity_specified':False};a,z=row_zone(origin),row_zone(destination);matches=[];ds=travel_date.isoformat() if isinstance(travel_date,date) else str(travel_date or '')[:10]
    for r in rules:
        if r.get('line')!=line.get('code'):continue
        if ds and ((r.get('valid_from') and ds<r['valid_from']) or (r.get('valid_to') and ds>r['valid_to'])):continue
        if r.get('scope')=='urban_line':matches.append(r);continue
        direct=a in r.get('origins',[]) and z in r.get('destinations',[]);reverse=r.get('bidirectional') and z in r.get('origins',[]) and a in r.get('destinations',[])
        if a and z and (direct or reverse):matches.append(r)
    if not matches:return empty
    if len({(r['amount_minor'],r['ticket']) for r in matches})!=1:return {**empty,'status':'ambiguous'}
    r=matches[0];observed=r.get('observed_on') or observed_hint or line.get('fare_observed_on');return {'status':{'live':'published','reference':'reference','cached':'cached'}.get(state,'published'),'price':format_price(r['amount_minor']),'amount_minor':r['amount_minor'],'currency':'EUR','ticket':r['ticket'],'source':r['source'],'observed_on':observed,'published_route':r['published_route'],'valid_from':r.get('valid_from'),'valid_to':r.get('valid_to'),'validity_specified':bool(r.get('valid_from') or r.get('valid_to')),'travel_after_check':bool(ds and observed and ds>observed[:10])}
def common_quote(quotes):
    if not quotes:return {'status':'not_verified','price':''}
    first=quotes[0]
    if all(q.get('amount_minor') is not None and q.get('amount_minor')==first.get('amount_minor') and q.get('ticket')==first.get('ticket') for q in quotes):return first
    return {'status':'select_arrival','price':'','amount_minor':None,'source':first.get('source','')}
