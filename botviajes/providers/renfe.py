"""Proveedor Renfe: consulta el backend real de venta (protocolo DWR).

Método basado en el proyecto MIT `emartinez-dev/renfe-bot`.
Devuelve TODOS los trenes Renfe (AVE, Alvia, MD, Avlo…) de una ruta y fecha,
con su disponibilidad real (mismo dato que produce el "tren completo").
"""

import random
import re
import string
import urllib.parse
from datetime import datetime
from typing import List

import requests

try:
    import json5
    def _loads(t):
        return json5.loads(t)
except ImportError:
    import json as _json
    def _loads(t):
        return _json.loads(t)

from botviajes.models import Offer
from botviajes.providers.base import Provider

SEARCH_URL         = "https://venta.renfe.com/vol/buscarTren.do?Idioma=es&Pais=ES"
DWR_ENDPOINT       = "https://venta.renfe.com/vol/dwr/call/plaincall/"
SYSTEM_ID_URL      = DWR_ENDPOINT + "__System.generateId.dwr"
UPDATE_SESSION_URL = DWR_ENDPOINT + "buyEnlacesManager.actualizaObjetosSesion.dwr"
TRAIN_LIST_URL     = DWR_ENDPOINT + "trainEnlacesManager.getTrainsList.dwr"
BUY_URL            = "https://www.renfe.com/es/es"

USER_AGENT = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")


def _to_float(value):
    if value is None:
        return None
    try:
        return float(str(value).replace(",", "."))
    except (ValueError, TypeError):
        return None


def _usable_fares(train):
    """Tarifas que un viajero normal puede comprar.

    Descarta las que solo dejan la plaza reservada a movilidad reducida
    (`soloPlazasH`, dentro de cada tarifa). Ojo: NO es lo mismo que el
    `soloPlazaH` del nivel del tren, que Renfe solo rellena a veces —
    cuando el tren se queda a plaza H el aviso fiable es este.
    `plazaH` por tarifa tampoco sirve: aparece a True en trenes con sitio.
    """
    return [f for f in (train.get("tarifasDisponibles") or [])
            if not f.get("soloPlazasH")]


def _tokenify(number):
    charmap = "1234567890abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ*$"
    buf, rem = [], number
    while rem > 0:
        buf.append(charmap[rem & 0x3F])
        rem //= 64
    return "".join(buf)


def _search_id():
    return "_" + "".join(random.choice(string.ascii_letters + string.digits) for _ in range(4))


class RenfeProvider(Provider):
    name = "renfe"

    def __init__(self):
        self._stations = self.load_json("renfe_stations.json")

    def resolve(self, query):
        return self.match_station(
            query,
            self._stations.values(),
            name_getter=lambda s: s.get("desgEstacion", ""),
            code_getter=lambda s: s.get("cdgoEstacion", ""),
        )

    def search(self, origin, destination, date) -> List[Offer]:
        o_name, o_code = self.resolve(origin)
        d_name, d_code = self.resolve(destination)
        if not o_code or not d_code:
            raise ValueError("Renfe: estación no encontrada (%s / %s)" % (origin, destination))
        date_ddmmyyyy = datetime.strptime(date, "%Y-%m-%d").strftime("%d/%m/%Y")
        raw = _RenfeSession(o_name, o_code, d_name, d_code, date_ddmmyyyy).get_train_list()
        return self._parse(raw, o_name, d_name, date)

    def _parse(self, data, o_name, d_name, date) -> List[Offer]:
        offers = []
        for way in data.get("listadoTrenes", []):
            for t in way.get("listviajeViewEnlaceBean", []):
                usable = _usable_fares(t)
                # Precio de la tarifa más barata COMPRABLE; si no hay ninguna,
                # cae a tarifaMinima solo para poder mostrar el tren agotado.
                prices = [p for p in (_to_float(f.get("precioTarifa")) for f in usable)
                          if p is not None]
                price = min(prices) if prices else _to_float(t.get("tarifaMinima"))
                available = (
                    not t.get("completo")
                    and str(t.get("razonNoDisponible") or "") in ("", "8")
                    and price is not None
                    and not t.get("soloPlazaH")
                    and bool(usable)     # si todas las tarifas son de plaza H, está agotado
                )
                offers.append(Offer(
                    provider=self.name, origin=o_name, destination=d_name, date=date,
                    departure=(t.get("horaSalida") or "").strip().replace(".", ":"),
                    arrival=(t.get("horaLlegada") or "").strip().replace(".", ":"),
                    label=t.get("tipoTrenUno", "?"),
                    price=price, available=bool(available), buy_url=BUY_URL,
                    raw={"completo": t.get("completo"),
                         "razonNoDisponible": t.get("razonNoDisponible"),
                         "soloPlazaH": t.get("soloPlazaH"),
                         "tarifas": len(t.get("tarifasDisponibles") or []),
                         "tarifas_comprables": len(usable)},
                ))
        return offers


class _RenfeSession:
    """Encapsula el baile de DWR necesario para obtener la lista de trenes."""

    def __init__(self, o_name, o_code, d_name, d_code, date_ddmmyyyy):
        self.o_name, self.o_code = o_name, o_code
        self.d_name, self.d_code = d_name, d_code
        self.date = date_ddmmyyyy
        self.api = requests.Session()
        self.api.headers.update({
            "User-Agent": USER_AGENT, "Accept": "*/*",
            "Accept-Encoding": "gzip, deflate", "Connection": "keep-alive",
        })
        self.search_id = _search_id()
        self._batch = 0
        self.dwr_token = None
        self.script_session_id = None

    def _next_batch(self):
        b = self._batch
        self._batch += 1
        return b

    def get_train_list(self):
        self._do_search()
        self._get_dwr_token()
        self._update_session()
        return self._get_train_list()

    def _do_search(self):
        cookie = {
            "origen": {"code": self.o_code, "name": self.o_name},
            "destino": {"code": self.d_code, "name": self.d_name},
            "pasajerosAdultos": 1, "pasajerosNinos": 0, "pasajerosSpChild": 0,
        }
        self.api.cookies.set("Search", str(cookie), domain=".renfe.com", path="/")
        payload = {
            "tipoBusqueda": "autocomplete", "currenLocation": "menuBusqueda",
            "vengoderenfecom": "SI", "desOrigen": self.o_name, "desDestino": self.d_name,
            "cdgoOrigen": self.o_code, "cdgoDestino": self.d_code, "idiomaBusqueda": "ES",
            "FechaIdaSel": self.date, "FechaVueltaSel": "", "_fechaIdaVisual": self.date,
            "_fechaVueltaVisual": "", "adultos_": "1", "ninos_": "0", "ninosMenores": "0",
            "codPromocional": "", "plazaH": "false", "sinEnlace": "false",
            "asistencia": "false", "franjaHoraI": "", "franjaHoraV": "",
            "Idioma": "es", "Pais": "ES",
        }
        r = self.api.post(SEARCH_URL, data=payload, allow_redirects=True, timeout=30)
        r.raise_for_status()

    def _generate_id_payload(self):
        page = "page=%2Fvol%2FbuscarTrenEnlaces.do%3Fc%3D" + self.search_id + "\n"
        return ("callCount=1\nc0-scriptName=__System\nc0-methodName=generateId\nc0-id=0\n"
                "batchId=" + str(self._next_batch()) + "\ninstanceId=0\n" + page +
                "scriptSessionId=\nwindowName=\n")

    def _get_dwr_token(self):
        self.api.post(SYSTEM_ID_URL, data=self._generate_id_payload(), timeout=30)
        r = self.api.post(SYSTEM_ID_URL, data=self._generate_id_payload(), timeout=30)
        r.raise_for_status()
        m = re.search(r'r\.handleCallback\("[^"]+","[^"]+","([^"]+)"\)', r.text)
        if not m:
            raise RuntimeError("Renfe: no se pudo obtener el token DWR.")
        self.dwr_token = m.group(1)
        self.api.cookies.set("DWRSESSIONID", self.dwr_token, path="/vol", domain="venta.renfe.com")
        date_token = _tokenify(int(datetime.now().timestamp() * 1000))
        rand_token = _tokenify(random.randint(0, int(1e16)))
        self.script_session_id = "%s/%s-%s" % (self.dwr_token, date_token, rand_token)

    def _update_session(self):
        payload = ("callCount=1\nwindowName=\n"
                   "c0-scriptName=buyEnlacesManager\nc0-methodName=actualizaObjetosSesion\nc0-id=0\n"
                   "c0-e1=string:" + self.search_id + "\nc0-e2=string:\n"
                   "c0-param0=array:[reference:c0-e1,reference:c0-e2]\n"
                   "batchId=" + str(self._next_batch()) + "\ninstanceId=0\n"
                   "page=%2Fvol%2FbuscarTrenEnlaces.do%3Fc%3D" + self.search_id + "\n"
                   "scriptSessionId=" + self.script_session_id + "\n")
        r = self.api.post(UPDATE_SESSION_URL, data=payload, timeout=30)
        r.raise_for_status()

    def _get_train_list(self):
        fecha = urllib.parse.quote_plus(self.date)
        payload = ("callCount=1\nwindowName=\n"
                   "c0-scriptName=trainEnlacesManager\nc0-methodName=getTrainsList\nc0-id=0\n"
                   "c0-e1=string:false\nc0-e2=string:false\nc0-e3=string:false\n"
                   "c0-e4=string:\nc0-e5=string:\nc0-e6=string:\nc0-e7=string:\n"
                   "c0-e8=string:" + fecha + "\nc0-e9=string:\n"
                   "c0-e10=string:1\nc0-e11=string:0\nc0-e12=string:0\n"
                   "c0-e13=string:I\nc0-e14=string:\n"
                   "c0-param0=Object_Object:{atendo:reference:c0-e1, sinEnlace:reference:c0-e2, "
                   "plazaH:reference:c0-e3, tipoFranjaI:reference:c0-e4, tipoFranjaV:reference:c0-e5, "
                   "horaFranjaIda:reference:c0-e6, horaFranjaVuelta:reference:c0-e7, "
                   "fechaSalida:reference:c0-e8, fechaVuelta:reference:c0-e9, adultos:reference:c0-e10, "
                   "ninos:reference:c0-e11, ninosMenores:reference:c0-e12, trayecto:reference:c0-e13, "
                   "idaVuelta:reference:c0-e14}\n"
                   "batchId=" + str(self._next_batch()) + "\ninstanceId=0\n"
                   "page=%2Fvol%2FbuscarTrenEnlaces.do%3Fc%3D" + self.search_id + "\n"
                   "scriptSessionId=" + self.script_session_id + "\n")
        r = self.api.post(TRAIN_LIST_URL, data=payload, timeout=30)
        r.raise_for_status()
        m = re.search(r"r\.handleCallback\([^,]+,\s*[^,]+,\s*(\{.*\})\);", r.text, re.DOTALL)
        if not m:
            raise RuntimeError("Renfe: respuesta de trenes vacía o con formato inesperado.")
        return _loads(m.group(1))
