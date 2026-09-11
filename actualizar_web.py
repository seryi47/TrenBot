#!/usr/bin/env python3
"""Consulta el precio real de cada tramo y genera los datos de la web.

    ./venv/bin/python actualizar_web.py            # solo regenera web/datos.json
    ./venv/bin/python actualizar_web.py --desplegar  # además publica en Vercel

Lee los itinerarios de rutas.json, pregunta el precio a la aerolínea (Ryanair y
Wizz, para el número real de pasajeros) y escribe web/datos.json con precios,
enlaces de compra y el histórico para ver si suben o bajan.
"""

import argparse
import datetime as dt
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from botviajes.providers import get_provider   # noqa: E402

RAIZ = os.path.dirname(os.path.abspath(__file__))
RUTAS = os.path.join(RAIZ, "rutas.json")
WATCHES = os.path.join(RAIZ, "watches.json")
WEB = os.path.join(RAIZ, "web")
DATOS = os.path.join(WEB, "datos.json")
HIST = os.path.join(RAIZ, "historico.json")


def clave(t):
    return "%s|%s|%s|%s" % (t["cia"], t["de"], t["a"], t["fecha"])


def minutos(txt):
    """'2 h 40 min' -> 160. Sirve para sumar los trayectos por tierra."""
    h = re.search(r"(\d+)\s*h", txt or "")
    m = re.search(r"(\d+)\s*min", txt or "")
    return (int(h.group(1)) * 60 if h else 0) + (int(m.group(1)) if m else 0)


def instante(fecha, hora, dia_siguiente=False):
    d = dt.datetime.fromisoformat("%sT%s" % (fecha, hora))
    return d + dt.timedelta(days=1) if dia_siguiente else d


def resumen(tramos):
    """Datos que hacen falta para poder comparar opciones de un vistazo."""
    vuelos = [t for t in tramos if t["tipo"] == "vuelo"]
    if not vuelos:
        return {}
    ida, vuelta = vuelos[0], vuelos[-1]
    llegada = instante(ida["fecha"], ida["llega"], ida["llega"] < ida["sale"])
    salida = instante(vuelta["fecha"], vuelta["sale"])
    tierra = sum(minutos(t.get("duracion", "")) for t in tramos if t["tipo"] == "tierra")
    horas = (salida - llegada).total_seconds() / 3600 - tierra / 60
    # Dos molestias distintas: madrugar para coger el avión, y aterrizar de
    # madrugada. Conviene poder filtrarlas por separado.
    sale_temprano = any(v["sale"] < "07:00" for v in vuelos)
    llega_noche = any(v["llega"] < v["sale"] for v in vuelos)
    # Llegar tarde el 8 compensa (se gana el viernes); llegar tarde el 9 no:
    # se pierde el día y no se gana nada a cambio.
    ida_tarde = (ida["fecha"] == "2026-10-09"
                 and (ida["llega"] < ida["sale"] or ida["llega"] > "20:00"))
    return {
        "ida_fecha": ida["fecha"], "ida_hora": ida["sale"], "ida_iata": ida["a"],
        "ida_ciudad": ida["a_nombre"],
        "vuelta_fecha": vuelta["fecha"], "vuelta_hora": vuelta["sale"],
        "vuelta_llega": vuelta["llega"], "vuelta_iata": vuelta["de"],
        "vuelta_ciudad": vuelta["de_nombre"],
        "horas_destino": round(horas),
        "minutos_tierra": tierra,
        "saltos": sum(1 for t in tramos if t["tipo"] == "tierra"),
        "sale_temprano": sale_temprano,
        "ida_tarde": ida_tarde,
        "llega_noche": llega_noche,
        "vuelve_lunes": vuelta["fecha"] == "2026-10-12",
    }


def desde_watches(tramo):
    """Reaprovecha el precio que ya consultó el bot, para no preguntar dos veces
    lo mismo a la aerolínea y para que la web y Telegram digan lo mismo."""
    if not os.path.exists(WATCHES):
        return None
    for w in json.load(open(WATCHES, encoding="utf-8")):
        if (tramo["cia"] in w.get("providers", []) and w.get("origin") == tramo["de"]
                and w.get("destination") == tramo["a"] and w.get("date") == tramo["fecha"]
                and w.get("ultimo_precio") is not None):
            # Si lo último que se supo fue un precio orientativo y es más
            # reciente que el firme, manda el orientativo: enseñar el firme
            # viejo como si siguiera vigente sería engañar.
            if (w.get("ultimo_orientativo") and
                    (w.get("orientativo_visto") or "") > (w.get("ultimo_visto") or "")):
                return {"estado": "orientativo", "precio": w["ultimo_orientativo"],
                        "sale": tramo["sale"], "llega": tramo.get("llega", ""),
                        "etiqueta": "precio orientativo", "url": w.get("ultimo_url", ""),
                        "plazas": None, "visto": w.get("orientativo_visto")}
            serie = [p[1] for p in (w.get("serie") or []) if p[1] and p[1] > 0]
            return {"estado": "ok", "precio": w["ultimo_precio"],
                    "sale": w.get("ultimo_salida") or tramo["sale"],
                    "llega": w.get("ultimo_llegada") or tramo.get("llega", ""),
                    "etiqueta": w.get("ultimo_etiqueta") or tramo.get("vuelo", ""),
                    "url": w.get("ultimo_url", ""),
                    "plazas": w.get("ultimo_plazas"),
                    "duracion": w.get("ultimo_duracion"),
                    "minimo": min(serie) if serie else None,
                    "maximo": max(serie) if serie else None,
                    "visto": w.get("ultimo_visto")}
    return None


def consultar(tramo, pasajeros):
    """Precio real de ese vuelo concreto. Devuelve dict con lo que se sabe."""
    prov = get_provider(tramo["cia"])
    try:
        ofertas = prov.search(tramo["de"], tramo["a"], tramo["fecha"], adults=pasajeros)
    except Exception as e:
        print("   ! %s: %s" % (clave(tramo), e))
        return {"estado": "error", "detalle": str(e)[:120]}

    # Se busca el vuelo por su hora de salida; si el proveedor no la da (Wizz por
    # timetable devuelve solo una), se coge el único que haya.
    exacto = [o for o in ofertas if o.departure == tramo["sale"]]
    elegido = exacto[0] if exacto else (ofertas[0] if len(ofertas) == 1 else None)
    if elegido is None:
        return {"estado": "sin_vuelo",
                "detalle": "no aparece salida a las %s" % tramo["sale"]}
    orientativo = bool((elegido.raw or {}).get("orientativo"))
    return {
        "estado": "orientativo" if orientativo
                  else ("ok" if elegido.available else "agotado"),
        "precio": elegido.price,
        "sale": elegido.departure or tramo["sale"],
        "llega": elegido.arrival or tramo.get("llega", ""),
        "etiqueta": elegido.label,
        "url": elegido.buy_url,
        "plazas": (elegido.raw or {}).get("plazas"),
        "duracion": (elegido.raw or {}).get("duracion"),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--desplegar", action="store_true", help="publica en Vercel al terminar")
    ap.add_argument("--consultar", action="store_true",
                    help="pregunta el precio a la aerolínea en vez de reusar el del bot")
    args = ap.parse_args()

    cfg = json.load(open(RUTAS, encoding="utf-8"))
    pasajeros = cfg["viaje"]["pasajeros"]

    # Un mismo vuelo aparece en varias opciones: se consulta una sola vez.
    tramos = {}
    for op in cfg["opciones"]:
        for t in op["tramos"]:
            if t["tipo"] == "vuelo":
                tramos.setdefault(clave(t), t)

    print("Resolviendo %d vuelos para %d pasajeros...\n" % (len(tramos), pasajeros))
    precios = {}
    for k, t in tramos.items():
        r = None if args.consultar else desde_watches(t)
        if r is None:
            r = consultar(t, pasajeros)
        precios[k] = r
        print("  %-28s %-9s %s" % (
            k, r["estado"],
            ("%.2f €" % r["precio"]) if r.get("precio") is not None else r.get("detalle", "")))

    ahora = datetime.now(timezone.utc).astimezone()
    # El histórico lo escribe SOLO el motor (botviajes/engine.py). Aquí se lee
    # y punto: con dos escritores el fichero acababa pisándose a sí mismo.
    historico = json.load(open(HIST, encoding="utf-8")) if os.path.exists(HIST) else {}

    # Se monta la salida para la web
    opciones = []
    for op in cfg["opciones"]:
        salida = dict(op)
        total, completo = 0.0, True
        tramos_out = []
        for t in op["tramos"]:
            t2 = dict(t)
            if t["tipo"] == "vuelo":
                r = precios[clave(t)]
                t2.update({k: v for k, v in r.items() if k != "estado"})
                t2["estado"] = r["estado"]
                serie = historico.get(clave(t), [])
                t2["historico"] = serie[-20:]
                t2["variacion"] = (round(serie[-1][1] - serie[0][1], 2)
                                   if len(serie) > 1 else 0.0)
                if r.get("precio") is not None:
                    total += r["precio"]
                    if r["estado"] == "orientativo":
                        salida["tiene_orientativo"] = True
                else:
                    completo = False
            tramos_out.append(t2)
        salida["tramos"] = tramos_out
        salida["total_persona"] = round(total, 2) if completo else None
        salida["total_grupo"] = round(total * pasajeros, 2) if completo else None
        salida.update(resumen(tramos_out))
        salida["total_referencia"] = round(
            sum(t["ref"] for t in op["tramos"] if t["tipo"] == "vuelo"), 2)
        salida["dentro_presupuesto"] = (
            completo and total <= cfg["viaje"]["tope_por_persona"])
        opciones.append(salida)

    opciones.sort(key=lambda o: (o["total_persona"] is None, o["total_persona"] or 0))
    datos = {"viaje": cfg["viaje"], "opciones": opciones,
             "actualizado": ahora.strftime("%Y-%m-%d %H:%M"),
             "actualizado_iso": ahora.isoformat()}
    os.makedirs(WEB, exist_ok=True)
    json.dump(datos, open(DATOS, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("\nweb/datos.json escrito (%d opciones)" % len(opciones))
    for o in opciones:
        print("  %-22s %s" % (o["id"], ("%.2f €/persona" % o["total_persona"])
                              if o["total_persona"] else "incompleta"))

    if args.desplegar:
        print("\nDesplegando en Vercel...")
        r = subprocess.run(["vercel", "deploy", "--prod", "--yes", WEB],
                           capture_output=True, text=True)
        print(r.stdout.strip()[-500:] or r.stderr.strip()[-500:])


if __name__ == "__main__":
    main()
