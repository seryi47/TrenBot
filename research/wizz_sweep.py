"""Barrido de tarifas Wizz Air desde/hacia ALC (octubre 2026).

La API de Wizz (be.wizzair.com) exige la cabecera X-RequestVerificationToken,
cuyo valor sale de la cookie del mismo nombre que entrega /Api/asset/culture.
"""
import json, os, sys, threading, time
from concurrent.futures import ThreadPoolExecutor

from curl_cffi import requests as cr

S = os.path.dirname(os.path.abspath(__file__))
VER = "29.14.0"
BASE = "https://be.wizzair.com/%s/Api" % VER
HDRS = {"Origin": "https://www.wizzair.com", "Referer": "https://www.wizzair.com/es-es",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "es-ES,es;q=0.9", "Content-Type": "application/json"}
_local = threading.local()


def sesion():
    """Una sesion con token por hilo (el token va ligado a la cookie de sesion)."""
    s = getattr(_local, "s", None)
    if s is None:
        s = cr.Session(impersonate="chrome")
        s.headers.update(HDRS)
        s.post(BASE + "/asset/culture", json={"languageCode": "es-es"}, timeout=30)
        s.headers["X-RequestVerificationToken"] = s.cookies.get("RequestVerificationToken")
        _local.s = s
    return s


def mapa():
    s = sesion()
    r = s.get(BASE + "/asset/map?languageCode=es-es&withConnections=true", timeout=90)
    r.raise_for_status()
    return r.json()


def timetable(pares, desde, hasta):
    """pares: [(o,d)]. Devuelve {(o,d): {dia: (precio, [horas])}}."""
    s = sesion()
    fl = [{"departureStation": o, "arrivalStation": d, "from": desde, "to": hasta}
          for o, d in pares]
    pl = {"flightList": fl, "priceType": "regular",
          "adultCount": 1, "childCount": 0, "infantCount": 0}
    for intento in range(3):
        try:
            r = s.post(BASE + "/search/timetable", json=pl, timeout=60)
            if r.status_code == 429:
                time.sleep(3 * (intento + 1)); continue
            if r.status_code != 200:
                return {}, r.text[:120]
            d = r.json()
            res = {}
            for clave in ("outboundFlights", "returnFlights"):
                for f in d.get(clave, []) or []:
                    o, dd = f.get("departureStation"), f.get("arrivalStation")
                    if not o:
                        continue
                    dia = (f.get("departureDate") or "")[:10]
                    p = (f.get("price") or {}).get("amount")
                    horas = [x[11:16] for x in (f.get("departureDates") or [])]
                    if p is None:
                        continue
                    res.setdefault((o, dd), {})[dia] = (round(float(p), 2), horas)
            return res, None
        except Exception as e:
            time.sleep(2 * (intento + 1))
            err = str(e)[:120]
    return {}, err


# Paises con sentido para un viaje de 3-4 dias saltando a un segundo pais.
PAISES = {
    "Eslovaquia", "República Checa", "Hungría", "Polonia", "Alemania", "Austria",
    "Eslovenia", "Croacia", "Serbia", "Bosnia y Herzegovina", "Montenegro",
    "Rumanía", "Bulgaria", "Macedonia del Norte", "Kosovo", "Albania", "Italia",
    "Lituania", "Letonia", "Estonia", "Suiza", "Francia", "Bélgica",
    "Países Bajos", "Dinamarca", "Grecia", "Moldavia",
}


def main():
    d = mapa()
    cities = {c["iata"]: c for c in d["cities"]}
    json.dump(d, open(os.path.join(S, "wizz_map.json"), "w"))
    alc = cities["ALC"]
    destinos = []
    for c in alc.get("connections", []):
        t = cities.get(c["iata"])
        if not t:
            continue
        pais = (t.get("countryName") or "").strip()
        if pais in PAISES and len(c["iata"]) == 3:
            destinos.append(c["iata"])
    # Anadimos a mano aeropuertos clave por si el mapa no los lista como conexion.
    EXTRA = ["PRG", "KRK", "KSC", "TAT", "VIE", "LJU", "ZAG", "SPU", "ZAD", "RJK",
             "BER", "NUE", "STR", "DTM", "FMM", "FKB", "WRO", "POZ", "RZE", "LUZ",
             "WAW", "KTW", "GDN", "BUD", "BTS", "TSF", "VCE", "TRN", "BGY", "MXP",
             "SJJ", "TZL", "BEG", "OTP", "TSR", "SOF", "SKP", "TIA", "PRN", "OHD",
             "VNO", "KUN", "TLL", "RIX", "CLJ", "IAS", "DEB", "GHV", "SBZ", "OMR"]
    destinos = sorted(set(destinos) | set(EXTRA))
    print("destinos Wizz europeos desde ALC: %d" % len(destinos))

    salida = {"airports": {}, "out": {}, "back": {}}
    for iata, c in cities.items():
        salida["airports"][iata] = {
            "name": (c.get("shortName") or "").strip().replace("\n", " "),
            "country": (c.get("countryName") or "").strip(),
            "cc": c.get("countryCode"), "lat": c.get("latitude"), "lon": c.get("longitude")}

    errores = []

    def job(iata):
        res, err = timetable([("ALC", iata), (iata, "ALC")], "2026-10-06", "2026-10-16")
        return iata, res, err

    with ThreadPoolExecutor(max_workers=4) as ex:
        for i, (iata, res, err) in enumerate(ex.map(job, destinos), 1):
            if err:
                errores.append((iata, err))
            salida["out"][iata] = {k: v for k, v in res.get(("ALC", iata), {}).items()}
            salida["back"][iata] = {k: v for k, v in res.get((iata, "ALC"), {}).items()}
            if i % 15 == 0:
                print("  ...%d/%d" % (i, len(destinos)))

    json.dump(salida, open(os.path.join(S, "wizz_octubre.json"), "w"), ensure_ascii=False)
    print("guardado wizz_octubre.json | errores: %d" % len(errores))
    for e in errores[:10]:
        print("   ", e)

    IDA = ["2026-10-08", "2026-10-09"]
    VUE = ["2026-10-11", "2026-10-12"]
    filas = []
    for iata in destinos:
        o, b = salida["out"][iata], salida["back"][iata]
        mo = min([(o[x][0], x, o[x][1]) for x in IDA if x in o], default=None)
        mb = min([(b[x][0], x, b[x][1]) for x in VUE if x in b], default=None)
        if mo or mb:
            a = salida["airports"][iata]
            filas.append((iata, a["name"], a["country"], mo, mb))
    filas.sort(key=lambda f: ((f[3][0] if f[3] else 9e9) + (f[4][0] if f[4] else 9e9)))
    print("\n%-5s %-24s %-16s %-22s %-22s" % ("IATA", "Ciudad", "Pais", "IDA 8/9", "VUELTA 11/12"))
    for f in filas:
        i = "%.2f %s %s" % (f[3][0], f[3][1][5:], ",".join(f[3][2])) if f[3] else "-"
        v = "%.2f %s %s" % (f[4][0], f[4][1][5:], ",".join(f[4][2])) if f[4] else "-"
        print("%-5s %-24s %-16s %-22s %-22s" % (f[0], f[1][:24], f[2][:16], i, v))


if __name__ == "__main__":
    main()
