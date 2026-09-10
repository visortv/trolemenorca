from __future__ import annotations
import argparse,copy,json,sys,zipfile
from pathlib import Path
from datetime import datetime,timezone,timedelta
from adapters import tmsa,torres,fornells
from storage import ROOT,data_dir,read_json,previous_snapshot,merge_operator,commit_snapshot
from net import Client,atomic_json
from domain import VERSION
from place_labels import audit
from fares import enrich_lines
from locations import sync_locations
from smart_sync import decide,finish_state,policy,parse_time,load_state
ADAPTERS={'TMSA':tmsa,'TORRES':torres,'FORNELLS':fornells}
def previous_operator(previous,code):return [copy.deepcopy(l) for l in previous.get('line_catalog',previous.get('lines',[])) if l.get('operator_code','TMSA')==code]
def existing_fare_report(lines):
    states=sorted({l.get('fare_state') for l in lines if l.get('fare_state')});rules=sum(len(l.get('fares',[])) for l in lines);sources=sorted({l.get('fare_source') for l in lines if l.get('fare_source')});return {'rules':rules,'states':states or ['conservadas'],'source':', '.join(sources),'state':'conservadas'}
def geo_due(state,config):
    loc=data_dir()/'stop_locations.json'
    if not loc.exists():return True
    stamp=parse_time(state.get('last_locations_sync'))
    if not stamp:
        try:return datetime.now(timezone.utc)-datetime.fromtimestamp(loc.stat().st_mtime,timezone.utc)>=timedelta(hours=policy(config)['locations_refresh_hours'])
        except OSError:return True
    return datetime.now(timezone.utc)-stamp>=timedelta(hours=policy(config)['locations_refresh_hours'])
def write_fast_summary(decision,previous):
    now=datetime.now(timezone.utc).isoformat();reason={'recent_check':'sin comprobación de red: ya se comprobó recientemente','unchanged':'comprobación ligera: fuentes sin cambios','probe_failed_cached':'comprobación ligera parcial: se conservan datos verificados','offline_cached':'sin conexión: se conservan datos verificados'}.get(decision.get('reason'),decision.get('reason',''));text=(f'MENORCA BUS {VERSION}\n'f'Arranque: {now}\n\n'f'SINCRONIZACIÓN INTELIGENTE: {reason}.\n''No se han vuelto a descargar ni reinterpretar todos los horarios.\n'f"Snapshot utilizado: {previous.get('synced_at') or previous.get('sync_attempted_at') or 'anterior verificado'}\n")
    if decision.get('errors'):text+='\nAvisos de comprobación ligera:\n'+''.join(f'  {k}: {v}\n' for k,v in decision['errors'].items())
    (data_dir()/'SYNC_RESUMEN.txt').write_text(text,'utf-8');(ROOT/'SYNC_RESUMEN.txt').write_text(text,'utf-8');print(text,flush=True)
def main(argv=None):
    ap=argparse.ArgumentParser(add_help=False);ap.add_argument('--force',action='store_true');opts,_=ap.parse_known_args(argv);attempted=datetime.now(timezone.utc).isoformat();previous=previous_snapshot();config=read_json(ROOT/'config'/'sources.json');rawdir=data_dir()/'sources';rawdir.mkdir(parents=True,exist_ok=True);decision=decide(previous,rawdir,config,force=opts.force,client_class=Client);selected=set(decision['operators'])
    print('MENORCA BUS '+VERSION+' - sincronización inteligente',flush=True)
    if opts.force:print('Modo forzado: se revisarán todas las fuentes.',flush=True)
    elif decision['reason']=='recent_check':print('Datos comprobados recientemente: arranque inmediato sin red.',flush=True)
    elif decision['reason']=='unchanged':print('Fuentes principales sin cambios: no se releen todos los horarios.',flush=True)
    elif selected:print('Cambios/revisión profunda: '+', '.join(sorted(selected)),flush=True)
    elif decision.get('errors'):print('No se pudo completar la comprobación ligera; se usa la copia verificada.',flush=True)
    if not selected and previous.get('lines'):
        if decision.get('did_probe'):finish_state(data_dir(),decision,config,rawdir,[],now=datetime.now(timezone.utc))
        write_fast_summary(decision,previous);return 0
    all_lines=[];reports=[];deep_success=[]
    for code,adapter in ADAPTERS.items():
        cfg=config[code]
        if code not in selected:
            kept=previous_operator(previous,code);all_lines.extend(kept);fr=existing_fare_report(kept);reports.append({'operator_code':code,'operator':cfg['operator'],'attempted_at':attempted,'mode':'reused_unchanged','success':True,'error':None,'catalog_lines':len(kept),'newly_verified_lines':0,'cached_lines':sum(bool(l.get('blocks')) for l in kept),'verified_blocks':sum(len(l.get('blocks',[])) for l in kept),'requests':decision.get('probe_logs',{}).get(code,[]),'lines':[{'code':l.get('code'),'freshness':l.get('freshness'),'blocks':len(l.get('blocks',[])),'errors':[],'warnings':l.get('warnings',[]),'error':l.get('sync_error')} for l in kept],'fares':fr});print(cfg['operator']+': sin cambios; reutilizado sin sincronización profunda.',flush=True);continue
        client=Client(rawdir/code,cfg['hosts']);error=None;new=[]
        try:new=adapter.sync(client,cfg)
        except Exception as e:error=type(e).__name__+': '+str(e)
        merged=merge_operator(previous,code,new,error,attempted);fare_report=enrich_lines(merged,code,client,cfg,previous,attempted,ROOT/'config/fares_reference.json')
        if error is None:deep_success.append(code)
        all_lines.extend(merged);reports.append({'operator_code':code,'operator':cfg['operator'],'attempted_at':attempted,'mode':'deep_sync','success':error is None,'error':error,'catalog_lines':len(merged),'newly_verified_lines':sum(bool(l.get('blocks')) and l.get('freshness') in ('fresh','partial') for l in merged),'cached_lines':sum(bool(l.get('blocks')) and l.get('freshness')=='cached' for l in merged),'verified_blocks':sum(len(l.get('blocks',[])) for l in merged),'requests':client.log,'lines':[{'code':l.get('code'),'freshness':l.get('freshness'),'blocks':len(l.get('blocks',[])),'errors':l.get('resource_errors',l.get('validation_errors',[])),'warnings':l.get('warnings',[]),'error':l.get('sync_error')} for l in merged],'fares':fare_report});print(cfg['operator']+': '+str(reports[-1]['newly_verified_lines'])+' líneas verificadas; '+str(reports[-1]['cached_lines'])+' conservadas.',flush=True)
    snap={'lines':[l for l in all_lines if l.get('blocks')],'line_catalog':all_lines,'sync_attempted_at':attempted,'sync_report':reports,'source':'TMSA / Bus Torres / Autos Fornells','seed':False};verified=[l.get('checked_at') for l in snap['lines'] if l.get('freshness') in ('fresh','partial') and l.get('checked_at')];snap['synced_at']=max(verified) if verified else previous.get('synced_at')
    if snap['lines']:commit_snapshot(snap)
    else:atomic_json(data_dir()/'last_attempt.json',snap)
    state=finish_state(data_dir(),decision,config,rawdir,deep_success,now=datetime.now(timezone.utc))
    if geo_due(state,config):
        try:
            geo_report=sync_locations(data_dir(),read_json(ROOT/'config'/'geolocation.json'),client_class=Client);state=load_state(data_dir());state['last_locations_sync']=datetime.now(timezone.utc).isoformat();from smart_sync import save_state;save_state(data_dir(),state)
        except Exception as e:geo_report={'status':'unavailable','stops':0,'error':str(e)}
    else:
        old_geo=read_json(data_dir()/'GPS_DIAGNOSTICO.json',{});geo_report={'status':'cached_not_due','stops':old_geo.get('stops',0)}
    print('Ubicaciones de paradas: '+str(geo_report.get('stops',0))+'; '+str(geo_report.get('status')),flush=True);atomic_json(data_dir()/'DIAGNOSTICO_LUGARES.json',audit(snap));atomic_json(data_dir()/'DIAGNOSTICO_FUENTES.json',{'version':VERSION,'attempted_at':attempted,'smart_sync':decision,'reports':reports,'stop_locations':geo_report});text=['MENORCA BUS '+VERSION,'Fecha del intento: '+attempted,'','Sincronización inteligente: '+decision.get('reason','')+'.','Operadores revisados en profundidad: '+(', '.join(selected) if selected else 'ninguno'),'']
    for r in reports:
        text += [r['operator']+f" ({r.get('mode','')}):",f"  Verificadas ahora: {r['newly_verified_lines']}; conservadas: {r['cached_lines']}; bloques: {r['verified_blocks']}"]
        if r['error']:text.append('  ERROR: '+r['error'])
        fr=r.get('fares',{});text.append('  Tarifas: '+str(fr.get('rules',0))+' reglas; '+', '.join(fr.get('states',[fr.get('state','')]))+'; '+str(fr.get('source','')))
        if fr.get('error'):text.append('  AVISO TARIFAS: '+fr['error'])
    text+=['','Cartografía de paradas: '+str(geo_report.get('stops',0))+' ubicaciones; '+str(geo_report.get('status')),'','Arranque normal: evita sincronización profunda si no hay cambios.'];summary='\n'.join(text)+'\n';(data_dir()/'SYNC_RESUMEN.txt').write_text(summary,'utf-8');(ROOT/'SYNC_RESUMEN.txt').write_text(summary,'utf-8');zpath=ROOT/'DIAGNOSTICO_MENORCA.zip'
    try:
        with zipfile.ZipFile(zpath,'w',zipfile.ZIP_DEFLATED) as z:
            for p in [data_dir()/'DIAGNOSTICO_FUENTES.json',data_dir()/'SYNC_RESUMEN.txt',data_dir()/'DIAGNOSTICO_LUGARES.json',data_dir()/'GPS_DIAGNOSTICO.json',data_dir()/'stop_locations.json',data_dir()/'sync_state.json']:
                if p.exists():z.write(p,'report/'+p.name)
    except Exception:pass
    print(summary,flush=True);return 0 if snap['lines'] else 2
if __name__=='__main__':
    try:raise SystemExit(main())
    except KeyboardInterrupt:raise SystemExit(130)
