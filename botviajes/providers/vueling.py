"""Vueling, contra su propia API. Sin scraping y sin intermediarios.

Cómo se encontró (por si hay que repetirlo cuando lo cambien): su buscador es
una SPA que carga el código en trozos. Capturando TODOS los .js que descarga y
buscando dentro aparece una tabla con sus 79 endpoints:

    var vr = {baseUrl:"https://ams.vueling.com", routes:{
        "auth-v1":            {endpoint:"asm/v1/Auth"},
        "avy-graphql-v1":     {endpoint:"avy/v1/graphql"},
        "get-all-flights-v3": {endpoint:"avy/v3/AvailabilityServices/allFlights"}, ...}}

Dos trampas que costaron encontrar:

1. `allFlights` NO sirve para esto: es un calendario con el precio MÁS BARATO de
   cada día, y ese precio puede ser de un vuelo CON ESCALA. Para el 5-dic daba
   94,06 € de un vuelo con conexión mientras el directo costaba 125,99 €. El
   campo que lo delata es `isConnectionFlight`, no `connectionFlight`.
2. En el GraphQL, `bundleControlFilter` es un ENTERO y vale 2. Con 0, 1 o nulo
   la consulta revienta con "Cannot return null for non-nullable field".

Verificado contra Google Flights el 05-oct-2026: ALC→BRU del 5-dic, VY7862
12:20→14:55, 125,99 € aquí y 126 € allí.
"""

import json
import os
import time
from typing import List

from curl_cffi import requests as cr

from botviajes.models import Offer
from botviajes.providers.base import Provider

BASE = "https://ams.vueling.com"
# El identificador de cliente web de Vueling, el mismo que manda su propia web.
PERFIL_WEB = "e8ffa738-cb67-4a02-b501-9bfd975a4b65"
CONSULTA = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "data", "vueling_getavy.graphql")
COMPRA = "https://tickets.vueling.com/"


class VuelingProvider(Provider):
    name = "vueling"

    def __init__(self):
        self._sesion = None
        self._token = None
        self._token_hasta = 0
        try:
            with open(CONSULTA, encoding="utf-8") as fh:
                self._query = fh.read()
        except OSError:
            self._query = ""

    def _sess(self):
        if self._sesion is None:
            s = cr.Session(impersonate="chrome")
            s.headers.update({"Content-Type": "application/json",
                              "Accept": "application/json",
                              "Accept-Language": "es-ES",
                              "Origin": "https://tickets.vueling.com",
                              "Referer": "https://tickets.vueling.com/"})
            self._sesion = s
        return self._sesion

    def _auth(self):
        """El token caduca en una hora; se renueva solo."""
        if self._token and time.time() < self._token_hasta - 120:
            return self._token
        s = self._sess()
        r = s.post(BASE + "/asm/v1/Auth", json={"profileId": PERFIL_WEB}, timeout=30)
        if r.status_code != 200:
            print("  [vueling] Auth %s" % r.status_code)
            return None
        j = r.json()
        self._token = j.get("accessToken")
        self._token_hasta = time.time() + 3300
        s.headers["Authorization"] = "Bearer " + (self._token or "")
        return self._token

    def search(self, origin, destination, date, adults: int = 1) -> List[Offer]:
        if not self._query:
            print("  [vueling] falta data/vueling_getavy.graphql")
            return []
        if not self._auth():
            return []
        variables = {"requestAVY": {"request": {
            "criteria": [{"origin": origin, "destination": destination, "date": date}],
            "cultureCode": "es-ES", "currencyCode": "EUR",
            # DIRECT + maxConnections 0: nada de escalas, que es la regla del viaje.
            "flightType": "DIRECT", "itineraryType": "ONE_WAY", "maxConnections": 0,
            "passengers": [{"count": adults, "type": "Adult"}],
            "serviceCode": "Search1Day", "servicesToRequest": [],
            "bundleControlFilter": 2}, "trackingPoint": "BBV"}}
        try:
            r = self._sess().post(BASE + "/avy/v1/graphql",
                                  json={"query": self._query, "variables": variables},
                                  timeout=60)
        except Exception as e:
            print("  [vueling] %s->%s %s: %s" % (origin, destination, date, str(e)[:70]))
            return []
        if r.status_code != 200:
            print("  [vueling] graphql %s" % r.status_code)
            return []
        j = r.json()
        if j.get("errors"):
            print("  [vueling] %s" % str(j["errors"][0].get("message"))[:90])
            return []
        datos = (j.get("data") or {}).get("amsAvy") or {}
        precios = self._precios(datos.get("faresAvailable"))
        ofertas = []
        for trip in (datos.get("trips") or []):
            for sub in (trip.get("trips") or []):
                for mercado in (sub.get("journeysAvailableByMarket") or []):
                    for viaje in (mercado.get("value") or []):
                        of = self._a_oferta(viaje, precios, origin, destination, date)
                        if of:
                            ofertas.append(of)
        return ofertas

    @staticmethod
    def _precios(fares):
        """fareAvailabilityKey -> precio por persona más barato."""
        fuera = {}
        for x in (fares or []):
            v = (x or {}).get("value") or {}
            clave = v.get("fareAvailabilityKey")
            for f in (v.get("fares") or []):
                for pf in (f.get("passengerFares") or []):
                    importe = pf.get("amsFareAmount")
                    if clave and importe is not None:
                        if clave not in fuera or importe < fuera[clave]:
                            fuera[clave] = float(importe)
        return fuera

    def _a_oferta(self, viaje, precios, origin, destination, date):
        segs = viaje.get("segments") or []
        if not segs:
            return None
        des = viaje.get("designator") or segs[0].get("designator") or {}
        sale = (des.get("departure") or "")[11:16]
        llega = (des.get("arrival") or "")[11:16]
        ident = (segs[0].get("identifier") or {})
        vuelo = "%s%s" % (ident.get("carrierCode") or "VY", ident.get("identifier") or "")
        barato = None
        for f in (viaje.get("fares") or []):
            p = precios.get(f.get("fareAvailabilityKey"))
            if p is not None and (barato is None or p < barato):
                barato = p
        # Capacidad y vendidos vienen en el tramo: plazas libres de verdad.
        plazas = None
        info = ((segs[0].get("legs") or [{}])[0].get("legInfo") or {})
        if isinstance(info.get("lid"), int) and isinstance(info.get("sold"), int):
            plazas = max(info["lid"] - info["sold"], 0)
        dur = viaje.get("duration") or segs[0].get("segmentDuration")
        return Offer(
            provider=self.name, origin=origin, destination=destination, date=date,
            departure=sale, arrival=llega, label=vuelo, price=barato,
            available=barato is not None, buy_url=COMPRA,
            raw={"plazas": plazas, "vuelo": vuelo,
                 "duracion": "%d:%02d" % (dur // 60, dur % 60) if isinstance(dur, int) else None,
                 "escalas": len(segs) - 1})
