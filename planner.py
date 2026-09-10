from __future__ import annotations
import re
from fares import quote,common_quote,DEFAULT_SOURCES
from place_labels import describe,place_choices,quote_row
from domain import active_lines,pairs,parse_date,norm,clean,fingerprint,line_periods,status_for,VERSION,today

_FARE_ALIASES={'arenal castell':"arenal d'en castell","arenal d en castell":"arenal d'en castell",'arenal den castell':"arenal d'en castell",'port d addaia':"port d'addaia",'port d addaia ':"port d'addaia",'favaritx':'favàritx','far favaritx':'far favàritx','parking favaritx':'pàrking favàritx','cami de cavalls':'camí de cavalls'}
def _fare_row(line,row): return row if line.get('operator_code') in DEFAULT_SOURCES else quote_row(row)
def fare_place(value):
    v=norm(value or '')
    if not v:return ''
    v=re.sub(r'\blinea\s*l?\d+\b','',v).strip();v=re.sub(r'\s+',' ',v);return norm(_FARE_ALIASES.get(v,v))
def fare_for(line,a,z):
    target={fare_place(a),fare_place(z)};target.discard('')
    for f in line.get('fares',[]):
        parts=[clean(x) for x in re.split(r'\s+[\-–—]\s+',f.get('route','')) if clean(x)]
        if len(parts)!=2:continue
        seen={fare_place(x) for x in parts};seen.discard('')
        if seen==target:return f.get('price','')
    return ''

class Planner:
    def __init__(self,snapshot,d):
        self.snap=snapshot;self.date=parse_date(d);self.services={};self.origins=set();self.routes={};self.place_metadata={}
        for line,b in active_lines(snapshot,self.date):
            rows=b['rows']
            for r in rows:
                meta=self.place_metadata.setdefault(r['area'],dict(r.get('place') or describe(r['area'])));meta.setdefault('lines',[]);meta.setdefault('operators',[])
                if line.get('code') not in meta['lines']:meta['lines'].append(line.get('code'))
                if line.get('operator') not in meta['operators']:meta['operators'].append(line.get('operator'))
            for c,oi,di,dm,am in pairs(b,self.date):
                o,z=rows[oi],rows[di];key=fingerprint([line.get('operator_code'),line.get('id'),b['id'],c,oi]);s=self.services.setdefault(key,{'key':key,'line':line,'block':b,'column':c,'origin_index':oi,'origin_stop':o,'departure':o['times'][c],'departure_minutes':dm,'arrivals':[]});s['arrivals'].append({'row':z,'index':di,'arrival':z['times'][c],'arrival_minutes':am,'next_day':am//1440>dm//1440});self.origins.add(o['area']);self.routes.setdefault(o['area'],set()).add(z['area'])
    def places(self,areas):return place_choices(areas,self.place_metadata)
    def destinations(self,origin):return sorted(self.routes.get(origin,set()))
    def stops(self,origin,destination):
        found={}
        for s in self.services.values():
            r=s['origin_stop']
            if r['area']!=origin or not any(a['row']['area']==destination for a in s['arrivals']):continue
            x=found.setdefault(r['key'],{'key':r['key'],'name':r['stop'],'area':r['area'],'place':r.get('place',describe(r['area'])),'lines':set(),'operators':set()});x['lines'].add(s['line'].get('code',''));x['operators'].add(s['line'].get('operator',''))
        return sorted([{**x,'lines':sorted(x['lines']),'operators':sorted(x['operators'])} for x in found.values()],key=lambda x:(norm(x['name']),x['key']))
    def departures(self,origin,destination,stop):
        out=[]
        for s in self.services.values():
            r=s['origin_stop'];line=s['line'];b=s['block']
            if r['area']!=origin or stop not in (r['key'],r['stop']):continue
            arrivals=[a for a in s['arrivals'] if a['row']['area']==destination]
            if not arrivals:continue
            fq=common_quote([quote(line,_fare_row(line,r),_fare_row(line,a['row']),self.date) for a in arrivals]);out.append({'key':s['key'],'line_id':line.get('id'),'line_code':line.get('code'),'line_name':line.get('name'),'operator':line.get('operator'),'direction':b.get('direction',''),'block_id':b['id'],'column':s['column'],'origin_index':s['origin_index'],'departure':s['departure'],'departure_minutes':s['departure_minutes'],'days':b.get('days',''),'day_mask':b.get('day_mask'),'valid_from':b['valid_from'],'valid_to':b['valid_to'],'source':b['source'],'arrival_count':len(arrivals),'fare':fq.get('price',''),'fare_quote':fq,'freshness':line.get('freshness'),'checked_at':line.get('checked_at'),'warnings':b.get('warnings',[])+b.get('limitations',[])})
        return sorted(out,key=lambda x:(x['departure_minutes'],x['operator'],x['line_code']))
    def arrivals(self,key,destination):
        if key not in self.services:raise ValueError('La salida ya no es válida. Vuelve a seleccionar la hora.')
        s=self.services[key];b=s['block'];rows=b['rows'];line=s['line'];oi=s['origin_index'];c=s['column'];order=b.get('trip_orders',{}).get(str(c),list(range(len(rows))));origins=order.index(oi);out=[]
        for a in s['arrivals']:
            if a['row']['area']!=destination:continue
            end=order.index(a['index']);via=[]
            for i in order[origins:end+1]:
                r=rows[i]
                if r['times'][c] is None:continue
                area=r['area']
                if area.startswith('Parada:'):continue
                if not via or via[-1]!=area:via.append(area)
            fq=quote(line,_fare_row(line,s['origin_stop']),_fare_row(line,a['row']),self.date);out.append({'fare_quote':fq,'fare':fq.get('price',''),'key':a['row']['key'],'stop':a['row']['stop'],'area':a['row']['area'],'place':a['row'].get('place',describe(a['row']['area'])),'arrival':a['arrival'],'next_day':a['next_day'],'via_areas':via,'row_index':a['index']})
        shared=common_quote([a['fare_quote'] for a in out]);return {'ok':True,'destinations':out,'source':b['source'],'operator':line.get('operator'),'fare':shared.get('price',''),'fare_quote':shared}
    def catalog(self):
        out=[]
        for l in self.snap.get('line_catalog',self.snap.get('lines',[])):out.append({'operator':l.get('operator','TMSA'),'code':l.get('code'),'name':l.get('name'),'status':status_for(l,self.date),'periods':line_periods(l),'freshness':l.get('freshness'),'checked_at':l.get('checked_at'),'blocks':len(l.get('blocks',[])),'error':l.get('sync_error'),'source':l.get('url','')})
        return sorted(out,key=lambda x:(x['operator'],x['code'] or ''))
