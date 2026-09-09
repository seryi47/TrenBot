"""Comprueba los trayectos por tierra de verdad, con la API de FlixBus.

El modelo por distancia se equivoca donde hay montañas o el trazado da un
rodeo (Marsella-Turín cruza los Alpes). Aquí se pregunta a FlixBus por la
fecha real del viaje y se apunta la duración y el precio que dan ellos.
"""
import json, sys, time
from curl_cffi import requests as cr

AUTO = "https://global.api.flixbus.com/search/autocomplete/cities"
BUSCA = "https://global.api.flixbus.com/search/service/v4/search"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/128.0 Safari/537.36")

s = cr.Session(impersonate="chrome")
s.headers.update({"User-Agent": UA, "Accept": "application/json",
                  "Referer": "https://www.flixbus.es/"})
_cache = {}


def ciudad(nombre):
    if nombre in _cache:
        return _cache[nombre]
    r = s.get(AUTO, params={"q": nombre, "lang": "es", "country": "ES"}, timeout=30)
    if r.status_code != 200 or not r.json():
        _cache[nombre] = None
        return None
    # el primero que sea ciudad de verdad, no una parada de aeropuerto
    for c in r.json():
        if c.get("is_flixbus_city") and "eropuerto" not in c["name"]:
            _cache[nombre] = (c["id"], c["name"])
            return _cache[nombre]
    c = r.json()[0]
    _cache[nombre] = (c["id"], c["name"])
    return _cache[nombre]


def trayecto(origen, destino, fecha):
    """fecha en dd.mm.aaaa. Devuelve (duracion_min, precio_eur, directo) o None."""
    a, b = ciudad(origen), ciudad(destino)
    if not a or not b:
        return None, "no encuentro %s" % (origen if not a else destino)
    r = s.get(BUSCA, params={
        "from_city_id": a[0], "to_city_id": b[0], "departure_date": fecha,
        "products": json.dumps({"adult": 2}), "currency": "EUR", "locale": "es",
        "search_by": "cities", "include_after_midnight_rides": 1}, timeout=40)
    if r.status_code != 200:
        return None, "HTTP %s" % r.status_code
    d = r.json()
    viajes = list((d.get("trips") or [{}])[0].get("results", {}).values())
    if not viajes:
        return None, "sin autobuses ese día"
    mejores = []
    for v in viajes:
        if v.get("status") not in ("available", "sold_out", None):
            continue
        dur = (v.get("duration") or {}).get("hours", 0) * 60 + (v.get("duration") or {}).get("minutes", 0)
        precio = ((v.get("price") or {}).get("total"))
        mejores.append((dur, precio, v.get("transfer_type") == "direct",
                        (v.get("departure") or {}).get("date", "")[11:16],
                        (v.get("arrival") or {}).get("date", "")[11:16]))
    if not mejores:
        return None, "sin plazas"
    mejores.sort()
    return mejores[0], None


CASOS = [
    ("Marsella", "Turín", "10.10.2026", "Marsella + Turín"),
    ("París", "Bruselas", "11.10.2026", "París + Bruselas"),
    ("Colonia", "Bruselas", "11.10.2026", "Colonia + Bruselas"),
    ("Belfast", "Dublín", "10.10.2026", "Belfast + Dublín"),
    ("Wroclaw", "Praga", "10.10.2026", "Wroclaw + Praga/Pardubice"),
    ("Viena", "Zagreb", "10.10.2026", "Viena + Zagreb"),
    ("Bratislava", "Praga", "10.10.2026", "Bratislava + Praga"),
    ("Bratislava", "Viena", "11.10.2026", "Bratislava + Viena"),
    ("Viena", "Praga", "11.10.2026", "Viena + Praga"),
    ("Bratislava", "Budapest", "10.10.2026", "Bratislava + Budapest"),
    ("Viena", "Linz", "12.10.2026", "Viena + Linz"),
    ("Katowice", "Praga", "10.10.2026", "Katowice + Praga"),
]

print("%-28s %-9s %-9s %-8s %s" % ("TRAYECTO", "DURACIÓN", "PRECIO(2)", "DIRECTO", "HORARIO"))
print("-" * 78)
for o, d, f, etiq in CASOS:
    r, err = trayecto(o, d, f)
    if err:
        print("%-28s %s" % (etiq, err))
    else:
        dur, precio, directo, sale, llega = r
        print("%-28s %2dh%02d    %8s   %-8s %s→%s" % (
            etiq, dur // 60, dur % 60,
            ("%.2f €" % precio) if precio else "—",
            "sí" if directo else "con cambio", sale, llega))
    time.sleep(1.5)
