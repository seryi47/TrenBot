"""Cruza tarifas de Ryanair y Wizz y saca las combinaciones que cumplen las reglas.

Reglas:
  - Ida: 8-oct saliendo a las 20:00 o mas tarde, o 9-oct a cualquier hora.
  - Vuelta: 11-oct a cualquier hora, o 12-oct aterrizando en ALC a las 18:00 o antes.
  - Maximo 160 EUR por persona sumando ida y vuelta.
  - Open jaw permitido si hay conexion real por tierra (tabla enlaces_tierra).
"""
import datetime as dt
import json, os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from enlaces_tierra import enlace

S = os.path.dirname(os.path.abspath(__file__))
TOPE = 160.0
IDA_8, IDA_9 = "2026-10-08", "2026-10-09"
VUE_11, VUE_12 = "2026-10-11", "2026-10-12"
HORA_MIN_8, HORA_MAX_LLEGADA_12 = "20:00", "18:00"
DUR_WIZZ = {"BTS": 2.83, "BUD": 3.17, "KTW": 3.25, "WAW": 3.58, "GDN": 3.83,
            "BEG": 3.0, "OTP": 3.5, "CLJ": 3.33, "VCE": 2.17, "MXP": 2.0}


def hhmm(t):
    h, m = t.split(":")[:2]
    return int(h) * 60 + int(m)


def cuando(dia, hora, dia_siguiente=False):
    d = dt.datetime.fromisoformat(dia + "T" + hora)
    return d + dt.timedelta(days=1) if dia_siguiente else d


def cargar():
    ry = json.load(open(os.path.join(S, "ryanair_octubre.json")))
    wz = json.load(open(os.path.join(S, "wizz_octubre.json")))
    wcities = {c["iata"]: c for c in json.load(open(os.path.join(S, "wizz_map.json")))["cities"]}
    aero = {c: {"name": a["name"], "country": a["country"]} for c, a in ry["airports"].items()}
    for code in set(list(wz["out"]) + list(wz["back"])):
        c = wcities.get(code)
        if c and code not in aero:
            aero[code] = {"name": (c.get("shortName") or "").strip().replace("\n", " "),
                          "country": (c.get("countryName") or "").strip()}
    return ry, wz, aero


def piernas(ry, wz):
    idas, vueltas = [], []
    for code, precios in ry["out"].items():
        for dia in (IDA_8, IDA_9):
            p = precios.get(dia)
            if p is None:
                continue
            for num, sale, llega in ry.get("sched_out", {}).get(code, {}).get(dia, []):
                if dia == IDA_8 and hhmm(sale) < hhmm(HORA_MIN_8):
                    continue
                cruza = hhmm(llega) < hhmm(sale)
                idas.append({"iata": code, "cia": "Ryanair", "dia": dia, "sale": sale,
                             "llega": llega, "precio": p, "num": num,
                             "t_llega": cuando(dia, llega, cruza)})
    for code, precios in ry["back"].items():
        for dia in (VUE_11, VUE_12):
            p = precios.get(dia)
            if p is None:
                continue
            for num, sale, llega in ry.get("sched_back", {}).get(code, {}).get(dia, []):
                cruza = hhmm(llega) < hhmm(sale)
                if dia == VUE_12 and (cruza or hhmm(llega) > hhmm(HORA_MAX_LLEGADA_12)):
                    continue
                vueltas.append({"iata": code, "cia": "Ryanair", "dia": dia, "sale": sale,
                                "llega": llega, "precio": p, "num": num,
                                "t_sale": cuando(dia, sale)})
    for code, dias in wz["out"].items():
        for dia in (IDA_8, IDA_9):
            if dia not in dias:
                continue
            p, horas = dias[dia]
            for sale in horas:
                if dia == IDA_8 and hhmm(sale) < hhmm(HORA_MIN_8):
                    continue
                m = hhmm(sale) + int(DUR_WIZZ.get(code, 3.0) * 60)
                llega = "%02d:%02d" % divmod(m % 1440, 60)
                idas.append({"iata": code, "cia": "Wizz", "dia": dia, "sale": sale,
                             "llega": llega, "precio": p, "num": "W6",
                             "t_llega": cuando(dia, llega, m >= 1440)})
    for code, dias in wz["back"].items():
        for dia in (VUE_11, VUE_12):
            if dia not in dias:
                continue
            p, horas = dias[dia]
            for sale in horas:
                m = hhmm(sale) + int(DUR_WIZZ.get(code, 3.0) * 60) - 60   # ALC va 1h por detras
                llega = "%02d:%02d" % divmod(m % 1440, 60)
                if dia == VUE_12 and m > hhmm(HORA_MAX_LLEGADA_12):
                    continue
                vueltas.append({"iata": code, "cia": "Wizz", "dia": dia, "sale": sale,
                                "llega": llega, "precio": p, "num": "W6",
                                "t_sale": cuando(dia, sale)})
    return idas, vueltas


def main():
    ry, wz, aero = cargar()
    idas, vueltas = piernas(ry, wz)
    combos = []
    for a in idas:
        for v in vueltas:
            total = round(a["precio"] + v["precio"], 2)
            if total > TOPE:
                continue
            e = enlace(a["iata"], v["iata"])
            if e is None:
                continue
            horas_salto, como = e
            if horas_salto > 5.0:
                continue
            ca, cv = aero[a["iata"]], aero[v["iata"]]
            libres = (v["t_sale"] - a["t_llega"]).total_seconds() / 3600 - horas_salto
            if libres < 36:
                continue
            combos.append({"total": total, "a": a, "v": v, "ca": ca, "cv": cv,
                           "salto": horas_salto, "como": como, "libres": libres,
                           "paises": len({ca["country"], cv["country"]})})

    combos.sort(key=lambda c: (-c["paises"], c["total"]))
    dos = [c for c in combos if c["paises"] == 2]
    uno = [c for c in combos if c["paises"] == 1]
    print("=" * 78)
    print("OPCIONES DE 2 PAISES  (%d)" % len(dos))
    print("=" * 78)
    mostrar(dos)
    print("\n" + "=" * 78)
    print("OPCIONES DE 1 PAIS  (%d)" % len(uno))
    print("=" * 78)
    mostrar(uno, 8)


def mostrar(lista, tope=25):
    vistos = set()
    n = 0
    for c in lista:
        clave = (c["a"]["iata"], c["v"]["iata"])
        if clave in vistos:
            continue
        vistos.add(clave)
        n += 1
        if n > tope:
            break
        a, v = c["a"], c["v"]
        print("\n%6.2f EUR/persona   %s -> %s   [%s + %s]" %
              (c["total"], c["ca"]["name"], c["cv"]["name"],
               c["ca"]["country"], c["cv"]["country"]))
        print("   IDA     %s  %s  ALC %s -> %s %s   %s %s   %6.2f" %
              (a["dia"][8:10] + "-oct", a["cia"][:7].ljust(7), a["sale"],
               c["ca"]["name"][:14], a["llega"], a["cia"][:2], a["num"], a["precio"]))
        print("   VUELTA  %s  %s  %s %s -> ALC %s   %s %s   %6.2f" %
              (v["dia"][8:10] + "-oct", v["cia"][:7].ljust(7), c["cv"]["name"][:14],
               v["sale"], v["llega"], v["cia"][:2], v["num"], v["precio"]))
        if c["salto"]:
            print("   TIERRA  %s" % c["como"])
        print("   en destino: %.0f h utiles" % c["libres"])


if __name__ == "__main__":
    main()
