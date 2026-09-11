"""Qué viaje completo permite un vuelo suelto.

El bot vigila tramos por separado, pero tú no viajas en tramos: si te aviso de
que el Alicante→Belfast ha bajado, lo que quieres saber es desde dónde vuelves
y cuánto sale el viaje entero. Esto cruza el tramo con las combinaciones
definidas en rutas.json y las valora con los precios de hoy.
"""

import json
import os

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUTAS = os.path.join(RAIZ, "rutas.json")

_cache = {"t": None, "cfg": None}


def _config():
    """rutas.json, releído solo si el fichero ha cambiado."""
    try:
        t = os.path.getmtime(RUTAS)
    except OSError:
        return None
    if _cache["t"] != t:
        try:
            with open(RUTAS, encoding="utf-8") as fh:
                _cache["cfg"] = json.load(fh)
            _cache["t"] = t
        except Exception:
            return None
    return _cache["cfg"]


def _clave(cia, origen, destino, fecha):
    return "%s|%s|%s|%s" % (cia, origen, destino, fecha)


def viajes_con(watch, watches, precio_actual=None):
    """Combinaciones completas que incluyen el vuelo de `watch`.

    Devuelve una lista ordenada por precio: cada elemento trae el título, el
    total por persona, si cabe en el presupuesto y desde dónde se vuelve.
    Se valora con el último precio conocido de cada tramo. Para el tramo del
    propio aviso se usa `precio_actual`: cuando se construye el mensaje, la
    bajada todavía no se ha guardado, y sin esto el total saldría con el
    precio viejo y no cuadraría con la cifra que anuncia el propio aviso.
    """
    cfg = _config()
    if not cfg:
        return []
    precios, urls, etiquetas, rangos, plazas, duraciones = {}, {}, {}, {}, {}, {}
    for w in watches:
        if w.get("ultimo_precio") is None or not w.get("providers"):
            continue
        k = _clave(w["providers"][0], w["origin"], w["destination"], w["date"])
        precios[k] = w["ultimo_precio"]
        urls[k] = w.get("ultimo_url")
        etiquetas[k] = w.get("ultimo_etiqueta")
        plazas[k] = w.get("ultimo_plazas")
        duraciones[k] = w.get("ultimo_duracion")
        serie = [p[1] for p in (w.get("serie") or []) if p[1] and p[1] > 0]
        if serie:
            rangos[k] = (min(serie), max(serie))

    mio = _clave(watch["providers"][0], watch["origin"],
                 watch["destination"], watch["date"])
    if precio_actual is not None:
        precios[mio] = precio_actual
    tope = (cfg.get("viaje") or {}).get("tope_por_persona")
    salida = []
    for op in cfg.get("opciones", []):
        vuelos = [t for t in op.get("tramos", []) if t.get("tipo") == "vuelo"]
        claves = [_clave(t["cia"], t["de"], t["a"], t["fecha"]) for t in vuelos]
        if mio not in claves:
            continue
        if any(k not in precios for k in claves):
            continue        # falta el precio de algún tramo: no se inventa
        total = round(sum(precios[k] for k in claves), 2)
        # Cada tramo con su precio de hoy y su enlace, para poder enseñar el
        # viaje entero en el aviso y no solo "vuelta desde Dublín".
        detalle = []
        for t in op.get("tramos", []):
            if t.get("tipo") != "vuelo":
                detalle.append(dict(t))
                continue
            k = _clave(t["cia"], t["de"], t["a"], t["fecha"])
            minimo, maximo = rangos.get(k, (None, None))
            detalle.append(dict(t, precio=precios.get(k), url=urls.get(k),
                                etiqueta=etiquetas.get(k) or t.get("vuelo"),
                                minimo=minimo, maximo=maximo,
                                plazas=plazas.get(k),
                                duracion=duraciones.get(k),
                                es_del_aviso=(k == mio)))
        vuelta = [t for t in detalle if t.get("tipo") == "vuelo"][-1]
        salida.append({
            "titulo": op.get("titulo", op.get("id", "")),
            "total": total,
            "dentro": tope is not None and total <= tope,
            "tramos": detalle,
            "vuelta_desde": vuelta.get("de_nombre") or vuelta.get("de"),
            "vuelta_fecha": vuelta.get("fecha"),
            "vuelta_hora": vuelta.get("sale"),
            "paises": op.get("paises", []),
        })
    return sorted(salida, key=lambda x: x["total"])
