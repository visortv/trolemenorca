from __future__ import annotations
import csv,io,re
from urllib.parse import urljoin,urlencode
from bs4 import BeautifulSoup
from domain import clean,norm,cell,iso,DataError,validate_block,area_for
NAME_KEYS=('stop_name','parada','stop','nombre','name','nom');TIME_KEYS=('times','horas','hores','departures','salidas')
def get_key(d,keys):
    by={norm(k):v for k,v in d.items()};return next((by[norm(k)] for k in keys if norm(k) in by),None)
def check_counts(rows,meta):
    expected_n=meta.get('stop_count');expected_c=meta.get('departure_count')
    if expected_n is not None and len(rows)!=int(expected_n):raise DataError('Número de paradas diferente al manifiesto')
    lengths={len(r['times']) for r in rows}
    if len(lengths)!=1 or not next(iter(lengths),0):raise DataError('Longitud desigual entre paradas')
    if expected_c is not None and next(iter(lengths))!=int(expected_c):raise DataError('Número de expediciones diferente al manifiesto')
def parse_json_rows(payload,meta):
    if isinstance(payload,dict) and payload.get('ok') is False:raise DataError('API informa de error')
    candidates=[]
    def walk(v):
        if isinstance(v,list):
            if len(v)>=2 and all(isinstance(x,dict) for x in v):candidates.append(v)
            for x in v:walk(x)
        elif isinstance(v,dict):
            for x in v.values():walk(x)
    walk(payload);good=[]
    for lst in candidates:
        rows=[]
        try:
            for d in lst:
                name=get_key(d,NAME_KEYS);times=get_key(d,TIME_KEYS)
                if not name or not isinstance(times,list):raise DataError('Esquema de fila no soportado')
                vals=[]
                for v in times:
                    if isinstance(v,dict):
                        unknown=set(v)-{'time','hora','value','raw'}
                        if unknown:raise DataError('Celda con restricciones no implementadas: '+','.join(sorted(unknown)))
                        v=next((v[k] for k in ('time','hora','value','raw') if k in v),None)
                    vals.append(cell(v))
                locality=get_key(d,('town','locality','poblacion'));rows.append({'stop':clean(name),'stop_id':get_key(d,('stop_code','stop_id','codigo','code','codi')),'source_locality':clean(locality) if locality else None,'area':area_for(name,locality),'times':vals})
            check_counts(rows,meta);good.append(rows)
        except (DataError,TypeError):continue
    if not good:raise DataError('Esquema JSON no reconocido o columnas incompletas; se probará CSV publicado')
    if len(good)>1 and any(x!=good[0] for x in good[1:]):raise DataError('Más de una matriz JSON posible')
    return good[0]
def parse_csv_rows(text,meta):
    try:dialect=csv.Sniffer().sniff(text[:6000],delimiters=';,\t')
    except csv.Error:dialect=csv.excel
    raw=list(csv.reader(io.StringIO(text.lstrip('\ufeff')),dialect));rows=[];name_col=None;start_col=None;code_col=None
    for values in raw:
        labels=[norm(x) for x in values]
        if name_col is None:
            name_col=next((i for i,x in enumerate(labels) if x in ('parada','stop','stop name','nombre','nom')),None)
            if name_col is not None:
                code_col=next((i for i,x in enumerate(labels) if x in ('codigo','code','codi','stop code','stop id')),None);start_col=max(name_col,code_col if code_col is not None else name_col)+1;continue
            c=meta.get('departure_count')
            if c and len(values)==int(c)+2 and values[0].strip().isdigit():name_col=1;code_col=0;start_col=2
            elif c and len(values)==int(c)+1:name_col=0;start_col=1
            else:continue
        if not any(clean(v) for v in values):continue
        if len(values)<=name_col or not clean(values[name_col]):raise DataError('Fila CSV sin parada')
        vals=[cell(x) for x in values[start_col:]];name=clean(values[name_col]);rows.append({'stop':name,'stop_id':values[code_col] if code_col is not None else None,'area':area_for(name),'times':vals})
    if len(rows)<2:raise DataError('CSV sin filas horarias')
    check_counts(rows,meta);return rows
def apply_notes(b,meta):
    note=clean((meta.get('service_note_translations') or {}).get('es') or meta.get('service_note',''));n=norm(note);b['service_note']=note;b['excluded_dates']=[]
    if any(x in n for x in ('holidays','festivos','festius')):b['excluded_dates']=[iso(x) for x in re.findall(r'\b\d{2}/\d{2}/\d{4}\b',note)]
    b['holiday_service']=not (re.search(r'(festivos|holidays|festius).{0,25}(sin servicio|no service|sense servei)',n) or re.search(r'excluding holidays',n));masks=[b['day_mask']]*b['columns'];uncertain=[];daywords=[('lunes',0),('martes',1),('miercoles',2),('jueves',3),('viernes',4),('sabado',5),('domingo',6)]
    for part in re.split(r'[/\n.]',note):
        pn=norm(part)
        if not re.search(r'\bno\b|without|sin servicio',pn):continue
        excluded={v for k,v in daywords if k in pn};named=re.search(r'\b([0-2]?\d:[0-5]\d)\b',part)
        if named:
            target=cell(named[1])
            for c in range(b['columns']):
                first=next((r['times'][c] for r in b['rows'] if r['times'][c] is not None),None)
                if first==target:masks[c]=''.join('0' if i in excluded else v for i,v in enumerate(masks[c]))
        elif 'sombread' in pn or 'negrita' in pn:
            if any(b['day_mask'][i]=='1' for i in excluded):uncertain.extend(sorted(excluded));masks=[''.join('0' if i in excluded else v for i,v in enumerate(mask)) for mask in masks]
    if masks!=[b['day_mask']]*b['columns']:b['column_masks']=masks
    if uncertain:b['limitations']=['Días con horarios sombreados omitidos: el CSV/JSON no ha identificado qué columnas circulan.']
    return b
def sync(client,config):
    manifest=client.json(config['index'])
    if not isinstance(manifest,dict) or manifest.get('ok') is not True or not isinstance(manifest.get('data'),list):raise DataError('Manifiesto Bus Torres no reconocido')
    lines={}
    for item in manifest['data']:
        code=clean(item.get('code')).upper()
        if not code:continue
        l={'id':'torres-'+code.lower(),'code':code,'name':code,'operator':'Bus Torres','operator_code':'TORRES','regular':True,'url':config['catalog_page'],'blocks':[],'periods':[],'resource_errors':[]}
        for m in item.get('schedules',[]):
            try:
                vf,vt=iso(m['valid_from']),iso(m['valid_until']);mask=m.get('service_days','')
                if not re.fullmatch('[01]{7}',mask):raise DataError('Faltan días de servicio explícitos')
                l['periods'].append({'from':vf,'to':vt});l['name']=clean(m.get('title')) or l['name'];u=m.get('json_url') or config['index']+'?'+urlencode({'horario':m['code']})
                try:rows=parse_json_rows(client.json(u),m)
                except (DataError,ValueError):
                    if not m.get('csv_url'):raise
                    rows=parse_csv_rows(client.text(m['csv_url']),m)
                b={'direction':clean(m.get('title')) or code,'days':'','day_mask':mask,'valid_from':vf,'valid_to':vt,'rows':rows,'columns':len(rows[0]['times']),'source':u,'strategy':'official_api_exact_columns','schedule_id':m['code']};apply_notes(b,m);l['blocks'].append(validate_block(b,'TORRES'))
            except Exception as e:l['resource_errors'].append({'schedule':m.get('code'),'error':str(e)})
        if l['resource_errors']:l['sync_error']='No se han verificado todos los horarios del manifiesto'
        print('TORRES',code,len(l['blocks']),'bloques',flush=True);lines[code]=l
    try:
        soup=BeautifulSoup(client.text(config['catalog_page']),'html.parser')
        for a in soup.find_all('a'):
            txt=clean(a.get_text(' ',strip=True));m=re.match(r'^(L\d{2}|NATI)\s*(.*)$',txt,re.I)
            if m:
                code=m[1].upper();name=clean(m[2]) or code
                if code in lines:lines[code]['commercial_name']=name
                else:lines[code]={'id':'torres-'+code.lower(),'code':code,'name':name,'operator':'Bus Torres','operator_code':'TORRES','regular':True,'url':config['catalog_page'],'blocks':[],'periods':[],'publication_state':'no_schedule_in_manifest'}
    except Exception:pass
    return list(lines.values())
