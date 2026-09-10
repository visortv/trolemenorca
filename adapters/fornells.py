from __future__ import annotations
import io,re
from urllib.parse import urljoin
from bs4 import BeautifulSoup
from domain import clean,norm,iso,DataError,parse_calendar,area_for,validate_block,minute
PERIOD=re.compile(r'(\d{2}/\d{2}/\d{4})\s*[-–]\s*(\d{2}/\d{2}/\d{4})')
def discover(html,base):
    soup=BeautifulSoup(html,'html.parser');result={}
    for h in soup.find_all(['h2','h3','h4']):
        txt=clean(h.get_text(' ',strip=True));m=re.match(r'^(L\d+)\b\s*(.*)',txt,re.I)
        if not m:continue
        code=m[1].upper();period=PERIOD.search(txt);l=result.setdefault(code,{'id':'fornells-'+code.lower(),'code':code,'name':m[2],'operator':'Autos Fornells','operator_code':'FORNELLS','regular':True,'url':base,'periods':[],'resources':[],'blocks':[]})
        if not period:continue
        l['name']=PERIOD.sub('',m[2]).strip(' ()');p={'from':iso(period[1]),'to':iso(period[2])}
        if p not in l['periods']:l['periods'].append(p)
        for n in h.next_elements:
            if getattr(n,'name',None) in ('h2','h3','h4') and n is not h:break
            if getattr(n,'name',None)=='a' and n.get('href'):
                title=norm(n.get_text(' ',strip=True));u=urljoin(base,n['href'])
                if ('horario general paradas' in title or 'horari general parades' in title) and u not in [r['url'] for r in l['resources']]:l['resources'].append({'url':u,**p})
    for a in soup.find_all('a',href=True):
        n=norm(a.get_text(' ',strip=True))
        if 'alaior' in n and 'punta grossa' in n:result.setdefault('L44',{'id':'fornells-l44','code':'L44','name':clean(a.get_text(' ',strip=True)),'operator':'Autos Fornells','operator_code':'FORNELLS','regular':True,'url':urljoin(base,a['href']),'periods':[],'resources':[],'blocks':[]})
    if not result:raise DataError('No se reconocen líneas regulares en el índice Fornells')
    return list(result.values())
def timetable_cell(text):
    if text is None or clean(text) in ('','>','-','–','—','→'):return None,None
    value=clean(text);gap=re.fullmatch(r'([123①②③\s]*)[>→\-–—]([123①②③\s]*)',value)
    if gap:
        flags=(gap[1]+gap[2]).translate(str.maketrans({'①':'1','②':'2','③':'3'}));return None,''.join(sorted(set(flags.replace(' ',''))))
    match=re.fullmatch(r'((?:[123①②③]\s+)*)(\d{1,2}:[0-5]\d)\s*([123①②③\s]*)',value)
    if not match:raise DataError('Celda PDF ambigua: '+value)
    minute(match[2]);flags=(match[1]+match[3]).translate(str.maketrans({'①':'1','②':'2','③':'3'}));return match[2],''.join(sorted(set(flags.replace(' ',''))))
def matrix_to_blocks(matrix,context,line,source,period):
    blocks=[];header=context.get('header');day=context.get('day');services=[];flags=[];issues=[]
    def flush():
        nonlocal services,flags
        if not services:return
        if not header or not day:raise DataError('Tabla PDF sin cabecera o calendario')
        cols=len(services);rows=[];orders={};excluded=[]
        for i,name in enumerate(header):rows.append({'stop':name,'area':area_for(name),'times':[v[i] for v in services]})
        for c,ann in enumerate(flags):
            if any('2' in x or '3' in x for x in ann):excluded.append(c);issues.append('Servicio con nota de salida no anunciada/recorrido especial excluido');continue
            if any('1' in x for x in ann):
                eligible=[i for i,x in enumerate(ann) if x]
                if line['code']=='L41' and all(any(a in norm(header[i]) for a in ('fornells','cala tirant')) for i in eligible):
                    timed=[i for i,r in enumerate(rows) if r['times'][c] is not None];untimed=[i for i,r in enumerate(rows) if r['times'][c] is None];orders[str(c)]=sorted(timed,key=lambda i:minute(rows[i]['times'][c]))+untimed
                else:excluded.append(c);issues.append('Nota 1 no reconocida en esta línea')
        b={'direction':context.get('direction',''),'days':day,'valid_from':period['from'],'valid_to':period['to'],'rows':rows,'columns':cols,'source':source,'strategy':'pdf_cells','excluded_columns':excluded,'trip_orders':orders,'warnings':list(dict.fromkeys(issues))}
        try:blocks.append(validate_block(b,'FORNELLS'))
        except DataError as e:issues.append(str(e))
        services=[];flags=[]
    for row in matrix:
        texts=[clean(x) for x in row];nonempty=[x for x in texts if x]
        if not nonempty:continue
        joined=' '.join(nonempty)
        if any(x in norm(joined) for x in ('lunes','dilluns','sabado','dissabte','domingo','diumenge')):flush();parse_calendar(joined);day=joined;continue
        if any(re.search(r'\d+:\d+',t) for t in texts):
            if not header or len(texts)!=len(header):raise DataError('Columnas PDF sin cabecera inequívoca')
            try:
                parsed=[timetable_cell(x) for x in row];services.append([p[0] for p in parsed]);flags.append([p[1] or '' for p in parsed])
            except DataError as e:issues.append(str(e))
        elif len(nonempty)==len(row) and len(row)>=2 and not any(re.search(r'salidas no anunciadas|horarios|direccio',norm(t)) for t in texts):flush();header=texts
    flush();context['header']=header;context['day']=day;return blocks,issues
def _parse_pdf_tables(data,line,resource):
    import pdfplumber
    if not data.startswith(b'%PDF'):raise DataError('El recurso no es un PDF')
    blocks=[];problems=[];context={}
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        text='\n'.join(p.extract_text() or '' for p in pdf.pages);m=PERIOD.search(text)
        if not m:raise DataError('PDF sin vigencia visible; no se presupone un año completo')
        p={'from':iso(m[1]),'to':iso(m[2])}
        if resource.get('from') and (resource['from'],resource['to'])!=(p['from'],p['to']):raise DataError('La fecha del índice no coincide con la vigencia del PDF')
        for page in pdf.pages:
            tables=page.find_tables(table_settings={'vertical_strategy':'lines','horizontal_strategy':'lines','snap_tolerance':3,'join_tolerance':3})
            for table in sorted(tables,key=lambda t:t.bbox[1]):
                top=table.bbox[1];above=page.crop((0,0,page.width,max(1,top))).extract_text() or '';dirs=re.findall(r'DIRECCI[ÓO]\s*[→\-–>]\s*([^\n]+)',above,re.I)
                if dirs:
                    dr=clean(dirs[-1]);changed=dr!=context.get('direction');context['direction']=dr
                    if changed:context.pop('header',None);context.pop('day',None)
                if not context.get('direction'):continue
                try:bb,errors=matrix_to_blocks(table.extract(),context,line,resource['url'],p);blocks.extend(bb);problems.extend(errors)
                except DataError as e:problems.append(str(e))
    if not blocks:raise DataError('No se ha reconocido una tabla PDF verificable: '+'; '.join(problems[:3]))
    return blocks,problems
def _direction_label(text):
    match=re.search(r'DIRECCI[ÓO]\s*[→\-–>]\s*(.*)',text,re.I)
    if not match:return None
    words=[]
    for word in match[1].split():
        if any(c.isalpha() for c in word) and word.upper()!=word:break
        words.append(word)
    label=clean(' '.join(words));return label or None
def _chars_text(chars):
    from pdfplumber.utils import extract_text
    return clean(extract_text(chars,x_tolerance=1,y_tolerance=2) if chars else '')
def _header_geometry(page,top,bottom):
    groups={}
    for rect in page.rects:
        if rect['x0']<0 or rect['x1']>page.width or rect['top']<top or rect['bottom']>bottom or rect['width']<10 or rect['height']<8:continue
        band=(round(rect['top'],1),round(rect['bottom'],1));groups.setdefault(band,{})[(round(rect['x0'],1),round(rect['x1'],1))]=rect
    candidates=[]
    for band,rectangles in groups.items():
        cells=sorted(rectangles.values(),key=lambda r:r['x0'])
        if len(cells)<2 or any(abs(a['x1']-b['x0'])>1 for a,b in zip(cells,cells[1:])):continue
        labels=[]
        for r in cells:
            chars=[c for c in page.chars if r['x0']<=(c['x0']+c['x1'])/2<r['x1'] and r['top']<=(c['top']+c['bottom'])/2<r['bottom']];labels.append(_chars_text(chars))
        if not all(label and re.search(r'[A-Za-zÀ-ÿ]',label) and not re.search(r'\d+:\d+|dilluns|lunes|www\.',label,re.I) for label in labels):continue
        candidates.append((band,cells,labels))
    if not candidates:return None
    _,cells,labels=max(candidates,key=lambda item:item[0][1]);return {'header':labels,'edges':[r['x0'] for r in cells]+[cells[-1]['x1']],'bottom':cells[-1]['bottom']}
def _is_calendar_line(text):return len(text)<300 and bool(re.search(r'\b(?:lunes|martes|miercoles|jueves|viernes|sabados?|domingos?|dilluns|dimarts|dimecres|dijous|divendres|dissabtes?|diumenges?)\b',norm(text)))
def _parse_pdf_geometry(data,line,resource):
    import pdfplumber
    blocks=[];problems=[];matrix=[];context={};geometry=None
    def flush():
        nonlocal matrix
        if not matrix:return
        bb,issues=matrix_to_blocks(matrix,context.copy(),line,resource['url'],period)
        for block in bb:block['strategy']='pdf_header_coordinates'
        blocks.extend(bb);problems.extend(issues);matrix=[]
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        whole_text='\n'.join(p.extract_text() or '' for p in pdf.pages);match=PERIOD.search(whole_text)
        if not match:raise DataError('PDF sin vigencia visible; no se presupone un año completo')
        period={'from':iso(match[1]),'to':iso(match[2])}
        if resource.get('from') and (resource['from'],resource['to'])!=(period['from'],period['to']):raise DataError('La fecha del índice no coincide con la vigencia del PDF')
        for page_no,page in enumerate(pdf.pages,1):
            visible=page.filter(lambda o:o.get('object_type')!='char' or (0<=(o['x0']+o['x1'])/2<=page.width and 0<=(o['top']+o['bottom'])/2<=page.height));text_lines=visible.extract_text_lines(x_tolerance=1,y_tolerance=2,return_chars=True)
            for index,textline in enumerate(text_lines):
                text=clean(textline['text']);direction=_direction_label(text)
                if direction:
                    flush();calendar=next((v for v in text_lines[index+1:] if _is_calendar_line(v['text'])),None);geometry=_header_geometry(page,textline['bottom'],calendar['top']) if calendar else None
                    if not geometry:context={};problems.append(f'Página {page_no}: cabecera no resuelta para {direction}');continue
                    context={'direction':direction,'header':geometry['header']};matrix=[geometry['header']];continue
                if not geometry or not context:continue
                if _is_calendar_line(text):parse_calendar(text);matrix.append([text]+[None]*(len(geometry['header'])-1));context['seen_calendar']=True;continue
                if not context.get('seen_calendar') or not re.search(r'\d+:\d+',text):continue
                if re.search(r'[^\d\s:>→\-–—①②③]',text):continue
                chars=textline['chars'];edges=geometry['edges'];values=[_chars_text([c for c in chars if edges[i]<=(c['x0']+c['x1'])/2<edges[i+1]]) for i in range(len(edges)-1)];outside=[c for c in chars if clean(c['text']) and not edges[0]<=(c['x0']+c['x1'])/2<edges[-1]]
                if outside:problems.append(f'Página {page_no}, fila y={textline["top"]:.1f}: caracteres fuera de las columnas; fila excluida');continue
                matrix.append(values)
        flush()
    if not blocks:raise DataError('No se ha reconocido una tabla PDF por coordenadas: '+'; '.join(problems[:3]))
    return blocks,list(dict.fromkeys(problems))
def parse_pdf(data,line,resource):
    if not data.startswith(b'%PDF'):raise DataError('El recurso no es un PDF')
    try:return _parse_pdf_geometry(data,line,resource)
    except DataError as geometric_error:
        try:return _parse_pdf_tables(data,line,resource)
        except (DataError,ValueError) as table_error:raise DataError(f'{geometric_error}; lector de tablas: {table_error}') from geometric_error
def parse_fares_page(html):
    soup=BeautifulSoup(html,'html.parser');lines=[];current=None
    for table in soup.find_all('table'):
        for row in table.find_all('tr'):
            cells=[clean(td.get_text(' ',strip=True)) for td in row.find_all(['th','td'])]
            if not cells:continue
            if len(cells)==1 and re.fullmatch(r'L\d+',cells[0],re.I):current=cells[0].upper();continue
            if len(cells)>=2 and current and cells[0] and cells[1] and re.search(r'€',cells[1]):lines.append((current,{'route':cells[0],'price':cells[1].replace(' ','')}))
    out={}
    for code,item in lines:out.setdefault(code,[]).append(item)
    return out
def sync(client,config):
    lines=discover(client.text(config['index']),config['index'])
    for line in lines:
        line['resource_errors']=[]
        for resource in line['resources'][:config.get('max_schedule_resources_per_line',12)]:
            try:
                data=client.get(resource['url'])['bytes'];bb,issues=parse_pdf(data,line,resource);line['blocks'].extend(bb);line.setdefault('resource_checks',[]).append({'url':resource['url'],'blocks':len(bb),'strategy':'pdf_header_coordinates','warnings':issues})
                if issues:line.setdefault('warnings',[]).extend(issues)
            except Exception as e:line['resource_errors'].append({'url':resource['url'],'error':str(e)})
        if line['resource_errors']:line['sync_error']='Uno o varios PDF no se han podido interpretar con seguridad'
        print('FORNELLS',line['code'],len(line['blocks']),'bloques',flush=True)
    return lines
