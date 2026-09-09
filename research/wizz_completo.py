"""Barrido Wizz de TODOS sus destinos europeos desde Alicante.

El anterior solo miró Centroeuropa y se dejó fuera Francia, Benelux, Alemania
del oeste, Italia... El flightList admite 2 entradas como mucho, así que va
ruta a ruta, despacio, con ALC siempre delante (así los precios llegan en EUR).
"""
import json, os, time
from curl_cffi import requests as cr

S = os.path.dirname(os.path.abspath(__file__))
BASE = "https://be.wizzair.com/29.14.0/Api"
DESDE, HASTA = "2026-10-06", "2026-10-16"
EUROPA = {
    "AT","BE","BA","BG","HR","CZ","DK","EE","FI","FR","DE","GR","HU","IS","IE",
    "IT","XK","LV","LT","LU","MK","MT","MD","ME","NL","NO","PL","PT","RO","RS",
    "SK","SI","ES","SE","CH","GB","AL","UA",
}


def ses():
    s = cr.Session(impersonate="chrome")
    s.headers.update({"Origin": "https://www.wizzair.com",
                      "Referer": "https://www.wizzair.com/es-es",
                      "Accept": "application/json, text/plain, */*",
                      "Accept-Language": "es-ES,es;q=0.9",
                      "Content-Type": "application/json"})
    s.post(BASE + "/asset/culture", json={"languageCode": "es-es"}, timeout=30)
    s.headers["X-RequestVerificationToken"] = s.cookies.get("RequestVerificationToken")
    return s


def pedir(s, iata, adultos=2):
    pl = {"flightList": [
              {"departureStation": "ALC", "arrivalStation": iata, "from": DESDE, "to": HASTA},
              {"departureStation": iata, "arrivalStation": "ALC", "from": DESDE, "to": HASTA}],
          "priceType": "regular", "adultCount": adultos,
          "childCount": 0, "infantCount": 0}
    for i in range(4):
        r = s.post(BASE + "/search/timetable", json=pl, timeout=60)
        if r.status_code == 200:
            return r.json(), None
        if r.status_code == 400:
            return None, "sin ruta directa"
        time.sleep(20 * (i + 1))
    return None, "HTTP %s" % r.status_code


def main():
    s = ses()
    mapa = json.load(open(os.path.join(S, "wizz_map.json")))
    cities = {c["iata"]: c for c in mapa["cities"] if c.get("iata")}
    alc = cities["ALC"]
    cand = sorted({c["iata"] for c in alc.get("connections", [])
                   if len(c.get("iata", "")) == 3
                   and (cities.get(c["iata"], {}).get("countryCode") in EUROPA)})
    print("candidatos europeos: %d" % len(cand))

    salida = {"out": {}, "back": {}, "airports": {}, "sin_ruta": []}
    for i, c in enumerate(cand, 1):
        j, err = pedir(s, c)
        if err:
            salida["sin_ruta"].append(c)
        else:
            for clave in ("outboundFlights", "returnFlights"):
                for f in j.get(clave, []) or []:
                    o, d = f["departureStation"], f["arrivalStation"]
                    dia = f["departureDate"][:10]
                    p = (f.get("price") or {})
                    reg = salida["out"] if o == "ALC" else salida["back"]
                    reg.setdefault(c, {})[dia] = [
                        round(float(p.get("amount", 0)), 2), p.get("currencyCode"),
                        [x[11:16] for x in (f.get("departureDates") or [])]]
            ci = cities.get(c, {})
            salida["airports"][c] = {
                "name": (ci.get("shortName") or "").strip().replace("\n", " "),
                "country": (ci.get("countryName") or "").strip().replace("\n", " "),
                "cc": ci.get("countryCode"),
                "lat": ci.get("latitude"), "lon": ci.get("longitude")}
        if i % 10 == 0:
            print("  %d/%d  (con ruta: %d)" % (i, len(cand), len(salida["airports"])))
        time.sleep(4)

    json.dump(salida, open(os.path.join(S, "wizz_completo.json"), "w"), ensure_ascii=False)
    print("\nrutas directas Wizz desde ALC: %d" % len(salida["airports"]))
    for c in sorted(salida["airports"]):
        a = salida["airports"][c]
        print("  %-4s %-26s %s" % (c, a["name"][:26], a["country"]))


if __name__ == "__main__":
    main()
