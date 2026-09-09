"""Conversión a euros de los precios que las aerolíneas dan en moneda local.

Ryanair y Wizz cotizan en la divisa del país desde el que sale el vuelo: un
Pardubice→Alicante llega en coronas checas y un Budapest→Alicante en forintos.
Para poder compararlo todo contra un `max_price` en euros hay que convertirlo.

La fuente es el tipo de cambio oficial diario del BCE (XML público, sin clave).
"""

import time
import xml.etree.ElementTree as ET

import requests

ECB_URL = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml"
TTL = 6 * 3600          # el BCE publica una vez al día; refrescar cada 6 h sobra

_cache = {"t": 0, "rates": {}}


def _rates():
    """{divisa: unidades por 1 EUR}. Cachea y, si falla la red, reusa lo último."""
    if _cache["rates"] and time.time() - _cache["t"] < TTL:
        return _cache["rates"]
    try:
        r = requests.get(ECB_URL, timeout=20)
        r.raise_for_status()
        root = ET.fromstring(r.content)
        rates = {"EUR": 1.0}
        for cube in root.iter():
            if cube.get("currency") and cube.get("rate"):
                rates[cube.get("currency")] = float(cube.get("rate"))
        if len(rates) > 5:
            _cache.update({"t": time.time(), "rates": rates})
    except Exception as e:
        print("  [fx] no se pudo actualizar el cambio del BCE: %s" % e)
    return _cache["rates"]


def a_euros(cantidad, divisa):
    """Convierte a EUR. Devuelve None si no hay tipo de cambio para esa divisa."""
    if cantidad is None:
        return None
    divisa = (divisa or "EUR").upper()
    if divisa == "EUR":
        return round(float(cantidad), 2)
    tasa = _rates().get(divisa)
    if not tasa:
        return None
    return round(float(cantidad) / tasa, 2)
