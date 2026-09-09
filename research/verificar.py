"""Verifica precios contra el sistema de venta real de cada aerolinea.

Ryanair: /api/booking/v4/{mkt}/availability  (exige cabeceras client + client-version)
Wizz:    /Api/search/search                  (exige X-RequestVerificationToken)
"""
import json, sys, time

from curl_cffi import requests as cr

RY_CASOS = [
    ("ALC", "VIE", "2026-10-08"), ("ALC", "BTS", "2026-10-09"),
    ("PED", "ALC", "2026-10-11"), ("LNZ", "ALC", "2026-10-12"),
    ("BTS", "ALC", "2026-10-12"), ("BTS", "ALC", "2026-10-11"),
    ("VIE", "ALC", "2026-10-11"), ("BUD", "ALC", "2026-10-11"),
]
WZ_CASOS = [
    ("ALC", "BTS", "2026-10-09"), ("BUD", "ALC", "2026-10-11"),
    ("BTS", "ALC", "2026-10-12"), ("ALC", "BUD", "2026-10-09"),
]
ADULTOS = 2


def ses_ryanair():
    s = cr.Session(impersonate="chrome")
    s.headers.update({"Accept": "application/json, text/plain, */*",
                      "Accept-Language": "es-ES", "client": "desktop",
                      "client-version": "3.213.0",
                      "Referer": "https://www.ryanair.com/es/es/trip/flights/select"})
    s.get("https://www.ryanair.com/es/es", timeout=30)
    return s


def ryanair(s, o, d, fecha):
    u = ("https://www.ryanair.com/api/booking/v4/es-es/availability"
         "?ADT=%d&TEEN=0&CHD=0&INF=0&Origin=%s&Destination=%s&promoCode="
         "&IncludeConnectingFlights=false&DateOut=%s&DateIn=&FlexDaysBeforeOut=0"
         "&FlexDaysOut=0&RoundTrip=false&ToUs=AGREED&Disc=0" % (ADULTOS, o, d, fecha))
    r = s.get(u, timeout=40)
    if r.status_code != 200:
        return "HTTP %s" % r.status_code, []
    j = r.json()
    out = []
    for t in j.get("trips", []):
        for dt in t.get("dates", []):
            if not dt["dateOut"].startswith(fecha):
                continue
            for f in dt.get("flights", []):
                fares = (f.get("regularFare") or {}).get("fares") or []
                out.append({"vuelo": f["flightNumber"], "sale": f["time"][0][11:16],
                            "llega": f["time"][1][11:16], "dur": f.get("duration"),
                            "plazas": f.get("faresLeft"),
                            "precio_pax": fares[0]["amount"] if fares else None,
                            "moneda": j.get("currency"),
                            "operado": f.get("operatedBy") or "Ryanair"})
    return "ok", out


def ses_wizz():
    s = cr.Session(impersonate="chrome")
    s.headers.update({"Origin": "https://www.wizzair.com",
                      "Referer": "https://www.wizzair.com/es-es",
                      "Accept": "application/json, text/plain, */*",
                      "Accept-Language": "es-ES,es;q=0.9",
                      "Content-Type": "application/json"})
    s.post("https://be.wizzair.com/29.14.0/Api/asset/culture",
           json={"languageCode": "es-es"}, timeout=30)
    s.headers["X-RequestVerificationToken"] = s.cookies.get("RequestVerificationToken")
    return s


def wizz(s, o, d, fecha):
    pl = {"isFlightChange": False, "isSeniorOrStudent": False, "wdc": False,
          "flightList": [{"departureStation": o, "arrivalStation": d,
                          "departureDate": fecha}],
          "adultCount": ADULTOS, "childCount": 0, "infantCount": 0}
    r = s.post("https://be.wizzair.com/29.14.0/Api/search/search", json=pl, timeout=60)
    if r.status_code != 200:
        return "HTTP %s %s" % (r.status_code, r.text[:80]), []
    j = r.json()
    out = []
    for t in j.get("outboundFlights", []):
        fares = t.get("fares") or []
        barata = None
        for f in fares:
            a = ((f.get("discountedPrice") or f.get("basePrice") or {}) or {}).get("amount")
            if a is not None and (barata is None or a < barata[0]):
                barata = (a, (f.get("discountedPrice") or f.get("basePrice"))["currencyCode"],
                          f.get("bundle"))
        out.append({"vuelo": t.get("flightNumber"),
                    "sale": (t.get("departureDateTime") or "")[11:16],
                    "llega": (t.get("arrivalDateTime") or "")[11:16],
                    "plazas": t.get("availableSeatCount") or t.get("availableSeats"),
                    "precio_pax": barata[0] if barata else None,
                    "moneda": barata[1] if barata else None,
                    "tarifa": barata[2] if barata else None})
    return "ok", out


def main():
    print("### RYANAIR (precio por pasajero, %d adultos en la busqueda)\n" % ADULTOS)
    s = ses_ryanair()
    for o, d, f in RY_CASOS:
        est, vuelos = ryanair(s, o, d, f)
        print("%s->%s %s : %s" % (o, d, f[5:], est))
        for v in vuelos:
            print("     %s  %s->%s (%s)  %s %s  plazas:%s  [%s]" %
                  (v["vuelo"], v["sale"], v["llega"], v["dur"], v["precio_pax"],
                   v["moneda"], v["plazas"], v["operado"]))
        if est == "ok" and not vuelos:
            print("     sin vuelos a la venta ese dia")
        time.sleep(1.5)

    print("\n### WIZZ AIR\n")
    w = ses_wizz()
    for o, d, f in WZ_CASOS:
        est, vuelos = wizz(w, o, d, f)
        print("%s->%s %s : %s" % (o, d, f[5:], est))
        for v in vuelos:
            print("     %s  %s->%s  %s %s  plazas:%s  tarifa:%s" %
                  (v["vuelo"], v["sale"], v["llega"], v["precio_pax"], v["moneda"],
                   v["plazas"], v["tarifa"]))
        time.sleep(3)


if __name__ == "__main__":
    main()
