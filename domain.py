"""Reglas de horarios. Sin red, sin Flask y sin modificar los datos de origen."""
from __future__ import annotations
import copy, hashlib, json, re, unicodedata
from datetime import date, datetime
from pathlib import Path
try:
    from zoneinfo import ZoneInfo
except ImportError:
    ZoneInfo = None

VERSION = '12.16'
class DataError(ValueError): pass

def clean(v): return re.sub(r'\s+', ' ', str(v or '')).strip()
def norm(v):
    return re.sub(r'[^a-z0-9]+',' ',unicodedata.normalize('NFKD',clean(v)).encode('ascii','ignore').decode().lower()).strip()
def fingerprint(obj):
    return hashlib.sha256(json.dumps(obj,ensure_ascii=False,sort_keys=True).encode()).hexdigest()[:20]
def today():
    try: return datetime.now(ZoneInfo('Europe/Madrid')).date()
    except Exception: return datetime.now().date()
def parse_date(v):
    if isinstance(v,date): return v
    for f in ('%Y-%m-%d','%d-%m-%Y','%d/%m/%Y'):
        try: return datetime.strptime(str(v),f).date()
        except ValueError: pass
    raise DataError('Fecha no válida: '+str(v))
def iso(v): return parse_date(v).isoformat()
def minute(v):
    m=re.fullmatch(r'([0-2]?\d):([0-5]\d)',str(v or '').strip())
    if not m or int(m[1])>29: raise DataError('Hora no válida: '+str(v))
    return int(m[1])*60+int(m[2])
def cell(v):
    if v is None: return None
    s=clean(v)
    if s in ('','-','–','—','>','→','»','--'): return None
    if isinstance(v,(dict,list)): raise DataError('Celda horaria no escalar')
    m=minute(s)
    return f'{m//60:02d}:{m%60:02d}'

def parse_calendar(label='', mask=''):
    if isinstance(mask,list) and len(mask)==7: mask=''.join(str(int(bool(x))) for x in mask)
    n=norm(label)
    if mask:
        if not re.fullmatch('[01]{7}',str(mask)): raise DataError('Máscara de días desconocida')
        days={i for i,c in enumerate(mask) if c=='1'}
    else:
        for a,b in [('dilluns','lunes'),('dimarts','martes'),('dimecres','miercoles'),('dijous','jueves'),('divendres','viernes'),('dissabtes','sabados'),('dissabte','sabado'),('diumenges','domingos'),('diumenge','domingo'),('festius','festivos')]: n=n.replace(a,b)
        days=set()
        if any(x in n for x in ('todos los dias','diario','every day','daily')): days=set(range(7))
        names=['lunes','martes','miercoles','jueves','viernes','sabado','domingo']
        ranges=list(re.finditer(r'(lunes|martes|miercoles|jueves|viernes|sabados?|domingos?)\s+(?:a|al|hasta)\s+(lunes|martes|miercoles|jueves|viernes|sabados?|domingos?)',n))
        if ranges:
            for m in ranges:
                a=names.index(m[1].rstrip('s') if m[1] in ('sabados','domingos') else m[1]); b=names.index(m[2].rstrip('s') if m[2] in ('sabados','domingos') else m[2]); days.update((a+i)%7 for i in range((b-a)%7+1))
        elif not days:
            for i,k in enumerate(names):
                if re.search(r'\b'+k+r's?\b',n): days.add(i)
        if not days and 'laborable' in n: days=set(range(5))
        if not days and 'festiv' not in n: raise DataError('Calendario no reconocido: '+label)
    excluded=bool(re.search(r'(excepto|except|exclu\w*|no|sin)\s+(?:los\s+)?(?:dias\s+)?festiv',n))
    if 'festiv' in n: holiday=not excluded
    elif len(days)==7: holiday=True
    elif 'domingo' in n: holiday=True
    else: holiday=False
    return {'day_mask':''.join('1' if i in days else '0' for i in range(7)),'holiday_service':holiday}

ALIASES={
 'Ciutadella':['ciutadella','placa de la pau','placa dels pins','via perimetral','bisbe juano','piscina municipal','josep mascaro pasarius'],
 'Maó':['estacio autobusos mao','estacio d autobusos de mao','hospital mateu orfila','ies joan ramis','mao','mahon','poligon mao'],
 'Alaior':['alaior'], 'L\'Argentina':['l argentina'], 'Es Mercadal':['es mercadal'],
 'Ferreries':['ferreries'], 'Es Castell':['es castell'], 'Sant Lluís':['sant lluis'],
 'Sant Climent':['sant climent'], 'Es Migjorn Gran':['es migjorn gran'],
 'Cala Galdana':['cala galdana'], 'Cala en Porter':['cala en porter'],
 'Son Bou':['son bou','torre soli','bella mirada','club san jaime'], 'Sant Tomàs':['sant tomas'],
 'Es Canutells':['canutells'], 'Sa Mesquida':['sa mesquida'], 'Cala Llonga':['cala llonga'],
 'Trebalúger':['trebaluger'], 'Alcalfar':['alcalfar'], "S'Algar":['s algar'],
 'Punta Prima':['punta prima'], 'Binibèquer':['binibequer','binibeca'], 'Binissafúller':['binissafuller'],
 'Bintalfa':['bintalfa'], 'Aeroport':['aeroport','airport'], 'Cos Nou':['cos nou'],
 'Llucmaçanes':['llucmacanes'], 'Cala Blanes':['cala blanes'], 'Cala en Forcat':['cala en forcat','cala forcat'],
 'Delfines':['delfines'], 'Cala Morell':['cala morell'], 'La Vall':['la vall','algaiarens'],
 'Santandria':['santandria'], 'Cala Blanca':['cala blanca'], 'Sa Caleta':['sa caleta','caleta'],
 "Cala'n Bosch":['cala bosch','calan bosch','cala n bosch'], 'Son Xoriguer':['son xoriguer'],
 'Son Saura':['son saura'], 'Cala Turqueta':['cala turqueta'], 'Macarella':['macarella'],
 'Punta Nati':['punta nati'], 'Port Son Blanc':['son blanc'], 'Fornells':['fornells'],
 'Cala Tirant':['cala tirant'], 'Son Parc':['son parc'], "Port d'Addaia":['port d addaia','p addaia'],
 "Arenal d'en Castell":['arenal d en castell','a castell'], 'Es Grau':['es grau'], 'Favàritx':['favaritx','cami de cavalls'],
 'Na Macaret':['na macaret'], 'Punta Grossa':['punta grossa']}
def area_for(name, explicit=None):
    if explicit and clean(explicit) not in ('Otra','Otros'): return clean(explicit)
    n=' '+norm(name)+' '
    matches=[(len(alias),area) for area,aliases in ALIASES.items() for alias in aliases if ' '+alias+' ' in n]
    if matches: return max(matches)[1]
    return 'Parada: '+clean(name)

def validate_block(raw, operator=''):
    b=copy.deepcopy(raw)
    b['valid_from']=iso(b.get('valid_from')); b['valid_to']=iso(b.get('valid_to'))
    if b['valid_to']<b['valid_from']: raise DataError('Periodo invertido')
    if not b.get('source'): raise DataError('Horario sin fuente')
    cal=parse_calendar(b.get('days',''),b.get('day_mask',''))
    b.setdefault('holiday_service',cal['holiday_service']); b['day_mask']=cal['day_mask']
    rows=b.get('rows')
    if not isinstance(rows,list) or len(rows)<2: raise DataError('Faltan filas de paradas')
    lengths={len(r.get('times',[])) for r in rows}
    if len(lengths)!=1 or not next(iter(lengths)): raise DataError('Filas desalineadas: no se rellenan ni recortan')
    columns=next(iter(lengths))
    if b.get('columns',columns)!=columns: raise DataError('Recuento de expediciones no coincide')
    b['columns']=columns
    for i,r in enumerate(rows):
        if not clean(r.get('stop')): raise DataError('Parada sin nombre')
        r['stop']=clean(r['stop']); r['times']=[cell(x) for x in r['times']]
        r['area']=area_for(r['stop'],r.get('area'))
        r['key']=r.get('key') or fingerprint([operator,str(r.get('stop_id','')),r['stop']])
        r['sequence']=i
    if b.get('column_masks') and len(b['column_masks'])!=columns: raise DataError('Calendarios de expedición desalineados')
    for x in b.get('column_masks',[]):
        if not re.fullmatch('[01]{7}',x): raise DataError('Días de expedición inválidos')
    bad=[]
    for c in range(columns):
        order=b.get('trip_orders',{}).get(str(c),list(range(len(rows))))
        if sorted(order)!=list(range(len(rows))): raise DataError('Orden de paradas inválido')
        mins=[minute(rows[i]['times'][c]) for i in order if rows[i]['times'][c] is not None]
        if len(mins)<2: bad.append(c); continue
        unwrapped=[]; offset=0; last=None; invalid=False
        for m in mins:
            v=m+offset
            if last is not None and v<last:
                if last%1440>=20*60 and m<6*60 and offset==0: offset=1440; v=m+offset
                else: invalid=True; break
            unwrapped.append(v); last=v
        if invalid or unwrapped[-1]-unwrapped[0]>6*60: bad.append(c)
    excluded=set(b.get('excluded_columns',[]))|set(bad)
    if len(excluded)==columns: raise DataError('Todas las expediciones son incoherentes o carecen de dos paradas')
    b['excluded_columns']=sorted(excluded)
    b['id']=b.get('id') or fingerprint({k:b[k] for k in ('direction','valid_from','valid_to','day_mask','rows','columns') if k in b})
    return b

def validate_line(raw):
    line=copy.deepcopy(raw); op=line.get('operator_code') or 'TMSA'
    line['operator_code']=op; line.setdefault('operator',{'TMSA':'TMSA','TORRES':'Bus Torres','FORNELLS':'Autos Fornells'}.get(op,op))
    good=[]; errors=[]; seen=set()
    for raw_b in line.get('blocks',[]):
        try:
            b=validate_block(raw_b,op)
            k=fingerprint({k:v for k,v in b.items() if k not in ('id','source','checked_at')})
            if k not in seen: good.append(b); seen.add(k)
        except (DataError,TypeError,ValueError) as e: errors.append(str(e))
    line['blocks']=good
    line['sync_complete']=bool(good)
    line['validation_errors']=errors
    if not line.get('directions'):
        line['directions']=[{'name':b.get('direction',''),'stops':[r['stop'] for r in b['rows']],'areas':[r['area'] for r in b['rows']]} for b in good]
    from place_labels import enrich_line
    return enrich_line(line)

HOLIDAYS_2026={'2026-'+s for s in ['01-01','01-06','03-02','04-02','04-03','04-06','05-01','08-15','10-12','12-08','12-25','12-26']}
def calendar_ok(b,d,c=None):
    ds=d.isoformat()
    if ds<b['valid_from'] or ds>b['valid_to']: return False
    if ds in b.get('excluded_dates',[]): return False
    override=b.get('date_overrides',{}).get(ds)
    wd=d.weekday()
    if override is False: return False
    if override is not None and override is not True: wd=int(override)
    holiday=ds in HOLIDAYS_2026 and override is None
    if holiday and not b.get('holiday_service',False): return False
    mask=b['day_mask']
    if c is not None:
        if c in b.get('excluded_columns',[]): return False
        if b.get('column_masks'): mask=b['column_masks'][c]
    if override is True: return True
    if holiday: return b.get('holiday_service',False) and (not b.get('column_masks') or mask[6]=='1')
    return mask[wd]=='1'

def pairs(b,d):
    rows=b['rows']
    for c in range(b['columns']):
        if not calendar_ok(b,d,c): continue
        order=b.get('trip_orders',{}).get(str(c),list(range(len(rows))))
        calls=[]; offset=0; prev=None
        for i in order:
            t=rows[i]['times'][c]
            if t is None: continue
            m=minute(t)+offset
            if prev is not None and m<prev: offset+=1440; m+=1440
            calls.append((i,m)); prev=m
        for at,(oi,dm) in enumerate(calls):
            if rows[oi].get('pickup_allowed') is False: continue
            for di,am in calls[at+1:]:
                if rows[di].get('dropoff_allowed') is False: continue
                if rows[oi]['key']==rows[di]['key']: continue
                yield c,oi,di,dm,am

def active_lines(snap,d):
    for raw in snap.get('lines',[]):
        if raw.get('operational') is False and raw.get('status_observed_on')==d.isoformat(): continue
        for b in raw.get('blocks',[]):
            if calendar_ok(b,d): yield raw,b

def line_periods(l):
    out={}
    for p in l.get('periods',[]):
        try: a,z=iso(p.get('from')),iso(p.get('to'))
        except (DataError,AttributeError): continue
        out[a,z]={'from':a,'to':z}
    for b in l.get('blocks',[]): out[b['valid_from'],b['valid_to']]={'from':b['valid_from'],'to':b['valid_to']}
    return sorted(out.values(),key=lambda p:p['from'])
def status_for(l,d):
    if l.get('operational') is False and l.get('status_observed_on')==d.isoformat(): return 'operator_not_operating'
    if any(any(pairs(b,d)) for b in l.get('blocks',[])): return 'in_service'
    periods=line_periods(l); ds=d.isoformat()
    if any(p['from']<=ds<=p['to'] for p in periods): return 'no_service_today' if l.get('blocks') else 'unverified_schedule'
    if any(p['from']>ds for p in periods): return 'future_period'
    if periods: return 'outside_published_period'
    return 'unverified_schedule' if l.get('sync_error') else 'no_schedule_published'
