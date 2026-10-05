"""TUI fly Belgium (TB), contra su GraphQL. Sin claves, sin cookies, sin captcha.

Cómo se encontró (por si lo cambian):

1. La home lleva un `<tui-flight-search-bar link="https://www.tuifly.be/flight/...">`.
2. Esa página monta los resultados con un micro-frontend cuyo cargador apunta a
   `mwa.tui.com/search/mwa/flight-search-results/static/main.js`.
3. Dentro de ese bundle están el endpoint GraphQL, la `query GetSearchResults`
   entera y los valores por defecto (channel WEB, environment prod).

Tres trampas:

- **Playwright NO sirve aquí**, al revés que con Vueling: Akamai responde
  "Access Denied". Hay que ir con `curl_cffi impersonate="chrome"`, que pasa a
  la primera.
- **`totalPrice` es el del GRUPO, no el de una persona.** Con 2 adultos el
  mismo vuelo da `pricePerPerson 149.99` y `totalPrice 299.98`. Se lee
  `pricePerPerson`, el mismo error conceptual que ya nos pilló con Google.
- **`availableSeats` viene siempre 10**, está topado. No son plazas reales, así
  que no se usa como el `lid − sold` de Vueling.

Directos: se exige `stopoverType.flightType == "direct"` Y un solo segmento.
Verificado contra Google Flights el 05-oct-2026: ALC→BRU 4-dic 149,99 €,
5-dic 174,99 €, BRU→ALC 8-dic 124,99 €.

Aviso a futuro: los vuelos TB que salgan a partir del 2027-05-01 se gestionan en
otro motor (extendednetwork.tuifly.com), así que esto habrá que rehacerlo.
"""

import os
from typing import List

from curl_cffi import requests as cr

from botviajes.models import Offer
from botviajes.providers.base import Provider

API = "https://mwa.tui.com/search/mwa/flight-search-results/graphql"
COMPRA = "https://www.tuifly.be/flight/en/search"
CONSULTA = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "data", "tuifly_search.graphql")


class TuiflyProvider(Provider):
    name = "tuifly"

    def __init__(self):
        try:
            with open(CONSULTA, encoding="utf-8") as fh:
                self._query = fh.read()
        except OSError:
            self._query = ""

    def search(self, origin, destination, date, adults: int = 1) -> List[Offer]:
        if not self._query:
            print("  [tuifly] falta data/tuifly_search.graphql")
            return []
        variables = {"sourceMarket": "BE", "origin": origin, "destination": destination,
                     "departureDate": date, "adult": str(adults), "environment": "prod",
                     "channel": "WEB", "journeyType": "ONE_WAY", "currency": "EUR",
                     "locale": "en-GB", "includeNearbyAirports": False}
        try:
            r = cr.post(API, json={"query": self._query, "variables": variables},
                        headers={"Content-Type": "application/json",
                                 "Origin": "https://www.tuifly.be",
                                 "Referer": "https://www.tuifly.be/"},
                        impersonate="chrome", timeout=60)
        except Exception as e:
            print("  [tuifly] %s->%s %s: %s" % (origin, destination, date, str(e)[:70]))
            return []
        if r.status_code != 200:
            print("  [tuifly] HTTP %s %s" % (r.status_code, r.text[:90]))
            return []
        j = r.json()
        if j.get("errors"):
            print("  [tuifly] %s" % str(j["errors"][0].get("message"))[:90])
            return []
        datos = ((j.get("data") or {}).get("getSearchResults") or {})
        ofertas = []
        for of in (datos.get("flightOffers") or []):
            precio = ((of.get("priceDetails") or {}).get("pricePerPerson"))
            for direccion in (of.get("directions") or []):
                segs = direccion.get("segments") or []
                tipo = ((direccion.get("stopoverType") or {}).get("flightType") or "")
                # Directo de verdad: lo dice el enum Y hay un solo tramo.
                if tipo != "direct" or len(segs) != 1:
                    continue
                if (direccion.get("origin") or {}).get("isAlternative") or \
                   (direccion.get("destination") or {}).get("isAlternative"):
                    continue          # aeropuerto cercano, no el que pedimos
                if precio is None:
                    continue
                vuelo = segs[0].get("flightNumber") or ""
                cia = (direccion.get("carrier") or {}).get("code") or "TB"
                ofertas.append(Offer(
                    provider=self.name, origin=origin, destination=destination,
                    date=date, departure=(direccion.get("departureTime") or "")[11:16],
                    arrival=(direccion.get("arrivalTime") or "")[11:16],
                    label="%s%s" % (cia, vuelo), price=float(precio),
                    available=True, buy_url=COMPRA,
                    # availableSeats viene topado a 10: no son plazas reales.
                    raw={"plazas": None, "total_grupo":
                         (of.get("priceDetails") or {}).get("totalPrice")}))
        return ofertas
