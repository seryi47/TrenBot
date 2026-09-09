"""Refresca solo las TARIFAS de Ryanair (los horarios no cambian) manteniendo
todo lo demás del fichero."""
import json, os, time
from concurrent.futures import ThreadPoolExecutor
import requests

S = os.path.dirname(os.path.abspath(__file__))
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/128.0 Safari/537.36")
FARE = "https://services-api.ryanair.com/farfnd/v4/oneWayFares/%s/%s/cheapestPerDay"
sess = requests.Session()
sess.headers.update({"User-Agent": UA, "Accept": "application/json",
                     "Referer": "https://www.ryanair.com/"})


def fares(o, d):
    for i in range(3):
        try:
            r = sess.get(FARE % (o, d), params={"outboundMonthOfDate": "2026-10-01",
                                                "currency": "EUR"}, timeout=25)
            if r.status_code == 404:
                return {}
            r.raise_for_status()
            out = (r.json() or {}).get("outbound") or {}
            return {f["day"]: round(float(f["price"]["value"]), 2)
                    for f in out.get("fares", [])
                    if f.get("price") and not f.get("unavailable") and not f.get("soldOut")}
        except Exception:
            time.sleep(1.5 * (i + 1))
    return {}


d = json.load(open(os.path.join(S, "ryanair_octubre.json")))
codes = sorted(d["airports"])
print("refrescando %d rutas x2..." % len(codes))
with ThreadPoolExecutor(max_workers=8) as ex:
    res = list(ex.map(lambda c: (c, fares("ALC", c), fares(c, "ALC")), codes))
cambios = 0
for c, o, b in res:
    for lado, nuevo in (("out", o), ("back", b)):
        for dia in ("2026-10-08", "2026-10-09", "2026-10-11", "2026-10-12"):
            viejo = d[lado].get(c, {}).get(dia)
            if nuevo.get(dia) != viejo:
                cambios += 1
    d["out"][c], d["back"][c] = o, b
json.dump(d, open(os.path.join(S, "ryanair_octubre.json"), "w"), ensure_ascii=False)
print("hecho. cambios en fechas clave: %d" % cambios)
