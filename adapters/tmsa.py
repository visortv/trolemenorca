from __future__ import annotations
import re
from urllib.parse import urljoin, unquote
from bs4 import BeautifulSoup
from domain import clean,norm,area_for,DataError,cell,validate_block,today
VALID=re.compile(r'(?:V[aá]lid[oa]|Desde)\s*:?\s*(\d{2}[-/]\d{2}[-/]\d{4})\s+(?:hasta|a)\s+(\d{2}[-/]\d{2}[-/]\d{4})',re.I)
def discover(html,url):
    soup=BeautifulSoup(html,'html.parser');lines={};mode=None
    for node in soup.find_all(['h1','h2','h3','a']):
        txt=clean(node.get_text(' ',strip=True));n=norm(txt)
        if re.search(r'lineas actualmente no operativas',n):mode=False
        elif re.search(r'lineas actualmente operativas',n):mode=True
        if node.name!='a':continue
        href=urljoin(url,node.get('href',''));m=re.search(r'/linea/(\d+)',href)
        if not m or not txt:continue
        lid=m[1];name=re.sub(r'^L\d+\s*[-–:]?\s*','',txt);code=clean(node.get('data-line','')) or ('L'+lid[-2:] if len(lid)==3 and lid.startswith('6') else 'ID '+lid);lines.setdefault(lid,{'id':lid,'code':code,'name':name,'url':href,'operational':mode})
        if mode is not None:lines[lid]['operational']=mode
    if not lines:raise DataError('Índice TMSA sin enlaces /linea/. Se conserva la copia anterior.')
    return list(lines.values())
def schedule_links(soup,base,lid):
    urls=[]
    for n in soup.find_all(True):
        for attr,v in n.attrs.items():
            if isinstance(v,list):v=' '.join(v)
            s=unquote(str(v)).replace('\\/','/')
            for m in re.finditer(r'(?:https?://[^\s\'"<>]+)?/(?:es/|ca/|en/)?horarios/'+re.escape(lid)+r'/[^\s\'"<>\)\(]+',s):
                u=urljoin(base,m[0]).rstrip(';')
                if u not in urls:urls.append(u)
    return urls
def line_page(html,line):
    soup=BeautifulSoup(html,'html.parser');tokens=[clean(t) for t in soup.stripped_strings if clean(t)];start=next((i for i,t in enumerate(tokens) if norm(t)=='recorrido de la linea'),None);end=next((i for i,t in enumerate(tokens) if start is not None and i>start and norm(t)=='horarios de la linea'),None);routes=[];cur=None
    if start is not None:
        for t in tokens[start+1:end]:
            m=re.match(r'^Sentido\s*:?\s*(.+)$',t,re.I)
            if m:
                if cur:routes.append(cur)
                cur={'name':clean(m[1]),'stops':[],'areas':[]};continue
            if cur and t and len(t)<180 and norm(t) not in ('ver mapa','actuales','previstos','tarjetas validas'):cur['stops'].append(t);cur['areas'].append(area_for(t))
        if cur:routes.append(cur)
    periods=[{'from':a,'to':z} for a,z in re.findall(r'Desde\s+(\d{2}-\d{2}-\d{4})\s+hasta\s+(\d{2}-\d{2}-\d{4})',' '.join(tokens),re.I)];fares=[];in_fares=False
    for i,t in enumerate(tokens[:-1]):
        if norm(t)=='tarifas de la linea':in_fares=True;continue
        if in_fares and any(x in norm(t) for x in ('suscripcion','noticias de la linea')):break
        if in_fares and ' - ' in t and re.fullmatch(r"\d+(?:[,.'’]\d{1,2})?\s*€",tokens[i+1]):fares.append({'route':t,'price':tokens[i+1].replace("'",',').replace('’',',')})
    overrides={}
    for h in soup.find_all(['h3','h4','h5']):
        t=clean(h.get_text(' ',strip=True));n=norm(t);date=re.search(r'\b(\d{2})/(\d{2})/(\d{4})\b',t)
        if date and 'horario normal' in n:
            day=int(date[1]);month=int(date[2]);year=int(date[3]);ds=f'{year:04}-{month:02}-{day:02}'
            if 'laborable' in n:overrides[ds]=0
            elif 'sabado' in n:overrides[ds]=5
    declared_codes=[clean(n.get_text(' ',strip=True)) for n in soup.select('.print-route-code')]
    if declared_codes and re.fullmatch(r'L\d+',declared_codes[0],re.I):line['code']=declared_codes[0].upper()
    return {**line,'directions':routes,'periods':periods,'fares':fares,'schedule_urls':schedule_links(soup,line['url'],line['id']),'date_overrides':overrides}
def context_before(table):
    parts=[]
    for n in table.find_all_previous(['h1','h2','h3','h4','h5','p','div'],limit=30):
        if table in n.descendants:continue
        t=clean(n.get_text(' ',strip=True))
        if t and len(t)<200:parts.append(t)
        if len(parts)>8:break
    return list(reversed(parts))
def context_meta(tokens):
    joined=' '.join(tokens);m=VALID.search(joined)
    if not m:raise DataError('Tabla sin vigencia inequívoca')
    ds=[re.sub(r'^Sentido\s*:\s*','',t,flags=re.I) for t in tokens if re.match(r'^Sentido\s*:',t,re.I)];labels=[t for t in tokens if any(w in norm(t) for w in ('lunes','martes','miercoles','jueves','viernes','sabado','domingo','diario')) and len(t)<100]
    if not ds or not labels:raise DataError('Tabla sin sentido/calendario')
    return ds[-1],labels[-1],m[1],m[2]
def is_time_or_gap(x):
    try:cell(x);return True
    except DataError:return False
def table_blocks(soup,line,url):
    out=[]
    for table in soup.find_all('table'):
        if table.find('table'):continue
        meta_tokens=context_before(table);rows=[]
        for tr in table.find_all('tr'):
            cells=tr.find_all(['td','th'],recursive=False)
            if not cells:continue
            texts=[clean(c.get_text(' ',strip=True)) for c in cells]
            if len(cells)==1 or any(int(c.get('colspan',1))>1 for c in cells):meta_tokens.extend(texts);continue
            for offset in (0,1):
                if len(texts)<=offset+1 or not texts[offset] or is_time_or_gap(texts[offset]):continue
                vals=texts[offset+1:]
                if all(is_time_or_gap(v) for v in vals) and any(':' in v for v in vals):rows.append({'stop':texts[offset],'area':area_for(texts[offset]),'times':vals});break
        if len(rows)<2:continue
        try:
            direction,days,vf,vt=context_meta(meta_tokens);out.append(validate_block({'direction':direction,'days':days,'valid_from':vf,'valid_to':vt,'rows':rows,'source':url,'strategy':'html_cells','date_overrides':line.get('date_overrides',{})},'TMSA'))
        except DataError:continue
    return out
def sequential_blocks(soup,line,url):
    tokens=[clean(x) for x in soup.stripped_strings if clean(x)];starts=[i for i,x in enumerate(tokens) if VALID.fullmatch(x)];out=[]
    for vi in starts:
        try:direction,days,vf,vt=context_meta(tokens[max(0,vi-8):vi+1])
        except DataError:continue
        route=next((r for r in line.get('directions',[]) if norm(r['name'])==norm(direction)),None)
        if not route:continue
        boundary=next((i for i in range(vi+1,len(tokens)) if re.match(r'^Sentido\s*:',tokens[i],re.I) or VALID.fullmatch(tokens[i]) or norm(tokens[i]).startswith('tarifas de la linea')),len(tokens));segment=tokens[vi+1:boundary];names=route['stops'];idx=0;last=None
        for pos,t in enumerate(segment):
            if idx<len(names) and norm(t)==norm(names[idx]):idx+=1;last=pos
            if idx==len(names):break
        if idx!=len(names) or last is None or any(re.fullmatch(r'\d{1,2}:\d{2}',x) for x in segment[:last]):continue
        vals=[]
        for x in segment[last+1:]:
            if is_time_or_gap(x):vals.append(cell(x))
            elif vals and any(w in norm(x) for w in ('lunes','sabado','domingo','horarios de la')):break
        if not vals or len(vals)%len(names):continue
        cols=len(vals)//len(names);rows=[{'stop':s,'area':area_for(s),'times':vals[j*cols:(j+1)*cols]} for j,s in enumerate(names)]
        try:out.append(validate_block({'direction':direction,'days':days,'valid_from':vf,'valid_to':vt,'columns':cols,'rows':rows,'source':url,'strategy':'sequential_exact','date_overrides':line.get('date_overrides',{})},'TMSA'))
        except DataError:pass
    return out
def print_grid_blocks(soup,line,url):
    out=[]
    for grid in soup.select('.print-table-block'):
        try:
            parent=grid.find_parent(class_='horario-print-page')
            if parent is None:raise DataError('Bloque TMSA sin página de impresión delimitada')
            strip=grid.find_previous(class_='print-route-strip');heading=grid.find_previous(class_='encabezado-horario')
            if strip is None or heading is None or strip.find_parent(class_='horario-print-page') is not parent or heading.find_parent(class_='horario-print-page') is not parent:raise DataError('Encabezado horario fuera de su bloque TMSA')
            route_title=strip.select_one('.print-route-title');direction_text=clean(route_title.get_text(' ',strip=True) if route_title else strip.get('aria-label',''))
            if '→' not in direction_text:raise DataError('Sentido TMSA no publicado en el encabezado')
            direction=clean(direction_text.rsplit('→',1)[1]);days_node=heading.select_one('.encabezado-horario-descripcion')
            if days_node is None:raise DataError('Faltan días de servicio TMSA')
            days=clean(days_node.get_text(' ',strip=True));period=VALID.search(heading.get_text(' ',strip=True))
            if not period:raise DataError('Falta vigencia en el bloque horario TMSA')
            stops=grid.select('.horario-columna-paradas .horario-parada-nombre');time_rows=grid.select('.horario-columna-horas .horario-fila-horas')
            if len(stops)<2 or len(stops)!=len(time_rows):raise DataError('Desajuste entre paradas y filas horarias de TMSA')
            declared=re.search(r'--horario-num-trayectos:\s*(\d+)',grid.get('style',''));rows=[];excluded=set()
            for stop_node,time_row in zip(stops,time_rows):
                name=clean(stop_node.get_text(' ',strip=True));cells=time_row.find_all(class_='horario-hora-print',recursive=False)
                if not cells:raise DataError('Fila TMSA sin celdas de expedición')
                values=[]
                for column,c in enumerate(cells):
                    raw=clean(c.get_text(' ',strip=True))
                    if re.fullmatch(r'\d{1,2}:[0-5]\d\*',raw):values.append(cell(raw[:-1]));excluded.add(column)
                    else:values.append(cell(raw))
                if declared and len(values)!=int(declared[1]):raise DataError('El recuento publicado de expediciones TMSA no coincide')
                rows.append({'stop':name,'area':area_for(name),'times':values})
            out.append(validate_block({'direction':direction,'route_label':direction_text,'days':days,'valid_from':period[1],'valid_to':period[2],'rows':rows,'source':url,'strategy':'tmsa_print_grid','excluded_columns':sorted(excluded),'warnings':['Salidas marcadas * (solo días lectivos) excluidas; calendario escolar no verificado'] if excluded else [],'date_overrides':line.get('date_overrides',{})},'TMSA'))
        except DataError as error:line.setdefault('warnings',[]).append('TMSA: '+str(error))
    return out
def sync(client,config):
    metas=discover(client.text(config['index']),config['index']);lines=[]
    for m in metas:
        print('TMSA',m['code'],m['name'],flush=True);line={**m,'operator_code':'TMSA','operator':'TMSA','blocks':[],'checked_at':None,'status_observed_on':today().isoformat()}
        try:
            line=line_page(client.text(m['url']),line);links=line['schedule_urls']
            if not links:links=[s.format(id=m['id']) for s in config.get('fallback_schedule_templates',[])]
            problems=[]
            for url in links[:config.get('max_schedule_resources_per_line',12)]:
                try:
                    soup=BeautifulSoup(client.text(url),'html.parser');bb=print_grid_blocks(soup,line,url) or table_blocks(soup,line,url) or sequential_blocks(soup,line,url)
                    if not bb:problems.append({'url':url,'error':'Matriz no reconocida sin ambigüedad'})
                    line['blocks'].extend(bb)
                except Exception as e:problems.append({'url':url,'error':str(e)})
            line['resource_errors']=problems
            if not line['blocks'] and (links or line.get('periods')):line['sync_error']='Se detectan fuentes, pero no una matriz verificada. Ver diagnóstico.'
        except Exception as e:line['sync_error']=str(e)
        lines.append(line)
    return lines
