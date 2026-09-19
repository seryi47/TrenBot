#!/usr/bin/env python3
"""Todas las combinaciones posibles, cruzando compañías.

La ida y la vuelta NO tienen que ser de la misma aerolínea: se puede ir con
Ryanair y volver con Wizz. Y los aeropuertos se agrupan por CIUDAD, porque
Roma FCO de Ryanair y Roma FCO de Wizz son el mismo sitio, y Venecia VCE y
Treviso TSF también (a 40 min en bus).

Reglas: ida el 8 desde las 20:00 o el 9 aterrizando antes de las 20:00;
vuelta el 11 a cualquier hora o el 12 aterrizando en ALC hasta las 18:00;
tope 170 €/persona; fuera Francia, Reino Unido, Irlanda, Alemania, España,
Milán y Turín.
"""
import json
import os
import sys

TOPE = 170.0
PAISES_FUERA = {"Francia", "Reino Unido", "Irlanda", "Alemania", "España"}

# Aeropuertos que son la misma ciudad a efectos de dormir allí.
CIUDAD = {"FCO": "Roma", "CIA": "Roma", "VCE": "Venecia", "TSF": "Venecia",
          "WAW": "Varsovia", "WMI": "Varsovia", "OTP": "Bucarest", "BBU": "Bucarest",
          "KTW": "Katowice", "KRK": "Cracovia", "GDN": "Gdansk", "WRO": "Wroclaw",
          "POZ": "Poznan", "LCJ": "Lodz", "BTS": "Bratislava", "BUD": "Budapest",
          "VIE": "Viena", "SOF": "Sofía", "BEG": "Belgrado", "CLJ": "Cluj-Napoca",
          "RMO": "Chisináu", "CTA": "Catania", "CRL": "Bruselas", "EIN": "Eindhoven",
          "LIS": "Lisboa", "OPO": "Oporto", "HEL": "Helsinki", "ARN": "Estocolmo",
          "RAK": "Marrakech", "TTU": "Tétouan", "MRS": "Marsella"}


def vale_ida(x):
    if not x.get("sale"):
        return False
    if x["fecha"] == "2026-10-08":
        return x["sale"] >= "20:00"
    return bool(x.get("llega")) and "03:00" < x["llega"] < "20:00"


def vale_vuelta(x):
    if x["fecha"] == "2026-10-11":
        return True
    return bool(x.get("llega")) and x["llega"] <= "18:00"


def cargar(*rutas):
    d = {}
    for r in rutas:
        if os.path.exists(r):
            d.update(json.load(open(r, encoding="utf-8")))
    return d


def main(rutas):
    d = cargar(*rutas)
    idas, vueltas = {}, {}       # ciudad -> lista de vuelos con su compañía
    for k, v in d.items():
        if (v.get("pais") or "") in PAISES_FUERA:
            continue
        c = CIUDAD.get(v["iata"], v["iata"])
        for x in v.get("ida", []):
            if x.get("precio") and vale_ida(x):
                idas.setdefault(c, []).append(dict(x, cia=v["cia"], iata=v["iata"],
                                                   pais=v["pais"]))
        for x in v.get("vuelta", []):
            if x.get("precio") and vale_vuelta(x):
                vueltas.setdefault(c, []).append(dict(x, cia=v["cia"], iata=v["iata"],
                                                      pais=v["pais"]))
    filas = []
    for c in sorted(set(idas) & set(vueltas)):
        i = min(idas[c], key=lambda z: z["precio"])
        u = min(vueltas[c], key=lambda z: z["precio"])
        filas.append((i["precio"] + u["precio"], c, i, u))
    filas.sort()
    sig = lambda x: "FR" if x["cia"] == "ryanair" else "W6"
    print("TODAS LAS COMBINACIONES · una ciudad · cruzando compañías · tope %d €\n" % TOPE)
    print("%-14s %-11s %-21s %-21s %8s" % ("ciudad", "país", "IDA", "VUELTA", "TOTAL"))
    print("-" * 82)
    for tot, c, i, u in filas:
        mix = "  ⇄" if i["cia"] != u["cia"] else ""
        print("%-14s %-11s %-21s %-21s %8.2f %s%s"
              % (c[:14], (i["pais"] or "")[:11],
                 "%s %s %s %.0f€" % (sig(i), i["fecha"][5:], i["sale"], i["precio"]),
                 "%s %s %s %.0f€" % (sig(u), u["fecha"][5:], u["sale"], u["precio"]),
                 tot, "✅" if tot <= TOPE else "", mix))
    print("\ndentro de %d €: %d de %d" % (TOPE, sum(1 for f in filas if f[0] <= TOPE), len(filas)))
    mixtas = [f for f in filas if f[2]["cia"] != f[3]["cia"]]
    print("combinaciones que cruzan compañía: %d" % len(mixtas))
    for tot, c, i, u in mixtas:
        print("   %-14s %s ida + %s vuelta = %.2f €" % (c, sig(i), sig(u), tot))


if __name__ == "__main__":
    main(*[sys.argv[1:]] if len(sys.argv) > 1 else [[]])
