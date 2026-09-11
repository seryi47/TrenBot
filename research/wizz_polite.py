"""Barrido Wizz educado: una sesion, en serie, muchas rutas por peticion.

El endpoint /search/timetable acepta varias entradas en flightList, asi que
agrupamos rutas para hacer pocas llamadas y no provocar 429/503.
"""
import json, os, time


def _base_wizz():
    """Versión de la API de Wizz que esté vigente ahora mismo.

    La suben cada pocas semanas y al jubilar la vieja devuelven 503, así que
    dejarla escrita a fuego rompe el script. Se coge la que el proveedor tiene
    cacheada (él ya sabe auto-detectarla).
    """
    import json as _j, os as _o
    ruta = _o.path.join(_o.path.dirname(_o.path.dirname(_o.path.abspath(__file__))),
                        "data", "wizz_version.json")
    try:
        v = _j.load(open(ruta)).get("version")
    except Exception:
        v = None
    return "https://be.wizzair.com/%s/Api" % (v or "29.16.0")



from curl_cffi import requests as cr

S = os.path.dirname(os.path.abspath(__file__))
BASE = _base_wizz()
DESDE, HASTA = "2026-10-06", "2026-10-16"

CANDIDATOS = [
    "BTS", "BUD", "PRG", "KSC", "TAT", "DEB",            # SK / CZ / HU
    "KRK", "KTW", "WAW", "WRO", "POZ", "GDN", "RZE", "LUZ",  # PL
    "VIE", "SZG", "LNZ",                                  # AT
    "BER", "NUE", "STR", "DTM", "FMM", "FKB",             # DE
    "LJU", "ZAG", "ZAD", "SPU", "RJK", "DBV",             # SI / HR
    "SJJ", "TZL", "BEG", "TGD",                           # BA / RS / ME
    "OTP", "TSR", "CLJ", "IAS", "SOF",                    # RO / BG
    "SKP", "TIA", "PRN", "OHD",                           # MK / AL / XK
    "VNO", "KUN", "TLL",                                  # LT / EE
    "VCE", "TSF", "TRN", "MXP", "BGY",                    # IT
]


def nueva_sesion():
    s = cr.Session(impersonate="chrome")
    s.headers.update({"Origin": "https://www.wizzair.com",
                      "Referer": "https://www.wizzair.com/es-es",
                      "Accept": "application/json, text/plain, */*",
                      "Accept-Language": "es-ES,es;q=0.9",
                      "Content-Type": "application/json"})
    s.post(BASE + "/asset/culture", json={"languageCode": "es-es"}, timeout=30)
    s.headers["X-RequestVerificationToken"] = s.cookies.get("RequestVerificationToken")
    return s


def esperar_desbloqueo(s, maximo=600):
    """Sondea suavemente hasta que la API deje de devolver 503/429."""
    t0 = time.time()
    espera = 20
    while time.time() - t0 < maximo:
        pl = {"flightList": [{"departureStation": "ALC", "arrivalStation": "BTS",
                              "from": DESDE, "to": HASTA}],
              "priceType": "regular", "adultCount": 1, "childCount": 0, "infantCount": 0}
        r = s.post(BASE + "/search/timetable", json=pl, timeout=45)
        if r.status_code == 200:
            print("  API disponible tras %ds" % int(time.time() - t0))
            return True
        print("  bloqueada (%s), reintento en %ds" % (r.status_code, espera))
        time.sleep(espera)
        espera = min(espera + 20, 90)
        s = nueva_sesion()
    return False


def lote(s, rutas):
    """rutas: [(o,d)] -> {(o,d): {dia: (precio, [horas])}}"""
    fl = [{"departureStation": o, "arrivalStation": d, "from": DESDE, "to": HASTA}
          for o, d in rutas]
    pl = {"flightList": fl, "priceType": "regular",
          "adultCount": 1, "childCount": 0, "infantCount": 0}
    for intento in range(4):
        r = s.post(BASE + "/search/timetable", json=pl, timeout=90)
        if r.status_code == 200:
            d = r.json()
            res = {}
            for clave in ("outboundFlights", "returnFlights"):
                for f in d.get(clave, []) or []:
                    o, dd = f.get("departureStation"), f.get("arrivalStation")
                    dia = (f.get("departureDate") or "")[:10]
                    p = (f.get("price") or {}).get("amount")
                    if p is None or not o:
                        continue
                    res.setdefault((o, dd), {})[dia] = (
                        round(float(p), 2), [x[11:16] for x in (f.get("departureDates") or [])])
            return res, None
        if r.status_code == 400:
            return {}, r.text[:100]          # mercado inexistente
        time.sleep(15 * (intento + 1))
    return {}, "HTTP %s" % r.status_code


def main():
    s = nueva_sesion()
    if not esperar_desbloqueo(s):
        print("sigue bloqueada; abortamos"); return
    s = nueva_sesion()

    salida = {"out": {}, "back": {}, "sin_ruta": []}
    # 6 rutas (=12 entradas) por peticion; si el lote falla por mercado invalido,
    # se reintenta ruta a ruta para descartar solo la mala.
    TAM = 6
    grupos = [CANDIDATOS[i:i + TAM] for i in range(0, len(CANDIDATOS), TAM)]
    for gi, g in enumerate(grupos, 1):
        rutas = [("ALC", x) for x in g] + [(x, "ALC") for x in g]
        res, err = lote(s, rutas)
        if err:
            print("[%d/%d] lote %s -> %s ; voy una a una" % (gi, len(grupos), ",".join(g), err))
            res = {}
            for x in g:
                r1, e1 = lote(s, [("ALC", x), (x, "ALC")])
                if e1:
                    salida["sin_ruta"].append(x)
                else:
                    res.update(r1)
                time.sleep(4)
        for x in g:
            salida["out"][x] = res.get(("ALC", x), {})
            salida["back"][x] = res.get((x, "ALC"), {})
        con = [x for x in g if salida["out"][x] or salida["back"][x]]
        print("[%d/%d] %s -> con vuelos: %s" % (gi, len(grupos), ",".join(g),
                                                ",".join(con) or "ninguno"))
        time.sleep(6)

    json.dump(salida, open(os.path.join(S, "wizz_octubre.json"), "w"), ensure_ascii=False)
    print("\nguardado wizz_octubre.json | sin ruta directa: %s" % ",".join(salida["sin_ruta"]))


if __name__ == "__main__":
    main()

# NOTA IMPORTANTE (verificado 03/09/2026): /search/timetable devuelve el precio en
# la moneda de la estacion de salida del PRIMER tramo del flightList. Si se pide
# solo BUD->ALC llega en HUF; poniendo ("ALC","BUD") primero, todo llega en EUR.
# Por eso este barrido manda siempre el par con ALC delante. Ademas flightList
# admite como maximo 2 entradas ("FlightCount_MustBe_OneOrTwo").
