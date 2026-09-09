#!/usr/bin/env python3
"""Manda por Telegram el resumen del viaje con precios y enlaces de compra.

    ./venv/bin/python resumen_telegram.py
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from botviajes.engine import WEB_URL          # noqa: E402
from botviajes.notifier import Notifier       # noqa: E402
from botviajes.util_env import load_env       # noqa: E402

RAIZ = os.path.dirname(os.path.abspath(__file__))
DIAS = {"2026-10-08": "jue 8", "2026-10-09": "vie 9",
        "2026-10-11": "dom 11", "2026-10-12": "lun 12"}


def eur(n):
    return ("%.2f" % n).replace(".", ",") + " €"


def bloque(op, pasajeros):
    L = ["", "━━━━━━━━━━━━━━━━━━━━",
         "<b>%s</b>  ·  %s" % (op["titulo"], " + ".join(op["paises"])),
         "<b>%s por persona</b>  (%s los dos) · %d noches"
         % (eur(op["total_persona"]), eur(op["total_grupo"]), op["noches"])]
    if op.get("aviso"):
        L.append("⚠️ %s" % op["aviso"])
    L.append("")
    for t in op["tramos"]:
        if t["tipo"] == "tierra":
            L.append("   🚆 %s → %s · %s · %s"
                     % (t["de_nombre"], t["a_nombre"], t["duracion"], t["coste"]))
        else:
            cia = "Wizz" if t["cia"] == "wizz" else "Ryanair"
            L.append("✈️ <b>%s</b> · sale de %s a las <b>%s</b>, llega a %s a las %s"
                     % (DIAS.get(t["fecha"], t["fecha"]), t["de_nombre"], t["sale"],
                        t["a_nombre"], t["llega"]))
            L.append("   %s %s" % (cia, t.get("etiqueta") or ""))
            L.append("   <a href=\"%s\">Comprar por %s</a>%s"
                     % (t["url"], eur(t["precio"]),
                        ("  · quedan %s" % t["plazas"])
                        if isinstance(t.get("plazas"), int) and t["plazas"] > 0 else ""))
    return "\n".join(L)


def main():
    load_env()
    datos = json.load(open(os.path.join(RAIZ, "web", "datos.json"), encoding="utf-8"))
    v = datos["viaje"]
    n = Notifier(mac_alerts=False, open_browser=False)
    destino = os.environ.get("TELEGRAM_CHAT_ID", "")

    cab = ["✈️ <b>%s</b>" % v["titulo"],
           "%d combinaciones de <b>vuelo directo</b> que cumplen todo, "
           "para %d personas." % (len(datos["opciones"]), v["pasajeros"]),
           "", "🌐 <a href=\"%s\">Verlo todo en la web</a>" % WEB_URL,
           "Precios de %s. Vigilo cada 15 min y te aviso si bajan."
           % datos["actualizado"],
           "<i>Todas las horas son las locales de cada país.</i>"]
    partes, actual = [], "\n".join(cab)
    for op in datos["opciones"]:
        b = bloque(op, v["pasajeros"])
        if len(actual) + len(b) > 3500:
            partes.append(actual); actual = b
        else:
            actual += "\n" + b
    partes.append(actual)

    for i, p in enumerate(partes, 1):
        ok = n.telegram(destino, p)
        print("mensaje %d/%d: %s (%d caracteres)"
              % (i, len(partes), "enviado" if ok else "FALLÓ", len(p)))


if __name__ == "__main__":
    main()
