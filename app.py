
from flask import Flask, jsonify, request, send_from_directory
from pathlib import Path
from datetime import datetime, date
import json, re, unicodedata, os

app=Flask(__name__, static_folder="static")
SNAPSHOT=Path(__file__).with_name("data_snapshot.json")

def clean(x): return re.sub(r"\s+"," ",x or "").strip()
def norm(x):
    x=unicodedata.normalize("NFKD",clean(x)).encode("ascii","ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+"," ",x).strip()

def load():
    try: return json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    except Exception: return {"lines":[]}

def parse_date(s):
    try: return datetime.strptime(s,"%Y-%m-%d").date()
    except Exception: return date.today()

def block_date_ok(b,d):
    try:
        vf=datetime.strptime(b["valid_from"],"%d-%m-%Y").date()
        vt=datetime.strptime(b["valid_to"],"%d-%m-%Y").date()
        return vf<=d<=vt
    except Exception:
        return False

def day_ok(label,d):
    n=norm(label); wd=d.weekday()
    if not n: return True
    # Specials first.
    day_names=["lunes","martes","miercoles","jueves","viernes","sabado","domingo"]
    if "solo los" in n or "nomes" in n:
        mapping={"lunes":0,"martes":1,"miercoles":2,"jueves":3,"viernes":4,"sabado":5,"domingo":6}
        for k,v in mapping.items():
            if k in n: return wd==v
    if "lunes" in n and "viernes" in n: return wd<=4
    if "lunes" in n and "sabado" in n: return wd<=5
    if "sabado" in n and "domingo" in n: return wd in (5,6)
    if ("domingo" in n or "festiv" in n) and "sabado" not in n: return wd==6
    if "sabado" in n and "lunes" not in n: return wd==5
    # Single named weekday.
    mapping={"lunes":0,"martes":1,"miercoles":2,"jueves":3,"viernes":4}
    hits=[v for k,v in mapping.items() if k in n]
    if len(hits)==1: return wd==hits[0]
    return True

def active_blocks(snap,d):
    out=[]
    for line in snap.get("lines",[]):
        if line.get("operational") is False or not line.get("sync_complete",False):
            continue
        for b in line.get("blocks",[]):
            if block_date_ok(b,d) and day_ok(b.get("days",""),d):
                out.append((line,b))
    return out

def rows_index(b):
    return {r["stop"]:i for i,r in enumerate(b.get("rows",[]))}


AREA_ORDER = [
    "Maó","Es Castell","Sant Lluís","Sant Climent","Es Canutells","Sa Mesquida",
    "Cala Llonga","Trebalúger","Alcalfar","S'Algar","Punta Prima","Binibèquer",
    "Binissafúller","Alaior","Cala en Porter","Son Bou","Es Mercadal",
    "Es Migjorn Gran","Ferreries","Cala Galdana","Sant Tomàs","Ciutadella"
]


def topology_edges(snap):
    """
    Topología ESTRICTA:
    sólo relaciones origen->destino que existen realmente en:
    1) directions[].areas sincronizadas desde la página de línea;
    2) rows[].area de matrices horarias.

    No se deducen destinos por el nombre de la línea.
    """
    edges=set()

    # 1. Recorridos sincronizados.
    for line in snap.get("lines",[]):
        if line.get("operational") is False or not line.get("sync_complete",False):
            continue
        for d in line.get("directions",[]):
            areas=[a for a in d.get("areas",[]) if a and a!="Otra"]
            collapsed=[]
            for a in areas:
                if not collapsed or collapsed[-1]!=a:
                    collapsed.append(a)
            for i,a in enumerate(collapsed):
                for b in collapsed[i+1:]:
                    if a!=b:
                        edges.add((a,b))

    # 2. Matrices horarias.
    for line in snap.get("lines",[]):
        if line.get("operational") is False or not line.get("sync_complete",False):
            continue
        for b in line.get("blocks",[]):
            areas=[r.get("area") for r in b.get("rows",[])
                   if r.get("area") and r.get("area")!="Otra"]
            collapsed=[]
            for a in areas:
                if not collapsed or collapsed[-1]!=a:
                    collapsed.append(a)
            for i,a in enumerate(collapsed):
                for dest in collapsed[i+1:]:
                    if a!=dest:
                        edges.add((a,dest))

    return edges

def viable_destinations_for_date(snap, origin, d):
    """
    Devuelve sólo destinos realmente utilizables.
    Si existe matriz válida para la fecha, exige al menos una columna donde
    haya hora tanto en origen como en destino.
    Si no existe matriz válida, usa únicamente el recorrido sincronizado real.
    """
    dests=set()
    had_date_matrix=False

    # Preferencia: matriz horaria válida en la fecha.
    for line,b in active_blocks(snap,d):
        rows=b.get("rows",[])
        origins=[i for i,r in enumerate(rows) if r.get("area")==origin]
        if not origins:
            continue
        had_date_matrix=True

        for oi in origins:
            orow=rows[oi]
            for di in range(oi+1,len(rows)):
                drow=rows[di]
                area=drow.get("area")
                if not area or area in (origin,"Otra"):
                    continue

                cols=max(len(orow.get("times",[])),len(drow.get("times",[])))
                viable=False
                for col in range(cols):
                    ot=orow.get("times",[])
                    dt=drow.get("times",[])
                    dep=ot[col] if col<len(ot) else ""
                    arr=dt[col] if col<len(dt) else ""
                    if dep and dep!="-" and arr and arr!="-":
                        viable=True
                        break
                if viable:
                    dests.add(area)

    # Si hay matrices válidas, NO añadir nada por topología que no tenga servicio.
    if had_date_matrix:
        return dests

    # Sin matriz para esa fecha: usar sólo recorridos sincronizados reales.
    for line in snap.get("lines",[]):
        if line.get("operational") is False or not line.get("sync_complete",False):
            continue
        for direction in line.get("directions",[]):
            areas=[a for a in direction.get("areas",[]) if a and a!="Otra"]
            for i,a in enumerate(areas):
                if a!=origin:
                    continue
                for dest in areas[i+1:]:
                    if dest and dest not in (origin,"Otra"):
                        dests.add(dest)

    return dests


def fare_for(line, origin, destination):
    """Busca tarifa oficial por población, en cualquiera de los dos órdenes."""
    a=norm(origin); b=norm(destination)
    for f in line.get("fares",[]):
        route=f.get("route","")
        if " - " not in route:
            continue
        p1,p2=[clean(x) for x in route.split(" - ",1)]
        n1,n2=norm(p1),norm(p2)
        if (n1==a and n2==b) or (n1==b and n2==a):
            return f.get("price","")
    return ""

def collapsed_areas(rows,start_idx,end_idx):
    out=[]
    for r in rows[start_idx:end_idx+1]:
        a=clean(r.get("area",""))
        if not a or a=="Otra":
            continue
        if not out or out[-1]!=a:
            out.append(a)
    return out
@app.get("/")
def home():
    return send_from_directory("static","index.html")

@app.get("/api/bootstrap")
def bootstrap():
    snap=load()
    origins=set()

    # 1. Todas las poblaciones presentes en matrices sincronizadas.
    for line in snap.get("lines",[]):
        if line.get("operational") is False or not line.get("sync_complete",False):
            continue
        for b in line.get("blocks",[]):
            for r in b.get("rows",[]):
                a=clean(r.get("area",""))
                if a and a!="Otra":
                    origins.add(a)

    # 2. Todas las poblaciones presentes en recorridos sincronizados.
    for line in snap.get("lines",[]):
        if line.get("operational") is False or not line.get("sync_complete",False):
            continue
        for d in line.get("directions",[]):
            for a in d.get("areas",[]):
                a=clean(a)
                if a and a!="Otra":
                    origins.add(a)

    # 3. Si la sincronización aún no ha clasificado áreas, usar catálogo base
    # sólo para que el selector de origen nunca quede vacío.
    if not origins:
        origins.update([
            "Maó","Ciutadella","Alaior","Es Mercadal","Ferreries",
            "Es Castell","Sant Lluís","Sant Climent","Es Migjorn Gran",
            "Cala en Porter","Son Bou","Cala Galdana","Sant Tomàs",
            "Es Canutells","Sa Mesquida","Cala Llonga","Trebalúger",
            "Alcalfar","S'Algar","Punta Prima","Binibèquer","Binissafúller"
        ])

    edges=topology_edges(snap)

    return jsonify({
        "ok":bool(snap.get("lines")),
        "version":"10.8",
        "today":date.today().isoformat(),
        "synced_at":snap.get("synced_at",""),
        "seed":bool(snap.get("seed",False)),
        "sync_error":snap.get("sync_error",""),
        "areas":sorted(origins),
        "topology_edges":len(edges),
        "lines":[{"id":l.get("id"),"code":l.get("code"),"name":l.get("name"),
                  "operational":l.get("operational"),"blocks":len(l.get("blocks",[]))}
                 for l in snap.get("lines",[])]
    })

@app.get("/api/destinations")
def destinations():
    origin=request.args.get("origin","")
    d=parse_date(request.args.get("date",""))
    snap=load()

    dests=viable_destinations_for_date(snap,origin,d)

    return jsonify({
        "ok":True,
        "origin":origin,
        "date":d.isoformat(),
        "destinations":sorted(dests)
    })

@app.get("/api/origin-stops")
def origin_stops():
    origin=request.args.get("origin","")
    destination=request.args.get("destination","")
    d=parse_date(request.args.get("date",""))
    snap=load()

    found={}
    matching_blocks=0

    # PARADAS SIEMPRE desde matrices horarias reales.
    for line,b in active_blocks(snap,d):
        rows=b.get("rows",[])
        dest_indices=[i for i,r in enumerate(rows) if r.get("area")==destination]
        origin_indices=[i for i,r in enumerate(rows) if r.get("area")==origin]
        if not dest_indices or not origin_indices:
            continue
        matching_blocks+=1

        for oi in origin_indices:
            r=rows[oi]
            later=[di for di in dest_indices if di>oi]
            if not later:
                continue

            # La parada sólo aparece si existe al menos UNA expedición completa.
            viable_lines=set()
            for col,dep in enumerate(r.get("times",[])):
                if not dep or dep=="-":
                    continue
                if any(
                    col < len(rows[di].get("times",[]))
                    and rows[di]["times"][col]
                    and rows[di]["times"][col] != "-"
                    for di in later
                ):
                    viable_lines.add(line.get("code") or line.get("id"))

            if viable_lines:
                x=found.setdefault(r["stop"],{"name":r["stop"],"lines":set()})
                x["lines"].update(viable_lines)

    result=[{"name":k,"lines":sorted(v["lines"])} for k,v in found.items()]
    result.sort(key=lambda x:x["name"])

    return jsonify({
        "ok":True,
        "stops":result,
        "matching_blocks":matching_blocks,
        "message":"" if result else "No hay matriz horaria sincronizada para ese trayecto y fecha."
    })

@app.get("/api/departures")
def departures():
    origin=request.args.get("origin","")
    destination=request.args.get("destination","")
    stop=request.args.get("stop","")
    d=parse_date(request.args.get("date",""))
    snap=load()

    services=[]
    for line,b in active_blocks(snap,d):
        rows=b.get("rows",[])
        try: oi=next(i for i,r in enumerate(rows) if r.get("stop")==stop and r.get("area")==origin)
        except StopIteration: continue
        dest_indices=[i for i,r in enumerate(rows) if i>oi and r.get("area")==destination]
        if not dest_indices: continue

        orow=rows[oi]
        for col,dep in enumerate(orow.get("times",[])):
            if not dep or dep=="-": continue
            arrivals=[]
            for di in dest_indices:
                vals=rows[di].get("times",[])
                if col<len(vals) and vals[col] and vals[col]!="-":
                    arrivals.append({"stop":rows[di]["stop"],"arrival":vals[col]})
            if not arrivals: continue
            services.append({
                "key":f"{line.get('id')}|{b.get('id')}|{col}",
                "line_id":line.get("id"),
                "line_code":line.get("code") or line.get("id"),
                "line_name":line.get("name"),
                "direction":b.get("direction"),
                "block_id":b.get("id"),
                "column":col,
                "departure":dep,
                "days":b.get("days",""),
                "valid_from":b.get("valid_from",""),
                "valid_to":b.get("valid_to",""),
                "source":b.get("source",""),
                "arrival_count":len(arrivals),
                "fare":fare_for(line,origin,destination)
            })
    services.sort(key=lambda x:(x["departure"],x["line_code"]))
    return jsonify({"ok":True,"services":services})

@app.get("/api/arrival-stops")
def arrival_stops():
    line_id=request.args.get("line_id","")
    block_id=request.args.get("block_id","")
    origin_stop=request.args.get("origin_stop","")
    destination=request.args.get("destination","")
    try: col=int(request.args.get("column","-1"))
    except Exception: col=-1
    snap=load()

    line=next((l for l in snap.get("lines",[]) if str(l.get("id"))==str(line_id)),None)
    if not line: return jsonify({"ok":False,"error":"Línea no encontrada"}),404
    b=next((x for x in line.get("blocks",[]) if x.get("id")==block_id),None)
    if not b: return jsonify({"ok":False,"error":"Bloque horario no encontrado"}),404

    rows=b.get("rows",[])
    try: oi=next(i for i,r in enumerate(rows) if r.get("stop")==origin_stop)
    except StopIteration: return jsonify({"ok":False,"error":"Parada de salida no encontrada"}),404

    dests=[]
    for di,r in enumerate(rows[oi+1:],start=oi+1):
        if r.get("area")!=destination: continue
        vals=r.get("times",[])
        if col>=0 and col<len(vals) and vals[col] and vals[col]!="-":
            dests.append({
                "stop":r["stop"],
                "arrival":vals[col],
                "via_areas":collapsed_areas(rows,oi,di)
            })

    return jsonify({
        "ok":True,
        "line_code":line.get("code") or line.get("id"),
        "line_name":line.get("name"),
        "direction":b.get("direction"),
        "destinations":dests,
        "source":b.get("source",""),
        "fare":fare_for(line,
                        rows[oi].get("area",""),
                        destination)
    })



@app.get("/api/debug-blocks")
def debug_blocks():
    snap=load()
    return jsonify({
        "ok":True,
        "seed":bool(snap.get("seed",False)),
        "synced_at":snap.get("synced_at",""),
        "lines":[
            {
                "id":l.get("id"),
                "code":l.get("code"),
                "name":l.get("name"),
                "operational":l.get("operational"),
                "directions":len(l.get("directions",[])),
                "blocks":len(l.get("blocks",[]))
            }
            for l in snap.get("lines",[])
        ]
    })

@app.get("/api/debug-topology")
def debug_topology():
    snap=load()
    edges=sorted([{"origin":a,"destination":b} for a,b in topology_edges(snap)],
                 key=lambda x:(x["origin"],x["destination"]))
    return jsonify({
        "ok":True,
        "seed":bool(snap.get("seed",False)),
        "edge_count":len(edges),
        "edges":edges
    })

@app.get("/api/health")
def health():
    snap=load()
    matrix_blocks=sum(len(l.get("blocks",[])) for l in snap.get("lines",[]))
    route_directions=sum(len(l.get("directions",[])) for l in snap.get("lines",[]))
    route_areas=set()
    for l in snap.get("lines",[]):
        for d in l.get("directions",[]):
            for a in d.get("areas",[]):
                if a and a!="Otra":
                    route_areas.add(a)
    return jsonify({
        "ok":bool(snap.get("lines")),
        "line_count":len(snap.get("lines",[])),
        "matrix_blocks":matrix_blocks,
        "route_directions":route_directions,
        "route_area_count":len(route_areas),
        "route_areas":sorted(route_areas),
        "topology_edges":len(topology_edges(snap)),
        "seed":bool(snap.get("seed",False)),
        "sync_error":snap.get("sync_error","")
    })

@app.get("/api/snapshot")
def snapshot():
    s=load()
    return jsonify({
        "ok":bool(s.get("lines")),
        "synced_at":s.get("synced_at",""),
        "seed":s.get("seed",False),
        "sync_error":s.get("sync_error",""),
        "line_count":len(s.get("lines",[])),
        "lines":[{"id":l.get("id"),"code":l.get("code"),"name":l.get("name"),
                  "operational":l.get("operational"),
                  "directions":len(l.get("directions",[])),
                  "blocks":len(l.get("blocks",[])),
                  "sync_complete":bool(l.get("sync_complete",False)),
                  "error":l.get("sync_error","")}
                 for l in s.get("lines",[])]
    })

if __name__=="__main__":
    print("MENORCA BUS V10 - TODAS LAS LINEAS")
    print("http://127.0.0.1:5055/")
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT","5055")), debug=False)
