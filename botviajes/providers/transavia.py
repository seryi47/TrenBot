"""Transavia (HV), contra su propia API. Sin scraping y sin claves.

Cómo se encontró (por si lo cambian):

1. Su home da "Attention Required! | Cloudflare" con Playwright, pero
   `curl_cffi` con `impersonate="chrome"` entra a la primera. Aquí Cloudflare
   mira la huella TLS, no el user-agent: con un navegador automatizado no se
   pasa y con una petición bien fingida sí.
2. La base NO es `/search/api` (ahí solo vive `/general/disruptions`, por eso
   los nombres probados a ciegas daban 404) sino **`/start/api`**. La tabla
   entera está en los chunks de Next.js de su buscador, buscando `.endpoint({path:`.

Dos trampas:

- `/flight-availability` **no lleva origen y destino en la query**: los lee de
  la cookie `TransaviaFlightSearch`, que es el JSON del formulario. Sin ella
  responde 400 "Invalid flight availability request".
- El modo que funciona es `type=flight`; con `type=full` siempre da 400.

Cada elemento de la respuesta es UN solo `flightNumber` con su hora de salida y
llegada, así que por construcción no hay escalas. Además, la tabla de rutas de
su web marca ALC↔BRU como `isTransavia` (vuelo propio) y no `isDohop` (conexión
virtual, que va por otro dominio y este endpoint nunca devuelve).

Precio POR PERSONA: pidiendo 2 adultos sigue diciendo lo mismo.
Verificado contra Google Flights el 05-oct-2026: ALC→BRU 4-dic 134 €,
5-dic 179 €, BRU→ALC 8-dic 139 €. Los tres exactos.
"""

import json
import urllib.parse
from typing import List

from curl_cffi import requests as cr

from botviajes.models import Offer
from botviajes.providers.base import Provider

BASE = "https://www.transavia.com"
BUSCADOR = BASE + "/reservar/es-es/buscar-un-vuelo"


class TransaviaProvider(Provider):
    name = "transavia"

    @staticmethod
    def _cookie(origen, destino, fecha, adultos):
        """La cookie que deja su formulario. Es de donde salen origen y destino."""
        valores = {"flightType": "one-way",
                   "passengers": {"isValid": True, "adults": adultos,
                                  "children": 0, "infants": 0},
                   "route": {"validRoute": True, "departure": origen,
                             "arrival": destino},
                   "dates": {"from": fecha, "to": None},
                   "secondRoute": {"validRoute": False, "departure": None,
                                   "arrival": None},
                   "secondDates": None, "impartialDates": None,
                   "flyingBlue": False}
        return "TransaviaFlightSearch=" + urllib.parse.quote(
            json.dumps(valores, separators=(",", ":")))

    def search(self, origin, destination, date, adults: int = 1) -> List[Offer]:
        try:
            r = cr.get(BASE + "/start/api/flight-availability",
                       params={"type": "flight", "flightDirection": "outbound",
                               "date": date},
                       headers={"Accept": "application/json", "Referer": BUSCADOR,
                                "Cookie": self._cookie(origin, destination, date, adults)},
                       impersonate="chrome", timeout=60)
        except Exception as e:
            print("  [transavia] %s->%s %s: %s" % (origin, destination, date, str(e)[:70]))
            return []
        if r.status_code != 200:
            print("  [transavia] HTTP %s %s" % (r.status_code, r.text[:90]))
            return []
        ofertas = []
        for v in (r.json().get("data") or []):
            precio = v.get("price")
            if precio is None:
                continue
            plazas = v.get("availabilityCount")
            ofertas.append(Offer(
                provider=self.name, origin=origin, destination=destination, date=date,
                departure=(v.get("departureDateTime") or "")[11:16],
                arrival=(v.get("arrivalDateTime") or "")[11:16],
                label=v.get("flightNumber") or "HV", price=float(precio),
                available=True, buy_url=BUSCADOR,
                raw={"plazas": plazas if isinstance(plazas, int) else None,
                     "duracion": v.get("duration"),
                     "clase": v.get("fareClass")}))
        return ofertas
