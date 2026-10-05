"""TUI fly Belgium (TB), contra su propia API. Sin scraping y sin claves.

Cómo se encontró (misma técnica que con Vueling, con un matiz importante):

1. La home de tuifly.be lleva un <tui-flight-search-bar> cuyo atributo `link`
   descubre el motor de reservas:
       https://www.tuifly.be/flight/#lang#/search?flyingFrom[]=..&flyingTo[]=..
2. Esa página /flight/en/search es SAP Hybris y monta los resultados con un
   micro-frontend <flight-search-results-cfe>. Su cargador está en el HTML:
       https://mwa.tui.com/search/mwa/flight-search-results-cfe/static/main.js
   y ese bundle a su vez carga el de verdad:
       https://mwa.tui.com/search/mwa/flight-search-results/static/main.js
3. Dentro de ese bundle está el endpoint y la consulta entera:
       https://mwa.tui.com/search/mwa/flight-search-results/graphql
       query GetSearchResults(...)  +  fragment FlightResponseCommonFragment

Tres trampas:

- **Playwright headless NO sirve aquí**: Akamai devuelve "Access Denied" en
  /flight/ y en mwa.tui.com. Con curl_cffi impersonate="chrome" pasa a la
  primera. Sin impersonate, 403 de Akamai. (Con Vueling fue al revés: allí el
  navegador hacía falta para capturar los trozos de JS.)
- **`totalPrice` es el del GRUPO, no el de una persona**: con adult="2" el
  10:30 del 4-dic da pricePerPerson 149,99 y totalPrice 299,98. Hay que leer
  `priceDetails.pricePerPerson`.
- **`availableSeats` viene siempre 10**: está topado, no son plazas reales.

Directos: `directions[].stopoverType.flightType == "direct"` y
`len(directions[].segments) == 1`. Los otros valores del enum son "one_stop" y
"two_stopps". En el mercado BE todo lo que devuelve es punto a punto, pero el
filtro va puesto igual porque el campo existe.

Verificado contra Google Flights el 05-oct-2026 (precios por 1 persona):
    ALC->BRU 04-dic  TB1121 10:30-13:25  149,99 €  (Google 150 €)
    ALC->BRU 05-dic  TB1112 09:20-12:15  174,99 €  (Google 175 €)
    BRU->ALC 08-dic  TB1111 06:00-08:45  124,99 €  (Google 125 €)
"""

import json
import sys

from curl_cffi import requests as cr

API = "https://mwa.tui.com/search/mwa/flight-search-results/graphql"
COMPRA = ("https://www.tuifly.be/flight/en/search?flyingFrom%5B%5D={o}"
          "&flyingTo%5B%5D={d}&depDate={f}&adults={a}&children=0&childAge="
          "&choiceSearch=true&searchType=pricegrid&nearByAirports=false"
          "&currency=EUR&isOneWay=true")

# Recorte del fragment que trae el bundle: solo lo que hace falta.
QUERY = """
fragment FlightResponseCommonFragment on FlightResponse {
  flightOffers {
    flightOfferId
    combiHashCode
    priceDetails { pricePerPerson totalPrice type }
    sourcingSystem
    directions {
      id type duration
      stopoverType { flightType text }
      origin { iataCode name isAlternative }
      destination { iataCode name isAlternative }
      departureTime arrivalTime availableSeats
      carrier { name code }
      segments {
        id flightNumber departureTime arrivalTime duration airplaneType
        origin { iataCode } destination { iataCode } carrier { name code }
      }
    }
  }
}
query GetSearchResults(
  $sourceMarket: String!, $origin: String!, $destination: String!,
  $departureDate: String!, $returnDate: String, $adult: String!,
  $child: String, $infant: String, $environment: String!, $channel: String!,
  $journeyType: String!, $currency: String!, $locale: String!,
  $includeNearbyAirports: Boolean
) {
  getSearchResults(
    sourceMarket: $sourceMarket, origin: $origin, destination: $destination,
    departureDate: $departureDate, returnDate: $returnDate, adult: $adult,
    child: $child, infant: $infant, environment: $environment, channel: $channel,
    journeyType: $journeyType, currency: $currency, locale: $locale,
    includeNearbyAirports: $includeNearbyAirports
  ) { ...FlightResponseCommonFragment }
}
"""


def consultar(origen, destino, fecha, adultos=1, mercado="BE"):
    """Devuelve la lista cruda de flightOffers (o [] si falla)."""
    variables = {
        "sourceMarket": mercado, "origin": origen, "destination": destino,
        "departureDate": fecha, "adult": str(adultos), "environment": "prod",
        "channel": "WEB", "journeyType": "ONE_WAY", "currency": "EUR",
        "locale": "en-GB", "includeNearbyAirports": False,
    }
    # impersonate="chrome" es OBLIGATORIO: sin él Akamai responde 403.
    r = cr.post(API, json={"query": QUERY, "variables": variables},
                impersonate="chrome", timeout=60,
                headers={"Content-Type": "application/json",
                         "Origin": "https://www.tuifly.be",
                         "Referer": "https://www.tuifly.be/"})
    if r.status_code != 200:
        print("  [tuifly] HTTP %s" % r.status_code)
        return []
    j = r.json()
    if j.get("errors"):
        print("  [tuifly] %s" % str(j["errors"][0].get("message"))[:90])
        return []
    return ((j.get("data") or {}).get("getSearchResults") or {}).get("flightOffers") or []


def directos(origen, destino, fecha, adultos=1):
    """Solo vuelos TB directos, con el precio POR PERSONA."""
    fuera = []
    for of in consultar(origen, destino, fecha, adultos):
        for d in of.get("directions") or []:
            segs = d.get("segments") or []
            tipo = (d.get("stopoverType") or {}).get("flightType")
            if len(segs) != 1 or tipo != "direct":
                continue
            if d["origin"]["iataCode"] != origen or d["destination"]["iataCode"] != destino:
                continue
            if d["origin"].get("isAlternative") or d["destination"].get("isAlternative"):
                continue
            fuera.append({
                "vuelo": "%s%s" % (d["carrier"]["code"], segs[0]["flightNumber"]),
                "compania": d["carrier"]["name"],
                "salida": d["departureTime"][11:16],
                "llegada": d["arrivalTime"][11:16],
                "duracion_min": d.get("duration"),
                "precio": of["priceDetails"]["pricePerPerson"],   # por persona
                "total_grupo": of["priceDetails"]["totalPrice"],
                "oferta": of.get("flightOfferId"),
                "comprar": COMPRA.format(o=origen, d=destino, f=fecha, a=adultos),
            })
    return fuera


if __name__ == "__main__":
    pares = [("ALC", "BRU", "2026-12-04"), ("ALC", "BRU", "2026-12-05"),
             ("BRU", "ALC", "2026-12-08")]
    if len(sys.argv) >= 4:
        pares = [(sys.argv[1], sys.argv[2], sys.argv[3])]
    for o, d, f in pares:
        print("== %s->%s %s" % (o, d, f))
        for v in directos(o, d, f):
            print("   %(vuelo)s %(salida)s-%(llegada)s  %(precio)s EUR/persona" % v)
