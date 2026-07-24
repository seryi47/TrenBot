"""Proveedor Vuelos vía Amadeus Self-Service API (oficial, plan gratuito).

Alta gratis en https://developers.amadeus.com → crea una app → copia
API Key y API Secret en el .env:
    AMADEUS_API_KEY=...
    AMADEUS_API_SECRET=...
    AMADEUS_ENV=test        # "test" (gratis, datos limitados) o "production"

Origen/destino se indican como códigos IATA de aeropuerto (MAD, BCN, ALC…).
Disponibilidad = hay ofertas de vuelo comprables para esa fecha.
"""

import os
import time
from typing import List

import requests

from botviajes.models import Offer
from botviajes.providers.base import Provider

HOSTS = {
    "test": "https://test.api.amadeus.com",
    "production": "https://api.amadeus.com",
}


class AmadeusProvider(Provider):
    name = "amadeus"

    def __init__(self):
        self.key = os.environ.get("AMADEUS_API_KEY", "").strip()
        self.secret = os.environ.get("AMADEUS_API_SECRET", "").strip()
        self.host = HOSTS.get(os.environ.get("AMADEUS_ENV", "test").strip(), HOSTS["test"])
        self._token = None
        self._token_exp = 0

    def _get_token(self):
        if self._token and time.time() < self._token_exp - 30:
            return self._token
        r = requests.post(
            self.host + "/v1/security/oauth2/token",
            data={"grant_type": "client_credentials",
                  "client_id": self.key, "client_secret": self.secret},
            timeout=20,
        )
        r.raise_for_status()
        data = r.json()
        self._token = data["access_token"]
        self._token_exp = time.time() + int(data.get("expires_in", 1799))
        return self._token

    def search(self, origin, destination, date) -> List[Offer]:
        if not self.key or not self.secret:
            print("  [amadeus] sin credenciales (AMADEUS_API_KEY/SECRET). Se omite.")
            return []
        token = self._get_token()
        r = requests.get(
            self.host + "/v2/shopping/flight-offers",
            headers={"Authorization": "Bearer " + token},
            params={
                "originLocationCode": origin.upper(),
                "destinationLocationCode": destination.upper(),
                "departureDate": date, "adults": 1, "currencyCode": "EUR",
                "max": 20,
            },
            timeout=30,
        )
        if r.status_code == 400:
            print("  [amadeus] petición inválida:", r.text[:200])
            return []
        r.raise_for_status()
        return self._parse(r.json(), origin.upper(), destination.upper(), date)

    def _parse(self, data, o, d, date) -> List[Offer]:
        offers = []
        for off in data.get("data", []):
            try:
                price = float(off["price"]["grandTotal"])
            except (KeyError, ValueError, TypeError):
                price = None
            seg = off["itineraries"][0]["segments"][0]
            dep = seg["departure"]["at"][11:16]
            arr = off["itineraries"][0]["segments"][-1]["arrival"]["at"][11:16]
            carrier = seg.get("carrierCode", "")
            number = seg.get("number", "")
            offers.append(Offer(
                provider=self.name, origin=o, destination=d, date=date,
                departure=dep, arrival=arr, label="%s%s" % (carrier, number),
                price=price, available=True,
                buy_url="https://www.google.com/travel/flights",
                raw={"seats": off.get("numberOfBookableSeats")},
            ))
        return offers
