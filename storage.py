from __future__ import annotations
from datetime import datetime, timezone
from pathlib import Path
import copy,json,os,shutil
from domain import validate_line,DataError,fingerprint,today
from net import atomic_json
ROOT=Path(__file__).resolve().parent

def data_dir():
    specified=os.environ.get('MENORCA_DATA_DIR')
    if specified:return Path(specified).resolve()
    if os.name=='nt':return Path(os.environ.get('LOCALAPPDATA',str(ROOT)))/'MenorcaBus'
    return ROOT/'data'

def read_json(path,default=None):
    try:return json.loads(Path(path).read_text('utf-8'))
    except (OSError,ValueError):return {} if default is None else default

def normalize_snapshot(raw):
    out=copy.deepcopy(raw);lines=[];catalog=[]
    for l in raw.get('lines',[]):
        checked=validate_line(l);checked.setdefault('freshness','legacy');checked.setdefault('checked_at',raw.get('synced_at'))
        if checked['blocks']:lines.append(checked)
        catalog.append(checked)
    known={(l['operator_code'],str(l.get('id'))) for l in catalog}
    for l in raw.get('line_catalog',[]):
        checked=validate_line(l);k=checked['operator_code'],str(checked.get('id'))
        if k not in known:catalog.append(checked);known.add(k)
    out['lines']=lines;out['line_catalog']=catalog;out['schema_version']=2;out['snapshot_id']=out.get('snapshot_id') or fingerprint(lines);return out

def previous_snapshot():
    candidates=[data_dir()/'data_snapshot.json',ROOT/'data_snapshot.json',data_dir()/'backups'/'last_good.json']
    best=None
    for p in candidates:
        raw=read_json(p)
        try:s=normalize_snapshot(raw)
        except (DataError,TypeError,KeyError):continue
        if s.get('lines'):best=s;break
    return best or {'schema_version':2,'lines':[],'line_catalog':[],'snapshot_id':'empty'}

def merge_operator(previous,operator,new_lines,error,attempted):
    old_catalog={str(l.get('id')):l for l in previous.get('line_catalog',previous.get('lines',[])) if l.get('operator_code','TMSA')==operator};old_planner={str(l.get('id')):l for l in previous.get('lines',[]) if l.get('operator_code','TMSA')==operator};result=[]
    if error is not None:
        for l in old_catalog.values():
            l=copy.deepcopy(l);l['freshness']='cached';l['sync_error']=str(error);l['last_attempt_at']=attempted;result.append(l)
        return result
    present=set()
    for new in new_lines:
        l=validate_line(new);lid=str(l.get('id'));present.add(lid);old=old_planner.get(lid);l['last_attempt_at']=attempted;l['freshness']='fresh';l['checked_at']=attempted;issues=l.get('resource_errors') or l.get('validation_errors') or l.get('sync_error')
        if not l['blocks'] and issues and old:
            old=copy.deepcopy(old);old.update({k:v for k,v in l.items() if k not in ('blocks','directions','sync_complete','checked_at')});old['freshness']='cached';old['sync_complete']=True;l=old
        elif old:
            signatures={fingerprint(b) for b in l['blocks']}
            for b in old.get('blocks',[]):
                if b['valid_to']<today().isoformat() and fingerprint(b) not in signatures:l['blocks'].append(copy.deepcopy(b))
            if issues:l['freshness']='partial'
        result.append(l)
    for lid,old in old_catalog.items():
        if lid not in present:
            old=copy.deepcopy(old);old['freshness']='not_in_latest_catalog';old['publication_state']='not_in_latest_catalog';old['blocks']=[b for b in old.get('blocks',[]) if b['valid_to']<today().isoformat()];old['sync_complete']=bool(old['blocks']);result.append(old)
    return result

def commit_snapshot(snap):
    path=data_dir()/'data_snapshot.json';path.parent.mkdir(parents=True,exist_ok=True);old=read_json(path)
    if old.get('lines'):
        try:
            normalized=normalize_snapshot(old)
            if normalized['lines']:backup=path.parent/'backups'/'last_good.json';atomic_json(backup,old)
        except Exception:pass
    snap['snapshot_id']=fingerprint(snap.get('lines',[]));snap['schema_version']=2;atomic_json(path,snap);return path
