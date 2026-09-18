#!/usr/bin/env python3
"""Precios de las rutas que YA sabemos que cumplen horarios.

Se apoya en research/horarios.json (filtrado con el calendario real) para pedir
solo lo necesario: Ryanair responde 409 "Availability declined" a todo en cuanto
se le insiste, así que cada consulta cuenta. Va despacio a propósito.
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from botviajes.providers import get_provider          # noqa: E402

RAIZ = os.path.dirname(os.path.abspath(__file__))
PAUSA = 2.5

WIZZ = {"BBU": ("Bucarest Băneasa", "Rumanía"), "BEG": ("Belgrado", "Serbia"),
        "BTS": ("Bratislava", "Eslovaquia"), "BUD": ("Budapest", "Hungría"),
        "CLJ": ("Cluj-Napoca", "Rumanía"), "CTA": ("Catania", "Italia"),
        "FCO": ("Roma Fiumicino", "Italia"), "GDN": ("Gdansk", "Polonia"),
        "KRK": ("Cracovia", "Polonia"), "KTW": ("Katowice", "Polonia"),
        "OTP": ("Bucarest Otopeni", "Rumanía"), "RMO": ("Chisináu", "Moldavia"),
        "TSF": ("Venecia Treviso", "Italia"), "VCE": ("Venecia", "Italia"),
        "WAW": ("Varsovia Chopin", "Polonia")}


def vale_ida(x, f):
    if not x.departure:
        return False
    if f == "2026-10-08":
        return x.departure >= "20:00"
    return bool(x.arrival) and "03:00" < x.arrival < "20:00"


def vale_vuelta(x, f):
    return True if f == "2026-10-11" else (bool(x.arrival) and x.arrival <= "18:00")


def pedir(prov, o, d, f):
    try:
        out = [x for x in get_provider(prov).search(o, d, f, adults=2)
               if x.price and x.price > 0]
    except Exception as e:
        print("     ! %s %s->%s %s: %s" % (prov, o, d, f, str(e)[:60]))
        out = []
    time.sleep(PAUSA)
    return out


def main():
    hor = json.load(open(os.path.join(RAIZ, "horarios.json"), encoding="utf-8"))
    objetivo = [("ryanair", k, v["nombre"], v["pais"]) for k, v in hor["validos"].items()]
    objetivo += [("wizz", k, n, p) for k, (n, p) in WIZZ.items()]
    print("pidiendo precios de %d rutas (%d Ryanair + %d Wizz)\n"
          % (len(objetivo), len(hor["validos"]), len(WIZZ)))
    datos = {}
    for i, (prov, iata, nombre, pais) in enumerate(objetivo, 1):
        idas, vueltas = [], []
        for f in ("2026-10-08", "2026-10-09"):
            for x in pedir(prov, "ALC", iata, f):
                if vale_ida(x, f):
                    idas.append({"fecha": f, "sale": x.departure, "llega": x.arrival,
                                 "precio": x.price, "plazas": (x.raw or {}).get("plazas")})
        for f in ("2026-10-11", "2026-10-12"):
            for x in pedir(prov, iata, "ALC", f):
                if vale_vuelta(x, f):
                    vueltas.append({"fecha": f, "sale": x.departure, "llega": x.arrival,
                                    "precio": x.price, "plazas": (x.raw or {}).get("plazas")})
        datos["%s|%s" % (prov, iata)] = {"iata": iata, "nombre": nombre, "pais": pais,
                                         "cia": prov, "ida": idas, "vuelta": vueltas}
        mi = min([y["precio"] for y in idas], default=None)
        mv = min([y["precio"] for y in vueltas], default=None)
        print("%3d/%d  %-8s %-4s %-24s ida %-8s vuelta %-8s %s"
              % (i, len(objetivo), prov, iata, (nombre or "")[:24],
                 "%.2f" % mi if mi else "-", "%.2f" % mv if mv else "-",
                 "TOTAL %.2f" % (mi + mv) if mi and mv else ""))
        json.dump(datos, open(os.path.join(RAIZ, "precios.json"), "w"), ensure_ascii=False)
    print("\nlisto")


if __name__ == "__main__":
    main()
