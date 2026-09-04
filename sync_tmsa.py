
from bs4 import BeautifulSoup
from datetime import datetime
from pathlib import Path
import requests, re, json, os, unicodedata

BASE="https://www.tmsa.es"
OUT=Path(__file__).with_name("data_snapshot.json")
TMP=Path(__file__).with_name("data_snapshot.tmp.json")
SEED=Path(__file__).with_name("seed_snapshot.json")
LOG=Path(__file__).with_name("sync_error.log")

S=requests.Session()
S.headers.update({
    "User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/152 Safari/537.36",
    "Accept-Language":"es-ES,es;q=0.9"
})

# IDs/líneas publicadas actualmente por TMSA.
CATALOG=[
 ("601","L01","Maó-Ciutadella"),
 ("602","L02","Maó-Es Castell"),
 ("603","L03","Maó-Sant Lluís"),
 ("614","L14","Bus Exprés Maó-Ciutadella"),
 ("618","L18","Maó-Instituts Bintalfa"),
 ("621","L21","Maó-Sant Climent"),
 ("622","L22","Maó-Es Canutells"),
 ("624","L24","Maó-Sa Mesquida-Cala Llonga"),
 ("625","L25","Maó-Trebalúger-Maó"),
 ("631","L31","Maó-Cala en Porter"),
 ("632","L32","Maó-Son Bou"),
 ("633","L33","Cala en Porter-Alaior"),
 ("651","L51","Maó-Cala Galdana"),
 ("652","L52","Ciutadella-Cala Galdana"),
 ("653","L53","Ferreries-Cala Galdana"),
 ("654","L54","Es Migjorn Gran-Ferreries"),
 ("671","L71","Maó-Sant Tomàs"),
 ("672","L72","Ciutadella-Sant Tomàs"),
 ("673","L73","Maó-Alaior-Es Migjorn Gran"),
 ("691","L91","Maó-Alcalfar-S'Algar"),
 ("692","L92","Maó-Sant Lluís-Punta Prima"),
 ("693","L93","Maó-Sant Lluís-Binibèquer"),
 ("694","L94","Maó-Sant Lluís-Binissafúller"),
]

AREA_ALIASES=[
 ("Maó",["maó","mao","hospital mateu orfila","ies joan ramis","av francesc femenies","cementiri de mao","cementiri de maó"]),
 ("Ciutadella",["ciutadella","plaça de la pau","placa de la pau","platja gran","bisbe juano","via perimetral","josep mascaró pasarius","josep mascaro pasarius","piscina municipal"]),
 ("Es Castell",["es castell","església des castell","esglesia des castell","fontanelles","son vilar"]),
 ("Sant Lluís",["sant lluís","sant lluis"]),
 ("Sant Climent",["sant climent"]),
 ("Alaior",["alaior","l'argentina","l argentina"]),
 ("Es Mercadal",["es mercadal","mercadal"]),
 ("Ferreries",["ferreries"]),
 ("Es Migjorn Gran",["es migjorn gran"]),
 ("Cala en Porter",["cala en porter"]),
 ("Son Bou",["son bou","torre solí","torre soli","bella mirada","club san jaime"]),
 ("Cala Galdana",["cala galdana"]),
 ("Sant Tomàs",["sant tomàs","sant tomas"]),
 ("Es Canutells",["es canutells","canutells"]),
 ("Sa Mesquida",["sa mesquida"]),
 ("Cala Llonga",["cala llonga"]),
 ("Trebalúger",["trebalúger","trebaluger"]),
 ("Alcalfar",["alcalfar"]),
 ("S'Algar",["s'algar","s algar"]),
 ("Punta Prima",["punta prima"]),
 ("Binibèquer",["binibèquer","binibequer","binibeca"]),
 ("Binissafúller",["binissafúller","binissafuller"]),
 ("Bintalfa",["bintalfa"]),
]

def clean(x):
    return re.sub(r"\s+"," ",x or "").strip()

def norm(x):
    x=unicodedata.normalize("NFKD",clean(x)).encode("ascii","ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+"," ",x).strip()

def fetch(url,timeout=20):
    r=S.get(url,timeout=timeout)
    r.raise_for_status()
    return r.text

def direct_area(stop):
    n=norm(stop)
    for area,aliases in AREA_ALIASES:
        if any(norm(a) in n for a in aliases):
            return area
    return None

def infer_areas(stops,line_name):
    direct=[direct_area(s) for s in stops]
    # endpoints from line name help with street-only stops
    endpoint_areas=[]
    for area,aliases in AREA_ALIASES:
        if any(norm(a) in norm(line_name) for a in aliases):
            endpoint_areas.append(area)
    out=[]
    for i,s in enumerate(stops):
        if direct[i]:
            out.append(direct[i]); continue
        left=right=None
        for j in range(i-1,-1,-1):
            if direct[j]: left=(j,direct[j]); break
        for j in range(i+1,len(stops)):
            if direct[j]: right=(j,direct[j]); break
        if left and right and left[1]==right[1]:
            out.append(left[1])
        elif left and right:
            out.append(left[1] if i-left[0] <= right[0]-i else right[1])
        elif left:
            out.append(left[1])
        elif right:
            out.append(right[1])
        elif endpoint_areas:
            out.append(endpoint_areas[0])
        else:
            out.append("Otra")
    return out

def current_status():
    html=fetch(BASE+"/transporte-regular")
    soup=BeautifulSoup(html,"html.parser")
    tokens=[clean(x) for x in soup.stripped_strings if clean(x)]
    mode=None
    status={}
    by_name={norm(name):(lid,code,name) for lid,code,name in CATALOG}
    for t in tokens:
        n=norm(t)
        if "lineas actualmente operativas" in n:
            mode=True; continue
        if "lineas actualmente no operativas" in n:
            mode=False; continue
        for nn,(lid,code,name) in by_name.items():
            if n==nn:
                if mode is not None:
                    status[lid]=mode
                break
    return status

def parse_line_page(lid,code,name):
    url=f"{BASE}/linea/{lid}"
    html=fetch(url)
    soup=BeautifulSoup(html,"html.parser")
    tokens=[clean(x) for x in soup.stripped_strings if clean(x)]

    start=None; end=None
    for i,t in enumerate(tokens):
        n=norm(t)
        if start is None and "recorrido de la linea" in n:
            start=i+1
            continue
        if start is not None and "horarios de la linea" in n:
            end=i
            break
    if start is None:
        raise RuntimeError("No se encontró 'Recorrido de la línea'")
    if end is None:
        end=len(tokens)

    directions=[]
    cur=None
    for t in tokens[start:end]:
        if re.match(r"^Sentido\b",t,re.I):
            if cur and len(cur["stops"])>=2:
                cur["areas"]=infer_areas(cur["stops"],name)
                directions.append(cur)
            dname=re.sub(r"^Sentido\s*:?\s*","",t,flags=re.I).strip()
            cur={"name":dname,"stops":[]}
            continue
        if cur:
            n=norm(t)
            if not t or len(t)>180: continue
            if any(x in n for x in ("parada solo de subida","parada solo de bajada","ver mapa","tarifas")):
                continue
            # Most route stops are plain text between direction headings.
            if t not in cur["stops"]:
                cur["stops"].append(t)
    if cur and len(cur["stops"])>=2:
        cur["areas"]=infer_areas(cur["stops"],name)
        directions.append(cur)

    if not directions:
        raise RuntimeError("No se extrajeron sentidos/paradas")

    periods=[]
    text="\n".join(tokens)
    for a,b in re.findall(r"Desde\s+(\d{2}-\d{2}-\d{4})\s+hasta\s+(\d{2}-\d{2}-\d{4})",text,re.I):
        periods.append({"from":a,"to":b})

    # Tarifas oficiales publicadas en la misma página de la línea.
    fares=[]
    fare_start=None
    for i,t in enumerate(tokens):
        if "tarifas de la linea" in norm(t):
            fare_start=i+1
            break
    if fare_start is not None:
        price_re=re.compile(r"^(\d+(?:[,.']\d{1,2})?)\s*€$")
        i=fare_start
        while i < len(tokens)-1:
            n=norm(tokens[i])
            if any(x in n for x in ("suscripcion a avisos","noticias de la linea","rutas y horarios")):
                break
            route_label=tokens[i]
            m=price_re.match(tokens[i+1])
            if m and " - " in route_label:
                price=m.group(1).replace("'",",").replace(".",",")
                fares.append({"route":route_label,"price":price+" €"})
                i+=2
                continue
            i+=1

    return {
        "id":lid,"code":code,"name":name,"url":url,
        "directions":directions,"periods":periods,"fares":fares
    }

TIME_RE=re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$|^-$")
VALID_RE=re.compile(r"^Válido:\s*(\d{2}-\d{2}-\d{4})\s+hasta\s+(\d{2}-\d{2}-\d{4})$",re.I)

def is_day_label(t):
    n=norm(t)
    return len(t)<120 and any(x in n for x in (
        "lunes","martes","miercoles","jueves","viernes","sabado","domingo","festiv"
    ))

def match_direction(line,raw):
    nr=norm(raw)
    exact=[d for d in line["directions"] if norm(d["name"])==nr]
    if exact: return exact[0]
    c=[d for d in line["directions"] if nr in norm(d["name"]) or norm(d["name"]) in nr]
    return c[0] if c else None

def parse_schedule(line):
    # Éste es el recurso "Horarios actuales" que usa TMSA.
    url=f"{BASE}/es/horarios/{line['id']}/VISIBLE/1"
    html=fetch(url)
    soup=BeautifulSoup(html,"html.parser")
    tokens=[clean(x) for x in soup.stripped_strings if clean(x)]

    blocks=[]
    for vi,t in enumerate(tokens):
        m=VALID_RE.match(t)
        if not m:
            continue

        direction_raw=None
        dir_idx=None
        for j in range(vi-1,max(-1,vi-10),-1):
            if re.match(r"^Sentido\s*:",tokens[j],re.I):
                direction_raw=clean(tokens[j].split(":",1)[1])
                dir_idx=j
                break
        if not direction_raw:
            continue
        route=match_direction(line,direction_raw)
        if not route:
            continue

        day=""
        if dir_idx is not None:
            for j in range(dir_idx-1,max(-1,dir_idx-8),-1):
                if is_day_label(tokens[j]):
                    day=tokens[j]
                    break

        expected=route["stops"]
        # Find the complete stop sequence after Valid.
        ei=0; k=vi+1; last=None
        while k<len(tokens) and ei<len(expected):
            if norm(tokens[k])==norm(expected[ei]):
                ei+=1; last=k
            elif k>vi+1 and VALID_RE.match(tokens[k]):
                break
            k+=1
        if ei!=len(expected) or last is None:
            continue

        vals=[]; k=last+1
        while k<len(tokens):
            if VALID_RE.match(tokens[k]) and vals: break
            if re.match(r"^Sentido\s*:",tokens[k],re.I) and vals: break
            if is_day_label(tokens[k]) and vals: break
            if norm(tokens[k]).startswith("tarifas de la linea"): break
            if TIME_RE.match(tokens[k]):
                vals.append(tokens[k])
            k+=1

        n=len(expected)
        usable=(len(vals)//n)*n
        if usable<n:
            continue
        vals=vals[:usable]
        cols=usable//n
        rows=[]
        for r,stop in enumerate(expected):
            rows.append({
                "stop":stop,
                "area":route["areas"][r] if r<len(route["areas"]) else "Otra",
                "times":vals[r*cols:(r+1)*cols]
            })
        blocks.append({
            "id":f"{line['id']}-{len(blocks)}",
            "direction":route["name"],
            "days":day,
            "valid_from":m.group(1),
            "valid_to":m.group(2),
            "columns":cols,
            "rows":rows,
            "source":url
        })

    # Deduplicate exact blocks.
    uniq=[]; seen=set()
    for b in blocks:
        key=(norm(b["direction"]),norm(b["days"]),b["valid_from"],b["valid_to"],
             b["columns"],tuple(r["stop"] for r in b["rows"]))
        if key not in seen:
            seen.add(key); uniq.append(b)
    for i,b in enumerate(uniq):
        b["id"]=f"{line['id']}-{i}"
    return url,uniq

def sync_all():
    st=current_status()
    snap={
        "source":BASE+"/transporte-regular",
        "synced_at":datetime.now().astimezone().isoformat(),
        "seed":False,
        "lines":[]
    }
    for idx,(lid,code,name) in enumerate(CATALOG,1):
        print(f"[{idx}/{len(CATALOG)}] {code} {name}")
        line={
            "id":lid,"code":code,"name":name,
            "operational":st.get(lid),
            "directions":[],"blocks":[],
            "sync_complete":False
        }
        try:
            parsed=parse_line_page(lid,code,name)
            line.update(parsed)
            # Non-operational lines keep route info but do not require current schedule.
            if line.get("operational") is False:
                line["sync_complete"]=True
                print(f"    NO OPERATIVA; sentidos={len(line['directions'])}")
            else:
                surl,blocks=parse_schedule(line)
                line["schedule_url"]=surl
                line["blocks"]=blocks
                line["sync_complete"]=bool(line["directions"] and blocks)
                if not line["sync_complete"]:
                    line["sync_error"]="No se obtuvo matriz de horarios/paradas"
                print(f"    sentidos={len(line['directions'])}, bloques={len(blocks)}, complete={line['sync_complete']}")
        except Exception as e:
            line["sync_error"]=repr(e)
            print("    ERROR:",repr(e))
        snap["lines"].append(line)

    # A live snapshot must have at least L01 complete and several usable lines.
    usable=[l for l in snap["lines"] if l.get("operational") is not False and l.get("sync_complete")]
    l01=next((l for l in snap["lines"] if l["id"]=="601"),None)
    if not l01 or not l01.get("sync_complete"):
        raise RuntimeError("L01 no quedó sincronizada con paradas y horarios")
    if len(usable)<1:
        raise RuntimeError("No hay líneas operativas completas")
    snap["validation"]={
        "usable_lines":len(usable),
        "operational_lines":sum(1 for l in snap["lines"] if l.get("operational") is True),
        "complete_line_codes":[l["code"] for l in usable]
    }
    return snap

def main():
    print("SINCRONIZACIÓN DIRECTA TMSA")
    snap=sync_all()
    TMP.write_text(json.dumps(snap,ensure_ascii=False,indent=2),encoding="utf-8")
    os.replace(TMP,OUT)
    print("Snapshot válido guardado.")
    return 0

def fallback(exc):
    msg=f"{datetime.now().astimezone().isoformat()} | {type(exc).__name__}: {exc!r}"
    LOG.write_text(msg,encoding="utf-8")
    print("ERROR SINCRONIZANDO:",msg)
    # Keep previous snapshot only if it has at least one complete line.
    try:
        if OUT.exists():
            d=json.loads(OUT.read_text(encoding="utf-8"))
            if any(l.get("sync_complete") and l.get("blocks") for l in d.get("lines",[])):
                print("Se conserva el último snapshot con horarios.")
                return 0
    except Exception:
        pass
    print("No existe snapshot anterior utilizable.")
    return 1

if __name__=="__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception as e:
        raise SystemExit(fallback(e))
