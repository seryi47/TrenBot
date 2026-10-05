"""Transavia (HV), contra su propia API. Sin scraping de HTML y sin claves.

Cómo se encontró (por si lo cambian):

1. La home da "Attention Required! | Cloudflare" con Playwright, pero curl_cffi
   con impersonate="chrome" entra a la primera (HTTP 200). Cloudflare aquí
   mira la huella TLS/JA3, no el user-agent.
2. La web es un Next.js. La página del buscador es
   https://www.transavia.com/reservar/es-es/buscar-un-vuelo (a ella redirige
   /es-ES/reserva-un-vuelo/vuelos/). Bajando sus 25 chunks .js y buscando
   `.endpoint({path:` aparece la tabla entera de endpoints del BFF:

       /calendar-fares  /flight-availability  /flights/select
       /general/disruptions  /holidays/deeplink  /newsletter/subscribe
       /next-best-action/capture  /sitecore/refresh-session

   Todos cuelgan de la base "/start/api" (módulo 24495 del chunk 189-*.js).
   La base "/search/api" existe pero sólo sirve /general/disruptions; por eso
   los nombres que se probaron a ciegas bajo ella daban 404.

Dos trampas:

a) /flight-availability NO lleva origen/destino en la query: los lee de la
   COOKIE `TransaviaFlightSearch`, que es el JSON del formulario de búsqueda.
   Sin esa cookie devuelve 400 "Invalid flight availability request".
b) Dentro de esa llamada hay dos modos. `type=full` nunca llegó a funcionar
   (400 con todas las formas de cookie probadas); el que sirve es
   `type=flight&flightDirection=outbound&date=YYYY-MM-DD`, y ahí el parámetro
   `date` manda sobre la fecha de la cookie. El par origen/destino sí sale
   siempre de la cookie.

Sobre vuelos DIRECTOS: cada elemento de la respuesta es UN solo flightNumber
con su hora de salida y de llegada, así que por construcción no hay escalas.
Además, en el __NEXT_DATA__ de la página del buscador viene la tabla completa
de rutas (15494) con las banderas isTransavia / isDohop: sólo 849 son vuelos
propios de Transavia; las otras 14645 son conexiones virtuales de Dohop, y
esas la web las manda a otro dominio, no a este endpoint. ALC<->BRU figura
como isTransavia=True, isDohop=False.

Verificado contra Google Flights el 05-oct-2026 (1 adulto):
    ALC->BRU 2026-12-04  HV9004 10:10->12:40  134 EUR  (Google: 134 EUR)
    ALC->BRU 2026-12-05  HV9006 10:20->12:50  179 EUR  (Google: 179 EUR)
    BRU->ALC 2026-12-08  HV9003 07:00->09:30  139 EUR  (Google: 139 EUR)

El precio es POR PERSONA: pidiendo adults=2 el 4-dic sigue diciendo 134.

La antigua API pública gratuita de developer.transavia.com ya no existe:
redirige a partner-developer.transavia.com, que sólo tiene "Partner Login" y
"Employee Login", sin alta automática.
"""

import json
import urllib.parse

from curl_cffi import requests

BASE = "https://www.transavia.com"
BUSCADOR = BASE + "/reservar/es-es/buscar-un-vuelo"


def _cookie(origen, destino, fecha, adultos=1, ninos=0, bebes=0):
    """La cookie que el formulario deja al buscar. Es de donde salen O y D."""
    valores = {
        "flightType": "one-way",
        "passengers": {"isValid": True, "adults": adultos,
                       "children": ninos, "infants": bebes},
        "route": {"validRoute": True, "departure": origen, "arrival": destino},
        "dates": {"from": fecha, "to": None},
        "secondRoute": {"validRoute": False, "departure": None, "arrival": None},
        "secondDates": None,
        "impartialDates": None,
        "flyingBlue": False,
    }
    crudo = json.dumps(valores, separators=(",", ":"))
    return "TransaviaFlightSearch=" + urllib.parse.quote(crudo)


def vuelos(origen, destino, fecha, adultos=1):
    """Los vuelos directos de ese día, con hora, número y precio por persona."""
    r = requests.get(
        BASE + "/start/api/flight-availability",
        params={"type": "flight", "flightDirection": "outbound", "date": fecha},
        headers={"Accept": "application/json",
                 "Referer": BUSCADOR,
                 "Cookie": _cookie(origen, destino, fecha, adultos)},
        impersonate="chrome", timeout=60)
    if r.status_code != 200:
        return [], "HTTP %s %s" % (r.status_code, r.text[:120])
    return r.json().get("data", []), None


def calendario(origen, destino, mes, adultos=1):
    """El precio más barato de cada día del mes. No necesita cookie.

    `mes` es "2026-12", o "2026-12/2027-01" para pedir dos de golpe.
    """
    r = requests.get(
        BASE + "/start/api/calendar-fares",
        params={"dr": mes, "ac": adultos, "cc": 0, "ic": 0,
                "ds": origen, "as": destino, "lf": "Monetary"},
        headers={"Accept": "application/json", "Referer": BUSCADOR},
        impersonate="chrome", timeout=60)
    if r.status_code != 200:
        return [], "HTTP %s %s" % (r.status_code, r.text[:120])
    return r.json().get("data", []), None


if __name__ == "__main__":
    referencia = {
        ("ALC", "BRU", "2026-12-04"): 134,
        ("ALC", "BRU", "2026-12-05"): 179,
        ("BRU", "ALC", "2026-12-08"): 139,
    }
    for (origen, destino, fecha), esperado in referencia.items():
        lista, error = vuelos(origen, destino, fecha)
        if error:
            print("%s->%s %s  ERROR %s" % (origen, destino, fecha, error))
            continue
        for v in lista:
            print("%s->%s %s  %s  %s->%s  %s  %s EUR  (Google: %s EUR)  %s" % (
                origen, destino, fecha, v["flightNumber"],
                v["departureDateTime"][11:16], v["arrivalDateTime"][11:16],
                v["duration"], v["price"], esperado,
                "OK" if v["price"] == esperado else "NO CUADRA"))
