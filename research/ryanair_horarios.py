"""Horarios reales de Ryanair (octubre 2026) para todas las rutas desde/hacia ALC."""
import json, os, sys, time
from concurrent.futures import ThreadPoolExecutor

import requests

S = os.path.dirname(os.path.abspath(__file__))
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/128.0 Safari/537.36")
SCHED = "https://services-api.ryanair.com/timtbl/3/schedules/%s/%s/years/2026/months/10"
sess = requests.Session()
sess.headers.update({"User-Agent": UA, "Accept": "application/json",
                     "Referer": "https://www.ryanair.com/"})


def sched(o, d):
    for intento in range(3):
        try:
            r = sess.get(SCHED % (o, d), timeout=25)
            if r.status_code == 404:
                return {}
            if r.status_code != 200:
                time.sleep(1 + intento); continue
            res = {}
            for day in (r.json() or {}).get("days", []):
                vuelos = day.get("flights") or []
                if not vuelos:
                    continue
                res["2026-10-%02d" % day["day"]] = [
                    ["FR" + str(f["number"]).strip(), f["departureTime"], f["arrivalTime"]]
                    for f in vuelos]
            return res
        except Exception:
            time.sleep(1 + intento)
    return {}


def main():
    datos = json.load(open(os.path.join(S, "ryanair_octubre.json")))
    codes = sorted(datos["airports"])
    print("rutas a consultar: %d x2" % len(codes))
    out, back = {}, {}

    def job(c):
        return c, sched("ALC", c), sched(c, "ALC")

    with ThreadPoolExecutor(max_workers=6) as ex:
        for i, (c, o, b) in enumerate(ex.map(job, codes), 1):
            out[c], back[c] = o, b
            if i % 25 == 0:
                print("  ...%d/%d" % (i, len(codes)))

    datos["sched_out"], datos["sched_back"] = out, back
    json.dump(datos, open(os.path.join(S, "ryanair_octubre.json"), "w"), ensure_ascii=False)
    print("horarios guardados")
    for c in ["BTS", "VIE", "BUD", "PED", "ZAG", "KRK", "SZG", "LNZ"]:
        if c in out:
            for dia in ["2026-10-08", "2026-10-09", "2026-10-11", "2026-10-12"]:
                a = out[c].get(dia); b = back[c].get(dia)
                if a or b:
                    print("  %s %s | ALC->%s %s | %s->ALC %s" %
                          (c, dia[5:], c, a or "-", c, b or "-"))


if __name__ == "__main__":
    main()
