"""Descarga pública con caché condicional, límites y registro de fuentes."""
from __future__ import annotations
from pathlib import Path
from urllib.parse import urlparse
import hashlib, json, os, time, urllib.error, urllib.request
from domain import DataError, VERSION

def atomic_json(path,value):
    path=Path(path); path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_name(path.name+'.tmp')
    with tmp.open('w',encoding='utf-8') as f:
        json.dump(value,f,ensure_ascii=False,indent=2); f.flush(); os.fsync(f.fileno())
    os.replace(tmp,path)

class Client:
    def __init__(self,directory,hosts,timeout=18):
        self.root=Path(directory); self.root.mkdir(parents=True,exist_ok=True)
        self.hosts=set(hosts); self.timeout=timeout; self.log=[]; self.memo={}
    def allowed(self,url):
        p=urlparse(url)
        if p.scheme not in ('https','http') or p.hostname not in self.hosts or p.username or p.password:
            raise DataError('URL ajena a los dominios de la fuente: '+url)
    def get(self,url):
        self.allowed(url)
        if url in self.memo: return self.memo[url]
        k=hashlib.sha256(url.encode()).hexdigest(); bodypath=self.root/(k+'.bin'); metapath=self.root/(k+'.json')
        try: meta=json.loads(metapath.read_text('utf-8'))
        except Exception: meta={}
        headers={'User-Agent':'MenorcaBusLocal/'+VERSION+' (lector de horarios publicos)', 'Accept-Language':'es-ES,es;q=0.9','Accept':'*/*'}
        if bodypath.exists():
            for a,b in [('etag','If-None-Match'),('last_modified','If-Modified-Since')]:
                if meta.get(a): headers[b]=meta[a]
        t=time.monotonic(); result=None
        class Redirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(_self,req,fp,code,msg,hdrs,newurl):
                self.allowed(newurl)
                return super().redirect_request(req,fp,code,msg,hdrs,newurl)
        opener=urllib.request.build_opener(Redirect())
        for attempt in range(2):
            try:
                with opener.open(urllib.request.Request(url,headers=headers),timeout=self.timeout) as r:
                    raw=r.read(16*1024*1024+1)
                    if len(raw)>16*1024*1024: raise DataError('Documento excede 16 MiB')
                    result={'bytes':raw,'url':r.url,'content_type':r.headers.get('Content-Type',''),'status':r.status}
                    tmp=bodypath.with_suffix('.tmp'); tmp.write_bytes(raw); os.replace(tmp,bodypath)
                    atomic_json(metapath,{'url':url,'final_url':r.url,'content_type':result['content_type'],'etag':r.headers.get('ETag'),'last_modified':r.headers.get('Last-Modified'),'sha256':hashlib.sha256(raw).hexdigest()})
                break
            except urllib.error.HTTPError as e:
                if e.code==304 and bodypath.exists():
                    result={'bytes':bodypath.read_bytes(),'url':meta.get('final_url',url),'content_type':meta.get('content_type',''),'status':304}; break
                if attempt==0 and e.code in (429,500,502,503,504): time.sleep(1); continue
                self.log.append({'url':url,'http':e.code,'error':str(e),'seconds':round(time.monotonic()-t,2)})
                raise
            except (OSError,ValueError) as e:
                self.log.append({'url':url,'error':str(e),'seconds':round(time.monotonic()-t,2)})
                raise
        if result is None: raise DataError('Descarga sin respuesta')
        self.log.append({'url':url,'final_url':result['url'],'http':result['status'],'bytes':len(result['bytes']),'seconds':round(time.monotonic()-t,2)})
        self.memo[url]=result
        return result
    def text(self,url):
        r=self.get(url)
        return r['bytes'].decode('utf-8-sig',errors='replace')
    def json(self,url):
        text=self.text(url)
        try: return json.loads(text)
        except ValueError as e: raise DataError('La fuente no devolvió JSON: '+url) from e
