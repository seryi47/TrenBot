#!/usr/bin/env python3
"""Qué rutas cumplen los horarios, mirando el calendario real de Ryanair.

El endpoint de precios (`availability`) responde 409 en cuanto se le insiste, y
un 409 no distingue "esa ruta no vuela ese día" de "te he bloqueado". El de
horarios (`timtbl/3/schedules`) aguanta y dice exactamente qué días vuela cada
ruta y a qué hora, así que primero se filtra con él y solo se piden precios de
los que cumplen. Menos consultas y, sobre todo, negativos fiables.
"""
import json
import os
import sys
import time

import curl_cffi.requests as cr

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from research.barrido_total import destinos_ryanair   # noqa: E402

RAIZ = os.path.dirname(os.path.abspath(__file__))
BASE = "https://services-api.ryanair.com/timtbl/3/schedules/%s/%s/years/2026/months/10"


def calendario(s, o, d):
    try:
        r = s.get(BASE % (o, d), timeout=30)
    except Exception:
        return {}
    if r.status_code != 200:
        return {}
    fuera = {}
    for dia in r.json().get("days", []) or []:
        if dia.get("flights"):
            fuera[dia["day"]] = [(f.get("departureTime"), f.get("arrivalTime"),
                                  f.get("number")) for f in dia["flights"]]
    return fuera


def main():
    s = cr.Session(impersonate="chrome")
    s.headers.update({"Accept": "application/json", "Accept-Language": "es-ES",
                      "Referer": "https://www.ryanair.com/"})
    dest = destinos_ryanair()
    print("mirando el calendario de octubre de %d rutas\n" % len(dest))
    buenos, motivos = {}, {}
    for i, (iata, nombre, pais) in enumerate(dest, 1):
        ida_cal = calendario(s, "ALC", iata)
        time.sleep(0.6)
        # IDA: el 8 solo a partir de las 20:00; el 9, aterrizando antes de las
        # 20:00 Y el mismo día. Sin el "> 03:00" un vuelo que sale a las 22:00 y
        # aterriza a la 01:05 del día siguiente colaba, porque "01:05" < "20:00"
        # comparando textos. Es justo el caso que la regla quiere evitar.
        idas = [("2026-10-08",) + f for f in ida_cal.get(8, []) if f[0] >= "20:00"]
        idas += [("2026-10-09",) + f for f in ida_cal.get(9, [])
                 if "03:00" < f[1] < "20:00"]
        if not idas:
            hay = sorted(set([f[0] for f in ida_cal.get(8, [])] +
                             [f[0] for f in ida_cal.get(9, [])]))
            motivos[iata] = ("no vuela el 8 ni el 9" if not hay
                             else "vuela el 8/9 pero a las " + ", ".join(hay))
            print("%3d/%d  %-4s %-24s ❌ %s" % (i, len(dest), iata, (nombre or "")[:24],
                                                motivos[iata]))
            continue
        vta_cal = calendario(s, iata, "ALC")
        time.sleep(0.6)
        vueltas = [("2026-10-11",) + f for f in vta_cal.get(11, [])]
        vueltas += [("2026-10-12",) + f for f in vta_cal.get(12, []) if f[1] <= "18:00"]
        # OJO: una ida válida se guarda AUNQUE esta compañía no tenga vuelta que
        # sirva, porque se puede volver con la otra. Descartar el destino entero
        # aquí es lo que escondió la ida de Ryanair a Katowice.
        if not vueltas:
            hay = sorted(set(f[1] for f in vta_cal.get(12, [])))
            motivos[iata] = ("sin vuelta propia el 11 ni el 12" if not hay
                             else "su vuelta del 12 aterriza a las " + ", ".join(hay))
            print("%3d/%d  %-4s %-24s ⚠️  %d ida(s) válida(s), pero %s"
                  % (i, len(dest), iata, (nombre or "")[:24], len(idas), motivos[iata]))
        buenos[iata] = {"nombre": nombre, "pais": pais, "idas": idas, "vueltas": vueltas}
        print("%3d/%d  %-4s %-24s ✅ %d ida(s), %d vuelta(s)"
              % (i, len(dest), iata, (nombre or "")[:24], len(idas), len(vueltas)))
    json.dump({"validos": buenos, "descartados": motivos},
              open(os.path.join(RAIZ, "horarios.json"), "w"), ensure_ascii=False, indent=1)
    print("\ncumplen horarios: %d de %d" % (len(buenos), len(dest)))
    for k, v in buenos.items():
        print("  %-4s %-24s ida %s · vuelta %s" % (k, (v["nombre"] or "")[:24],
              " / ".join("%s %s→%s" % (d[5:], f[0], f[1]) for d, *f in
                         [(x[0], x[1], x[2], x[3]) for x in v["idas"]]),
              " / ".join("%s %s→%s" % (d[5:], f[0], f[1]) for d, *f in
                         [(x[0], x[1], x[2], x[3]) for x in v["vueltas"]])))


if __name__ == "__main__":
    main()
