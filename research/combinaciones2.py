"""Todas las combinaciones válidas, sin sesgo de región.

Cruza las tarifas frescas de Ryanair y Wizz con el modelo de conectividad por
tierra (conectividad.py) y aplica las reglas del viaje. A diferencia de la
primera versión, no parte de una lista de destinos escrita a mano.
"""
import datetime as dt
import json, math, os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from conectividad import enlace, km

S = os.path.dirname(os.path.abspath(__file__))
TOPE = 160.0
IDA_8, IDA_9, VUE_11, VUE_12 = "2026-10-08", "2026-10-09", "2026-10-11", "2026-10-12"
HORA_MIN_8, LLEGADA_MAX_12 = "20:00", "18:00"
ALC = (38.2822, -0.5582)

# Husos respecto a la España peninsular (CET). Los que van una hora por delante.
MAS_UNA = {"ro", "bg", "gr", "lt", "lv", "ee", "fi", "md", "ua", "cy"}
MENOS_UNA = {"pt", "gb", "ie", "is"}


def hm(t):
    h, m = t.split(":")[:2]
    return int(h) * 60 + int(m)


def dur_vuelo(lat, lon):
    """Duración aproximada del vuelo desde/hacia Alicante, en minutos."""
    d = km(ALC, (lat, lon))
    return d / 750.0 * 60 + 40


def llegada_estimada(salida, lat, lon, cc, hacia_alc):
    """Hora local de llegada. cc es el país del OTRO extremo."""
    desfase = 60 if cc in MAS_UNA else (-60 if cc in MENOS_UNA else 0)
    m = hm(salida) + dur_vuelo(lat, lon) + (-desfase if hacia_alc else desfase)
    return int(m)


def cargar():
    ry = json.load(open(os.path.join(S, "ryanair_octubre.json")))
    aero, idas, vueltas = {}, [], []

    for c, a in ry["airports"].items():
        aero[c] = {"iata": c, "name": a["name"], "country": a["country"],
                   "cc": (a.get("cc") or "").lower(), "lat": a["lat"], "lon": a["lon"]}

    for c, precios in ry["out"].items():
        for dia in (IDA_8, IDA_9):
            p = precios.get(dia)
            if p is None:
                continue
            for num, sale, llega in ry.get("sched_out", {}).get(c, {}).get(dia, []):
                if dia == IDA_8 and hm(sale) < hm(HORA_MIN_8):
                    continue
                idas.append({"iata": c, "cia": "Ryanair", "dia": dia, "sale": sale,
                             "llega": llega, "precio": p, "num": num})
    for c, precios in ry["back"].items():
        for dia in (VUE_11, VUE_12):
            p = precios.get(dia)
            if p is None:
                continue
            for num, sale, llega in ry.get("sched_back", {}).get(c, {}).get(dia, []):
                cruza = hm(llega) < hm(sale)
                if dia == VUE_12 and (cruza or hm(llega) > hm(LLEGADA_MAX_12)):
                    continue
                vueltas.append({"iata": c, "cia": "Ryanair", "dia": dia, "sale": sale,
                                "llega": llega, "precio": p, "num": num})

    fw = os.path.join(S, "wizz_completo.json")
    if os.path.exists(fw):
        wz = json.load(open(fw))
        # LON, MIL, ROM, VEN, WSW no son aeropuertos: son "todos los de la ciudad".
        METRO = {"LON", "MIL", "ROM", "VEN", "WSW", "BUH", "PAR", "BER", "STO"}
        for c, a in wz["airports"].items():
            if a.get("lat") is None or c in METRO:
                continue
            aero.setdefault(c, {"iata": c, "name": a["name"], "country": a["country"],
                                "cc": (a.get("cc") or "").lower(),
                                "lat": a["lat"], "lon": a["lon"]})
        for c, dias in wz["out"].items():
            a = None if c in METRO else aero.get(c)
            if not a:
                continue
            for dia in (IDA_8, IDA_9):
                if dia not in dias:
                    continue
                p, div, horas = dias[dia]
                if div != "EUR" or not p or p <= 0:
                    continue          # 0 € no es un precio: es un dato que falta
                for sale in horas:
                    if dia == IDA_8 and hm(sale) < hm(HORA_MIN_8):
                        continue
                    m = llegada_estimada(sale, a["lat"], a["lon"], a["cc"], False)
                    idas.append({"iata": c, "cia": "Wizz", "dia": dia, "sale": sale,
                                 "llega": "%02d:%02d" % divmod(m % 1440, 60),
                                 "precio": p, "num": "W6", "estimada": True})
        for c, dias in wz["back"].items():
            a = None if c in METRO else aero.get(c)
            if not a:
                continue
            for dia in (VUE_11, VUE_12):
                if dia not in dias:
                    continue
                p, div, horas = dias[dia]
                if div != "EUR" or not p or p <= 0:
                    continue          # 0 € no es un precio: es un dato que falta
                for sale in horas:
                    m = llegada_estimada(sale, a["lat"], a["lon"], a["cc"], True)
                    if dia == VUE_12 and m > hm(LLEGADA_MAX_12):
                        continue
                    vueltas.append({"iata": c, "cia": "Wizz", "dia": dia, "sale": sale,
                                    "llega": "%02d:%02d" % divmod(m % 1440, 60),
                                    "precio": p, "num": "W6", "estimada": True})
    return aero, idas, vueltas


def main():
    aero, idas, vueltas = cargar()
    print("idas válidas: %d | vueltas válidas: %d | aeropuertos: %d"
          % (len(idas), len(vueltas), len(aero)))

    combos = []
    for a in idas:
        ca = aero.get(a["iata"])
        if not ca:
            continue
        t_lleg = dt.datetime.fromisoformat(a["dia"] + "T" + a["llega"])
        if hm(a["llega"]) < hm(a["sale"]):
            t_lleg += dt.timedelta(days=1)
        for v in vueltas:
            total = round(a["precio"] + v["precio"], 2)
            if total > TOPE:
                continue
            cv = aero.get(v["iata"])
            if not cv:
                continue
            e = enlace(ca, cv)
            if e is None:
                continue
            horas, como, dist = e
            t_sale = dt.datetime.fromisoformat(v["dia"] + "T" + v["sale"])
            libres = (t_sale - t_lleg).total_seconds() / 3600 - horas
            if libres < 36:
                continue
            paises = {ca["country"], cv["country"]}
            combos.append({"total": total, "a": a, "v": v, "ca": ca, "cv": cv,
                           "horas": horas, "como": como, "dist": dist,
                           "libres": libres, "paises": len(paises)})

    dos = sorted([c for c in combos if c["paises"] == 2], key=lambda c: c["total"])
    print("\nCombinaciones de DOS PAÍSES bajo %d €: %d\n" % (TOPE, len(dos)))
    vistos = set()
    for c in dos:
        k = (c["a"]["iata"], c["v"]["iata"])
        if k in vistos:
            continue
        vistos.add(k)
        a, v = c["a"], c["v"]
        print("%6.2f €  %s (%s) → %s (%s)   %.0f h libres"
              % (c["total"], c["ca"]["name"][:18], c["ca"]["country"][:12],
                 c["cv"]["name"][:18], c["cv"]["country"][:12], c["libres"]))
        print("        IDA    %s %s  ALC %s→%s  %s %s  %.2f%s"
              % (a["dia"][8:10], a["cia"][:7], a["sale"], a["llega"], a["cia"][:2],
                 a["num"], a["precio"], "  (llegada estimada)" if a.get("estimada") else ""))
        print("        VUELTA %s %s  %s %s→%s ALC  %s %s  %.2f%s"
              % (v["dia"][8:10], v["cia"][:7], v["iata"], v["sale"], v["llega"],
                 v["cia"][:2], v["num"], v["precio"],
                 "  (llegada estimada)" if v.get("estimada") else ""))
        print("        TIERRA %.1f h · %s" % (c["horas"], c["como"]))
        print()


if __name__ == "__main__":
    main()
