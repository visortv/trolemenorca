"""Servidor WSGI local. Misma API/puerto, sin dependencia de Flask para arrancar."""
from __future__ import annotations
import json,mimetypes,os,threading,traceback,subprocess,sys,time
from pathlib import Path
from urllib.parse import parse_qs,unquote
from wsgiref.simple_server import make_server,WSGIServer,WSGIRequestHandler
from socketserver import ThreadingMixIn
from domain import VERSION,today,DataError,parse_date
from storage import ROOT,data_dir,read_json,normalize_snapshot,previous_snapshot
from planner import Planner
from locations import location_payload
from place_labels import audit

class Repository:
    def __init__(self): self.lock=threading.RLock();self.stamp=None;self.snapshot=None;self.planners={}
    def planner(self,date):
        with self.lock:
            path=data_dir()/'data_snapshot.json'
            stamp=(str(path),path.stat().st_mtime_ns if path.exists() else 0)
            if self.stamp!=stamp or self.snapshot is None:
                self.snapshot=previous_snapshot();self.stamp=stamp;self.planners={}
            if date not in self.planners:
                if len(self.planners)>8:self.planners={}
                self.planners[date]=Planner(self.snapshot,date)
            return self.planners[date]
REPO=Repository()

_WEB_SYNC_STARTED=False
_WEB_SYNC_LOCK=threading.Lock()

def _web_sync_loop():
    # Render puede atender peticiones inmediatamente con el snapshot disponible.
    # Después comprueba cambios sin bloquear el health check.
    time.sleep(12)
    first=True
    while True:
        try:
            args=[sys.executable,str(ROOT/'sync_all.py')]
            if first: args.append('--force')
            subprocess.run(args,cwd=str(ROOT),timeout=900,check=False)
        except Exception as exc:
            print('Sincronización web en segundo plano:',repr(exc),flush=True)
        first=False
        time.sleep(4*60*60)

def _start_web_sync_once():
    global _WEB_SYNC_STARTED
    # Gunicorn/Render define PORT. La ejecución local directa de app.py no entra aquí.
    if __name__=='__main__' or not os.environ.get('PORT'):
        return
    with _WEB_SYNC_LOCK:
        if _WEB_SYNC_STARTED:
            return
        _WEB_SYNC_STARTED=True
        threading.Thread(target=_web_sync_loop,name='menorca-smart-sync',daemon=True).start()

_start_web_sync_once()

def api(path,q):
    d=parse_date(q.get('date') or today().isoformat());p=REPO.planner(d.isoformat());snap=p.snap
    if path=='/api/version': return {'ok':True,'app':'menorca-bus','version':VERSION,'port':5055}
    if path=='/api/bootstrap':
        last=read_json(data_dir()/'last_attempt.json')
        return {'ok':True,'version':VERSION,'today':today().isoformat(),'areas':sorted(p.origins),'places':p.places(p.origins),'synced_at':snap.get('synced_at'),'snapshot_id':snap.get('snapshot_id'),'has_data':bool(snap.get('lines')),'sync_report':snap.get('sync_report') or last.get('sync_report',[]),'warning':not snap.get('lines') or any(l.get('freshness') in ('cached','legacy','partial') for l in snap.get('lines',[]))}
    if path=='/api/stop-locations':
        if any(k.lower() in ('lat','lon','lng','latitude','longitude','accuracy') for k in q):
            raise ValueError('Esta API sólo devuelve posiciones públicas de paradas; no acepta ubicación del usuario.')
        return location_payload(p, read_json(data_dir()/'stop_locations.json'),
                                read_json(data_dir()/'GPS_DIAGNOSTICO.json'),
                                destination=q.get('destination',''))
    if path=='/api/debug-locations':
        raw=read_json(data_dir()/'stop_locations.json')
        result=location_payload(p,raw,read_json(data_dir()/'GPS_DIAGNOSTICO.json'))
        return {'ok':True,'version':VERSION,'coverage':result['coverage'],
                'status':result['status'],'checked_at':result['checked_at'],
                'report':read_json(data_dir()/'GPS_DIAGNOSTICO.json')}
    if path=='/api/destinations':
        dests=p.destinations(q.get('origin',''))
        return {'ok':True,'destinations':dests,'places':p.places(dests)}
    if path=='/api/debug-places': return {'ok':True,'version':VERSION,**audit(snap)}
    if path=='/api/origin-stops': return {'ok':True,'stops':p.stops(q.get('origin',''),q.get('destination',''))}
    if path=='/api/departures': return {'ok':True,'services':p.departures(q.get('origin',''),q.get('destination',''),q.get('stop','')),'snapshot_id':snap.get('snapshot_id')}
    if path=='/api/arrival-stops': return p.arrivals(q.get('service_key',''),q.get('destination',''))
    if path=='/api/fares':
        return {'ok':True,'lines':[{'operator':l.get('operator'),'code':l.get('code'),'state':l.get('fare_state','legacy'),'source':l.get('fare_source',l.get('url','')),'observed_on':l.get('fare_observed_on'),'rules':l.get('fare_rules',l.get('fares',[])),'error':l.get('fare_error')} for l in snap.get('line_catalog',snap.get('lines',[]))]}
    if path=='/api/line-catalog': return {'ok':True,'date':d.isoformat(),'lines':p.catalog()}
    if path in ('/api/health','/api/debug-operators','/api/snapshot'):
        counts={}
        for l in snap.get('lines',[]):
            op=l.get('operator','TMSA');x=counts.setdefault(op,{'lines':0,'blocks':0});x['lines']+=1;x['blocks']+=len(l['blocks'])
        return {'ok':True,'ready':bool(snap.get('lines')),'version':VERSION,'line_count':len(snap.get('lines',[])),'matrix_blocks':sum(len(l['blocks']) for l in snap.get('lines',[])),'operators':counts,'source_attempts':snap.get('sync_report',[]),'snapshot_id':snap.get('snapshot_id')}
    raise LookupError('Ruta API no encontrada')

def app(environ,start_response):
    method=environ.get('REQUEST_METHOD','GET');path=unquote(environ.get('PATH_INFO','/'))
    headers=[('Cache-Control','no-store'),('X-Content-Type-Options','nosniff'),('Permissions-Policy','geolocation=(self)'),('Referrer-Policy','no-referrer')]
    status='200 OK';body=b''
    try:
        if method not in ('GET','HEAD'): status='405 Method Not Allowed';raise ValueError('Sólo lectura')
        if path.startswith('/api/'):
            q={k:v[-1] for k,v in parse_qs(environ.get('QUERY_STRING',''),keep_blank_values=True).items()}
            body=json.dumps(api(path,q),ensure_ascii=False).encode('utf-8');headers.append(('Content-Type','application/json; charset=utf-8'))
        else:
            if path=='/': f=ROOT/'static'/'index.html'
            elif path.startswith('/static/'):
                f=(ROOT/path.lstrip('/')).resolve()
                if not f.is_relative_to((ROOT/'static').resolve()):raise LookupError('Archivo no encontrado')
            else: raise LookupError('Página no encontrada')
            if not f.is_file():raise LookupError('Archivo no encontrado')
            body=f.read_bytes();headers.append(('Content-Type',(mimetypes.guess_type(f)[0] or 'application/octet-stream')+('; charset=utf-8' if f.suffix in ('.html','.js','.css') else '')))
    except LookupError as e:
        status='404 Not Found';body=json.dumps({'ok':False,'error':str(e)}).encode();headers=[x for x in headers if x[0]!='Content-Type']+[('Content-Type','application/json; charset=utf-8')]
    except (DataError,ValueError) as e:
        if not status.startswith('405'):status='400 Bad Request'
        body=json.dumps({'ok':False,'error':str(e)},ensure_ascii=False).encode();headers=[x for x in headers if x[0]!='Content-Type']+[('Content-Type','application/json; charset=utf-8')]
    except Exception:
        traceback.print_exc();status='500 Internal Server Error';body=b'{"ok":false,"error":"Error interno. Revisa el registro del servidor."}';headers.append(('Content-Type','application/json; charset=utf-8'))
    headers.append(('Content-Length',str(len(body))));start_response(status,headers)
    return [b'' if method=='HEAD' else body]

class ThreadedServer(ThreadingMixIn,WSGIServer): daemon_threads=True

def serve(host='127.0.0.1',port=5055):
    with make_server(host,port,app,server_class=ThreadedServer) as server:
        print('Menorca Bus '+VERSION+' - http://127.0.0.1:'+str(port)+'/',flush=True)
        server.serve_forever()
if __name__=='__main__': serve(os.environ.get('MENORCA_HOST','0.0.0.0'),int(os.environ.get('PORT','5055')))
