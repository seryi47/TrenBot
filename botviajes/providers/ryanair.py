"""Proveedor Ryanair: API de disponibilidad real de su web (la que usa el buscador).

    GET https://www.ryanair.com/api/booking/v4/{mercado}/availability

Dos detalles que hacen que funcione y que costó dar con ellos:

1. Sin las cabeceras `client: desktop` y `client-version` responde **409
   "Availability declined"**. Con ellas, 200.
2. El precio llega en la divisa del país de salida (un Pardubice→Alicante
   viene en coronas checas), así que se pasa a euros con `botviajes.fx`.

Devuelve el precio POR PASAJERO de la tarifa estándar, ya con tasas, sin
maleta facturada ni asiento elegido.
"""

import json
import os
import re
from typing import List

from curl_cffi import requests as cr

from botviajes.fx import a_euros
from botviajes.models import Offer
from botviajes.providers.base import Provider

AVAIL = "https://www.ryanair.com/api/booking/v4/es-es/availability"
HOME = "https://www.ryanair.com/es/es"
COMPRA = ("https://www.ryanair.com/es/es/trip/flights/select?adults=%d&teens=0&children=0"
          "&infants=0&dateOut=%s&isConnectedFlight=false&discount=0&isReturn=false"
          "&originIata=%s&destinationIata=%s")
# Ryanair exige la versión EXACTA de su app web en la cabecera client-version:
# cualquier otra (más alta, más baja o ausente) responde 409. Y la suben cada
# pocos días, así que no se puede dejar escrita a fuego: se lee de su web y se
# guarda en caché.
VERSION_POR_DEFECTO = "3.213.1"
CACHE_VERSION = "ryanair_version.json"
PAGINA_RESERVA = "https://www.ryanair.com/es/es/trip/flights/select"


class RyanairProvider(Provider):
    name = "ryanair"

    def __init__(self):
        self._est = self.load_json("ryanair_stations.json")
        self._sess = None
        self._version = self._cargar_version()

    # ---- versión del cliente ------------------------------------------------
    @staticmethod
    def _ruta_cache():
        from botviajes.providers.base import DATA_DIR
        return os.path.join(DATA_DIR, CACHE_VERSION)

    def _cargar_version(self):
        try:
            with open(self._ruta_cache(), encoding="utf-8") as fh:
                return json.load(fh).get("client_version") or VERSION_POR_DEFECTO
        except Exception:
            return VERSION_POR_DEFECTO

    def _guardar_version(self, v):
        try:
            with open(self._ruta_cache(), "w", encoding="utf-8") as fh:
                json.dump({"client_version": v}, fh)
        except Exception:
            pass

    def _detectar_version(self):
        """Lee la versión de la propia web de Ryanair.

        La página de selección de vuelos la deja en un comentario del HTML:
            <!-- Desktop version: 3.213.1 -->
        Son 3 KB, así que sale barato comprobarlo cuando hace falta.
        """
        try:
            r = cr.get(PAGINA_RESERVA, impersonate="chrome", timeout=25,
                       headers={"Accept-Language": "es-ES"})
            m = re.search(r"Desktop version:\s*(\d+\.\d+\.\d+)", r.text)
            if m and m.group(1) != self._version:
                print("  [ryanair] client-version %s -> %s" % (self._version, m.group(1)))
                self._version = m.group(1)
                self._guardar_version(self._version)
                return True
        except Exception as e:
            print("  [ryanair] no pude leer la versión: %s" % e)
        return False

    # ---- utilidades ---------------------------------------------------------
    def resolve(self, query):
        """Acepta código IATA ('BTS') o nombre de ciudad ('Bratislava')."""
        q = (query or "").strip()
        if len(q) == 3 and q.isalpha() and q.upper() in self._est:
            return self._est[q.upper()]["name"], q.upper()
        return self.match_station(
            q, self._est.items(),
            name_getter=lambda kv: kv[1]["name"],
            code_getter=lambda kv: kv[0],
        )

    def _session(self):
        if self._sess is None:
            s = cr.Session(impersonate="chrome")
            s.headers.update({
                "Accept": "application/json, text/plain, */*",
                "Accept-Language": "es-ES",
                "client": "desktop",              # sin esto -> 409
                "client-version": self._version,   # tiene que ser la exacta
                "Referer": HOME,
            })
            try:
                s.get(HOME, timeout=25)           # cookies de sesión
            except Exception:
                pass
            self._sess = s
        return self._sess

    # ---- búsqueda -----------------------------------------------------------
    def search(self, origin, destination, date, adults=1) -> List[Offer]:
        no, co = self.resolve(origin)
        nd, cd = self.resolve(destination)
        if not co or not cd:
            print("  [ryanair] no reconozco '%s' o '%s'" % (origin, destination))
            return []

        params = {"ADT": adults, "TEEN": 0, "CHD": 0, "INF": 0,
                  "Origin": co, "Destination": cd, "promoCode": "",
                  "IncludeConnectingFlights": "false", "DateOut": date, "DateIn": "",
                  "FlexDaysBeforeOut": 0, "FlexDaysOut": 0, "RoundTrip": "false",
                  "ToUs": "AGREED", "Disc": 0}
        s = self._session()
        r = s.get(AVAIL, params=params, timeout=40)
        if r.status_code == 409:
            # 409 = o la sesión caducó, o Ryanair ha subido su client-version.
            # Se comprueba lo segundo antes de darse por vencido.
            self._detectar_version()
            self._sess = None
            r = self._session().get(AVAIL, params=params, timeout=40)
        if r.status_code != 200:
            print("  [ryanair] %s->%s %s: HTTP %s" % (co, cd, date, r.status_code))
            return []

        data = r.json()
        divisa = data.get("currency", "EUR")
        compra = COMPRA % (adults, date, co, cd)
        ofertas = []
        for trip in data.get("trips", []):
            for dia in trip.get("dates", []):
                if not str(dia.get("dateOut", "")).startswith(date):
                    continue
                for f in dia.get("flights", []):
                    horas = f.get("time") or ["", ""]
                    tarifas = (f.get("regularFare") or {}).get("fares") or []
                    bruto = tarifas[0].get("amount") if tarifas else None
                    plazas = f.get("faresLeft")
                    # faresLeft == 0 -> agotado; -1 -> sin límite anunciado.
                    hay = bool(tarifas) and bruto is not None and plazas != 0
                    precio = a_euros(bruto, divisa)
                    etiqueta = f.get("flightNumber", "").replace(" ", "")
                    operador = f.get("operatedBy")
                    if operador and operador.lower() != "ryanair":
                        etiqueta += " (%s)" % operador
                    if plazas and plazas > 0:
                        etiqueta += " · %d plazas" % plazas
                    ofertas.append(Offer(
                        provider=self.name, origin=no or co, destination=nd or cd,
                        date=date, departure=horas[0][11:16], arrival=horas[1][11:16],
                        label=etiqueta, price=precio, available=hay, buy_url=compra,
                        raw={"divisa": divisa, "bruto": bruto, "plazas": plazas,
                             "pais_origen": self._est.get(co, {}).get("country", ""),
                             "pais_destino": self._est.get(cd, {}).get("country", "")},
                    ))
        return ofertas
