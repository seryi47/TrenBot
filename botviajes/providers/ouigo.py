"""Proveedor Ouigo España: API pública de su web (token + journeysearch).

Método basado en el proyecto `RicardoAlegreMiranda/ouigo`.
Disponibilidad = el viaje aparece con precio (price != null).
"""

from datetime import datetime
from typing import List

import requests

from botviajes.models import Offer
from botviajes.providers.base import Provider

TOKEN_URL   = "https://mdw02.api-es.ouigo.com/api/Token/login"
JOURNEY_URL = "https://mdw02.api-es.ouigo.com/api/Sale/journeysearch"
BUY_URL     = "https://www.ouigo.com/es"
# Credenciales públicas del cliente web de Ouigo (visibles en cualquier petición del navegador).
WEB_USER = "ouigo.web"
WEB_PASS = "SquirelWeb!2020"

USER_AGENT = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")


class OuigoProvider(Provider):
    name = "ouigo"

    def __init__(self):
        self._stations = self.load_json("ouigo_es_stations.json")

    def resolve(self, query):
        return self.match_station(
            query, self._stations,
            name_getter=lambda s: s.get("name", ""),
            code_getter=lambda s: s.get("_u_i_c_station_code", ""),
            synonyms_getter=lambda s: s.get("synonyms", []),
        )

    def _token(self, session):
        r = session.post(TOKEN_URL, json={"username": WEB_USER, "password": WEB_PASS},
                         timeout=20)
        r.raise_for_status()
        return r.json().get("token")

    def search(self, origin, destination, date) -> List[Offer]:
        o_name, o_code = self.resolve(origin)
        d_name, d_code = self.resolve(destination)
        if not o_code or not d_code:
            raise ValueError("Ouigo: estación no encontrada (%s / %s)" % (origin, destination))

        s = requests.Session()
        s.headers.update({"User-Agent": USER_AGENT, "content-type": "application/json"})
        s.get(BUY_URL + "/", timeout=20)  # cookies de sesión
        token = self._token(s)
        if not token:
            raise RuntimeError("Ouigo: no se pudo obtener el token.")

        payload = {
            "destination": d_code, "origin": o_code, "outbound_date": date,
            "passengers": [{"discount_cards": [], "disability_type": "NH", "type": "A"}],
        }
        r = s.post(JOURNEY_URL, json=payload,
                   headers={"authorization": "Bearer " + token}, timeout=20)
        r.raise_for_status()
        return self._parse(r.json(), o_name, d_name, date)

    def _parse(self, data, o_name, d_name, date) -> List[Offer]:
        offers = []
        for trip in (data.get("outbound") or []):
            price = trip.get("price")
            dep_ts = (trip.get("departure_timestamp")
                      or (trip.get("departure_station") or {}).get("departure_timestamp")
                      or trip.get("departure_date"))
            arr_ts = (trip.get("arrival_timestamp")
                      or (trip.get("arrival_station") or {}).get("arrival_timestamp"))
            offers.append(Offer(
                provider=self.name, origin=o_name, destination=d_name, date=date,
                departure=_hhmm(dep_ts), arrival=_hhmm(arr_ts),
                label="OUIGO", price=_to_float(price),
                available=price is not None, buy_url=BUY_URL,
                raw={"price": price, "dep": dep_ts},
            ))
        return offers


def _hhmm(ts):
    if not ts:
        return ""
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(str(ts), fmt).strftime("%H:%M")
        except ValueError:
            continue
    # último recurso: buscar "T##:##"
    s = str(ts)
    if "T" in s and len(s) >= 16:
        return s[11:16]
    return ""


def _to_float(value):
    if value is None:
        return None
    try:
        return float(str(value).replace(",", "."))
    except (ValueError, TypeError):
        return None
