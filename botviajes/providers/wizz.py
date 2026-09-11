"""Proveedor Wizz Air: API real de su web (be.wizzair.com).

Tres cosas que hay que saber para que responda (todas descubiertas capturando
el tráfico de su propia web con un navegador):

1. Exige la cabecera `X-RequestVerificationToken`, cuyo valor es el de la
   cookie del mismo nombre que entrega `POST /Api/asset/culture`. Sin ella
   responde 400 `InvalidProtocol`.
2. La versión va en la URL (`/29.14.0/Api`). Si Wizz la sube, se detecta sola
   leyendo la web y se reintenta.
3. Los precios llegan en la divisa de la estación de salida del PRIMER tramo
   del `flightList`. Pidiendo solo BUD→ALC vienen en forintos; poniendo delante
   un tramo que sale de zona euro, todo llega en euros. Aun así se pasa por
   `botviajes.fx` por si acaso.

`/search/search` da horas de llegada y plazas pero se satura enseguida (429);
`/search/timetable` aguanta mucho mejor. Se intenta el primero y se cae al
segundo. Por eso conviene un `poll_interval` alto (10 min o más) en vuelos.
"""

import json
import math
import os
import re
import time
from typing import List

from curl_cffi import requests as cr

from botviajes.fx import a_euros
from botviajes.models import Offer
from botviajes.providers.base import Provider

# Wizz sube esta versión cada pocas semanas; si cambia, _detectar_version()
# la lee de su propia web y sigue funcionando sin tocar nada.
VERSION_POR_DEFECTO = "29.16.0"
CACHE_VERSION = "wizz_version.json"

# Husos horarios respecto a UTC en octubre de 2026 (aún con horario de verano:
# en la UE termina el 25). Wizz no publica la zona horaria de sus aeropuertos y
# sin ella no se puede calcular a qué hora local aterriza un vuelo.
HUSO = {
    "PT": 1, "GB": 1, "IE": 1, "IS": 0,
    "ES": 2, "FR": 2, "BE": 2, "NL": 2, "LU": 2, "DE": 2, "CH": 2, "AT": 2,
    "IT": 2, "CZ": 2, "SK": 2, "PL": 2, "HU": 2, "SI": 2, "HR": 2, "BA": 2,
    "RS": 2, "ME": 2, "MK": 2, "AL": 2, "DK": 2, "SE": 2, "NO": 2, "MT": 2,
    "XK": 2, "GR": 3, "BG": 3, "RO": 3, "MD": 3, "FI": 3, "EE": 3, "LV": 3,
    "LT": 3, "UA": 3, "CY": 3, "TR": 3, "GE": 4, "AM": 4, "IL": 3,
    "AE": 4, "SA": 3, "EG": 3, "MA": 1, "JO": 3, "AZ": 4,
}
# Horas de llegada reales, aprendidas de la propia web de Wizz. El endpoint que
# aguanta el ritmo (timetable) NO devuelve la llegada, así que se guardan aquí
# las que se van conociendo y el resto se estima.
CACHE_HORARIOS = "wizz_horarios.json"
# Ruta de compra directa al vuelo. Ojo: la traducida (/es-es/reserva/seleccionar-vuelo)
# devuelve 404; la buena en español es /es-es/booking/select-flight (verificado 03/09/2026).
COMPRA = "https://www.wizzair.com/es-es/booking/select-flight/%s/%s/%s/null/%d/0/0/null"


class WizzProvider(Provider):
    name = "wizz"

    def __init__(self):
        self._est = self.load_json("wizz_stations.json")
        self._horarios = self._cargar_horarios()
        self._sess = None
        self._version = self._cargar_version()
        self._ultima = 0.0
        # /search/search se satura enseguida. Cuando devuelve 429 se aparca un
        # rato y se tira solo de /search/timetable, que aguanta bien.
        self._search_castigado_hasta = 0.0

    # ---- horas de llegada ---------------------------------------------------
    @staticmethod
    def _ruta_cache():
        from botviajes.providers.base import DATA_DIR
        return os.path.join(DATA_DIR, CACHE_HORARIOS)

    def _cargar_horarios(self):
        try:
            with open(self._ruta_cache(), encoding="utf-8") as fh:
                return json.load(fh)
        except Exception:
            return {}

    def _guardar_horarios(self):
        try:
            with open(self._ruta_cache(), "w", encoding="utf-8") as fh:
                json.dump(self._horarios, fh, ensure_ascii=False, indent=0, sort_keys=True)
        except Exception:
            pass

    @staticmethod
    def _clave(o, d, salida):
        return "%s-%s-%s" % (o, d, (salida or "").replace(":", ""))

    def _apuntar_llegada(self, o, d, salida, llegada):
        if not (salida and llegada):
            return
        k = self._clave(o, d, salida)
        if self._horarios.get(k) != llegada:
            self._horarios[k] = llegada
            self._guardar_horarios()

    def _llegada(self, o, d, salida):
        """(hora, es_estimada). Nunca devuelve vacío: si no se sabe, se calcula."""
        exacta = self._horarios.get(self._clave(o, d, salida))
        if exacta:
            return exacta, False
        a, b = self._est.get(o), self._est.get(d)
        if not (a and b and salida):
            return "", True
        r = 6371.0
        la1, lo1, la2, lo2 = map(math.radians, [a["lat"], a["lon"], b["lat"], b["lon"]])
        h = (math.sin((la2 - la1) / 2) ** 2
             + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2)
        km = 2 * r * math.asin(math.sqrt(h))
        vuelo = km / 750.0 * 60 + 35          # crucero + rodaje, subida y bajada
        desfase = (HUSO.get((b.get("cc") or "").upper(), 2)
                   - HUSO.get((a.get("cc") or "").upper(), 2)) * 60
        hh, mm = salida.split(":")[:2]
        total = int(int(hh) * 60 + int(mm) + vuelo + desfase) % 1440
        return "%02d:%02d" % divmod(total, 60), True

    # ---- utilidades ---------------------------------------------------------
    @property
    def base(self):
        return "https://be.wizzair.com/%s/Api" % self._version

    def resolve(self, query):
        q = (query or "").strip()
        if len(q) == 3 and q.isalpha() and q.upper() in self._est:
            return self._est[q.upper()]["name"], q.upper()
        return self.match_station(
            q, self._est.items(),
            name_getter=lambda kv: kv[1]["name"],
            code_getter=lambda kv: kv[0],
        )

    def _cargar_version(self):
        try:
            with open(self._ruta_cache_version(), encoding="utf-8") as fh:
                return json.load(fh).get("version") or VERSION_POR_DEFECTO
        except Exception:
            return VERSION_POR_DEFECTO

    @staticmethod
    def _ruta_cache_version():
        from botviajes.providers.base import DATA_DIR
        return os.path.join(DATA_DIR, CACHE_VERSION)

    def _detectar_version(self):
        """Si Wizz sube la versión de su API, la lee de su propia web."""
        try:
            r = cr.get("https://www.wizzair.com/es-es", impersonate="chrome", timeout=30)
            m = re.search(r"be\.wizzair\.com/(\d+\.\d+\.\d+)", r.text)
            if m and m.group(1) != self._version:
                print("  [wizz] versión de API %s -> %s" % (self._version, m.group(1)))
                self._version = m.group(1)
                try:
                    with open(self._ruta_cache_version(), "w", encoding="utf-8") as fh:
                        json.dump({"version": self._version}, fh)
                except Exception:
                    pass
                return True
        except Exception as e:
            print("  [wizz] no pude leer la versión: %s" % e)
        return False

    def _session(self, forzar=False):
        if self._sess is None or forzar:
            s = cr.Session(impersonate="chrome")
            s.headers.update({
                "Origin": "https://www.wizzair.com",
                "Referer": "https://www.wizzair.com/es-es",
                "Accept": "application/json, text/plain, */*",
                "Accept-Language": "es-ES,es;q=0.9",
                "Content-Type": "application/json",
            })
            s.post(self.base + "/asset/culture", json={"languageCode": "es-es"}, timeout=30)
            token = s.cookies.get("RequestVerificationToken")
            if token:
                s.headers["X-RequestVerificationToken"] = token
            self._sess = s
        return self._sess

    def _post(self, ruta, payload, intentos=2):
        """POST con espaciado mínimo entre llamadas y reintento suave."""
        for i in range(intentos):
            espera = 2.0 - (time.time() - self._ultima)
            if espera > 0:
                time.sleep(espera)
            s = self._session()
            r = s.post(self.base + ruta, json=payload, timeout=60)
            self._ultima = time.time()
            if r.status_code == 200:
                return r.json()
            if r.status_code in (400,) and "InvalidProtocol" in r.text:
                self._session(forzar=True)      # token caducado
                continue
            # Wizz jubila las versiones viejas devolviendo 503 (no 404), así que
            # ante CUALQUIER fallo se comprueba si han publicado una nueva antes
            # de dar la consulta por perdida.
            if r.status_code in (400, 404, 429, 503) and self._detectar_version():
                self._session(forzar=True)
                continue
            if r.status_code in (429, 503):
                if i + 1 < intentos:
                    time.sleep(20)
                    continue
                print("  [wizz] %s: HTTP %s (limitado, se reintenta al siguiente sondeo)"
                      % (ruta, r.status_code))
                return None
            print("  [wizz] %s: HTTP %s %s" % (ruta, r.status_code, r.text[:100]))
            return None
        return None

    def _en_euros(self, code):
        return (self._est.get(code, {}).get("currency") or "EUR") == "EUR"

    # ---- búsqueda -----------------------------------------------------------
    def search(self, origin, destination, date, adults=1) -> List[Offer]:
        no, co = self.resolve(origin)
        nd, cd = self.resolve(destination)
        if not co or not cd:
            print("  [wizz] no reconozco '%s' o '%s'" % (origin, destination))
            return []
        compra = COMPRA % (co, cd, date, adults)

        ofertas = None
        if time.time() >= self._search_castigado_hasta:
            ofertas = self._por_search(co, cd, date, adults, no, nd, compra)
            if ofertas is None:
                self._search_castigado_hasta = time.time() + 1800   # media hora
        if ofertas is None:
            ofertas = self._por_timetable(co, cd, date, adults, no, nd, compra)
        return ofertas or []

    def _por_search(self, co, cd, date, adults, no, nd, compra):
        """Vía preferida: trae horas de llegada y plazas. Se satura con facilidad."""
        pl = {"isFlightChange": False, "isSeniorOrStudent": False, "wdc": False,
              "flightList": [{"departureStation": co, "arrivalStation": cd,
                              "departureDate": date}],
              "adultCount": adults, "childCount": 0, "infantCount": 0}
        d = self._post("/search/search", pl, intentos=1)
        if not d:
            return None
        ofertas = []
        for f in d.get("outboundFlights", []) or []:
            barata, divisa = None, "EUR"
            for tarifa in (f.get("fares") or []):
                p = tarifa.get("discountedPrice") or tarifa.get("basePrice") or {}
                a = p.get("amount")
                # un 0 nunca es un precio real; es "no hay tarifa aquí"
                if a is not None and float(a) > 0 and (barata is None or a < barata):
                    barata, divisa = a, p.get("currencyCode", "EUR")
            plazas = f.get("availableSeatCount")
            self._apuntar_llegada(co, cd, (f.get("departureDateTime") or "")[11:16],
                                  (f.get("arrivalDateTime") or "")[11:16])
            precio = a_euros(barata, divisa)
            etiqueta = f.get("flightNumber") or "W6"
            if isinstance(plazas, int) and plazas >= 0:
                etiqueta += " · %d plazas" % plazas
            ofertas.append(Offer(
                provider=self.name, origin=no or co, destination=nd or cd, date=date,
                departure=(f.get("departureDateTime") or "")[11:16],
                arrival=(f.get("arrivalDateTime") or "")[11:16],
                label=etiqueta, price=precio,
                available=precio is not None and plazas != 0,
                buy_url=compra,
                raw={"divisa": divisa, "bruto": barata, "plazas": plazas,
                     "pais_origen": self._est.get(co, {}).get("country", ""),
                     "pais_destino": self._est.get(cd, {}).get("country", "")},
            ))
        return ofertas

    def _por_timetable(self, co, cd, date, adults, no, nd, compra):
        """Respaldo: aguanta mucho mejor, pero solo da precio y hora de salida."""
        tramos = [{"departureStation": co, "arrivalStation": cd, "from": date, "to": date}]
        # Si la salida no es en euros, se antepone el tramo inverso (que sí lo es)
        # para que Wizz devuelva los importes en EUR.
        if not self._en_euros(co) and self._en_euros(cd):
            tramos.insert(0, {"departureStation": cd, "arrivalStation": co,
                              "from": date, "to": date})
        pl = {"flightList": tramos, "priceType": "regular",
              "adultCount": adults, "childCount": 0, "infantCount": 0}
        d = self._post("/search/timetable", pl)
        if not d:
            return []
        ofertas = []
        for clave in ("outboundFlights", "returnFlights"):
            for f in d.get(clave, []) or []:
                if f.get("departureStation") != co or f.get("arrivalStation") != cd:
                    continue
                if not str(f.get("departureDate", "")).startswith(date):
                    continue
                p = f.get("price") or {}
                # OJO: Wizz marca algunos vuelos como priceType "checkPrice" y
                # entonces manda price.amount = 0. NO es que sea gratis: es que
                # no da precio ahí y hay que mirarlo en su web. Tragarse ese 0
                # provocaba avisos falsos de "billetes a 0,00 €".
                tipo = f.get("priceType")
                importe = p.get("amount")
                orientativo = False
                if tipo != "price" or importe is None or float(importe) <= 0:
                    # Wizz no da precio firme, pero sí suele dejar uno de
                    # referencia en originalPrice. Se usa SOLO como orientación:
                    # el vuelo se marca como no comprable y nunca dispara avisos.
                    orig = (f.get("originalPrice") or {}).get("amount")
                    precio = a_euros(orig, (f.get("originalPrice") or {}).get(
                        "currencyCode")) if orig and float(orig) > 0 else None
                    orientativo = precio is not None
                    print("  [wizz] %s->%s %s: Wizz no publica precio "
                          "(priceType=%r); %s"
                          % (co, cd, (f.get("departureDate") or "")[:10], tipo,
                             "uso %.2f € como orientativo" % precio if precio
                             else "sin dato"))
                else:
                    precio = a_euros(importe, p.get("currencyCode"))
                for salida in (f.get("departureDates") or [""]):
                    hora = salida[11:16]
                    llega, estimada = self._llegada(co, cd, hora)
                    ofertas.append(Offer(
                        provider=self.name, origin=no or co, destination=nd or cd,
                        date=date, departure=hora, arrival=llega,
                        label="W6 · precio orientativo" if orientativo else "W6",
                        price=precio,
                        # sin precio firme no se puede decir que sea comprable
                        available=precio is not None and not orientativo,
                        buy_url=compra,
                        raw={"divisa": p.get("currencyCode"), "bruto": p.get("amount"),
                             "via": "timetable", "llegada_estimada": estimada,
                             "priceType": tipo, "orientativo": orientativo,
                             "pais_origen": self._est.get(co, {}).get("country", ""),
                             "pais_destino": self._est.get(cd, {}).get("country", "")},
                    ))
        return ofertas
