#!/usr/bin/env python3
"""Barrido completo desde Alicante: TODOS los destinos directos, las dos compañías.

Reglas del viaje (las tuyas):
  IDA     8-oct saliendo >= 20:00   ó   9-oct aterrizando antes de las 20:00
  VUELTA  11-oct a cualquier hora   ó   12-oct aterrizando en ALC <= 18:00
  Directo siempre, 2 adultos, tope 160 €/persona.
  Fuera: Reino Unido, Irlanda, Alemania, España, Milán y Turín.

Guarda todo en research/barrido.json para poder combinar después sin repetir
consultas.
"""
import json
import os
import sys
import time

import curl_cffi.requests as cr

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from botviajes.providers import get_provider          # noqa: E402

RAIZ = os.path.dirname(os.path.abspath(__file__))
PAISES_FUERA = {"gb", "ie", "de", "es"}
IATA_FUERA = {"BGY", "MXP", "LIN", "TRN", "MIL"}      # Milán y Turín
IDA = ["2026-10-08", "2026-10-09"]
VUELTA = ["2026-10-11", "2026-10-12"]


def destinos_ryanair():
    s = cr.Session(impersonate="chrome")
    s.headers.update({"Accept": "application/json", "Accept-Language": "es-ES",
                      "Referer": "https://www.ryanair.com/"})
    r = s.get("https://www.ryanair.com/api/views/locate/searchWidget/routes/es/airport/ALC",
              timeout=40)
    fuera = []
    for x in r.json():
        a = x.get("arrivalAirport") or {}
        pais = ((a.get("country") or {}).get("code") or "").lower()
        if pais in PAISES_FUERA or a.get("code") in IATA_FUERA:
            continue
        fuera.append((a["code"], a.get("name"), (a.get("country") or {}).get("name")))
    return fuera


# El campo `conn` del caché de Wizz lista TODA su red, no solo lo directo desde
# Alicante, así que no sirve para esto. Esta lista salió de probar ruta por ruta
# (research/wizz_completo.log): son los directos reales desde ALC, ya sin Reino
# Unido ni Milán. Se valida sola: si alguna ya no vuela, no dará ida y se cae.
WIZZ_DESDE_ALC = ["BBU", "BEG", "BTS", "BUD", "CLJ", "CTA", "FCO", "GDN",
                  "KRK", "KTW", "OTP", "RMO", "TSF", "VCE", "WAW"]


def destinos_wizz():
    est = json.load(open(os.path.join(os.path.dirname(RAIZ), "data",
                                      "wizz_stations.json"), encoding="utf-8"))
    fuera = []
    for iata in WIZZ_DESDE_ALC:
        info = est.get(iata) or {}
        if (info.get("cc") or "").lower() in PAISES_FUERA or iata in IATA_FUERA:
            continue
        fuera.append((iata, info.get("name") or iata, info.get("country")))
    return fuera


def vale_ida(o, fecha):
    """8-oct solo de noche; 9-oct solo si aterriza antes de las 20:00."""
    if not o.departure:
        return False
    if fecha == "2026-10-08":
        return o.departure >= "20:00"
    return bool(o.arrival) and o.arrival < "20:00" and o.arrival > "03:00"


def vale_vuelta(o, fecha):
    """El 12 hay que estar en Alicante a las 18:00 como muy tarde."""
    if fecha == "2026-10-11":
        return True
    return bool(o.arrival) and o.arrival <= "18:00"


def sondear(prov, o, d, fecha, adults=2):
    try:
        return [x for x in get_provider(prov).search(o, d, fecha, adults=adults)
                if x.price and x.price > 0]
    except Exception as e:
        print("   ! %s %s->%s %s: %s" % (prov, o, d, fecha, str(e)[:60]))
        return []


def main():
    ry = destinos_ryanair()
    wz = destinos_wizz()
    print("destinos válidos: Ryanair %d · Wizz %d" % (len(ry), len(wz)))
    todos = [("ryanair",) + x for x in ry] + [("wizz",) + x for x in wz]
    datos = {}
    for i, (prov, iata, nombre, pais) in enumerate(todos, 1):
        clave = "%s|%s" % (prov, iata)
        datos[clave] = {"iata": iata, "nombre": nombre, "pais": pais,
                        "cia": prov, "ida": [], "vuelta": []}
        for f in IDA:
            for x in sondear(prov, "ALC", iata, f):
                if vale_ida(x, f):
                    datos[clave]["ida"].append(
                        {"fecha": f, "sale": x.departure, "llega": x.arrival,
                         "precio": x.price, "plazas": (x.raw or {}).get("plazas"),
                         "url": x.buy_url})
        if not datos[clave]["ida"]:
            print("%3d/%d  %-4s %-26s sin ida válida" % (i, len(todos), iata, (nombre or "")[:26]))
            continue
        for f in VUELTA:
            for x in sondear(prov, iata, "ALC", f):
                if vale_vuelta(x, f):
                    datos[clave]["vuelta"].append(
                        {"fecha": f, "sale": x.departure, "llega": x.arrival,
                         "precio": x.price, "plazas": (x.raw or {}).get("plazas"),
                         "url": x.buy_url})
        mi = min([y["precio"] for y in datos[clave]["ida"]], default=None)
        mv = min([y["precio"] for y in datos[clave]["vuelta"]], default=None)
        print("%3d/%d  %-4s %-26s ida %-8s vuelta %-8s  %s"
              % (i, len(todos), iata, (nombre or "")[:26],
                 "%.2f" % mi if mi else "-", "%.2f" % mv if mv else "-",
                 "TOTAL %.2f" % (mi + mv) if mi and mv else ""))
        json.dump(datos, open(os.path.join(RAIZ, "barrido.json"), "w"), ensure_ascii=False)
    json.dump(datos, open(os.path.join(RAIZ, "barrido.json"), "w"), ensure_ascii=False)
    print("\nlisto: %d destinos en research/barrido.json" % len(datos))


if __name__ == "__main__":
    main()
