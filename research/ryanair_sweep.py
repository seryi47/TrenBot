"""Barrido de tarifas Ryanair desde/hacia ALC para todo octubre 2026.

Usa los endpoints publicos de services-api.ryanair.com:
  - farfnd/v4/oneWayFares/{o}/{d}/cheapestPerDay  -> precio minimo por dia
  - timtbl/3/schedules/{o}/{d}/years/{y}/months/{m} -> horarios reales
"""
import json, os, sys, time
from concurrent.futures import ThreadPoolExecutor

import requests

S = os.path.dirname(os.path.abspath(__file__))
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/128.0 Safari/537.36")
HDRS = {"User-Agent": UA, "Accept": "application/json",
        "Accept-Language": "es-ES,es;q=0.9", "Referer": "https://www.ryanair.com/"}
FARE = "https://services-api.ryanair.com/farfnd/v4/oneWayFares/%s/%s/cheapestPerDay"
SCHED = "https://services-api.ryanair.com/timtbl/3/schedules/%s/%s/years/2026/months/10"

sess = requests.Session()
sess.headers.update(HDRS)


def fares(o, d):
    """Devuelve {dia: precio} para octubre 2026, o None si la ruta no existe."""
    for intento in range(3):
        try:
            r = sess.get(FARE % (o, d),
                         params={"outboundMonthOfDate": "2026-10-01", "currency": "EUR"},
                         timeout=25)
            if r.status_code == 404:
                return None
            r.raise_for_status()
            out = (r.json() or {}).get("outbound") or {}
            res = {}
            for f in out.get("fares", []):
                p = f.get("price")
                if f.get("unavailable") or f.get("soldOut") or not p:
                    continue
                res[f["day"]] = round(float(p["value"]), 2)
            return res
        except Exception:
            time.sleep(1.5 * (intento + 1))
    return None


def schedules(o, d):
    """Devuelve {dia_iso: [(numero, salida, llegada)]} de octubre 2026."""
    try:
        r = sess.get(SCHED % (o, d), timeout=25)
        if r.status_code != 200:
            return {}
        res = {}
        for day in (r.json() or {}).get("days", []):
            iso = "2026-10-%02d" % day["day"]
            res[iso] = [("FR" + str(f["number"]), f["departureTime"], f["arrivalTime"])
                        for f in day.get("flights", [])]
        return res
    except Exception:
        return {}


def main():
    routes = json.load(open(os.path.join(S, "..", "..", "..", "x"), "r")) if False else None
    dests = json.load(open(sys.argv[1]))
    airports = {}
    for r in dests:
        a = r["arrivalAirport"]
        airports[a["code"]] = {"name": a["name"], "country": a["country"]["name"],
                               "cc": a["country"]["code"],
                               "lat": a["coordinates"]["latitude"],
                               "lon": a["coordinates"]["longitude"]}
    print("destinos Ryanair desde ALC: %d" % len(airports))

    data = {"airports": airports, "out": {}, "back": {}, "sched_out": {}, "sched_back": {}}

    def job(code):
        return code, fares("ALC", code), fares(code, "ALC")

    with ThreadPoolExecutor(max_workers=8) as ex:
        for i, (code, o, b) in enumerate(ex.map(job, airports), 1):
            data["out"][code] = o or {}
            data["back"][code] = b or {}
            if i % 20 == 0:
                print("  ...%d/%d" % (i, len(airports)))

    with open(os.path.join(S, "ryanair_octubre.json"), "w") as fh:
        json.dump(data, fh, ensure_ascii=False)
    print("guardado ryanair_octubre.json")

    # resumen: destinos con salida el 8 o 9 y regreso el 11 o 12
    IDA = ["2026-10-08", "2026-10-09"]
    VUE = ["2026-10-11", "2026-10-12"]
    filas = []
    for code, info in airports.items():
        o = data["out"][code]
        b = data["back"][code]
        mo = min([(o[d], d) for d in IDA if d in o], default=None)
        mb = min([(b[d], d) for d in VUE if d in b], default=None)
        if mo or mb:
            filas.append((code, info["name"], info["country"],
                          mo[0] if mo else None, mo[1] if mo else "",
                          mb[0] if mb else None, mb[1] if mb else ""))
    filas.sort(key=lambda x: (x[3] or 9e9) + (x[5] or 9e9))
    print("\n%-5s %-26s %-16s %8s %-11s %8s %-11s" %
          ("IATA", "Ciudad", "Pais", "IDA", "dia", "VUELTA", "dia"))
    for f in filas:
        print("%-5s %-26s %-16s %8s %-11s %8s %-11s" %
              (f[0], f[1][:26], f[2][:16],
               ("%.2f" % f[3]) if f[3] else "-", f[4],
               ("%.2f" % f[5]) if f[5] else "-", f[6]))


if __name__ == "__main__":
    main()
