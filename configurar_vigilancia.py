#!/usr/bin/env python3
"""Deja la watchlist preparada con los vuelos del viaje de octubre.

Cada tramo se vigila por separado con dos disparadores:
  · objetivo  -> avisa si el precio cae por debajo de ese número
  · bajada    -> avisa ante cualquier caída de 3 € o más, aunque no llegue al objetivo

Los dos "sueños" (Viena→Alicante y Bratislava→Alicante) hoy están caros o agotados,
pero si se abren plazas baratas desbloquean la mejor versión del viaje, así que se
vigilan igual.
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

RAIZ = os.path.dirname(os.path.abspath(__file__))
ESTADO = os.path.join(RAIZ, "watches.json")

# (nombre, proveedor, origen, destino, fecha, hora_salida, objetivo_eur)
VUELOS = [
    ("IDA · Alicante→Bratislava (vie 9)",  "wizz",    "ALC", "BTS", "2026-10-09", "09:35", 55),
    ("IDA · Alicante→Viena (jue 8, 20:15)", "ryanair", "ALC", "VIE", "2026-10-08", "20:15", 80),
    ("VUELTA · Pardubice→Alicante (dom 11)", "ryanair", "PED", "ALC", "2026-10-11", "22:00", 42),
    ("VUELTA · Budapest→Alicante (dom 11)", "wizz",    "BUD", "ALC", "2026-10-11", "05:15", 50),
    ("VUELTA · Linz→Alicante (lun 12)",    "ryanair", "LNZ", "ALC", "2026-10-12", "11:45", 70),
    ("IDA · Alicante→Belfast (jue 8, 22:00)", "ryanair", "ALC", "BFS", "2026-10-08", "22:00", 80),
    ("VUELTA · Dublín→Alicante (dom 11)",   "ryanair", "DUB", "ALC", "2026-10-11", "16:25", 25),
    ("IDA · Alicante→Colonia (vie 9)",      "ryanair", "ALC", "CGN", "2026-10-09", "20:45", 75),
    ("VUELTA · Charleroi→Alicante (dom 11)", "ryanair", "CRL", "ALC", "2026-10-11", "06:30", 44),
    ("IDA · Alicante→Wrocław (vie 9)",      "ryanair", "ALC", "WRO", "2026-10-09", "05:50", 80),
    # Los dos que hoy no salen a cuenta pero cambiarían el viaje si bajan:
    ("OJALÁ · Viena→Alicante (dom 11)",    "ryanair", "VIE", "ALC", "2026-10-11", "16:20", 75),
    ("OJALÁ · Bratislava→Alicante (lun 12)", "wizz",  "BTS", "ALC", "2026-10-12", "05:40", 85),
]
PASAJEROS = 2
CADA = 900          # 15 min: las aerolíneas cortan si se les insiste más


def main():
    actuales = json.load(open(ESTADO, encoding="utf-8")) if os.path.exists(ESTADO) else []

    # La vigilancia vieja del tren era para el 31/07, que ya pasó: se desactiva
    # en vez de borrarla, por si quieres recuperarla.
    for w in actuales:
        if w.get("date", "") < "2026-09-03" and w.get("enabled", True):
            w["enabled"] = False
            print("desactivada (fecha pasada): #%s %s" % (w["id"], w["name"]))

    existentes = {(w["origin"], w["destination"], w["date"]) for w in actuales}
    siguiente = max([w["id"] for w in actuales], default=0) + 1

    for nombre, prov, o, d, fecha, hora, objetivo in VUELOS:
        if (o, d, fecha) in existentes:
            print("ya estaba: %s" % nombre)
            continue
        actuales.append({
            "id": siguiente, "name": nombre, "providers": [prov],
            "origin": o, "destination": d, "date": fecha, "time": hora,
            "max_price": objetivo, "chat_id": None, "enabled": True,
            "adults": PASAJEROS, "poll_interval": CADA,
            "avisar_bajadas": True, "umbral_bajada": 3.0,
        })
        print("añadida #%d  %-40s objetivo ≤%d €" % (siguiente, nombre, objetivo))
        siguiente += 1

    json.dump(actuales, open(ESTADO, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print("\nwatches.json guardado: %d vigilancias (%d activas)" %
          (len(actuales), sum(1 for w in actuales if w.get("enabled", True))))


if __name__ == "__main__":
    main()
